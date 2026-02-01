import cv2
import numpy as np
from .utils import find_card_contour, order_points

def _calculate_edge_score_smooth(whitening_percentage):
    """
    Calculate edge score with smooth interpolation.
    
    Args:
        whitening_percentage: Percentage of edge pixels that are white
    
    Returns:
        Score between 5.0 and 10.0
    """
    # Recalibrated thresholds (percentage, score)
    thresholds = [
        (0.0, 10.0),
        (1.0, 10.0),
        (2.5, 9.5),
        (5.0, 9.0),
        (15.0, 8.5),
        (30.0, 8.0),
        (60.0, 7.0),
        (float('inf'), 5.0),
    ]
    
    # Linear interpolation
    for i in range(len(thresholds) - 1):
        lower_pct, upper_score = thresholds[i]
        upper_pct, lower_score = thresholds[i + 1]
        
        if whitening_percentage <= upper_pct:
            if upper_pct == lower_pct:
                return upper_score
            
            pct_range = upper_pct - lower_pct
            score_range = upper_score - lower_score
            pct_position = (whitening_percentage - lower_pct) / pct_range if pct_range > 0 else 0
            
            score = upper_score - (score_range * pct_position)
            return round(score, 1)
    
    return 5.0  # Fallback


def calculate_edge_grade(edge_scores_dict):
    """
    Calculate overall edge grade from 4 edge measurements.
    Considers multiple edges with wear and applies gradual penalties.
    
    Args:
        edge_scores_dict: Dictionary of edge scores
    
    Returns:
        Final edge grade
    """
    scores = list(edge_scores_dict.values())
    
    if not scores:
        return 7.0
    
    # Count how many edges have wear
    edges_with_wear = sum(1 for s in scores if s < 9.0)
    
    # Average the scores
    avg_score = sum(scores) / len(scores)
    
    # Apply penalty for multiple edges with wear
    if edges_with_wear >= 3:
        # Wear on 3-4 edges significantly impacts grade
        penalty = edges_with_wear * 0.4
    elif edges_with_wear >= 2:
        # Wear on 2 edges moderate impact
        penalty = 0.5
    else:
        # Wear on 0-1 edges minimal impact
        penalty = 0
    
    final_score = max(avg_score - penalty, min(scores))
    
    return round(final_score, 1)

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
            
            # Smooth scoring with interpolation
            score = _calculate_edge_score_smooth(whitening_percentage)
            
            results[edge_name] = {
                "score": score,
                "whitening_percentage": round(whitening_percentage, 2),
            }
        
        # Calculate overall edge grade and confidence
        edge_scores = {k: v["score"] for k, v in results.items()}
        overall_grade = calculate_edge_grade(edge_scores)
        
        # Confidence based on ROI extraction success
        confidence = 1.0
        errors = sum(1 for v in results.values() if v.get("note"))
        if errors > 0:
            confidence = max(0.5, 1.0 - (errors * 0.15))
        
        return {
            "edges": results,
            "overall_grade": overall_grade,
            "confidence": confidence
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_edge_wear(sys.argv[1]), indent=2))
