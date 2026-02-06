"""
Advanced edge wear detection using color space analysis.
"""
import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from .vision.image_preprocessing import find_card_contour


def create_border_mask(
    image: np.ndarray,
    contour: np.ndarray,
    border_thickness: int = 30
) -> np.ndarray:
    """
    Create a mask isolating the card border region.
    
    Args:
        image: Input image
        contour: Card boundary contour
        border_thickness: Width of border in pixels
        
    Returns:
        Binary mask of border region
    """
    # Create full card mask
    full_mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.drawContours(full_mask, [contour], -1, 255, -1)
    
    # Create inner mask (eroded)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (border_thickness, border_thickness))
    inner_mask = cv2.erode(full_mask, kernel, iterations=1)
    
    # Border = full - inner
    border_mask = cv2.subtract(full_mask, inner_mask)
    
    return border_mask


def detect_blue_regions(image: np.ndarray) -> np.ndarray:
    """
    Detect blue regions (Pokémon card borders are blue).
    
    Args:
        image: BGR image
        
    Returns:
        Binary mask of blue regions
    """
    # Convert to HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    
    # Define blue color range
    # Hue: 100-130 (blue)
    # Saturation: 50-255 (avoid gray/white)
    # Value: 30-255 (avoid pure black)
    # Broadened range to catch dark/light blues
    lower_blue = np.array([90, 40, 20])
    upper_blue = np.array([140, 255, 255])
    
    blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)
    
    # Clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_OPEN, kernel)
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, kernel)
    
    return blue_mask


def analyze_whitening_in_region(
    image: np.ndarray,
    mask: np.ndarray
) -> Tuple[float, int, int]:
    """
    Analyze whitening (lightness) in a masked region.
    
    Args:
        image: BGR image
        mask: Binary mask of region to analyze
        
    Returns:
        (whitening_percentage, whitened_pixels, total_pixels)
    """
    if cv2.countNonZero(mask) == 0:
        return 0.0, 0, 0

    # Convert to LAB color space (better for lightness)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]  # Lightness channel
    
    # Extract pixels in the masked region
    region_pixels = l_channel[mask > 0]
    
    if len(region_pixels) == 0:
        return 0.0, 0, 0
    
    # Threshold for "whitened" pixels
    # In LAB space, L ranges 0-255
    # Pure blue should be around 50-120
    # Whitened blue (edge wear) will be 150+
    WHITENING_THRESHOLD = 155
    
    whitened_pixels = np.sum(region_pixels > WHITENING_THRESHOLD)
    total_pixels = len(region_pixels)
    
    whitening_percentage = (whitened_pixels / total_pixels) * 100
    
    return whitening_percentage, whitened_pixels, total_pixels


def split_edges(
    border_mask: np.ndarray,
    image_shape: Tuple[int, int]
) -> Dict[str, np.ndarray]:
    """
    Split border mask into 4 edges (top, right, bottom, left).
    
    Args:
        border_mask: Binary mask of border region
        image_shape: (height, width) of image
        
    Returns:
        Dict mapping edge name to mask
    """
    height, width = image_shape
    
    # Define regions
    edges = {
        'top': np.zeros_like(border_mask),
        'right': np.zeros_like(border_mask),
        'bottom': np.zeros_like(border_mask),
        'left': np.zeros_like(border_mask)
    }
    
    # Top edge (top 20%)
    limit_y = int(height * 0.20)
    edges['top'][:limit_y, :] = border_mask[:limit_y, :]
    
    # Bottom edge (bottom 20%)
    limit_y_btm = int(height * 0.80)
    edges['bottom'][limit_y_btm:, :] = border_mask[limit_y_btm:, :]
    
    # Left edge (left 20%)
    limit_x = int(width * 0.20)
    edges['left'][:, :limit_x] = border_mask[:, :limit_x]
    
    # Right edge (right 20%)
    limit_x_right = int(width * 0.80)
    edges['right'][:, limit_x_right:] = border_mask[:, limit_x_right:]
    
    return edges


def score_whitening_percentage(whitening_pct: float) -> float:
    """
    Convert whitening percentage to score (1-10).
    
    Args:
        whitening_pct: Percentage of whitened pixels
        
    Returns:
        Score from 1.0 to 10.0
    """
    if whitening_pct < 0.2:
        return 10.0  # Gem Mint
    elif whitening_pct < 0.5:
        return 9.5
    elif whitening_pct < 1.0:
        return 9.0  # Mint
    elif whitening_pct < 1.5:
        return 8.5
    elif whitening_pct < 2.5:
        return 8.0  # NM-MT
    elif whitening_pct < 4.0:
        return 7.0
    elif whitening_pct < 6.0:
        return 6.0
    elif whitening_pct < 8.0:
        return 5.0
    elif whitening_pct < 12.0:
        return 4.0
    elif whitening_pct < 18.0:
        return 3.0
    else:
        return max(1.0, 3.0 - (whitening_pct - 18.0) / 10.0)


