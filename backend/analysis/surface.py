import cv2
import numpy as np
from .utils import find_card_contour


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
    
    # Threshold variance map - high variance indicates texture/holo
    holo_mask = (variance_map > 200).astype(np.uint8) * 255
    
    # Clean up with morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    holo_mask = cv2.morphologyEx(holo_mask, cv2.MORPH_CLOSE, kernel)
    holo_mask = cv2.morphologyEx(holo_mask, cv2.MORPH_OPEN, kernel)
    
    return holo_mask


def analyze_surface_damage(image_path: str) -> dict:
    """
    Analyzes a Pokemon card image for surface damage including scratches and marks.
    Explicitly flags creases/dents for severe grade capping.
    Now includes holographic region detection to reduce false positives.
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
        min_scratch_area = total_card_area * 0.0001  # 0.01% of card area
        major_damage_threshold = total_card_area * 0.0015  # 0.15% of card area
        
        # Glare Filtering
        hsv = cv2.cvtColor(card_roi, cv2.COLOR_BGR2HSV)
        lower_glare = np.array([0, 0, 230])
        upper_glare = np.array([180, 30, 255])
        glare_mask = cv2.inRange(hsv, lower_glare, upper_glare)
        kernel = np.ones((5, 5), np.uint8)
        glare_mask = cv2.dilate(glare_mask, kernel, iterations=2)
        
        # Holographic Region Detection - NEW
        holo_mask = detect_holographic_regions(card_roi)
        holo_percentage = (cv2.countNonZero(holo_mask) / total_card_area) * 100 if total_card_area > 0 else 0
        
        # Combine exclusion masks (glare + holo)
        exclusion_mask = cv2.bitwise_or(glare_mask, holo_mask)
        
        # Scratch Detection
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(card_gray)
        
        scratch_edges = cv2.Canny(enhanced, 100, 200)
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
            # Use resolution-independent threshold
            if area < min_scratch_area: continue
            valid_scratches.append(area)
            
        scratch_count = len(valid_scratches)
        
        # Major Damage (Crease/Dent/Stain) - resolution-independent
        _, dark_mask = cv2.threshold(card_gray, 40, 255, cv2.THRESH_BINARY_INV)
        dark_mask = cv2.bitwise_and(dark_mask, cv2.bitwise_not(exclusion_mask))
        
        dark_contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Use resolution-independent threshold
        major_damage = [c for c in dark_contours if cv2.contourArea(c) > major_damage_threshold] 
        major_damage_detected = len(major_damage) > 0
        
        # More lenient scoring
        score = 10.0
        if scratch_count == 0: score = 10.0
        elif scratch_count <= 3: score = 9.5
        elif scratch_count <= 7: score = 9.0
        elif scratch_count <= 12: score = 8.0
        elif scratch_count <= 20: score = 7.0
        else: score = 6.5
        
        # Only apply major damage penalty if really severe
        if major_damage_detected:
            score = min(score, 7.0)
        
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
                "major_damage_detected": major_damage_detected,
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

