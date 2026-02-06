"""
Image quality validation before analysis.
"""
import cv2
import numpy as np
from typing import Dict, Tuple


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
            "error": "Could not load image"
        }
    
    # Check resolution
    height, width = image.shape[:2]
    min_resolution = 600  # Minimum width or height (lowered slightly for safety)
    
    # Calculate metrics
    blur_score = calculate_blur_score(image)
    brightness = calculate_brightness(image)
    contrast = calculate_contrast(image)
    
    # Quality thresholds
    issues = []
    warnings = []
    
    if width < min_resolution or height < min_resolution:
        issues.append(f"Low resolution: {width}x{height} (minimum {min_resolution}px)")
    
    if blur_score < 100:
        # Strict fail for very blurry images
        issues.append(f"Image too blurry (score: {blur_score:.1f})")
    elif blur_score < 200:
        warnings.append(f"Image slightly blurry (score: {blur_score:.1f})")
    
    if brightness < 40:
        issues.append(f"Image too dark (brightness: {brightness:.1f})")
    elif brightness > 230:
        issues.append(f"Image overexposed (brightness: {brightness:.1f})")
    elif brightness < 80 or brightness > 180:
        warnings.append(f"Suboptimal lighting (brightness: {brightness:.1f})")
    
    if contrast < 20:
        issues.append(f"Low contrast (score: {contrast:.1f})")
    elif contrast < 40:
        warnings.append(f"Low contrast (score: {contrast:.1f})")
    
    # Determine overall quality
    # We want to be lenient enough to allow analysis but strict enough to prevent garbage results
    if len(issues) > 0:
        quality = "poor"
        # If blurry or dark, we might still want to try but warn heavily
        # For now, let's mark can_analyze=False only for critical failures
        can_analyze = False
        
        # Override: if only resolution issue, maybe proceed?
        # No, resolution is critical for pixel measurements.
    elif len(warnings) > 2:
        quality = "fair"
        can_analyze = True
    elif len(warnings) > 0:
        quality = "good"
        can_analyze = True
    else:
        quality = "excellent"
        can_analyze = True
    
    return {
        "valid": True,
        "can_analyze": can_analyze,
        "quality": quality,
        "resolution": f"{width}x{height}",
        "metrics": {
            "blur_score": round(blur_score, 1),
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1)
        },
        "issues": issues,
        "warnings": warnings
    }
