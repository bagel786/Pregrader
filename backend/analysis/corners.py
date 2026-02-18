import cv2
import numpy as np
import logging
from .utils import find_card_contour, order_points

logger = logging.getLogger(__name__)


def _calculate_corner_score_smooth(whitening_percentage):
    """
    Calculate corner score with smooth interpolation.
    
    Args:
        whitening_percentage: Percentage of white pixels in corner ROI (0-100)
    
    Returns:
        Score between 1.0 and 10.0
    """
    # Resolution-independent thresholds (percentage of ROI area, score)
    thresholds = [
        (0.0, 10.0),     # Perfect
        (0.5, 10.0),     # Near perfect
        (1.5, 9.5),      # Excellent
        (3.0, 9.0),      # Very good
        (5.0, 8.5),      # Good
        (8.0, 8.0),      # Fair
        (12.0, 7.0),     # Acceptable
        (18.0, 6.0),     # Worn
        (25.0, 5.0),     # Heavy wear
        (35.0, 4.0),     # Severe
        (float('inf'), 3.0),  # Destroyed
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
    
    return 3.0  # Fallback for extreme damage


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


def _detect_whitening_adaptive(roi_bgr: np.ndarray) -> float:
    """
    Adaptive whitening detection that works for any card border color.
    
    Instead of using absolute HSV thresholds (which false-positive on 
    yellow/light borders), this compares corner pixels against the 
    local median color. Pixels significantly brighter and less saturated 
    than the local median indicate wear/whitening.
    
    Args:
        roi_bgr: BGR corner ROI image
        
    Returns:
        Whitening percentage (0-100)
    """
    if roi_bgr.size == 0:
        return 0.0
    
    # Convert to LAB for perceptually uniform lightness
    lab = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0].astype(np.float32)
    
    # Also use HSV for saturation info
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    s_channel = hsv[:, :, 1].astype(np.float32)
    
    # Get median lightness and saturation of the ROI
    median_lightness = np.median(l_channel)
    median_saturation = np.median(s_channel)
    
    # Whitened pixels are BOTH:
    # 1. Significantly brighter than median (paper showing through)
    # 2. Less saturated than median (color stripped away)
    
    # Adaptive lightness threshold: must be > median + threshold
    # Higher threshold = less sensitive = fewer false positives
    lightness_threshold = median_lightness + 45
    
    # Saturation threshold: must be below this AND below median
    # Whitened areas lose their color
    sat_threshold = max(median_saturation * 0.5, 30)
    
    # Count pixels matching whitening criteria
    bright_mask = l_channel > lightness_threshold
    desaturated_mask = s_channel < sat_threshold
    
    whitened_mask = bright_mask & desaturated_mask
    
    total_pixels = roi_bgr.shape[0] * roi_bgr.shape[1]
    whitened_pixels = np.sum(whitened_mask)
    
    whitening_pct = (whitened_pixels / total_pixels * 100) if total_pixels > 0 else 0.0
    
    return whitening_pct


def analyze_corner_wear(image_path: str) -> dict:
    """
    Analyzes the 4 corners of a Pokemon card for whitening/wear.
    Uses adaptive whitening detection that works for any card border color.
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
        
        card_pts = np.squeeze(card_approx)
        if card_pts.ndim != 2 or card_pts.shape[0] != 4:
            x, y, w, h = cv2.boundingRect(card_approx)
            card_pts = np.array([[x, y], [x+w, y], [x+w, y+h], [x, y+h]], dtype="float32")
        card_pts = card_pts.reshape(4, 2)
        ordered_pts = order_points(card_pts)

        # Create a mask of just the card area (to exclude background)
        card_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.fillConvexPoly(card_mask, ordered_pts.astype(np.int32), 255)

        results = {}
        corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]
        
        # Get image dimensions first
        h, w = image.shape[:2]
        # Resolution-independent ROI: 4% of card dimension (min 30px for very small images)
        roi_size = max(30, int(min(h, w) * 0.04))

        for i, (pt_x, pt_y) in enumerate(ordered_pts):
            pt_x, pt_y = int(pt_x), int(pt_y)
            name = corner_names[i]
            
            # Set up ROI - position it INSIDE the card (not centered on corner point)
            # This avoids including background pixels
            if "left" in name:
                x1 = max(0, pt_x)
                x2 = min(w, pt_x + roi_size)
            else:
                x1 = max(0, pt_x - roi_size)
                x2 = min(w, pt_x)
            
            if "top" in name:
                y1 = max(0, pt_y)
                y2 = min(h, pt_y + roi_size)
            else:
                y1 = max(0, pt_y - roi_size)
                y2 = min(h, pt_y)
            
            roi = image[y1:y2, x1:x2]
            roi_mask = card_mask[y1:y2, x1:x2]
            
            if roi.size == 0 or roi_mask.size == 0:
                results[name] = {"score": 7.0, "whitening_pixels": 0, "note": "Error extracting ROI"}
                continue

            # Mask the ROI to only include pixels inside the card
            # Set background pixels to the median card color (to not affect scoring)
            if cv2.countNonZero(roi_mask) < roi.size // 6:
                # Less than ~17% of ROI is inside card - unreliable
                results[name] = {"score": 7.0, "whitening_pixels": 0, "note": "ROI mostly outside card"}
                continue
            
            # Apply mask: zero out background pixels
            roi_masked = cv2.bitwise_and(roi, roi, mask=roi_mask)
            
            # Only analyze the card pixels
            # Create a cropped version with just card pixels for coloring
            card_pixels_mask = roi_mask > 0
            if not np.any(card_pixels_mask):
                results[name] = {"score": 7.0, "whitening_pixels": 0, "note": "No card pixels in ROI"}
                continue
            
            # Use adaptive whitening detection
            whitening_pct = _detect_whitening_adaptive(roi_masked)
            
            # Account for masked area: adjust the percentage
            mask_coverage = cv2.countNonZero(roi_mask) / (roi_mask.shape[0] * roi_mask.shape[1])
            if mask_coverage < 0.5:
                # Less than half the ROI is card - reduce confidence but keep the score
                whitening_pct = whitening_pct * mask_coverage  # Scale down false positives
            
            score = _calculate_corner_score_smooth(whitening_pct)
            
            results[name] = {
                "score": score,
                "whitening_pct": round(whitening_pct, 2),
                "mask_coverage": round(mask_coverage, 2),
            }
            
        # Calculate overall corner grade and confidence
        corner_scores = [c["score"] for c in results.values()]
        overall_grade = calculate_corner_grade(corner_scores)
        
        # Confidence based on ROI extraction success
        confidence = 1.0
        if any(c.get("note") for c in results.values()):
            confidence = 0.6  # Had issues extracting some corners
        
        logger.info(
            f"Corner analysis: scores={[c['score'] for c in results.values()]}, "
            f"overall={overall_grade}, confidence={confidence}"
        )
        
        # Overall grade calculated in grading_system.py, but we return the raw data
        return {
            "corners": results,
            "overall_grade": overall_grade,
            "confidence": confidence
        }

    except Exception as e:
        logger.error(f"Corner analysis failed: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        print(json.dumps(analyze_corner_wear(sys.argv[1]), indent=2))
