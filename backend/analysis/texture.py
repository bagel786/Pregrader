"""
OpenCV-based border wear detection using multi-scale gradient analysis.

Detects surface wear (whitening) on card borders via:
1. Multi-scale Sobel gradients (fine ksize=3, coarse ksize=7) — detects edge fraying
2. Local intensity std dev (7x7 windows) — detects texture disruption

No scikit-image or ML required — pure numpy + opencv.
Confidence deliberately set to 0.55 (below 0.60 damage cap gate) so this signal
affects label display only, not grade cap enforcement.
"""

import logging
import numpy as np
import cv2

logger = logging.getLogger(__name__)

# Thresholds (empirically calibrated from real card tests)
# Score range observed: clean=5-15, minor_whitening=40-80, moderate=100+
# Raised from initial conservative values (18/35/55) after first validation
THRESH_MINOR = 40.0  # below: definitely clean
THRESH_MODERATE = 100.0  # below: minor wear only
THRESH_EXTENSIVE = 150.0  # below: moderate wear; above: extensive


def detect_border_wear(image: np.ndarray) -> dict:
    """
    Analyze card border texture for wear/fraying via multi-scale Sobel + local std dev.

    Args:
        image: BGR image (numpy array), any size

    Returns:
        {
            "whitening_coverage": "none" | "minor" | "moderate" | "extensive",
            "confidence": 0.55,
            "score": float (combined multi-scale gradient + std dev percentile score)
        }
    """
    if image is None or image.size == 0:
        return {
            "whitening_coverage": "none",
            "confidence": 0.55,
            "score": 0.0,
        }

    try:
        # Step 1: Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Step 1b: Normalise to a fixed analysis width so Sobel thresholds are
        # resolution-independent. High-res captures (10MP+) produce proportionally
        # smaller per-pixel gradients; without this, extensive whitening is
        # suppressed on high-resolution inputs.
        _TARGET_WIDTH = 800
        h, w = gray.shape
        if w > _TARGET_WIDTH:
            _scale = _TARGET_WIDTH / w
            gray = cv2.resize(gray, (_TARGET_WIDTH, int(h * _scale)), interpolation=cv2.INTER_AREA)
            h, w = gray.shape

        # Step 2: Build border mask (fixed 12% margin from edges)
        # Region outside inner box [(h*0.12, w*0.12) to (h*0.88, w*0.88)] is the border
        border_mask = np.zeros((h, w), dtype=np.uint8)
        inner_h_start = int(h * 0.12)
        inner_h_end = int(h * 0.88)
        inner_w_start = int(w * 0.12)
        inner_w_end = int(w * 0.88)

        # Mark border region (1 = border, 0 = interior/artwork)
        border_mask[:inner_h_start, :] = 255
        border_mask[inner_h_end:, :] = 255
        border_mask[:, :inner_w_start] = 255
        border_mask[:, inner_w_end:] = 255

        # Step 3: Multi-scale Sobel gradients
        # Fine scale: ksize=3 (detect small frays)
        # Coarse scale: ksize=7 (detect large wear patterns)
        gray_f32 = gray.astype(np.float32) / 255.0

        # Compute Sobel X and Y at both scales
        sobel_x_fine = cv2.Sobel(gray_f32, cv2.CV_32F, 1, 0, ksize=3)
        sobel_y_fine = cv2.Sobel(gray_f32, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag_fine = np.sqrt(sobel_x_fine ** 2 + sobel_y_fine ** 2)

        sobel_x_coarse = cv2.Sobel(gray_f32, cv2.CV_32F, 1, 0, ksize=7)
        sobel_y_coarse = cv2.Sobel(gray_f32, cv2.CV_32F, 0, 1, ksize=7)
        grad_mag_coarse = np.sqrt(sobel_x_coarse ** 2 + sobel_y_coarse ** 2)

        # Take max across scales (captures both fine and coarse wear patterns)
        grad_mag_max = np.maximum(grad_mag_fine, grad_mag_coarse)

        # Step 4: Local intensity std dev (texture disruption)
        # Use E[X²] - E[X]² trick with cv2.blur for efficiency
        mean_pixel = cv2.blur(gray_f32, (7, 7))
        mean_pixel_sq = cv2.blur(gray_f32 ** 2, (7, 7))
        local_std = np.sqrt(np.maximum(mean_pixel_sq - mean_pixel ** 2, 0.0))

        # Step 5: Extract border-region values only
        border_pixels_grad = grad_mag_max[border_mask == 255]
        border_pixels_std = local_std[border_mask == 255]

        if border_pixels_grad.size == 0 or border_pixels_std.size == 0:
            return {
                "whitening_coverage": "none",
                "confidence": 0.55,
                "score": 0.0,
            }

        # Step 6: Combine signals using 80th percentile (focus on worst areas, not average)
        # This avoids false positives from printing texture (which has some gradients everywhere)
        percentile_grad = float(np.percentile(border_pixels_grad, 80))
        percentile_std = float(np.percentile(border_pixels_std, 80))

        # Weighted average: 50% gradient sharpness, 50% texture disruption
        score = 0.5 * percentile_grad + 0.5 * percentile_std

        # Step 7: Map score to whitening level
        if score < THRESH_MINOR:
            whitening = "none"
        elif score < THRESH_MODERATE:
            whitening = "minor"
        elif score < THRESH_EXTENSIVE:
            whitening = "moderate"
        else:
            whitening = "extensive"

        return {
            "whitening_coverage": whitening,
            "confidence": 0.55,  # Below 0.60 gate → doesn't trigger damage cap alone
            "score": score,
        }

    except Exception as exc:
        logger.warning(f"[texture.detect_border_wear] Failed to analyze border: {exc}")
        return {
            "whitening_coverage": "none",
            "confidence": 0.55,
            "score": 0.0,
        }