def analyze_edge_wear(
    image_path: str,
    debug_output_path: Optional[str] = None
) -> Dict:
    """
    Analyze edge wear (whitening) on card borders.
    
    Args:
        image_path: Path to card image
        debug_output_path: Optional path to save debug visualization
        
    Returns:
        Dict with edge analysis results
    """
    # Load image
    image = cv2.imread(image_path)
    if image is None:
        return {
            "success": False,
            "error": "Could not load image",
            "score": 5.0,
            "grade_estimate": 5.0
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
    
    # Create border mask (30px is a heuristic, scalable with image size?)
    # Ideally scaled by image size. A standard card is ~2000px high.
    # 30px is ~1.5%. Let's adapt it.
    h, w = image.shape[:2]
    border_px = max(15, int(min(h, w) * 0.03)) # 3% of width
    
    border_mask = create_border_mask(image, card_contour, border_thickness=border_px)
    
    # Detect blue regions (card borders) -- This assumes Pokemon card BACK or blue border front
    # If it's a front image that is NOT blue (e.g. fire type), this blue check might fail.
    # But usually front edges are silver/yellow.
    # Spec implied this is mostly for the BACK of the card where wear is visible.
    # But we apply it to front too?
    # Whitening is white paper showing.
    # Let's trust the blue detection for now as most wear analysis is on back or borders.
    # If blue detection returns empty, we might skip or fallback?
    blue_mask = detect_blue_regions(image)
    
    # Combine: we only care about blue border regions
    # If valid blue border found, intersect. If not (maybe front of non-blue card), use border mask?
    # Whitening relies on contrast against dark border.
    if cv2.countNonZero(blue_mask) > (cv2.countNonZero(border_mask) * 0.1):
        edge_mask = cv2.bitwise_and(border_mask, blue_mask)
    else:
        # Fallback: just use geometric border if colors don't match blue
        # Risk: Might detect artwork as whitening
        edge_mask = border_mask
    
    # Analyze overall whitening
    whitening_pct, whitened_px, total_px = analyze_whitening_in_region(image, edge_mask)
    
    # Split into individual edges for detailed analysis
    edge_masks = split_edges(edge_mask, image.shape[:2])
    edge_details = {}
    edges_data_legacy = {} # For backward compatibility
    
    for edge_name, edge_specific_mask in edge_masks.items():
        pct, white_px, tot_px = analyze_whitening_in_region(image, edge_specific_mask)
        score = score_whitening_percentage(pct)
        
        edge_details[edge_name] = {
            "whitening_pct": round(pct, 2),
            "whitened_pixels": white_px,
            "total_pixels": tot_px,
            "score": round(score, 1)
        }
        # Backward compatibility format
        edges_data_legacy[edge_name] = {"score": round(score, 1)}
    
    # Overall score (use worst edge vs average?)
    # Spec says "Worst Case" driven.
    worst_edge_score = min(details['score'] for details in edge_details.values())
    overall_whitening_score = score_whitening_percentage(whitening_pct)
    
    # Weighted final: heavy weight on worst edge
    final_score = min(overall_whitening_score, worst_edge_score)
    
    # Determine condition description
    if final_score >= 9.5:
        condition = "Gem Mint edges - no visible wear"
    elif final_score >= 9.0:
        condition = "Mint edges - minimal wear"
    elif final_score >= 8.0:
        condition = "Near Mint edges - slight wear visible"
    elif final_score >= 7.0:
        condition = "Light edge wear detected"
    elif final_score >= 5.0:
        condition = "Moderate edge wear"
    else:
        condition = "Heavy edge wear"
    
    # Count worn edges (score < 8.0)
    worn_edges = [name for name, details in edge_details.items() if details['score'] < 8.0]
    
    # Debug visualization
    if debug_output_path:
        debug_img = image.copy()
        
        # Overlay edge mask in red (regions checked)
        red_overlay = np.zeros_like(image)
        red_overlay[edge_mask > 0] = [0, 0, 255]
        debug_img = cv2.addWeighted(debug_img, 0.7, red_overlay, 0.3, 0)
        
        # Highlight whitened areas in yellow (wear detected)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        # Re-calc mask for viz
        whitened_areas = (lab[:, :, 0] > 155) & (edge_mask > 0)
        
        yellow_overlay = np.zeros_like(image)
        yellow_overlay[whitened_areas] = [0, 255, 255]
        debug_img = cv2.addWeighted(debug_img, 1.0, yellow_overlay, 0.5, 0) # Stronger overlay
        
        # Add text overlay
        cv2.putText(debug_img, f"Edge Score: {final_score:.1f}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        cv2.putText(debug_img, f"Whitening: {whitening_pct:.2f}%", (10, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        cv2.putText(debug_img, condition, (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        
        cv2.imwrite(debug_output_path, debug_img)
    
    return {
        "success": True,
        "score": round(final_score, 1),
        "overall_grade": round(final_score, 1), # Backward compatibility
        "grade_estimate": round(final_score, 1),
        "overall_whitening_pct": round(whitening_pct, 2),
        "condition": condition,
        "worn_edges_list": worn_edges,
        "worn_edge_count": len(worn_edges),
        "edges": edges_data_legacy, # Legacy format
        "detailed_edges": edge_details, # New format
        "confidence": 1.0 if total_px > 1000 else 0.5
    }
