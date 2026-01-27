import cv2
import numpy as np
from .utils import find_card_contour

def analyze_surface_damage(image_path: str) -> dict:
    """
    Analyzes a Pokemon card image for surface damage including scratches and marks.
    explicitly flags creases/dents for severe grade capping.
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
        
        # Glare Filtering
        hsv = cv2.cvtColor(card_roi, cv2.COLOR_BGR2HSV)
        lower_glare = np.array([0, 0, 230])
        upper_glare = np.array([180, 30, 255])
        glare_mask = cv2.inRange(hsv, lower_glare, upper_glare)
        kernel = np.ones((5, 5), np.uint8)
        glare_mask = cv2.dilate(glare_mask, kernel, iterations=2)
        
        # Scratch Detection
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(card_gray)
        
        scratch_edges = cv2.Canny(enhanced, 100, 200)
        scratch_edges = cv2.bitwise_and(scratch_edges, cv2.bitwise_not(glare_mask))
        
        line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5))
        vertical_lines = cv2.morphologyEx(scratch_edges, cv2.MORPH_OPEN, line_kernel)
        line_kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
        horizontal_lines = cv2.morphologyEx(scratch_edges, cv2.MORPH_OPEN, line_kernel_h)
        
        scratches_combined = cv2.bitwise_or(vertical_lines, horizontal_lines)
        scratch_contours, _ = cv2.findContours(scratches_combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        valid_scratches = []
        for cnt in scratch_contours:
            area = cv2.contourArea(cnt)
            if area < 20: continue
            valid_scratches.append(area)
            
        scratch_count = len(valid_scratches)
        
        # Major Damage (Crease/Dent/Stain)
        _, dark_mask = cv2.threshold(card_gray, 40, 255, cv2.THRESH_BINARY_INV)
        dark_mask = cv2.bitwise_and(dark_mask, cv2.bitwise_not(glare_mask))
        
        dark_contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        major_damage = [c for c in dark_contours if cv2.contourArea(c) > 500] 
        major_damage_detected = len(major_damage) > 0
        
        # Scoring
        score = 10.0
        if scratch_count == 0: score = 10.0
        elif scratch_count <= 2: score = 9.0  
        elif scratch_count <= 5: score = 8.5  
        elif scratch_count <= 10: score = 7.5
        else: score = 6.0
        
        if major_damage_detected:
            score = min(score, 6.0)
        
        # Wrapped return
        return {
            "surface": {
                "score": score,
                "scratch_count": scratch_count,
                "major_damage_detected": major_damage_detected
            }
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_surface_damage(sys.argv[1]), indent=2))
