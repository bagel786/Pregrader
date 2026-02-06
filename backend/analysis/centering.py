"""
Improved centering analysis with robust card detection.
"""
import cv2
import numpy as np
from typing import Dict, Optional
from .vision.image_preprocessing import (
    find_card_contour,
    get_card_corners,
    perspective_correct_card
)


def detect_inner_artwork_box(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect the inner artwork/text box of a Pokémon card.
    
    Args:
        image: Card image (should be perspective-corrected)
        
    Returns:
        Bounding rectangle [x, y, w, h] or None
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply Gaussian blur
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Canny edge detection
    edges = cv2.Canny(blurred, 50, 150)
    
    # Find contours
    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_SIMPLE
    )
    
    # Filter contours by area and position
    valid_boxes = []
    img_height, img_width = image.shape[:2]
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # Artwork box should be significant but not entire card
        # Typically 15-70% of card area
        if area < (img_width * img_height * 0.15):
            continue
        if area > (img_width * img_height * 0.70):
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        
        # Should be in upper portion of card (not the bottom text box)
        if y > img_height * 0.5:
            continue
        
        # Should have reasonable aspect ratio
        aspect = w / h
        if aspect < 0.8 or aspect > 1.5:
            continue
        
        valid_boxes.append((x, y, w, h))
    
    if not valid_boxes:
        return None
    
    # Return largest valid box (likely the artwork frame)
    return max(valid_boxes, key=lambda box: box[2] * box[3])


def calculate_centering_score(
    left: float,
    right: float,
    top: float,
    bottom: float
) -> float:
    """
    Calculate centering score based on border measurements.
    
    Uses smooth interpolation rather than hard cutoffs.
    
    Args:
        left, right, top, bottom: Border widths in pixels
        
    Returns:
        Score from 1.0 to 10.0
    """
    # Calculate ratios (smaller / larger for each axis)
    lr_ratio = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
    tb_ratio = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
    
    # Average the two ratios
    avg_ratio = (lr_ratio + tb_ratio) / 2.0
    
    # Smooth scoring using linear interpolation
    # Perfect centering (1.00 ratio) = 10.0
    # 0.95 ratio = 9.0
    # 0.90 ratio = 8.0
    # etc.
    if avg_ratio >= 0.975:
        return 10.0
    elif avg_ratio >= 0.95:
        # Interpolate between 9.0 and 10.0
        return 9.0 + (avg_ratio - 0.95) / 0.025
    elif avg_ratio >= 0.90:
        return 8.0 + (avg_ratio - 0.90) / 0.05 * 1.0
    elif avg_ratio >= 0.85:
        return 7.0 + (avg_ratio - 0.85) / 0.05 * 1.0
    elif avg_ratio >= 0.80:
        return 6.0 + (avg_ratio - 0.80) / 0.05 * 1.0
    elif avg_ratio >= 0.75:
        return 5.0 + (avg_ratio - 0.75) / 0.05 * 1.0
    elif avg_ratio >= 0.70:
        return 4.0 + (avg_ratio - 0.70) / 0.05 * 1.0
    else:
        # Very poor centering
        return max(1.0, avg_ratio * 5.0)


def calculate_centering_ratios(
    image_path: str,
    debug_output_path: Optional[str] = None
) -> Dict:
    """
    Analyze card centering and return detailed measurements.
    
    Args:
        image_path: Path to card image
        debug_output_path: Optional path to save debug visualization
        
    Returns:
        Dict with centering analysis results
    """
    # Load image
    image = cv2.imread(image_path)
    if image is None:
        return {
            "success": False,
            "error": "Could not load image",
            "score": 5.0
        }
    
    # Find card boundary
    card_contour = find_card_contour(image)
    if card_contour is None:
        return {
            "success": False,
            "error": "Could not detect card boundary",
            "score": 5.0,
            "grade_estimate": 5.0
        }
    
    # Get corners and apply perspective correction
    corners = get_card_corners(card_contour)
    corrected = perspective_correct_card(image, corners)
    
    # Detect inner artwork box
    artwork_box = detect_inner_artwork_box(corrected)
    if artwork_box is None:
        return {
            "success": False,
            "error": "Could not detect artwork box",
            "score": 6.0, # Slight penalty but don't fail hard
            "grade_estimate": 6.0
        }
    
    x, y, w, h = artwork_box
    img_height, img_width = corrected.shape[:2]
    
    # Calculate border widths
    left = x
    right = img_width - (x + w)
    top = y
    bottom = img_height - (y + h)
    
    # Calculate score
    score = calculate_centering_score(left, right, top, bottom)
    
    # Calculate percentages for display
    total_lr = left + right
    total_tb = top + bottom
    
    left_pct = (left / total_lr * 100) if total_lr > 0 else 50.0
    right_pct = (right / total_lr * 100) if total_lr > 0 else 50.0
    top_pct = (top / total_tb * 100) if total_tb > 0 else 50.0
    bottom_pct = (bottom / total_tb * 100) if total_tb > 0 else 50.0
    
    # Debug visualization
    if debug_output_path:
        debug_img = corrected.copy()
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        # Draw measurements
        cv2.putText(debug_img, f"L: {left}px", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"R: {right}px", (img_width - 100, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug_img, f"Score: {score:.1f}", (10, img_height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        cv2.imwrite(debug_output_path, debug_img)
    
    return {
        "success": True,
        "score": round(score, 1),
        "grade_estimate": round(score, 1), # Backward compatibility
        "measurements": {
            "left_px": left,
            "right_px": right,
            "top_px": top,
            "bottom_px": bottom,
            "left_right_ratio": f"{left_pct:.1f}/{right_pct:.1f}",
            "top_bottom_ratio": f"{top_pct:.1f}/{bottom_pct:.1f}"
        },
        "confidence": 1.0 if score > 3.0 else 0.5
    }

