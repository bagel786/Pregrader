import cv2
import numpy as np
from .utils import find_card_contour, order_points

def _calculate_corner_score_smooth(whitening_pixels):
    """
    Calculate corner score with smooth interpolation.
    
    Args:
        whitening_pixels: Number of white pixels detected in corner
    
    Returns:
        Score between 1.0 and 10.0
    """
    # Recalibrated thresholds (pixels, score)
    thresholds = [
        (0, 10.0),      # Perfect
        (10, 10.0),     # Near perfect
        (30, 9.5),      # Excellent
        (75, 9.0),      # Very good
        (150, 8.5),     # Good
        (300, 8.0),     # Fair
        (500, 7.0),     # Acceptable
        (float('inf'), 6.0),  # Worn
    ]
    
    # Linear interpolation
    for i in range(len(thresholds) - 1):
        lower_px, upper_score = thresholds[i]
        upper_px, lower_score = thresholds[i + 1]
        
        if whitening_pixels <= upper_px:
            if upper_px == lower_px:
                return upper_score
            
            px_range = upper_px - lower_px
            score_range = upper_score - lower_score
            px_position = (whitening_pixels - lower_px) / px_range if px_range > 0 else 0
            
            score = upper_score - (score_range * px_position)
            return round(score, 1)
    
    return 6.0  # Fallback


def calculate_corner_grade(corner_scores):
    """
    Calculate overall corner grade from 4 individual corner assessments.
    Uses averaging with penalty for worst corner.
    
    Args:
        corner_scores: List of 4 corner scores
    
    Returns:
        Final corner grade
    """
    if not corner_scores or len(corner_scores) != 4:
        return 7.0  # Conservative default
    
    # Average all corners
    avg_score = sum(corner_scores) / len(corner_scores)
    
    # Apply penalty based on worst corner
    worst_corner = min(corner_scores)
    
    # Penalty scaling: worse corners have bigger impact
    if worst_corner < 6.0:
        # Severe damage on one corner
        penalty = (6.0 - worst_corner) * 0.5
    elif worst_corner < 8.0:
        # Moderate damage
        penalty = (8.0 - worst_corner) * 0.3
    else:
        # Minor or no damage
        penalty = 0
    
    final_score = max(avg_score - penalty, worst_corner)
    
    return round(final_score, 1)

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
        
        # Get image dimensions first
        h, w = image.shape[:2]
        # Resolution-independent ROI: 4% of card dimension (min 30px for very small images)
        roi_size = max(30, int(min(h, w) * 0.04))

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
            
            # Scoring with smooth interpolation
            score = _calculate_corner_score_smooth(white_pixels)
            
            results[name] = {
                "score": score,
                "whitening_pixels": white_pixels,
            }
            
        # Calculate overall corner grade and confidence
        corner_scores = [c["score"] for c in results.values()]
        overall_grade = calculate_corner_grade(corner_scores)
        
        # Confidence based on ROI extraction success
        confidence = 1.0
        if any(c.get("note") for c in results.values()):
            confidence = 0.6  # Had issues extracting some corners
        
        # Overall grade calculated in grading_system.py, but we return the raw data
        return {
            "corners": results,
            "overall_grade": overall_grade,
            "confidence": confidence
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_corner_wear(sys.argv[1]), indent=2))
