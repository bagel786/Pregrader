"""
Split-region image preprocessing for damage detection enhancement.

Removes holographic foil noise via grayscale + CLAHE while avoiding
artwork-edge false positives. Border regions (whitening/wear) receive
aggressive enhancement; artwork interior receives mild enhancement only.
"""
import logging
import cv2
import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Attempt to import centering art box detection; graceful fallback if unavailable
try:
    from analysis.centering import detect_inner_artwork_box
    ART_BOX_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    ART_BOX_AVAILABLE = False
    logger.warning("centering.detect_inner_artwork_box not available; using fixed margin fallback")


def enhance_for_damage_detection(img: np.ndarray) -> np.ndarray:
    """
    Split-region enhancement for damage visibility on preprocessed image.

    Strips holographic foil rainbow noise (colour-dependent) via grayscale conversion.
    Then applies different preprocessing levels to card border vs. artwork interior:

    - **Border region** (outside art box):
      Grayscale → CLAHE(clip=3.0) → histogram equalization → BGR
      → Reveals whitening, edge wear, corner damage

    - **Artwork interior** (inside art box):
      Grayscale → CLAHE(clip=2.0) → BGR
      → Reveals creases without sharpening character art edges

    Falls back to fixed 15% margin from card edge if art box detection fails.

    Args:
        img: Perspective-corrected BGR uint8 numpy array (500×700 or similar).

    Returns:
        Enhanced BGR uint8 numpy array, same dimensions as input.
        Safe to pass directly to Vision AI (still a normal 3-channel image).
    """
    h, w = img.shape[:2]

    # ─────────────────────────────────────────────────────────────────────
    # Step 1: Detect artwork box or use fixed margin fallback
    # ─────────────────────────────────────────────────────────────────────

    if ART_BOX_AVAILABLE:
        try:
            art_box = detect_inner_artwork_box(img)
            if art_box is not None and art_box.get("success", False):
                left_border = art_box.get("left", int(w * 0.15))
                right_border = art_box.get("right", int(w * 0.15))
                top_border = art_box.get("top", int(h * 0.15))
                bottom_border = art_box.get("bottom", int(h * 0.15))
            else:
                # Fallback: fixed margin
                margin = int(min(w, h) * 0.15)
                left_border = right_border = margin
                top_border = bottom_border = margin
        except Exception as e:
            logger.debug(f"Art box detection failed; using fixed margin: {e}")
            margin = int(min(w, h) * 0.15)
            left_border = right_border = margin
            top_border = bottom_border = margin
    else:
        # No art box detector available: use fixed margin
        margin = int(min(w, h) * 0.15)
        left_border = right_border = margin
        top_border = bottom_border = margin

    # Art box coordinates (interior of the card art)
    art_x1 = left_border
    art_y1 = top_border
    art_x2 = w - right_border
    art_y2 = h - bottom_border

    # Ensure valid bounds
    art_x1 = max(0, min(art_x1, w - 1))
    art_y1 = max(0, min(art_y1, h - 1))
    art_x2 = max(art_x1 + 1, min(art_x2, w))
    art_y2 = max(art_y1 + 1, min(art_y2, h))

    # ─────────────────────────────────────────────────────────────────────
    # Step 2: Convert to grayscale (removes holographic colour noise)
    # ─────────────────────────────────────────────────────────────────────

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ─────────────────────────────────────────────────────────────────────
    # Step 4: Split-region enhancement
    # ─────────────────────────────────────────────────────────────────────

    result_gray = np.zeros_like(gray)

    # Border region: moderate enhancement (CLAHE + histogram equalization)
    # Reduced clipLimit from 3.0 to 1.5 to avoid over-amplifying normal wear
    border_mask = np.zeros((h, w), dtype=np.uint8)
    border_mask[0:art_y1, :] = 255  # Top border
    border_mask[art_y2:h, :] = 255  # Bottom border
    border_mask[:, 0:art_x1] = 255  # Left border
    border_mask[:, art_x2:w] = 255  # Right border

    clahe_border = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    border_pixels = clahe_border.apply(gray)

    # Skip histogram equalization on white-dominant cards (Mewtwo, Alakazam, etc.)
    # equalizeHist on a near-white histogram compresses it → masks wear signals
    border_gray_mean = float(np.mean(gray[border_mask == 255])) if np.any(border_mask) else 0.0
    if border_gray_mean < 200:
        border_pixels = cv2.equalizeHist(border_pixels)
    else:
        logger.debug(
            f"[damage_preprocessing] White-dominant card detected (border mean={border_gray_mean:.0f}); "
            f"skipping equalizeHist to preserve wear signals"
        )

    result_gray[border_mask == 255] = border_pixels[border_mask == 255]

    # Art interior region: mild enhancement (light CLAHE only)
    # Reduced clipLimit from 2.0 to 1.0 to avoid false creases from printing texture
    interior_mask = np.zeros((h, w), dtype=np.uint8)
    interior_mask[art_y1:art_y2, art_x1:art_x2] = 255

    clahe_mild = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(8, 8))
    interior_pixels = clahe_mild.apply(gray)  # Mild CLAHE only, no histogram eq
    result_gray[interior_mask == 255] = interior_pixels[interior_mask == 255]

    # ─────────────────────────────────────────────────────────────────────
    # Step 5: Convert back to BGR for Vision AI
    # ─────────────────────────────────────────────────────────────────────

    enhanced_bgr = cv2.cvtColor(result_gray, cv2.COLOR_GRAY2BGR)

    logger.debug(
        f"[damage_preprocessing] Enhanced image for damage detection. "
        f"Art box: ({art_x1}, {art_y1}) to ({art_x2}, {art_y2})"
    )

    return enhanced_bgr
