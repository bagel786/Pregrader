"""
Improved centering analysis with robust card detection.
Uses gradient-based border detection for reliable measurements.
"""
import cv2
import numpy as np
import logging
from typing import Dict, Optional, Tuple
from .vision.image_preprocessing import (
    find_card_contour,
    get_card_corners,
    perspective_correct_card
)

logger = logging.getLogger(__name__)


def detect_inner_artwork_box(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect the inner artwork/text box of a Pokémon card.
    
    Args:
        image: Card image (should be perspective-corrected)
        
    Returns:
        Bounding rectangle [x, y, w, h] or None
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply Gaussian blur
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Canny edge detection
    edges = cv2.Canny(blurred, 50, 150)
    
    # Find contours
    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_SIMPLE
    )
    
    # Filter contours by area and position
    valid_boxes = []
    img_height, img_width = image.shape[:2]
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # Artwork box should be significant but not entire card
        # Typically 15-70% of card area
        if area < (img_width * img_height * 0.15):
            continue
        if area > (img_width * img_height * 0.70):
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        
        # Relaxed: artwork can be anywhere (modern cards have varied layouts)
        # Just ensure it's not at the very edge
        margin = 0.05
        if x < img_width * margin and y < img_height * margin:
            continue  # Too close to top-left corner — probably the card itself
        
        # Should have reasonable aspect ratio for a card element
        aspect = w / h
        if aspect < 0.5 or aspect > 2.0:
            continue
        
        valid_boxes.append((x, y, w, h))
    
    if not valid_boxes:
        return None
    
    # Return largest valid box (likely the artwork frame)
    return max(valid_boxes, key=lambda box: box[2] * box[3])


