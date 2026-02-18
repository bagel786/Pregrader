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


def detect_border_widths_gradient(image: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Gradient-based border detection.
    
    Uses Sobel edge detection to find strong horizontal/vertical transitions
    near each edge of the card. The first significant gradient band from
    each side marks the border→artwork transition.
    
    This is more reliable than saturation-based detection for colored borders.
    
    Args:
        image: Perspective-corrected card image
        
    Returns:
        Tuple of (left, right, top, bottom) border widths
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply slight blur to reduce noise
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # Compute gradients
    # For left/right borders, we want strong vertical edges (gradient in X direction)
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_x = np.abs(grad_x)
    
    # For top/bottom borders, we want strong horizontal edges (gradient in Y direction)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    grad_y = np.abs(grad_y)
    
    # Normalize to 0-255
    grad_x = (grad_x / grad_x.max() * 255).astype(np.uint8) if grad_x.max() > 0 else grad_x.astype(np.uint8)
    grad_y = (grad_y / grad_y.max() * 255).astype(np.uint8) if grad_y.max() > 0 else grad_y.astype(np.uint8)
    
    # Threshold to find strong edges
    _, strong_x = cv2.threshold(grad_x, 40, 255, cv2.THRESH_BINARY)
    _, strong_y = cv2.threshold(grad_y, 40, 255, cv2.THRESH_BINARY)
    
    scan_limit = min(w // 4, 150)  # Don't scan more than 25% of dimension
    scan_limit_y = min(h // 4, 150)
    
    # Minimum border: at least 2% of dimension
    min_border_w = max(1, int(w * 0.02))
    min_border_h = max(1, int(h * 0.02))
    
    # For each edge, project the gradient onto that axis and find the first peak
    # LEFT: scan columns from left, look for column with high gradient density
    left_width = min_border_w
    for x in range(min_border_w, scan_limit):
        col_density = np.mean(strong_x[:, x])
        if col_density > 30:  # At least ~12% of pixels in this column are strong edges
            left_width = x
            break
    
    # RIGHT: scan columns from right
    right_width = min_border_w
    for x in range(w - 1 - min_border_w, w - scan_limit, -1):
        col_density = np.mean(strong_x[:, x])
        if col_density > 30:
            right_width = w - 1 - x
            break
    
    # TOP: scan rows from top
    top_width = min_border_h
    for y in range(min_border_h, scan_limit_y):
        row_density = np.mean(strong_y[y, :])
        if row_density > 30:
            top_width = y
            break
    
    # BOTTOM: scan rows from bottom
    bottom_width = min_border_h
    for y in range(h - 1 - min_border_h, h - scan_limit_y, -1):
        row_density = np.mean(strong_y[y, :])
        if row_density > 30:
            bottom_width = h - 1 - y
            break
    
    # Ensure minimum border width (at least 2% of dimension)
    left_width = max(left_width, w * 0.02)
    right_width = max(right_width, w * 0.02)
    top_width = max(top_width, h * 0.02)
    bottom_width = max(bottom_width, h * 0.02)
    
    return left_width, right_width, top_width, bottom_width


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
    
    # Smooth scoring using linear interpolation
    # Perfect centering (1.00 ratio) = 10.0
    # 0.95 ratio = 9.0
    # 0.90 ratio = 8.0
    # etc.
    if avg_ratio >= 0.975:
        return 10.0
    elif avg_ratio >= 0.95:
        # Interpolate between 9.0 and 10.0
        return 9.0 + (avg_ratio - 0.95) / 0.025
    elif avg_ratio >= 0.90:
        return 8.0 + (avg_ratio - 0.90) / 0.05 * 1.0
    elif avg_ratio >= 0.85:
        return 7.0 + (avg_ratio - 0.85) / 0.05 * 1.0
    elif avg_ratio >= 0.80:
        return 6.0 + (avg_ratio - 0.80) / 0.05 * 1.0
    elif avg_ratio >= 0.75:
        return 5.0 + (avg_ratio - 0.75) / 0.05 * 1.0
    elif avg_ratio >= 0.70:
        return 4.0 + (avg_ratio - 0.70) / 0.05 * 1.0
    else:
        # Very poor centering
        return max(1.0, avg_ratio * 5.0)


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
    
    if artwork_box is None:
        # Method 2: gradient-based border detection (most reliable)
        detection_method = "gradient_detection"
        left, right, top, bottom = detect_border_widths_gradient(corrected)
        
        # Validate gradient result
        lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
        tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
        
        if lr_ratio < 0.3 or tb_ratio < 0.3:
            # Still unreliable, try saturation fallback
            logger.warning(f"Gradient centering looks unreliable (lr={lr_ratio:.2f}, tb={tb_ratio:.2f}), trying saturation method")
            detection_method = "border_detection"
            left, right, top, bottom = detect_border_widths(corrected)
    
    # Final validation: if ALL methods give extreme asymmetry, 
    # it's likely a detection issue, not actual centering
    lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
    tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
    
    if lr_ratio < 0.3 or tb_ratio < 0.3:
        logger.warning(
            f"All centering methods gave extreme asymmetry "
            f"(L={left:.0f}, R={right:.0f}, T={top:.0f}, B={bottom:.0f}). "
            f"Likely a detection artifact. Using moderate default."
        )
        # Use a moderate default rather than a wildly wrong score
        score = 7.0
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
    elif detection_method == "gradient_detection":
        confidence = 0.8
    elif "fallback" in detection_method:
        confidence = 0.5
    else:
        confidence = 0.7
    
    return {
        "success": True,
        "score": round(score, 1),
        "grade_estimate": round(score, 1),  # Backward compatibility
        "detection_method": detection_method,
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
