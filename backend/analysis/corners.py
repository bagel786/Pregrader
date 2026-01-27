import cv2
import numpy as np
from .utils import find_card_contour, order_points

def analyze_corner_wear(image_path: str) -> dict:
    """
    Analyzes the 4 corners of a Pokemon card for whitening/wear.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        result = find_card_contour(image)
        if not result:
            return {"error": "Card not detected."}
            
        card_approx, _ = result
        
        # Force 4 points for corner extraction
        if len(card_approx) != 4:
            # Fallback handled in utils usually, but if not:
            x,y,w,h = cv2.boundingRect(card_approx)
            card_approx = np.array([[x,y], [x+w,y], [x+w,y+h], [x,y+h]], dtype="float32")
        
        card_pts = card_approx.reshape(4, 2)
        ordered_pts = order_points(card_pts)

        results = {}
        corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]
        
        roi_size = 60 
        h, w = image.shape[:2]

        for i, (pt_x, pt_y) in enumerate(ordered_pts):
            pt_x, pt_y = int(pt_x), int(pt_y)
            name = corner_names[i]
            
            x1 = max(0, pt_x - roi_size // 2)
            y1 = max(0, pt_y - roi_size // 2)
            x2 = min(w, pt_x + roi_size // 2)
            y2 = min(h, pt_y + roi_size // 2)
            
            roi = image[y1:y2, x1:x2]
            
            if roi.size == 0:
                results[name] = {"score": 5, "whitening_pixels": 0, "note": "Error extracting ROI"}
                continue

            # Whitening Detection
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            lower_white = np.array([0, 0, 180])
            upper_white = np.array([180, 40, 255])
            
            mask = cv2.inRange(hsv, lower_white, upper_white)
            white_pixels = cv2.countNonZero(mask)
            
            # Scoring per Spec
            score = 10.0
            if white_pixels <= 5: score = 10.0
            elif white_pixels <= 20: score = 9.5
            elif white_pixels <= 50: score = 9.0
            elif white_pixels <= 100: score = 8.5
            elif white_pixels <= 200: score = 8.0
            elif white_pixels <= 400: score = 7.0 # Rounded/Damaged
            else: score = 5.0 # Severe
            
            results[name] = {
                "score": score,
                "whitening_pixels": white_pixels,
            }
            
        # Overall grade calculated in grading_system.py, but we return the raw data
        return {
            "corners": results
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_corner_wear(sys.argv[1]), indent=2))
