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

def find_card_contour(image, min_area_threshold=2000):
    """
    Robustly finds the card contour in an image.
    Returns tuple: (score, approx_poly, bounding_rect)
    
    Strategy:
    1. Grayscale + Blur + Canny
    2. Find Contours
    3. Filter by area
    4. Prioritize 4-sided polygons, but fallback to largest contour if valid 4-sided not found
    """
    if image is None:
        return None
        
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Use Canny with automatic parameter tuning or fixed
    edges = cv2.Canny(blurred, 30, 150)
    
    # Dilate edges to connect broken lines (common in damaged cards)
    kernel = np.ones((3,3), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    candidates = []
    
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_threshold:
            continue
            
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        
        # If we have 4 points, great. If not, we might still want it if it's huge.
        candidates.append({
            "contour": contour,
            "approx": approx,
            "area": area,
            "points": len(approx),
            "rect": cv2.boundingRect(approx)
        })
        
    candidates.sort(key=lambda x: x["area"], reverse=True)
    
    if not candidates:
        return None
        
    # Best candidate selection logic
    best = candidates[0]
    
    # If the largest is not 4-sided (common with rounded/damaged corners)
    # create a 4-sided approximation from the bounding rect or convex hull
    if best["points"] != 4:
        # Check if we have a smaller but significantly large 4-sided candidate?
        # Maybe, but usually the largest object is the card.
        # Let's force a 4-point approximation from the Rect 
        # (This loses rotation info, but robust for scanning)
        x, y, w, h = best["rect"]
        
        # Or better: MinAreaRect (rotated rectangle)
        rect_rotated = cv2.minAreaRect(best["contour"])
        box = cv2.boxPoints(rect_rotated)
        box = box.astype(int)  # Convert to integer coordinates (NumPy 2.0+ compatible)
        best["approx"] = box
    
    return best["approx"], best["rect"]
