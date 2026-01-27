import cv2
import numpy as np
from .utils import find_card_contour

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
        
        # Grade Mapping (Strict)
        # We take the WORST of the two ratios (conservative)
        worst_ratio = min(ratio_h, ratio_v)
        
        est_grade = 7.0
        if worst_ratio >= 0.95: est_grade = 10.0
        elif worst_ratio >= 0.90: est_grade = 9.5
        elif worst_ratio >= 0.85: est_grade = 9.0
        elif worst_ratio >= 0.80: est_grade = 8.5
        elif worst_ratio >= 0.75: est_grade = 8.0
        else: est_grade = 7.0 # or lower

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
            "grade_estimate": est_grade
        }

    except Exception as e:
        return {"error": str(e), "grade_estimate": 0}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(calculate_centering_ratios(sys.argv[1]), indent=2))
