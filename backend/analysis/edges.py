import cv2
import numpy as np
from .utils import find_card_contour, order_points

def analyze_edge_wear(image_path: str) -> dict:
    """
    Analyzes the 4 edges of a Pokemon card for whitening/wear.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        result = find_card_contour(image)
        if not result:
            return {"error": "Card not detected."}
            
        card_approx, (x, y, w, h) = result
        
        if len(card_approx) != 4:
            card_approx = np.array([[x,y], [x+w,y], [x+w,y+h], [x,y+h]], dtype="float32")
        
        # Edge regions
        edge_thickness = max(10, min(w, h) // 30)
        
        edge_regions = {
            "top": (x, y, w, edge_thickness),
            "bottom": (x, y + h - edge_thickness, w, edge_thickness),
            "left": (x, y, edge_thickness, h),
            "right": (x + w - edge_thickness, y, edge_thickness, h)
        }
        
        results = {}
        img_h, img_w = image.shape[:2]
        
        for edge_name, (ex, ey, ew, eh) in edge_regions.items():
            ex = max(0, ex)
            ey = max(0, ey)
            ew = min(ew, img_w - ex)
            eh = min(eh, img_h - ey)
            
            if ew <= 0 or eh <= 0:
                results[edge_name] = {"score": 5, "note": "Region error"}
                continue
            
            roi = image[ey:ey+eh, ex:ex+ew]
            if roi.size == 0:
                results[edge_name] = {"score": 5, "note": "ROI empty"}
                continue
            
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            lower_white = np.array([0, 0, 180])
            upper_white = np.array([180, 50, 255])
            
            mask = cv2.inRange(hsv, lower_white, upper_white)
            white_pixels = cv2.countNonZero(mask)
            
            total_pixels = roi.shape[0] * roi.shape[1]
            whitening_percentage = (white_pixels / total_pixels) * 100 if total_pixels > 0 else 0
            
            # Detailed Scoring per Spec
            score = 10.0
            if whitening_percentage <= 0.5: score = 10.0
            elif whitening_percentage <= 1.5: score = 9.5
            elif whitening_percentage <= 3.0: score = 9.0 # Minor specks
            elif whitening_percentage <= 10.0: score = 8.5 # Continuous/Noticeable
            elif whitening_percentage <= 25.0: score = 8.0
            elif whitening_percentage <= 50.0: score = 7.0
            else: score = 4.0 # Severe
            
            results[edge_name] = {
                "score": score,
                "whitening_percentage": round(whitening_percentage, 2),
            }
        
        return {
            "edges": results
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_edge_wear(sys.argv[1]), indent=2))
