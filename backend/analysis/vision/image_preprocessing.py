"""
Image preprocessing utilities for robust card detection.
"""
import cv2
import numpy as np
from typing import Optional, Tuple

# Pokémon card dimensions (standard TCG size)
POKEMON_CARD_ASPECT_RATIO = 2.5 / 3.5  # Width / Height = ~0.714
ASPECT_RATIO_TOLERANCE = 0.10  # ±10% tolerance


def enhance_card_image(image: np.ndarray) -> np.ndarray:
    """
    Enhance image quality for better card detection.
    
    Args:
        image: Input BGR image
        
    Returns:
        Enhanced BGR image
    """
    # Convert to LAB color space
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    
    # Convert back to BGR
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    
    # Reduce noise
    enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)
    
    return enhanced


def create_card_mask(image: np.ndarray) -> np.ndarray:
    """
    Create binary mask highlighting potential card regions.
    
    Args:
        image: Input BGR image
        
    Returns:
        Binary mask (0 or 255)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Method 1: Adaptive thresholding
    adaptive = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=2
    )
    
    # Method 2: Otsu's thresholding
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Combine both methods
    combined = cv2.bitwise_or(adaptive, otsu)
    
    # Morphological operations to clean up
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    
    # Close small gaps
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    # Remove small noise
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)
    
    return combined


def is_valid_card_contour(
    contour: np.ndarray,
    image_shape: Tuple[int, int],
    min_area_percent: float = 20.0,
    max_area_percent: float = 90.0
) -> bool:
    """
    Validate if contour represents a Pokémon card.
    
    Args:
        contour: Contour to validate
        image_shape: (height, width) of the image
        min_area_percent: Minimum area as % of image
        max_area_percent: Maximum area as % of image
        
    Returns:
        True if valid card contour
    """
    # Calculate contour area
    area = cv2.contourArea(contour)
    image_area = image_shape[0] * image_shape[1]
    area_percent = (area / image_area) * 100
    
    # Check area bounds
    if area_percent < min_area_percent or area_percent > max_area_percent:
        return False
    
    # Get bounding rectangle
    x, y, w, h = cv2.boundingRect(contour)
    
    # Check aspect ratio
    aspect_ratio = float(w) / h
    expected_ratio = POKEMON_CARD_ASPECT_RATIO
    
    lower_bound = expected_ratio * (1 - ASPECT_RATIO_TOLERANCE)
    upper_bound = expected_ratio * (1 + ASPECT_RATIO_TOLERANCE)
    
    # Relax aspect ratio check slightly for perspective distorted cards
    # If the user took the photo, it might be landscape (rotated 90 deg)
    # Check both portrait and landscape ratios
    inv_expected = 1.0 / POKEMON_CARD_ASPECT_RATIO
    inv_lower = inv_expected * (1 - ASPECT_RATIO_TOLERANCE)
    inv_upper = inv_expected * (1 + ASPECT_RATIO_TOLERANCE)
    
    is_portrait = lower_bound <= aspect_ratio <= upper_bound
    is_landscape = inv_lower <= aspect_ratio <= inv_upper
    
    if not (is_portrait or is_landscape):
        return False
    
    # Check if contour is roughly rectangular (4 corners)
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    
    # Should have 4 corners (or close to it)
    if len(approx) < 4 or len(approx) > 8:
        return False
    
    return True


def find_card_contour(
    image: np.ndarray,
    debug: bool = False
) -> Optional[np.ndarray]:
    """
    Detect the card boundary contour in an image.
    
    Args:
        image: Input BGR image
        debug: If True, return debug info
        
    Returns:
        Largest valid card contour, or None if not found
    """
    # Enhance image
    enhanced = enhance_card_image(image)
    
    # Create binary mask
    mask = create_card_mask(enhanced)
    
    # Find contours
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )
    
    if len(contours) == 0:
        return None
    
    # Filter valid card contours
    valid_contours = [
        cnt for cnt in contours
        if is_valid_card_contour(cnt, image.shape[:2])
    ]
    
    # Return largest valid contour
    if valid_contours:
        card_contour = max(valid_contours, key=cv2.contourArea)
        return card_contour
        
    # Fallback: Check if the image itself is the card (pre-cropped)
    # The frontend app often crops to the card frame.
    h, w = image.shape[:2]
    if h > 0 and w > 0:
        aspect = min(w, h) / max(w, h)
        # Accept if aspect ratio is roughly correct (allow some variance)
        # Pokemon cards are ~0.714
        if 0.60 <= aspect <= 0.85:
            # Create a contour that covers the whole image
            full_image_contour = np.array([
                [0, 0],
                [w-1, 0],
                [w-1, h-1],
                [0, h-1]
            ], dtype=np.int32)
            
            return full_image_contour

    return None


def get_card_corners(contour: np.ndarray) -> np.ndarray:
    """
    Extract 4 corner points from card contour.
    
    Args:
        contour: Card boundary contour
        
    Returns:
        4x2 array of corner points [top-left, top-right, bottom-right, bottom-left]
    """
    # Approximate to polygon
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    
    # If we got exactly 4 points, we're done
    if len(approx) == 4:
        points = approx.reshape(4, 2)
    else:
        # Otherwise, use bounding rectangle corners
        rect = cv2.minAreaRect(contour)
        points = cv2.boxPoints(rect)
    
    # Sort corners: top-left, top-right, bottom-right, bottom-left
    points = points.astype(np.float32)
    
    # Logic to sort points order effectively
    # Top-left has smallest sum (x+y)
    # Bottom-right has largest sum
    # Top-right has smallest difference (y-x) or largest (x-y)
    # Bottom-left has largest difference... 
    
    # Alternative robust sorting:
    center = points.mean(axis=0)
    sorted_points = np.zeros((4, 2), dtype=np.float32)
    
    for p in points:
        if p[0] < center[0] and p[1] < center[1]:
            sorted_points[0] = p # TL
        elif p[0] > center[0] and p[1] < center[1]:
            sorted_points[1] = p # TR
        elif p[0] > center[0] and p[1] > center[1]:
            sorted_points[2] = p # BR
        elif p[0] < center[0] and p[1] > center[1]:
            sorted_points[3] = p # BL
            
    # Fallback to simple sum sort if bounding box aligned
    if np.all(sorted_points == 0):
         s = points.sum(axis=1)
         d = np.diff(points, axis=1)
         sorted_points[0] = points[np.argmin(s)]
         sorted_points[2] = points[np.argmax(s)]
         sorted_points[1] = points[np.argmin(d)]
         sorted_points[3] = points[np.argmax(d)]
            
    return sorted_points


def perspective_correct_card(
    image: np.ndarray,
    corners: np.ndarray,
    output_width: int = 500,
    output_height: int = 700
) -> np.ndarray:
    """
    Apply perspective transformation to get top-down view of card.
    
    Args:
        image: Input BGR image
        corners: 4 corner points of card
        output_width: Desired output width
        output_height: Desired output height
        
    Returns:
        Perspective-corrected card image
    """
    # Destination points (rectangle)
    dst = np.array([
        [0, 0],
        [output_width - 1, 0],
        [output_width - 1, output_height - 1],
        [0, output_height - 1]
    ], dtype=np.float32)
    
    # Calculate perspective transform matrix
    matrix = cv2.getPerspectiveTransform(corners, dst)
    
    # Apply transformation
    corrected = cv2.warpPerspective(
        image,
        matrix,
        (output_width, output_height)
    )
    
    return corrected
