import cv2
import numpy as np
from .utils import find_card_contour

def _calculate_centering_grade_smooth(worst_ratio):
    """
    Calculate centering grade with smooth linear interpolation.
    No sharp boundaries - gradual scoring between thresholds.
    
    Args:
        worst_ratio: The smaller of horizontal and vertical centering ratios
    
    Returns:
        Grade estimate (float)
    """
    # Define calibrated thresholds (ratio, grade)
    # Recalibrated to remove need for 1.25x boost
    thresholds = [
        (1.00, 10.0),   # Perfect
        (0.95, 10.0),   # Near perfect
        (0.90, 9.0),    # Excellent  
        (0.85, 8.5),    # Very good
        (0.80, 8.0),    # Good
        (0.75, 7.5),    # Fair
        (0.70, 7.0),    # Acceptable
        (0.65, 6.5),    # Poor
        (0.00, 5.0),    # Very poor
    ]
    
    # Linear interpolation between thresholds
    for i in range(len(thresholds) - 1):
        upper_ratio, upper_grade = thresholds[i]
        lower_ratio, lower_grade = thresholds[i + 1]
        
        if worst_ratio >= lower_ratio:
            # Interpolate between these two points
            if upper_ratio == lower_ratio:
                return upper_grade
            
            ratio_range = upper_ratio - lower_ratio
            grade_range = upper_grade - lower_grade
            ratio_position = (worst_ratio - lower_ratio) / ratio_range
            
            grade = lower_grade + (grade_range * ratio_position)
            return round(grade, 1)
    
    return 5.0  # Fallback

def calculate_centering_ratios(image_path: str) -> dict:
    """
    Analyzes a Pokemon card image to determine centering ratios.
    """
    try:
        # 1. Load Image
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        # 2. Find Exterior Contour (Outer Border)
        result = find_card_contour(image)
        if not result:
             # Just return a rough estimate if we can't find it clearly?
             # No, spec says "conservative bias". Error implies manual review needed.
             return {"error": "No card detected."}
        
        _, (ox, oy, ow, oh) = result
        outer_area = ow * oh

        # 3. Search for Inner Border (Artwork)
        roi = image[oy:oy+oh, ox:ox+ow]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_blur = cv2.GaussianBlur(roi_gray, (5, 5), 0)
        roi_edges = cv2.Canny(roi_blur, 30, 100)
        
        roi_contours, _ = cv2.findContours(roi_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        inner_candidates = []
        for cnt in roi_contours:
            perimeter = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * perimeter, True)
            
            if len(approx) == 4:
                rect = cv2.boundingRect(approx)
                ix, iy, iw, ih = rect
                area = iw * ih
                
                # Check if it's substantially smaller than the outer box but large enough
                # Artwork is usually ~60-80% of the card area
                if area < (outer_area * 0.95) and area > (outer_area * 0.3):
                    inner_candidates.append((area, rect))

        inner_candidates.sort(key=lambda x: x[0], reverse=True)
        
        if not inner_candidates:
             return {
                "error": "Card found, but inner artwork frame not detected.",
                "grade_estimate": 8.0 # Conservative fail-safe
            }
            
        _, (rix, riy, riw, rih) = inner_candidates[0]
        
        # Calculate Borders
        left_border = max(1, rix)
        top_border = max(1, riy)
        right_border = max(1, ow - (rix + riw))
        bottom_border = max(1, oh - (riy + rih))

        # Calculate Ratios (Smaller / Larger) as per spec
        ratio_h = min(left_border, right_border) / max(left_border, right_border)
        ratio_v = min(top_border, bottom_border) / max(top_border, bottom_border)
        
        # Calculate worst ratio (conservative)
        worst_ratio = min(ratio_h, ratio_v)
        
        # Smooth grade calculation with linear interpolation (no sharp boundaries)
        est_grade = _calculate_centering_grade_smooth(worst_ratio)
        
        # Calculate confidence based on detection quality
        confidence_factors = []
        
        # Factor 1: Were all borders detected?
        if all([left_border > 0, right_border > 0, top_border > 0, bottom_border > 0]):
            confidence_factors.append(1.0)
        else:
            confidence_factors.append(0.3)
        
        # Factor 2: Are measurements consistent?
        h_variance = abs(left_border - right_border) / max(left_border, right_border)
        v_variance = abs(top_border - bottom_border) / max(top_border, bottom_border)
        
        if h_variance < 0.15 and v_variance < 0.15:
            confidence_factors.append(1.0)
        elif h_variance < 0.30 and v_variance < 0.30:
            confidence_factors.append(0.7)
        else:
            confidence_factors.append(0.4)
        
        # Factor 3: Artwork frame was detected
        confidence_factors.append(1.0)  # If we got here, frame was detected
        
        overall_confidence = sum(confidence_factors) / len(confidence_factors)

        return {
            "horizontal": {
                "left_px": left_border,
                "right_px": right_border,
                "ratio": round(ratio_h, 3),
            },
            "vertical": {
                "top_px": top_border,
                "bottom_px": bottom_border,
                "ratio": round(ratio_v, 3),
            },
            "worst_ratio": round(worst_ratio, 3),
            "grade_estimate": est_grade,
            "confidence": round(overall_confidence, 2)
        }

    except Exception as e:
        return {"error": str(e), "grade_estimate": 0, "confidence": 0.0}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(calculate_centering_ratios(sys.argv[1]), indent=2))
