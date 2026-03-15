# DEPRECATED: Superseded by backend/grading/vision_assessor.py
# Surface analysis is now performed by Vision AI. This file is retained for
# reference and potential hybrid fallback if needed during calibration.
import cv2
import numpy as np
from ..utils import find_card_contour


def detect_holographic_regions(image: np.ndarray) -> np.ndarray:
    """
    Detect areas with holographic foil patterns.
    These regions should be excluded from scratch detection.
    
    Args:
        image: BGR card image
        
    Returns:
        Binary mask where 255 = holographic region
    """
    # Convert to LAB for better color separation
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0].astype(np.float32)
    
    # Holo areas have high local variance in brightness
    # Use a sliding window approach
    kernel_size = 15
    
    # Calculate local variance: E[X^2] - E[X]^2
    mean_sq = cv2.blur(l_channel ** 2, (kernel_size, kernel_size))
    sq_mean = cv2.blur(l_channel, (kernel_size, kernel_size)) ** 2
    variance_map = mean_sq - sq_mean
    
    # Threshold variance map - high variance indicates texture/holo.
    # Use the 85th percentile of local variance rather than a fixed value so the
    # detector adapts to different lighting conditions instead of relying on an
    # absolute number calibrated for a single environment.
    variance_threshold = np.percentile(variance_map, 85)
    holo_mask = (variance_map > variance_threshold).astype(np.uint8) * 255
    
    # Clean up with morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    holo_mask = cv2.morphologyEx(holo_mask, cv2.MORPH_CLOSE, kernel)
    holo_mask = cv2.morphologyEx(holo_mask, cv2.MORPH_OPEN, kernel)
    
    return holo_mask


def _detect_border_staining(card_roi: np.ndarray, border_mask: np.ndarray) -> float:
    """
    Detect localised colour anomalies in the card border region that indicate staining.

    Uses the border's own LAB a* (green-red) and b* (blue-yellow) distribution as
    the baseline rather than comparing border-to-interior.  This avoids false positives
    on warm-toned or gold borders where the entire border is shifted — only pixels
    that deviate significantly from the *border median* are flagged.

    Args:
        card_roi: BGR image of the card area
        border_mask: Binary mask isolating the border ring

    Returns:
        stain_pct: Percentage of border pixels classified as stained (0–100)
    """
    if cv2.countNonZero(border_mask) == 0:
        return 0.0

    lab = cv2.cvtColor(card_roi, cv2.COLOR_BGR2LAB)
    # Shift LAB a*/b* from 0-255 range to -128 to +127
    a_ch = lab[:, :, 1].astype(np.float32) - 128.0
    b_ch = lab[:, :, 2].astype(np.float32) - 128.0

    border_a = a_ch[border_mask > 0]
    border_b = b_ch[border_mask > 0]

    if len(border_a) == 0:
        return 0.0

    a_median = np.median(border_a)
    b_median = np.median(border_b)
    a_std = np.std(border_a)
    b_std = np.std(border_b)

    # Avoid division by zero on perfectly uniform borders; a floor of 2.0 LAB units
    # prevents extremely tight std from flagging normal JPEG noise as staining.
    a_std = max(a_std, 2.0)
    b_std = max(b_std, 2.0)

    # Flag pixels that deviate more than 2.5 standard deviations from the border median
    stained_a = int(np.sum(border_a > a_median + 2.5 * a_std))
    stained_b = int(np.sum(border_b > b_median + 2.5 * b_std))

    # Normalise over both channels to get a combined stain percentage
    stain_pct = (stained_a + stained_b) / (2.0 * len(border_a)) * 100.0
    return float(stain_pct)