def _detect_border_widths_gradient_single(
    gray: np.ndarray,
    h: int,
    w: int,
    sobel_threshold: int = 40,
) -> Tuple[float, float, float, float]:
    """Single-pass gradient border detection with a given Sobel threshold."""
    # Compute gradients
    grad_x = np.abs(cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3))
    grad_y = np.abs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))

    # Normalize to 0-255
    grad_x = (grad_x / grad_x.max() * 255).astype(np.uint8) if grad_x.max() > 0 else grad_x.astype(np.uint8)
    grad_y = (grad_y / grad_y.max() * 255).astype(np.uint8) if grad_y.max() > 0 else grad_y.astype(np.uint8)

    # Threshold to find strong edges
    _, strong_x = cv2.threshold(grad_x, sobel_threshold, 255, cv2.THRESH_BINARY)
    _, strong_y = cv2.threshold(grad_y, sobel_threshold, 255, cv2.THRESH_BINARY)

    scan_limit = min(w // 4, 150)
    scan_limit_y = min(h // 4, 150)
    min_border_w = max(1, int(w * 0.02))
    min_border_h = max(1, int(h * 0.02))

    left_width = min_border_w
    for x in range(min_border_w, scan_limit):
        if np.mean(strong_x[:, x]) > 30:
            left_width = x
            break

    right_width = min_border_w
    for x in range(w - 1 - min_border_w, w - scan_limit, -1):
        if np.mean(strong_x[:, x]) > 30:
            right_width = w - 1 - x
            break

    top_width = min_border_h
    for y in range(min_border_h, scan_limit_y):
        if np.mean(strong_y[y, :]) > 30:
            top_width = y
            break

    bottom_width = min_border_h
    for y in range(h - 1 - min_border_h, h - scan_limit_y, -1):
        if np.mean(strong_y[y, :]) > 30:
            bottom_width = h - 1 - y
            break

    left_width = max(left_width, w * 0.02)
    right_width = max(right_width, w * 0.02)
    top_width = max(top_width, h * 0.02)
    bottom_width = max(bottom_width, h * 0.02)

    return left_width, right_width, top_width, bottom_width


def detect_border_widths_hsv(image: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    """
    HSV outermost-colour border detection.

    Samples the dominant border hue from a thin inward strip (~3px) at each edge,
    then scans inward until the HSV colour diverges from that hue.  This detects
    the outermost print border rather than the first strong gradient, which on
    Pokémon cards (thick border + artwork frame + text) often fires on the wrong edge.

    Args:
        image: Perspective-corrected card image (BGR)

    Returns:
        (left, right, top, bottom) border widths, or None if detection failed.
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.float32)
    sat = hsv[:, :, 1].astype(np.float32)

    SAMPLE_STRIP = 3   # px strip at the very edge to sample border hue
    HUE_TOL = 20       # hue units — border ends when hue deviates this much
    SAT_MIN = 40       # ignore low-saturation (white/grey) columns/rows

    def _border_width_axis(strip_hue: np.ndarray, strip_sat: np.ndarray,
                           scan_hue: np.ndarray, scan_sat: np.ndarray,
                           dim: int, reverse: bool = False) -> Optional[float]:
        """Measure one border width along a single axis."""
        # Use median hue of the sample strip, ignoring desaturated pixels
        sat_ok = strip_sat > SAT_MIN
        if sat_ok.sum() < 5:
            return None
        ref_hue = float(np.median(strip_hue[sat_ok]))

        scan_range = range(SAMPLE_STRIP, min(dim // 3, 120))
        if reverse:
            scan_range = range(dim - 1 - SAMPLE_STRIP, max(dim - dim // 3, dim - 120), -1)

        for idx in scan_range:
            col = scan_hue[idx] if not reverse else scan_hue[idx]
            col_sat = scan_sat[idx]
            sat_mask = col_sat > SAT_MIN
            if sat_mask.sum() < 3:
                # Mostly desaturated column/row — likely transitioned into artwork
                width = (idx if not reverse else dim - 1 - idx)
                return float(width)
            col_hue = col[sat_mask]
            # Circular hue distance
            diff = np.abs(col_hue.astype(float) - ref_hue)
            diff = np.minimum(diff, 180 - diff)
            if np.median(diff) > HUE_TOL:
                width = (idx if not reverse else dim - 1 - idx)
                return float(width)
        return None

    # Left border: sample leftmost strip, scan right
    left_strip_hue = hue[:, :SAMPLE_STRIP].flatten()
    left_strip_sat = sat[:, :SAMPLE_STRIP].flatten()
    left = _border_width_axis(left_strip_hue, left_strip_sat, hue.T, sat.T, w, reverse=False)

    # Right border: sample rightmost strip, scan left
    right_strip_hue = hue[:, w - SAMPLE_STRIP:].flatten()
    right_strip_sat = sat[:, w - SAMPLE_STRIP:].flatten()
    right = _border_width_axis(right_strip_hue, right_strip_sat, hue.T, sat.T, w, reverse=True)

    # Top border
    top_strip_hue = hue[:SAMPLE_STRIP, :].flatten()
    top_strip_sat = sat[:SAMPLE_STRIP, :].flatten()
    top = _border_width_axis(top_strip_hue, top_strip_sat, hue, sat, h, reverse=False)

    # Bottom border
    bot_strip_hue = hue[h - SAMPLE_STRIP:, :].flatten()
    bot_strip_sat = sat[h - SAMPLE_STRIP:, :].flatten()
    bottom = _border_width_axis(bot_strip_hue, bot_strip_sat, hue, sat, h, reverse=True)

    if any(v is None for v in (left, right, top, bottom)):
        return None

    # Ensure minimums
    left = max(left, w * 0.02)
    right = max(right, w * 0.02)
    top = max(top, h * 0.02)
    bottom = max(bottom, h * 0.02)

    return left, right, top, bottom


def detect_border_widths_gradient(image: np.ndarray) -> Tuple[float, float, float, float, bool]:
    """
    Gradient-based border detection using median-of-3 for stability.

    Runs Sobel edge detection at 3 slightly different thresholds (35, 40, 45)
    and takes the median result, reducing sensitivity to threshold choice.

    Args:
        image: Perspective-corrected card image

    Returns:
        Tuple of (left, right, top, bottom, symmetry_corrected) where
        symmetry_corrected is True if any border was clamped by the symmetry heuristic.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Run at 3 thresholds and take median for each border
    results = []
    for threshold in (35, 40, 45):
        results.append(_detect_border_widths_gradient_single(gray, h, w, threshold))

    # Median of each border measurement
    left_width = sorted(r[0] for r in results)[1]
    right_width = sorted(r[1] for r in results)[1]
    top_width = sorted(r[2] for r in results)[1]
    bottom_width = sorted(r[3] for r in results)[1]

    # Symmetry validation: if one border is suspiciously small compared to its
    # opposite and below 5% of the dimension, clamp to 10% of dimension.
    # This prevents detection artifacts from producing extreme asymmetry.
    # Returns whether any correction was applied so callers can reduce confidence.
    min_w = w * 0.05
    min_h = h * 0.05
    symmetry_corrected = False
    if left_width < min_w and right_width > left_width * 3:
        left_width = max(left_width, w * 0.10)
        symmetry_corrected = True
    if right_width < min_w and left_width > right_width * 3:
        right_width = max(right_width, w * 0.10)
        symmetry_corrected = True
    if top_width < min_h and bottom_width > top_width * 3:
        top_width = max(top_width, h * 0.10)
        symmetry_corrected = True
    if bottom_width < min_h and top_width > bottom_width * 3:
        bottom_width = max(bottom_width, h * 0.10)
        symmetry_corrected = True

    return left_width, right_width, top_width, bottom_width, symmetry_corrected


def detect_border_widths(image: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Fallback centering detection using border color analysis.
    
    Measures the colored border width on each side by detecting
    where the saturated border color ends and artwork begins.
    Works better for holographic and full-art cards.
    
    Args:
        image: Perspective-corrected card image
        
    Returns:
        Tuple of (left, right, top, bottom) border widths
    """
    h, w = image.shape[:2]
    
    # Convert to HSV to detect saturated (colored) borders
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    
    # Borders are typically saturated (yellow, blue, etc.)
    # Threshold to find saturated regions
    _, border_mask = cv2.threshold(saturation, 60, 255, cv2.THRESH_BINARY)
    
    # Sample from center of each edge to find where border ends
    # Left border: scan from left edge toward center
    left_width = 0
    for x in range(min(w // 4, 100)):  # Don't scan more than 1/4 of width
        col = border_mask[:, x]
        # If less than 60% of column is saturated, we've exited the border
        if np.mean(col) < 150:  # 255 * 0.6 ≈ 153
            left_width = x
            break
    else:
        left_width = w // 20  # Fallback: assume 5% border
    
    # Right border: scan from right edge toward center
    right_width = 0
    for x in range(w - 1, max(w - w // 4, w - 100), -1):
        col = border_mask[:, x]
        if np.mean(col) < 150:
            right_width = w - 1 - x
            break
    else:
        right_width = w // 20
    
    # Top border: scan from top edge toward center
    top_width = 0
    for y in range(min(h // 4, 100)):
        row = border_mask[y, :]
        if np.mean(row) < 150:
            top_width = y
            break
    else:
        top_width = h // 20
    
    # Bottom border: scan from bottom edge toward center  
    bottom_width = 0
    for y in range(h - 1, max(h - h // 4, h - 100), -1):
        row = border_mask[y, :]
        if np.mean(row) < 150:
            bottom_width = h - 1 - y
            break
    else:
        bottom_width = h // 20
    
    # Ensure minimum border width (at least 2% of dimension)
    left_width = max(left_width, w * 0.02)
    right_width = max(right_width, w * 0.02)
    top_width = max(top_width, h * 0.02)
    bottom_width = max(bottom_width, h * 0.02)
    
    return left_width, right_width, top_width, bottom_width


def calculate_centering_score(
    left: float,
    right: float,
    top: float,
    bottom: float
) -> float:
    """
    Calculate centering score based on border measurements.
    
    Uses smooth interpolation rather than hard cutoffs.
    
    Args:
        left, right, top, bottom: Border widths in pixels
        
    Returns:
        Score from 1.0 to 10.0
    """
    # Calculate ratios (smaller / larger for each axis)
    lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
    tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
    
    # Average the two ratios
    avg_ratio = (lr_ratio + tb_ratio) / 2.0
    
    # Dampened scoring curve — wider brackets in the mid-range (0.5-0.8)
    # to reduce sensitivity to measurement noise.
    # Top band widened: 9.0→10.0 now spans 0.93–0.975 (was 0.95–0.975).
    # The previous 0.025 range (~6px on a 500px card) was within natural noise;
    # a well-centred card could randomly score 9.0 instead of 10.0.
    if avg_ratio >= 0.975:
        return 10.0
    elif avg_ratio >= 0.93:
        return 9.0 + (avg_ratio - 0.93) / 0.045
    elif avg_ratio >= 0.90:
        return 8.0 + (avg_ratio - 0.90) / 0.05
    elif avg_ratio >= 0.85:
        return 7.0 + (avg_ratio - 0.85) / 0.05
    elif avg_ratio >= 0.75:
        # Dampened: 0.10 ratio range → 1.0 grade (was 0.05 → 1.0)
        return 6.0 + (avg_ratio - 0.75) / 0.10
    elif avg_ratio >= 0.60:
        # Dampened: 0.15 ratio range → 1.0 grade (was 0.10 → 2.0)
        return 5.0 + (avg_ratio - 0.60) / 0.15
    elif avg_ratio >= 0.45:
        return 4.0 + (avg_ratio - 0.45) / 0.15
    else:
        return max(2.0, 4.0 * avg_ratio / 0.45)


def calculate_centering_ratios(
    image_path: str,
    debug_output_path: Optional[str] = None
) -> Dict:
    """
    Analyze card centering and return detailed measurements.
    
    Uses a multi-method approach:
    1. Try artwork box detection (most precise)
    2. Fall back to gradient-based border detection (most reliable)
    3. Fall back to saturation-based border detection (legacy)
    
    Includes validation to detect and handle unreliable measurements.
    
    Args:
        image_path: Path to card image
        debug_output_path: Optional path to save debug visualization
        
    Returns:
        Dict with centering analysis results
    """
    # Load image
    image = cv2.imread(image_path)
    if image is None:
        return {
            "success": False,
            "error": "Could not load image",
            "score": 5.0
        }
    
    # Find card boundary
    card_contour = find_card_contour(image)
    if card_contour is None:
        return {
            "success": False,
            "error": "Could not detect card boundary",
            "score": 5.0,
            "grade_estimate": 5.0
        }
    
    # Get corners and apply perspective correction
    corners = get_card_corners(card_contour)
    corrected = perspective_correct_card(image, corners)
    
    img_height, img_width = corrected.shape[:2]
    
    # Method 1: Detect inner artwork box
    artwork_box = detect_inner_artwork_box(corrected)
    detection_method = "artwork_box"
    
    if artwork_box is not None:
        # Primary method: use artwork box boundaries
        x, y, w, h = artwork_box
        left = x
        right = img_width - (x + w)
        top = y
        bottom = img_height - (y + h)
        
        # Validate artwork box result
        lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
        tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
        
        if lr_ratio < 0.3 or tb_ratio < 0.3:
            # Artwork box detection gave extreme results, likely wrong
            logger.warning(f"Artwork box centering looks unreliable (lr={lr_ratio:.2f}, tb={tb_ratio:.2f}), trying gradient method")
            artwork_box = None  # Fall through to gradient method
    
    symmetry_corrected = False
    if artwork_box is None:
        # Method 2: HSV outermost-colour detection — finds the true print border
        # rather than firing on the artwork frame like gradient detection can.
        detection_method = "hsv_border"
        hsv_result = detect_border_widths_hsv(corrected)
        if hsv_result is not None:
            left, right, top, bottom = hsv_result
            lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
            tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
            if lr_ratio < 0.3 or tb_ratio < 0.3:
                logger.warning(f"HSV centering looks unreliable (lr={lr_ratio:.2f}, tb={tb_ratio:.2f}), falling back to gradient")
                hsv_result = None

        if hsv_result is None:
            # Method 3: gradient-based border detection (fallback)
            detection_method = "gradient_detection"
            left, right, top, bottom, symmetry_corrected = detect_border_widths_gradient(corrected)

            # Validate gradient result
            lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
            tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0

            if lr_ratio < 0.3 or tb_ratio < 0.3:
                # Still unreliable, try saturation fallback
                logger.warning(f"Gradient centering looks unreliable (lr={lr_ratio:.2f}, tb={tb_ratio:.2f}), trying saturation method")
                detection_method = "border_detection"
                left, right, top, bottom = detect_border_widths(corrected)
                symmetry_corrected = False

    # Final validation: if ALL methods give extreme asymmetry,
    # it's likely a detection issue, not actual centering
    lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
    tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0

    if lr_ratio < 0.3 or tb_ratio < 0.3:
        logger.warning(
            f"All centering methods gave extreme asymmetry "
            f"(L={left:.0f}, R={right:.0f}, T={top:.0f}, B={bottom:.0f}). "
            f"Likely a detection artifact. Using ratio-derived conservative score."
        )
        # Derive a score from the measured ratios rather than returning a fixed 5.0.
        # This avoids artificially inflating severely off-centre cards.
        score = max(2.0, calculate_centering_score(left, right, top, bottom))
        detection_method = f"{detection_method}_fallback"
    else:
        # Calculate score normally
        score = calculate_centering_score(left, right, top, bottom)
    
    logger.info(
        f"Centering via {detection_method}: "
        f"L={left:.0f} R={right:.0f} T={top:.0f} B={bottom:.0f} "
        f"lr_ratio={lr_ratio:.3f} tb_ratio={tb_ratio:.3f} "
        f"score={score:.1f}"
    )
    
    # Calculate percentages for display
    total_lr = left + right
    total_tb = top + bottom
    
    left_pct = (left / total_lr * 100) if total_lr > 0 else 50.0
    right_pct = (right / total_lr * 100) if total_lr > 0 else 50.0
    top_pct = (top / total_tb * 100) if total_tb > 0 else 50.0
    bottom_pct = (bottom / total_tb * 100) if total_tb > 0 else 50.0
    
    # Debug visualization
    if debug_output_path:
        debug_img = corrected.copy()
        
        if artwork_box is not None:
            x, y, w, h = artwork_box
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
        else:
            # Draw border measurement lines
            left_int, right_int = int(left), int(right)
            top_int, bottom_int = int(top), int(bottom)
            cv2.line(debug_img, (left_int, 0), (left_int, img_height), (0, 255, 0), 1)
            cv2.line(debug_img, (img_width - right_int, 0), (img_width - right_int, img_height), (0, 255, 0), 1)
            cv2.line(debug_img, (0, top_int), (img_width, top_int), (0, 255, 0), 1)
            cv2.line(debug_img, (0, img_height - bottom_int), (img_width, img_height - bottom_int), (0, 255, 0), 1)
        
        # Draw measurements
        cv2.putText(debug_img, f"L: {left:.0f}px", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"R: {right:.0f}px", (img_width - 120, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"T: {top:.0f}px", (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"B: {bottom:.0f}px", (img_width - 120, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"Score: {score:.1f} ({detection_method})", (10, img_height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        cv2.imwrite(debug_output_path, debug_img)
    
    # Determine confidence based on detection method
    if detection_method == "artwork_box":
        confidence = 0.9
    elif detection_method == "hsv_border":
        confidence = 0.85
    elif detection_method == "gradient_detection":
        confidence = 0.8
    elif "fallback" in detection_method:
        confidence = 0.5
    else:
        confidence = 0.7

    # Symmetry correction overwrites a measurement with a heuristic default.
    # Signal that the result is less reliable so it doesn't present at full confidence.
    if symmetry_corrected:
        confidence = min(confidence, 0.6)
    
    return {
        "success": True,
        "score": round(score, 1),
        "grade_estimate": round(score, 1),  # Backward compatibility
        "detection_method": detection_method,
        "lr_ratio": round(lr_ratio, 4),
        "tb_ratio": round(tb_ratio, 4),
        "measurements": {
            "left_px": left,
            "right_px": right,
            "top_px": top,
            "bottom_px": bottom,
            "left_right_ratio": f"{left_pct:.1f}/{right_pct:.1f}",
            "top_bottom_ratio": f"{top_pct:.1f}/{bottom_pct:.1f}"
        },
        "confidence": confidence
    }
