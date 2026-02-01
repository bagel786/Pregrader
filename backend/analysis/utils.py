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


def calculate_card_score(aspect_ratio, rectangularity, solidity, area_ratio):
    """
    Score how likely a contour is to be a card.
    Higher score = more likely to be a card.
    
    Args:
        aspect_ratio: Width/height ratio (normalized to <1)
        rectangularity: Area / bounding box area
        solidity: Area / convex hull area
        area_ratio: Contour area / image area
    
    Returns:
        Score between 0 and 1
    """
    # Ideal aspect ratio for Pokemon cards is 2.5:3.5 = 0.714
    aspect_score = 1.0 - abs(aspect_ratio - 0.714) / 0.714
    aspect_score = max(0.0, aspect_score)
    
    # Prefer cards that fill 40-80% of frame
    if area_ratio < 0.40:
        area_score = area_ratio / 0.40
    elif area_ratio > 0.80:
        area_score = (0.95 - area_ratio) / 0.15
    else:
        area_score = 1.0
    area_score = max(0.0, min(1.0, area_score))
    
    # Weighted combination
    total_score = (
        aspect_score * 0.40 +      # Aspect ratio most important
        rectangularity * 0.25 +     # Should be rectangular
        solidity * 0.20 +           # Should be solid/convex
        area_score * 0.15           # Reasonable size
    )
    
    return total_score


def find_best_card_contour(contours, image_shape):
    """
    Find the contour most likely to be a Pokemon card.
    
    Args:
        contours: List of contours from cv2.findContours
        image_shape: Shape of the image (h, w, c)
    
    Returns:
        Best card contour or None
    """
    h, w = image_shape[:2]
    image_area = h * w
    
    candidates = []
    
    for contour in contours:
        area = cv2.contourArea(contour)
        
        # Area filtering - card should be 20-95% of image
        if area < image_area * 0.20 or area > image_area * 0.95:
            continue
            
        # Approximate polygon
        epsilon = 0.02 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        # Should have 4 corners (or close to it for damaged cards)
        if len(approx) < 4 or len(approx) > 8:
            continue
        
        # Get bounding rectangle
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        box_w, box_h = rect[1]
        
        if box_w == 0 or box_h == 0:
            continue
            
        # Calculate aspect ratio
        aspect = min(box_w, box_h) / max(box_w, box_h)
        
        # Pokemon cards are 2.5" x 3.5" = 0.714 aspect ratio
        # Allow 0.60-0.85 range for perspective distortion
        if aspect < 0.60 or aspect > 0.85:
            continue
        
        # Calculate rectangularity (how rectangular the contour is)
        rect_area = box_w * box_h
        rectangularity = area / rect_area if rect_area > 0 else 0
        
        # Should be at least 85% rectangular
        if rectangularity < 0.85:
            continue
        
        # Calculate solidity (ratio of contour area to convex hull area)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        
        # Should be at least 90% solid (not concave)
        if solidity < 0.90:
            continue
        
        # Score this candidate
        score = calculate_card_score(
            aspect_ratio=aspect,
            rectangularity=rectangularity,
            solidity=solidity,
            area_ratio=area / image_area
        )
        
        candidates.append((contour, score, approx))
    
    if not candidates:
        return None
    
    # Return highest scoring candidate
    best_contour, best_score, best_approx = max(candidates, key=lambda x: x[1])
    return best_contour


def calculate_contour_confidence(contour, image_shape):
    """
    Calculate confidence score for detected contour.
    
    Returns:
        Confidence between 0 and 1
    """
    h, w = image_shape[:2]
    
    # Get metrics
    area = cv2.contourArea(contour)
    rect = cv2.minAreaRect(contour)
    box_w, box_h = rect[1]
    
    if box_w == 0 or box_h == 0:
        return 0.0
    
    aspect = min(box_w, box_h) / max(box_w, box_h)
    
    # Calculate confidence based on how close to ideal
    confidence = calculate_card_score(
        aspect_ratio=aspect,
        rectangularity=area / (box_w * box_h) if box_w * box_h > 0 else 0,
        solidity=0.95,  # Assume good solidity if we got here
        area_ratio=area / (h * w)
    )
    
    return confidence