def analyze_surface_damage(image_path: str, is_front: bool = True) -> dict:
    """
    Analyzes a Pokemon card image for surface damage including scratches and marks.
    Explicitly flags creases/dents for severe grade capping.
    Now includes holographic region detection to reduce false positives.

    Args:
        image_path: Path to card image.
        is_front: True if this is the card front. Front cards have complex dark
            artwork that can trigger false crease detection, so a stricter threshold
            is applied. Back cards are a flat blue field where dark blobs reliably
            indicate real damage.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        result = find_card_contour(image)
        if not result:
            return {"error": "Card not detected."}

        _, (cx, cy, cw, ch) = result

        padding = 10
        roi_x = max(0, cx + padding)
        roi_y = max(0, cy + padding)
        roi_w = min(cw - 2 * padding, image.shape[1] - roi_x)
        roi_h = min(ch - 2 * padding, image.shape[0] - roi_y)

        card_roi = image[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
        card_gray = cv2.cvtColor(card_roi, cv2.COLOR_BGR2GRAY)

        # Calculate resolution-independent thresholds
        total_card_area = card_roi.shape[0] * card_roi.shape[1]
        min_scratch_area = total_card_area * 0.0005  # 0.05% of card area
        # Front card artwork is inherently dark (dark-type Pokémon, black backgrounds).
        # Use a 4× stricter threshold for fronts to avoid false crease detection.
        # Back cards are flat blue fields where dark blobs genuinely indicate damage.
        major_damage_threshold = total_card_area * (0.0015 if not is_front else 0.0060)
        
        # Glare Filtering
        hsv = cv2.cvtColor(card_roi, cv2.COLOR_BGR2HSV)
        lower_glare = np.array([0, 0, 230])
        upper_glare = np.array([180, 30, 255])
        glare_mask = cv2.inRange(hsv, lower_glare, upper_glare)
        kernel = np.ones((5, 5), np.uint8)
        glare_mask = cv2.dilate(glare_mask, kernel, iterations=1)
        
        # Holographic Region Detection - NEW
        holo_mask = detect_holographic_regions(card_roi)
        holo_percentage = (cv2.countNonZero(holo_mask) / total_card_area) * 100 if total_card_area > 0 else 0
        
        # Combine exclusion masks (glare + holo)
        exclusion_mask = cv2.bitwise_or(glare_mask, holo_mask)
        
        # Scratch Detection
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(card_gray)
        
        scratch_edges = cv2.Canny(enhanced, 120, 200)
        # Exclude both glare AND holo regions from scratch detection
        scratch_edges = cv2.bitwise_and(scratch_edges, cv2.bitwise_not(exclusion_mask))
        
        line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5))
        vertical_lines = cv2.morphologyEx(scratch_edges, cv2.MORPH_OPEN, line_kernel)
        line_kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
        horizontal_lines = cv2.morphologyEx(scratch_edges, cv2.MORPH_OPEN, line_kernel_h)
        
        scratches_combined = cv2.bitwise_or(vertical_lines, horizontal_lines)
        scratch_contours, _ = cv2.findContours(scratches_combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        valid_scratches = []
        for cnt in scratch_contours:
            area = cv2.contourArea(cnt)
            if area < min_scratch_area: continue
            # Filter by aspect ratio: real scratches are elongated (>3:1)
            _, (sw, sh) = cv2.minAreaRect(cnt)[:2]
            if sw > 0 and sh > 0:
                aspect = max(sw, sh) / min(sw, sh)
                if aspect < 3.0:
                    continue  # Compact shape — likely texture, not a scratch
            valid_scratches.append(area)

        scratch_count = len(valid_scratches)
        # Total scratch pixel area as a percentage of card area.
        # A single long crease scores worse than many tiny nicks at the same count.
        total_scratch_area_pct = (sum(valid_scratches) / total_card_area * 100) if total_card_area > 0 else 0.0

        # Major Damage (Crease/Dent/Stain) - resolution-independent
        _, dark_mask = cv2.threshold(card_gray, 25, 255, cv2.THRESH_BINARY_INV)
        dark_mask = cv2.bitwise_and(dark_mask, cv2.bitwise_not(exclusion_mask))

        dark_contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Use resolution-independent threshold
        major_damage = [c for c in dark_contours if cv2.contourArea(c) > major_damage_threshold]
        major_damage_detected = len(major_damage) > 0

        # Area-weighted scratch scoring — one long crease scores worse than many tiny nicks.
        # Bands expressed as % of total card area covered by valid scratch contours.
        if total_scratch_area_pct == 0:
            score = 10.0
        elif total_scratch_area_pct < 0.05:
            score = 9.5
        elif total_scratch_area_pct < 0.15:
            score = 9.0
        elif total_scratch_area_pct < 0.30:
            score = 8.5
        elif total_scratch_area_pct < 0.60:
            score = 8.0
        elif total_scratch_area_pct < 1.20:
            score = 7.0
        elif total_scratch_area_pct < 2.50:
            score = 6.0
        elif total_scratch_area_pct < 4.00:
            score = 5.0
        else:
            score = 4.0

        # Apply major damage penalty (creases, dents, stains)
        if major_damage_detected:
            score = min(score, 3.0)  # Creases/dents cap at 3

        # Border stain detection — build a thin ring mask (3% of smaller dimension)
        # and check for localised colour anomalies in the LAB a*/b* channels.
        stain_pct = 0.0
        stain_detected = False
        try:
            border_px = max(10, int(min(card_roi.shape[:2]) * 0.03))
            border_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (border_px, border_px)
            )
            full_mask_s = np.ones(card_roi.shape[:2], dtype=np.uint8) * 255
            inner_mask_s = cv2.erode(full_mask_s, border_kernel, iterations=1)
            border_ring = cv2.subtract(full_mask_s, inner_mask_s)
            # Exclude glare/holo from stain analysis
            border_ring = cv2.bitwise_and(border_ring, cv2.bitwise_not(exclusion_mask))
            stain_pct = _detect_border_staining(card_roi, border_ring)
            stain_detected = stain_pct > 1.0
            # Cap score for visible staining
            if stain_pct > 15.0:
                score = min(score, 6.0)
            elif stain_pct > 5.0:
                score = min(score, 8.0)
        except Exception:
            pass  # Stain detection failure is non-fatal

        # Calculate confidence based on excluded regions
        glare_pixels = cv2.countNonZero(glare_mask)
        glare_percentage = (glare_pixels / total_card_area) * 100 if total_card_area > 0 else 0

        # Obscured area reduces confidence
        obscured_percentage = (cv2.countNonZero(exclusion_mask) / total_card_area) * 100 if total_card_area > 0 else 0

        confidence = 1.0
        if obscured_percentage > 40:
            confidence = 0.6
        elif obscured_percentage > 25:
            confidence = 0.7
        elif obscured_percentage > 15:
            confidence = 0.85
        # Large glare mask means a meaningful portion could not be assessed
        if glare_percentage > 20:
            confidence = min(confidence, 0.7)
        
        # Generate analysis note
        note = None
        if holo_percentage > 30:
            note = "Holographic card - surface grading confidence reduced"
        elif glare_percentage > 15:
            note = "High glare detected - retake with diffused lighting"
        
        # Wrapped return
        return {
            "surface": {
                "score": score,
                "scratch_count": scratch_count,
                "scratch_area_pct": round(total_scratch_area_pct, 3),
                "major_damage_detected": major_damage_detected,
                "stain_pct": round(stain_pct, 2),
                "stain_detected": stain_detected,
                "confidence": confidence,
                "glare_percentage": round(glare_percentage, 1),
                "holo_percentage": round(holo_percentage, 1),
                "note": note
            }
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_surface_damage(sys.argv[1]), indent=2))

