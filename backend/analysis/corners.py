import cv2
import numpy as np

def order_points(pts):
    """
    Orders coordinates in the order: top-left, top-right, bottom-right, bottom-left
    """
    rect = np.zeros((4, 2), dtype="float32")
    
    # Sum: TL is min sum, BR is max sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    
    # Diff: TR is min diff (x-y), BL is max diff (x-y)
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    
    return rect

def analyze_corner_wear(image_path: str) -> dict:
    """
    Analyzes the 4 corners of a Pokemon card for whitening/wear.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        # 1. Find Card Contour (Similar to centering.py)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) # External only for outer shape

        candidates = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            if len(approx) == 4:
                rect = cv2.boundingRect(approx)
                area = rect[2] * rect[3]
                if area > 5000: # Slightly higher threshold
                    candidates.append((area, approx))
        
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        if not candidates:
            return {"error": "Card not detected."}

        # Largest 4-sided polygon is the card
        _, card_approx = candidates[0]
        card_pts = card_approx.reshape(4, 2)
        ordered_pts = order_points(card_pts) # TL, TR, BR, BL

        results = {}
        corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]
        
        total_whitening_score = 0
        
        # 2. Extract and Analyze Each Corner
        # ROI Size: Dynamic based on card size? Let's use fixed 60x60 for now, 
        # but in production should be relative to resolution (e.g. 5% of width).
        roi_size = 60 
        
        h, w = image.shape[:2]

        for i, (pt_x, pt_y) in enumerate(ordered_pts):
            pt_x, pt_y = int(pt_x), int(pt_y)
            name = corner_names[i]
            
            # Calculate crop coordinates with boundary checks
            x1 = max(0, pt_x - roi_size // 2)
            y1 = max(0, pt_y - roi_size // 2)
            x2 = min(w, pt_x + roi_size // 2)
            y2 = min(h, pt_y + roi_size // 2)
            
            roi = image[y1:y2, x1:x2]
            
            if roi.size == 0:
                results[name] = {"error": "ROI empty"}
                continue

            # 3. Whitening Detection
            # Convert to HSV
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            
            # Define White/Grey ranges
            # Low Saturation, High Brightness
            lower_white = np.array([0, 0, 180])   # Very low sat, bright
            upper_white = np.array([180, 40, 255]) # Allow slight hue, low sat, max brightness
            
            mask = cv2.inRange(hsv, lower_white, upper_white)
            
            # Count white pixels
            white_pixels = cv2.countNonZero(mask)
            
            # Score (10 = Perfect, 1 = Ruined)
            # Thresholds need tuning.
            # 0-10 pixels: 10
            # 10-50 pixels: 9
            # 50-100 pixels: 8
            # ...
            score = 10
            if white_pixels > 10: score = 9
            if white_pixels > 50: score = 8
            if white_pixels > 120: score = 7
            if white_pixels > 200: score = 6
            if white_pixels > 300: score = 5
            
            total_whitening_score += score
            
            results[name] = {
                "score": score,
                "whitening_pixels": white_pixels,
                # "debug_roi_center": (pt_x, pt_y)
            }
            
        final_grade = round(total_whitening_score / 4.0, 1)

        return {
            "corners": results,
            "overall_corner_grade": final_grade
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(analyze_corner_wear(sys.argv[1]))
    else:
        print("Usage: python corners.py <image_path>")
