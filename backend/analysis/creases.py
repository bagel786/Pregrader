"""
Heuristic surface crease detection using HoughLinesP.

Detects creases by finding long diagonal lines in the card interior
via Canny edge detection + Probabilistic Hough Transform.

Only uses the interior of the card (7% border stripped each side) to avoid
false positives from card border edges, corner damage, and frame boundaries.
"""
import math
import logging
import cv2
import numpy as np
from typing import Dict

logger = logging.getLogger(__name__)

# --- Tunable constants (exposed as module-level for easy calibration) ---

# Border strip fraction to exclude from each side (avoid card border artifacts)
INTERIOR_MARGIN_FRACTION = 0.07

# Canny thresholds — lower than corners.py to catch faint hairline creases
CANNY_LOW = 30
CANNY_HIGH = 100

# HoughLinesP core parameters
HOUGH_RHO = 1
HOUGH_THETA = np.pi / 180  # 1-degree resolution
HOUGH_THRESHOLD = 40  # min accumulator votes
HOUGH_MAX_GAP = 8  # px gap bridging within a crease line

# Minimum line length as fraction of card diagonal — primary false-positive filter
MIN_LINE_FRACTION = 0.15  # normal cards: require 15% of diagonal
MIN_LINE_FRACTION_HOLO = 0.22  # holographic cards: tighter threshold

# Angle exclusion zone around horizontal/vertical axes (degrees)
AXIS_ANGLE_EXCLUSION_DEG = 10

# Holofoil detection: if raw short-line count exceeds this, card is likely holo
HOLO_SHORT_LINE_THRESHOLD = 200

# Severity classification thresholds (normalized against card diagonal)
THRESHOLD_HAIRLINE_MAX = 0.12  # normalized_max_length >= this → at least hairline
THRESHOLD_MODERATE_MAX = 0.22  # normalized_max_length >= this → at least moderate
THRESHOLD_HEAVY_MAX = 0.40  # normalized_max_length >= this → heavy
THRESHOLD_HEAVY_TOTAL = 0.80  # OR: normalized_total_length >= this → heavy
THRESHOLD_MODERATE_TOTAL = 0.50  # normalized_total_length >= this when moderate → confirms moderate


def _angle_from_axes(x1: int, y1: int, x2: int, y2: int) -> float:
    """
    Return the minimum angular distance (degrees) of the line from
    either horizontal or vertical axis.
    """
    angle_deg = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
    dist_from_horizontal = min(angle_deg, 180 - angle_deg)
    dist_from_vertical = 90 - dist_from_horizontal
    return min(dist_from_horizontal, dist_from_vertical)


def _line_length(x1: int, y1: int, x2: int, y2: int) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def detect_surface_creases(
    image: np.ndarray,
    side: str = "front",
) -> Dict:
    """
    Heuristic crease detection using HoughLinesP on the card interior.

    Args:
        image: Perspective-corrected BGR uint8 card image.
        side: "front" or "back" (used only for logging).

    Returns:
        {
            "crease_detected": bool,
            "severity": "none" | "hairline" | "moderate" | "heavy",
            "confidence": float,
            "normalized_max_length": float,
            "normalized_total_length": float,
            "line_count": int,
            "is_likely_holo": bool,
        }
    """
    h, w = image.shape[:2]
    card_diagonal = math.sqrt(h**2 + w**2)

    # 1. Create interior mask (strip borders)
    margin_x = int(w * INTERIOR_MARGIN_FRACTION)
    margin_y = int(h * INTERIOR_MARGIN_FRACTION)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[margin_y : h - margin_y, margin_x : w - margin_x] = 255

    # 2. Grayscale + blur
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 3. Canny edges
    edges = cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)

    # 4. Apply interior mask
    edges_masked = cv2.bitwise_and(edges, mask)

    # 5. Holofoil detection pass (low threshold, short lines)
    short_lines = cv2.HoughLinesP(
        edges_masked,
        rho=HOUGH_RHO,
        theta=HOUGH_THETA,
        threshold=20,
        minLineLength=30,
        maxLineGap=5,
    )
    short_line_count = len(short_lines) if short_lines is not None else 0
    is_likely_holo = short_line_count > HOLO_SHORT_LINE_THRESHOLD

    # 6. Main crease detection pass
    min_line_frac = MIN_LINE_FRACTION_HOLO if is_likely_holo else MIN_LINE_FRACTION
    min_line_length = int(card_diagonal * min_line_frac)

    raw_lines = cv2.HoughLinesP(
        edges_masked,
        rho=HOUGH_RHO,
        theta=HOUGH_THETA,
        threshold=HOUGH_THRESHOLD,
        minLineLength=min_line_length,
        maxLineGap=HOUGH_MAX_GAP,
    )

    # 7. Angle filter: exclude axis-aligned lines (printed borders/frames)
    crease_lines = []
    if raw_lines is not None:
        for line in raw_lines:
            x1, y1, x2, y2 = line[0]
            if _angle_from_axes(x1, y1, x2, y2) > AXIS_ANGLE_EXCLUSION_DEG:
                crease_lines.append((x1, y1, x2, y2))

    # 8. Compute metrics
    line_count = len(crease_lines)
    if line_count == 0:
        logger.debug(
            f"[creases/{side}] No crease lines detected "
            f"(holo={is_likely_holo}, short_lines={short_line_count})"
        )
        return {
            "crease_detected": False,
            "severity": "none",
            "confidence": 0.70,
            "normalized_max_length": 0.0,
            "normalized_total_length": 0.0,
            "line_count": 0,
            "is_likely_holo": is_likely_holo,
        }

    lengths = [_line_length(*ln) for ln in crease_lines]
    total_length = sum(lengths)
    max_length = max(lengths)
    norm_max = max_length / card_diagonal
    norm_total = total_length / card_diagonal

    # 9. Severity classification
    if norm_max >= THRESHOLD_HEAVY_MAX or norm_total >= THRESHOLD_HEAVY_TOTAL:
        severity = "heavy"
        confidence = (
            0.70
            if norm_max >= THRESHOLD_HEAVY_MAX
            and norm_total >= THRESHOLD_HEAVY_TOTAL
            else 0.65
        )
    elif norm_max >= THRESHOLD_MODERATE_MAX:
        severity = "moderate"
        confidence = 0.70 if norm_total >= THRESHOLD_MODERATE_TOTAL else 0.65
    elif norm_max >= THRESHOLD_HAIRLINE_MAX:
        severity = "hairline"
        confidence = 0.65
    else:
        severity = "none"
        confidence = 0.70

    crease_detected = severity != "none"

    logger.info(
        f"[creases/{side}] severity={severity} confidence={confidence:.2f} "
        f"norm_max={norm_max:.3f} norm_total={norm_total:.3f} "
        f"lines={line_count} holo={is_likely_holo}"
    )

    return {
        "crease_detected": crease_detected,
        "severity": severity,
        "confidence": confidence,
        "normalized_max_length": round(norm_max, 4),
        "normalized_total_length": round(norm_total, 4),
        "line_count": line_count,
        "is_likely_holo": is_likely_holo,
    }