def detect_by_adaptive_edges(image):
    """
    Adaptive Canny edge detection with automatic thresholding.
    
    Returns:
        (contour, confidence) or (None, 0.0)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply CLAHE for better contrast in poor lighting
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Denoise while preserving edges
    denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)
    
    # Adaptive Canny thresholds based on image statistics
    sigma = 0.33
    median = np.median(denoised)
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))
    
    edges = cv2.Canny(denoised, lower, upper)
    
    # Morphological closing to connect broken edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    # Find contours
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Find best card-like contour
    card_contour = find_best_card_contour(contours, image.shape)
    
    if card_contour is not None:
        confidence = calculate_contour_confidence(card_contour, image.shape)
        return card_contour, confidence
    
    return None, 0.0


def detect_by_color_segmentation(image):
    """
    Detect card by color segmentation - cards are usually distinct from background.
    
    Returns:
        (contour, confidence) or (None, 0.0)
    """
    # Convert to LAB color space (better for color differentiation)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    
    # Apply K-means clustering to separate foreground/background
    pixels = lab.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, labels, centers = cv2.kmeans(pixels, 3, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    
    # Reshape labels back to image dimensions
    labels = labels.reshape(image.shape[:2])
    
    # Find the cluster that represents the card (largest coherent region)
    best_contour = None
    best_area = 0
    
    for i in range(3):
        mask = (labels == i).astype(np.uint8) * 255
        
        # Clean up mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # Find largest contour in this cluster
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            
            # Check if this looks like a card using our validation
            validated = find_best_card_contour([largest], image.shape)
            if validated is not None and area > best_area:
                best_contour = validated
                best_area = area
    
    if best_contour is not None:
        confidence = calculate_contour_confidence(best_contour, image.shape)
        return best_contour, confidence
    
    return None, 0.0


def detect_card_robust(image):
    """
    Robust card detection using multiple methods with fallbacks.
    
    Args:
        image: Input image (BGR format)
    
    Returns:
        (contour, confidence, method) or (None, 0.0, None)
    """
    methods = [
        ("adaptive_edges", detect_by_adaptive_edges),
        ("color_segmentation", detect_by_color_segmentation),
    ]
    
    best_result = None
    best_confidence = 0
    best_method = None
    
    for method_name, method_func in methods:
        try:
            contour, confidence = method_func(image)
            if confidence > best_confidence:
                best_result = contour
                best_confidence = confidence
                best_method = method_name
                
            # If we get high confidence, stop early
            if confidence > 0.85:
                break
        except Exception as e:
            # Log error but continue to next method
            print(f"Detection method {method_name} failed: {e}")
            continue
    
    return best_result, best_confidence, best_method


def correct_perspective(image, contour):
    """
    Apply perspective transform to get straight-on view of card.
    
    Args:
        image: Input image
        contour: Card contour
    
    Returns:
        Warped image (straightened card)
    """
    # Get the 4 corners of the card
    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    box = np.int0(box)
    
    # Order points: top-left, top-right, bottom-right, bottom-left
    pts = order_points(box.astype(np.float32))
    
    # Calculate target dimensions (maintain aspect ratio)
    (tl, tr, br, bl) = pts
    
    # Compute width
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))
    
    # Compute height
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))
    
    # Ensure correct aspect ratio (2.5:3.5 = 0.714)
    target_aspect = 0.714
    current_aspect = maxWidth / maxHeight if maxHeight > 0 else 0
    
    if current_aspect < target_aspect:
        # Too narrow, adjust width
        maxWidth = int(maxHeight * target_aspect)
    else:
        # Too wide, adjust height
        maxHeight = int(maxWidth / target_aspect)
    
    # Destination points for the perspective transform
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype=np.float32)
    
    # Calculate perspective transform matrix
    matrix = cv2.getPerspectiveTransform(pts, dst)
    
    # Apply perspective transform
    warped = cv2.warpPerspective(image, matrix, (maxWidth, maxHeight))
    
    return warped


# Legacy compatibility: Keep old function name as alias
def find_card_contour(image, min_area_threshold=2000):
    """
    Legacy compatibility wrapper for detect_card_robust.
    Returns tuple: (approx_poly, bounding_rect) or None
    """
    if image is None:
        return None
    
    contour, confidence, method = detect_card_robust(image)
    
    if contour is None or confidence < 0.5:
        return None
    
    # Approximate to 4 points if needed
    epsilon = 0.02 * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    
    # Force 4 points for consistency
    if len(approx) != 4:
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        approx = np.int0(box)
    
    # Get bounding rect
    bounding_rect = cv2.boundingRect(approx)
    
    return approx, bounding_rect
