"""
Image quality validation before analysis.
"""
import cv2
import numpy as np
from typing import Dict, Tuple, List


def calculate_blur_score(image: np.ndarray) -> float:
    """
    Calculate image blur using Laplacian variance.
    
    Args:
        image: Input BGR image
        
    Returns:
        Blur score (higher = sharper, typically >100 is good)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = laplacian.var()
    return variance


def calculate_brightness(image: np.ndarray) -> float:
    """
    Calculate average brightness.
    
    Args:
        image: Input BGR image
        
    Returns:
        Average brightness (0-255)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray.mean()


def calculate_contrast(image: np.ndarray) -> float:
    """
    Calculate image contrast using standard deviation.
    
    Args:
        image: Input BGR image
        
    Returns:
        Contrast score (higher = more contrast)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray.std()


def calculate_color_balance(image: np.ndarray) -> Tuple[bool, float, str]:
    """
    Check if image has severe color imbalance (tinted).
    
    Args:
        image: Input BGR image
        
    Returns:
        Tuple of (is_balanced, ratio, issue_message or None)
    """
    b, g, r = cv2.split(image)
    b_mean = cv2.mean(b)[0]
    g_mean = cv2.mean(g)[0]
    r_mean = cv2.mean(r)[0]
    
    means = [b_mean, g_mean, r_mean]
    max_mean = max(means)
    min_mean = max(min(means), 1)  # Avoid division by zero
    ratio = max_mean / min_mean
    
    if ratio > 1.5:
        # Determine which color is dominant
        if r_mean == max_mean:
            tint = "reddish"
        elif g_mean == max_mean:
            tint = "greenish"
        else:
            tint = "bluish"
        return False, ratio, f"Color imbalance detected ({tint} tint) - check lighting"
    
    return True, ratio, None


def validate_image_quality(image: np.ndarray) -> Tuple[bool, float, List[str]]:
    """
    Quick validation for real-time camera feedback.
    
    Args:
        image: Input BGR image (numpy array)
        
    Returns:
        Tuple of (is_valid, quality_score, list of issues)
    """
    issues = []
    
    # 1. Blur Detection (Laplacian Variance)
    blur_score = calculate_blur_score(image)
    if blur_score < 100:
        issues.append("Image too blurry - please hold camera steady")
    
    # 2. Exposure Check
    brightness = calculate_brightness(image)
    if brightness < 40:
        issues.append("Image too dark - improve lighting")
    elif brightness > 215:
        issues.append("Image overexposed - reduce lighting/flash")
    
    # 3. Resolution Check
    height, width = image.shape[:2]
    if height < 800 or width < 600:
        issues.append(f"Image resolution too low ({width}x{height}) - minimum 800x600px")
    
    # 4. Color Balance Check
    is_balanced, _, color_issue = calculate_color_balance(image)
    if not is_balanced and color_issue:
        issues.append(color_issue)
    
    quality_score = 1.0 - (len(issues) * 0.25)
    quality_score = max(0.0, quality_score)
    is_valid = len(issues) == 0
    
    return is_valid, quality_score, issues


def check_image_quality(image_path: str) -> Dict:
    """
    Perform comprehensive image quality checks.
    
    Args:
        image_path: Path to image file
        
    Returns:
        Dict with quality metrics and pass/fail status
    """
    image = cv2.imread(image_path)
    if image is None:
        return {
            "valid": False,
            "can_analyze": False,
            "error": "Could not load image",
            "user_feedback": ["Failed to load image - please try again"]
        }
    
    # Check resolution
    height, width = image.shape[:2]
    min_resolution = 480  # Minimum width or height (lowered for mobile photos)
    
    # Calculate metrics
    blur_score = calculate_blur_score(image)
    brightness = calculate_brightness(image)
    contrast = calculate_contrast(image)
    is_balanced, color_ratio, color_issue = calculate_color_balance(image)
    
    # Quality thresholds
    issues = []
    warnings = []
    user_feedback = []  # Actionable messages for users
    
    if width < min_resolution or height < min_resolution:
        issues.append(f"Low resolution: {width}x{height} (minimum {min_resolution}px)")
        user_feedback.append("Image resolution too low - move camera closer or use higher quality setting")
    
    if blur_score < 70:
        issues.append(f"Image too blurry (score: {blur_score:.1f})")
        user_feedback.append("Image is blurry - hold camera steady and tap to focus")
    elif blur_score < 150:
        warnings.append(f"Image slightly blurry (score: {blur_score:.1f})")
    
    if brightness < 40:
        issues.append(f"Image too dark (brightness: {brightness:.1f})")
        user_feedback.append("Image too dark - move to a well-lit area")
    elif brightness > 230:
        issues.append(f"Image overexposed (brightness: {brightness:.1f})")
        user_feedback.append("Image too bright - avoid direct flash or harsh lighting")
    elif brightness < 80 or brightness > 180:
        warnings.append(f"Suboptimal lighting (brightness: {brightness:.1f})")
    
    if contrast < 20:
        issues.append(f"Low contrast (score: {contrast:.1f})")
        user_feedback.append("Low contrast - ensure card is on a contrasting background")
    elif contrast < 40:
        warnings.append(f"Low contrast (score: {contrast:.1f})")
    
    if not is_balanced and color_issue:
        warnings.append(color_issue)
        user_feedback.append("Color appears off - use neutral/white lighting")
    
    # Determine overall quality
    if len(issues) > 0:
        quality = "poor"
        can_analyze = False
    elif len(warnings) > 2:
        quality = "fair"
        can_analyze = True
    elif len(warnings) > 0:
        quality = "good"
        can_analyze = True
    else:
        quality = "excellent"
        can_analyze = True
        user_feedback = ["Perfect! Ready to grade"]
    
    return {
        "valid": True,
        "can_analyze": can_analyze,
        "quality": quality,
        "resolution": f"{width}x{height}",
        "metrics": {
            "blur_score": round(blur_score, 1),
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
            "color_balance_ratio": round(color_ratio, 2)
        },
        "issues": issues,
        "warnings": warnings,
        "user_feedback": user_feedback if user_feedback else None
    }

