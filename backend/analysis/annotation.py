"""
Annotate card images with color-coded corners, edges, and centering overlays.

Draws visual annotations on a perspective-corrected card image showing:
- Corner scores as colored circles (green ≥8.5, orange 6.5–8.4, red <6.5)
- Edge scores as colored lines
- Centering crosshair with H/V ratio labels
"""

import base64
import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _score_color(score: float) -> tuple:
    """Return BGR color tuple based on score threshold."""
    if score >= 8.5:
        return (80, 200, 80)    # green
    elif score >= 6.5:
        return (0, 165, 255)    # orange
    else:
        return (60, 60, 220)    # red


def annotate_card_image(
    image_path: str,
    corner_scores: dict,
    edge_scores: dict,
    centering_data: dict,
    max_long_side: int = 800,
) -> Optional[str]:
    """
    Annotate a corrected card image with corner/edge scores and centering info.

    Args:
        image_path: Path to the corrected card image (JPG/PNG)
        corner_scores: Dict with keys 'front_top_left', 'front_top_right', etc.
                      Each value is a float score 1–10.
        edge_scores: Dict with keys 'front_top', 'front_right', 'front_bottom', 'front_left'.
                    Each value is a float score 1–10.
        centering_data: Dict containing centering_score and measurements sub-dict.
                       measurements dict should have left_px, right_px, top_px, bottom_px.
        max_long_side: Maximum pixel length of the longest dimension after resize (default 800).

    Returns:
        Base64-encoded JPEG string of the annotated image, or None on failure.
    """
    try:
        # Load the image
        img = cv2.imread(image_path)
        if img is None:
            logger.warning(f"Failed to load image: {image_path}")
            return None

        h, w = img.shape[:2]

        # Proportional sizing
        corner_radius = max(18, int(min(h, w) * 0.035))
        # Pad the image so corner circles sit entirely within bounds.
        # Padding = corner_radius + a small gap so circles aren't clipped.
        pad = corner_radius + 6
        annotated = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        h, w = annotated.shape[:2]

        corner_inset = pad  # circle centre exactly at pad distance from edge
        edge_thick = max(6, int(min(h, w) * 0.012))
        edge_inset = corner_inset + corner_radius + 4
        label_font = cv2.FONT_HERSHEY_SIMPLEX
        label_font_scale = max(0.55, min(h, w) / 900)
        label_thick = 2

        # Draw edges first (so they appear behind corners)
        edges_segments = {
            "front_top": ((edge_inset, edge_thick // 2), (w - edge_inset, edge_thick // 2)),
            "front_bottom": ((edge_inset, h - edge_thick // 2), (w - edge_inset, h - edge_thick // 2)),
            "front_left": ((edge_thick // 2, edge_inset), (edge_thick // 2, h - edge_inset)),
            "front_right": ((w - edge_thick // 2, edge_inset), (w - edge_thick // 2, h - edge_inset)),
        }

        for edge_name, (pt1, pt2) in edges_segments.items():
            score = edge_scores.get(edge_name, 5.0)
            color = _score_color(score)
            cv2.line(annotated, pt1, pt2, color, edge_thick, cv2.LINE_AA)

        # Draw corners
        corners_pos = {
            "front_top_left": (corner_inset, corner_inset),
            "front_top_right": (w - corner_inset, corner_inset),
            "front_bottom_left": (corner_inset, h - corner_inset),
            "front_bottom_right": (w - corner_inset, h - corner_inset),
        }

        for corner_name, (cx, cy) in corners_pos.items():
            score = corner_scores.get(corner_name, 5.0)
            color = _score_color(score)
            cv2.circle(annotated, (cx, cy), corner_radius, color, -1)
            # Draw score label inside circle
            score_text = f"{score:.1f}"
            text_size = cv2.getTextSize(score_text, label_font, label_font_scale * 0.8, 1)[0]
            text_x = cx - text_size[0] // 2
            text_y = cy + text_size[1] // 2
            cv2.putText(
                annotated,
                score_text,
                (text_x, text_y),
                label_font,
                label_font_scale * 0.8,
                (255, 255, 255),  # white text
                label_thick,
            )

        # Draw centering crosshair
        centering_score = centering_data.get("centering_score", 5.0)
        centering_color = _score_color(centering_score)
        measurements = centering_data.get("measurements", {})

        # Compute center of print area from measurements
        left_px = measurements.get("left_px", w * 0.08)
        right_px = measurements.get("right_px", w * 0.08)
        top_px = measurements.get("top_px", h * 0.08)
        bottom_px = measurements.get("bottom_px", h * 0.08)

        if left_px + right_px > 0 and top_px + bottom_px > 0:
            cx = int(left_px / (left_px + right_px) * w)
            cy = int(top_px / (top_px + bottom_px) * h)
        else:
            # Fallback to image center
            cx, cy = w // 2, h // 2

        # Draw dashed crosshair lines
        _dashed_line(
            annotated,
            (cx, corner_inset),
            (cx, h - corner_inset),
            centering_color,
            thickness=2,
        )
        _dashed_line(
            annotated,
            (corner_inset, cy),
            (w - corner_inset, cy),
            centering_color,
            thickness=2,
        )

        # Draw ratio labels near bottom
        lr_ratio = measurements.get("left_right_ratio", "?/?")
        tb_ratio = measurements.get("top_bottom_ratio", "?/?")

        ratio_label_y = h - 30
        h_label = f"H {lr_ratio}"
        v_label = f"V {tb_ratio}"

        cv2.putText(
            annotated,
            h_label,
            (cx - 100, ratio_label_y),
            label_font,
            0.55,
            centering_color,
            label_thick,
        )
        cv2.putText(
            annotated,
            v_label,
            (cx + 20, ratio_label_y),
            label_font,
            0.55,
            centering_color,
            label_thick,
        )

        # Resize if needed
        if max(h, w) > max_long_side:
            scale = max_long_side / max(h, w)
            new_h, new_w = int(h * scale), int(w * scale)
            annotated = cv2.resize(
                annotated,
                (new_w, new_h),
                interpolation=cv2.INTER_AREA,
            )

        # Encode as JPEG and return base64
        success, buf = cv2.imencode(
            ".jpg",
            annotated,
            [cv2.IMWRITE_JPEG_QUALITY, 88],
        )
        if not success:
            logger.warning("Failed to encode annotated image")
            return None

        b64_str = base64.b64encode(buf).decode("utf-8")
        return b64_str

    except Exception as exc:
        logger.warning(f"Annotation failed (non-critical): {exc}")
        return None


def _dashed_line(
    img,
    pt1,
    pt2,
    color,
    thickness: int = 2,
    dash_len: int = 12,
    gap_len: int = 8,
) -> None:
    """Draw a dashed line using OpenCV."""
    x1, y1 = pt1
    x2, y2 = pt2
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

    if length == 0:
        return

    dx = (x2 - x1) / length
    dy = (y2 - y1) / length

    pos = 0
    drawing = True

    while pos < length:
        next_pos = pos + (dash_len if drawing else gap_len)
        if drawing:
            sx = int(x1 + dx * pos)
            sy = int(y1 + dy * pos)
            ex = int(x1 + dx * min(next_pos, length))
            ey = int(y1 + dy * min(next_pos, length))
            cv2.line(img, (sx, sy), (ex, ey), color, thickness, cv2.LINE_AA)

        pos = next_pos
        drawing = not drawing
