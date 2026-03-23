"""
Stage 3: Vision AI Visual Assessment.

Replaces the OpenCV corner/edge/surface analysis with a single Vision AI call
that evaluates all three dimensions simultaneously using cropped card images.

Uses the same httpx pattern as backend/services/ai/vision_detector.py.
"""

import os
import base64
import json
import logging
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-20250514"
API_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_SECONDS = 30
MAX_JSON_RETRIES = 2

# Image preparation limits
CORNER_MAX_PX = 512    # max dimension for corner grid images
EDGE_MAX_PX = 512      # max dimension for edge strip composite images
SURFACE_MAX_PX = 1024  # max dimension for full surface images
JPEG_QUALITY = 80

# Corner crop: 15% of card dimension from each corner
CORNER_FRACTION = 0.15
# Edge strip: 10% of the perpendicular card dimension
EDGE_FRACTION = 0.10

# Dual-pass disagreement threshold
PASS_DISAGREEMENT_THRESHOLD = 1.5

# Confidence threshold below which we flag for manual review
LOW_CONFIDENCE_THRESHOLD = 0.60

# Composited image mode: send 6 composited images instead of 18 individual crops.
# Set to False during calibration if the model struggles to identify corners in grids.
COMPOSITE_MODE = True

# Load system prompt once at module load time
_PROMPT_PATH = Path(__file__).parent / "prompts" / "grading_prompt.txt"
try:
    SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    logger.error(f"Grading prompt not found at {_PROMPT_PATH}")
    SYSTEM_PROMPT = ""


class VisionAssessorError(Exception):
    """Raised when the Vision AI call fails unrecoverably."""


# ---------------------------------------------------------------------------
# Image preparation helpers
# ---------------------------------------------------------------------------

def _resize_to_max(img: np.ndarray, max_px: int) -> np.ndarray:
    """Resize image so its largest dimension is at most max_px, preserving aspect ratio."""
    h, w = img.shape[:2]
    if max(h, w) <= max_px:
        return img
    scale = max_px / max(h, w)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _to_jpeg_b64(img: np.ndarray, max_px: int) -> str:
    """Resize, encode to JPEG, return base64 string."""
    img = _resize_to_max(img, max_px)
    success, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not success:
        raise VisionAssessorError("Failed to JPEG-encode image")
    return base64.standard_b64encode(buf.tobytes()).decode("utf-8")


def _crop_corner(img: np.ndarray, position: str) -> np.ndarray:
    """
    Crop a corner region from the image.
    position: one of 'top_left', 'top_right', 'bottom_left', 'bottom_right'
    """
    h, w = img.shape[:2]
    ch = max(1, int(h * CORNER_FRACTION))
    cw = max(1, int(w * CORNER_FRACTION))

    if position == "top_left":
        return img[:ch, :cw]
    elif position == "top_right":
        return img[:ch, w - cw:]
    elif position == "bottom_left":
        return img[h - ch:, :cw]
    elif position == "bottom_right":
        return img[h - ch:, w - cw:]
    else:
        raise ValueError(f"Unknown corner position: {position}")


def _crop_edge(img: np.ndarray, edge: str) -> np.ndarray:
    """
    Crop an edge strip, excluding the corner regions.
    edge: one of 'top', 'right', 'bottom', 'left'
    """
    h, w = img.shape[:2]
    corner_h = max(1, int(h * CORNER_FRACTION))
    corner_w = max(1, int(w * CORNER_FRACTION))
    strip_h = max(1, int(h * EDGE_FRACTION))
    strip_w = max(1, int(w * EDGE_FRACTION))

    if edge == "top":
        return img[:strip_h, corner_w:w - corner_w]
    elif edge == "bottom":
        return img[h - strip_h:, corner_w:w - corner_w]
    elif edge == "left":
        return img[corner_h:h - corner_h, :strip_w]
    elif edge == "right":
        return img[corner_h:h - corner_h, w - strip_w:]
    else:
        raise ValueError(f"Unknown edge: {edge}")


def _make_corner_grid(img: np.ndarray) -> np.ndarray:
    """
    Arrange the 4 corner crops into a 2×2 grid image.
    Layout: TL | TR
            BL | BR
    Adds thin white separator lines between cells for clarity.
    """
    tl = _crop_corner(img, "top_left")
    tr = _crop_corner(img, "top_right")
    bl = _crop_corner(img, "bottom_left")
    br = _crop_corner(img, "bottom_right")

    # Normalize all crops to the same size (max of all sizes)
    cell_h = max(tl.shape[0], tr.shape[0], bl.shape[0], br.shape[0])
    cell_w = max(tl.shape[1], tr.shape[1], bl.shape[1], br.shape[1])

    def _pad(c: np.ndarray) -> np.ndarray:
        out = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
        out[:c.shape[0], :c.shape[1]] = c
        return out

    SEP = 2  # separator width in pixels
    row1 = np.concatenate([_pad(tl), np.full((cell_h, SEP, 3), 255, dtype=np.uint8), _pad(tr)], axis=1)
    row2 = np.concatenate([_pad(bl), np.full((cell_h, SEP, 3), 255, dtype=np.uint8), _pad(br)], axis=1)
    sep_row = np.full((SEP, row1.shape[1], 3), 255, dtype=np.uint8)
    grid = np.concatenate([row1, sep_row, row2], axis=0)
    return grid


def _make_edge_composite(img: np.ndarray) -> np.ndarray:
    """
    Arrange 4 edge strips into a single composite image.
    Layout (vertical stack): top edge / left edge / right edge / bottom edge
    Adds separator lines between strips.
    """
    top = _crop_edge(img, "top")
    bottom = _crop_edge(img, "bottom")
    left = _crop_edge(img, "left")
    right = _crop_edge(img, "right")

    # Normalize widths for horizontal strips, heights for vertical strips
    max_w = max(top.shape[1], bottom.shape[1])
    max_h_vert = max(left.shape[0], right.shape[0])

    def _pad_w(c: np.ndarray, target_w: int) -> np.ndarray:
        if c.shape[1] >= target_w:
            return c
        pad = np.zeros((c.shape[0], target_w - c.shape[1], 3), dtype=np.uint8)
        return np.concatenate([c, pad], axis=1)

    def _pad_h(c: np.ndarray, target_h: int) -> np.ndarray:
        if c.shape[0] >= target_h:
            return c
        pad = np.zeros((target_h - c.shape[0], c.shape[1], 3), dtype=np.uint8)
        return np.concatenate([c, pad], axis=0)

    # Make left/right same height, top/bottom same width
    left = _pad_h(left, max_h_vert)
    right = _pad_h(right, max_h_vert)

    # Composite: top / left | right (side-by-side) / bottom
    lr_row = np.concatenate([left, np.full((max_h_vert, 2, 3), 255, dtype=np.uint8), right], axis=1)
    # Portrait cards have wider top/bottom strips than lr_row; use the max width for all elements.
    composite_w = max(lr_row.shape[1], top.shape[1], bottom.shape[1])
    top_pad = _pad_w(top, composite_w)
    bottom_pad = _pad_w(bottom, composite_w)
    lr_row = _pad_w(lr_row, composite_w)
    sep = np.full((2, composite_w, 3), 255, dtype=np.uint8)

    composite = np.concatenate([top_pad, sep, lr_row, sep, bottom_pad], axis=0)
    return composite


def prepare_images(front_img: np.ndarray, back_img: np.ndarray) -> List[Dict]:
    """
    Prepare the 6 composited images for Vision AI assessment.

    Returns list of dicts: [{"label": str, "b64": str}, ...]
    Labels: front_corners, back_corners, front_edges, back_edges, front_surface, back_surface
    """
    images = []

    if COMPOSITE_MODE:
        images.append({"label": "front_corners", "b64": _to_jpeg_b64(_make_corner_grid(front_img), CORNER_MAX_PX)})
        images.append({"label": "back_corners",  "b64": _to_jpeg_b64(_make_corner_grid(back_img),  CORNER_MAX_PX)})
        images.append({"label": "front_edges",   "b64": _to_jpeg_b64(_make_edge_composite(front_img), EDGE_MAX_PX)})
        images.append({"label": "back_edges",    "b64": _to_jpeg_b64(_make_edge_composite(back_img),  EDGE_MAX_PX)})
    else:
        # Individual crops (18 images) — higher token cost, potentially more accurate
        for side, img in [("front", front_img), ("back", back_img)]:
            for pos in ("top_left", "top_right", "bottom_left", "bottom_right"):
                images.append({
                    "label": f"{side}_{pos}_corner",
                    "b64": _to_jpeg_b64(_crop_corner(img, pos), CORNER_MAX_PX),
                })
            for edge in ("top", "right", "bottom", "left"):
                images.append({
                    "label": f"{side}_{edge}_edge",
                    "b64": _to_jpeg_b64(_crop_edge(img, edge), EDGE_MAX_PX),
                })

    images.append({"label": "front_surface", "b64": _to_jpeg_b64(front_img, SURFACE_MAX_PX)})
    images.append({"label": "back_surface",  "b64": _to_jpeg_b64(back_img,  SURFACE_MAX_PX)})

    return images


# ---------------------------------------------------------------------------
# Vision AI API call
# ---------------------------------------------------------------------------

def _build_message_content(images: List[Dict]) -> List[Dict]:
    """Build the messages content array with all image blocks followed by the instruction."""
    content = []
    for img_info in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_info["b64"],
            },
        })
    if COMPOSITE_MODE:
        layout_desc = (
            "Images are in order: front corners grid, back corners grid, "
            "front edges composite, back edges composite, "
            "full front surface, full back surface."
        )
    else:
        layout_desc = (
            "Images are in order: 4 front corner crops (TL, TR, BL, BR), "
            "4 back corner crops (TL, TR, BL, BR), "
            "4 front edge strips (top, right, bottom, left), "
            "4 back edge strips (top, right, bottom, left), "
            "full front surface, full back surface."
        )
    content.append({
        "type": "text",
        "text": (
            f"Assess the card condition shown in these images. "
            f"{layout_desc} "
            f"Return only JSON as specified in your instructions."
        ),
    })
    return content


def _validate_response(data: Dict) -> None:
    """
    Validate Vision AI response. Raises ValueError with a reason if invalid.
    Checks:
    - Required keys present
    - All scores in [1.0, 10.0]
    - Not all corner scores identical (hallucination guard)
    """
    required_corners = [
        "front_top_left", "front_top_right", "front_bottom_left", "front_bottom_right",
        "back_top_left", "back_top_right", "back_bottom_left", "back_bottom_right",
    ]
    required_edges = [
        "front_top", "front_right", "front_bottom", "front_left",
        "back_top", "back_right", "back_bottom", "back_left",
    ]

    if "corners" not in data or "edges" not in data or "surface" not in data:
        raise ValueError("Missing top-level keys (corners/edges/surface)")

    for key in required_corners:
        if key not in data["corners"]:
            raise ValueError(f"Missing corner key: {key}")
        score = data["corners"][key].get("score")
        if score is None or not (1.0 <= float(score) <= 10.0):
            raise ValueError(f"Corner {key} score out of range: {score}")

    for key in required_edges:
        if key not in data["edges"]:
            raise ValueError(f"Missing edge key: {key}")
        score = data["edges"][key].get("score")
        if score is None or not (1.0 <= float(score) <= 10.0):
            raise ValueError(f"Edge {key} score out of range: {score}")

    for side in ("front", "back"):
        if side not in data["surface"]:
            raise ValueError(f"Missing surface side: {side}")
        score = data["surface"][side].get("score")
        if score is None or not (1.0 <= float(score) <= 10.0):
            raise ValueError(f"Surface {side} score out of range: {score}")

    # Hallucination guard: all 8 corners identical AND equal to an obvious placeholder value
    corner_scores = [float(data["corners"][k]["score"]) for k in required_corners]
    if len(set(corner_scores)) == 1 and corner_scores[0] in (1.0, 5.0, 10.0):
        raise ValueError("All corner scores are identical placeholder value — likely hallucinated output")


def _call_api_sync(images: List[Dict], api_key: str) -> Dict:
    """
    Make one synchronous Vision AI API call. Returns parsed JSON dict.
    Raises VisionAssessorError on timeout or permanent failure.
    Retries once on timeout; retries up to MAX_JSON_RETRIES on JSON parse failure.
    """
    content = _build_message_content(images)
    payload = {
        "model": MODEL,
        "max_tokens": 2048,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    def _do_request() -> str:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.post(API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    # One retry on timeout
    for attempt in range(2):
        try:
            raw_text = _do_request()
            break
        except httpx.TimeoutException:
            if attempt == 1:
                raise VisionAssessorError("Vision AI call timed out twice — aborting grade")
            logger.warning("Vision AI timeout, retrying once...")
        except httpx.HTTPStatusError as exc:
            raise VisionAssessorError(f"Vision AI API error {exc.response.status_code}: {exc.response.text}")

    # Parse JSON with retries on malformed output
    # Strip any accidental markdown fences the model might add despite instructions
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    last_exc: Optional[Exception] = None
    for retry in range(MAX_JSON_RETRIES + 1):
        try:
            data = json.loads(raw_text)
            _validate_response(data)
            return data
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_exc = exc
            if retry < MAX_JSON_RETRIES:
                logger.warning(f"Vision AI response invalid (attempt {retry + 1}): {exc} — retrying API call")
                try:
                    raw_text = _do_request()
                    raw_text = raw_text.strip()
                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        raw_text = "\n".join(
                            line for line in lines
                            if not line.strip().startswith("```")
                        ).strip()
                except httpx.TimeoutException:
                    raise VisionAssessorError("Vision AI timed out during JSON retry")

    raise VisionAssessorError(f"Vision AI returned unparseable response after {MAX_JSON_RETRIES + 1} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Dual-pass averaging
# ---------------------------------------------------------------------------

_CREASE_ORDER    = ["none", "hairline", "moderate", "heavy"]
_WHITENING_ORDER = ["none", "minor", "moderate", "extensive"]


def _most_severe(a: Optional[str], b: Optional[str], order: list) -> Optional[str]:
    """Return the more severe of two categorical labels, or None if both absent."""
    ia = order.index(a) if a in order else -1
    ib = order.index(b) if b in order else -1
    if ia < 0 and ib < 0:
        return None
    return order[max(ia, ib)]


def _most_severe_of_three(a: Optional[str], b: Optional[str], c: Optional[str], order: list) -> Optional[str]:
    """Return the most severe of three categorical labels, or None if all absent."""
    ranked = [order.index(x) for x in (a, b, c) if x in order]
    return order[max(ranked)] if ranked else None


def _extract_numeric_scores(data: Dict) -> Dict[str, float]:
    """Flatten all numeric scores from response into a flat key→score dict."""
    scores = {}
    for key, val in data.get("corners", {}).items():
        scores[f"corner_{key}"] = float(val["score"])
    for key, val in data.get("edges", {}).items():
        scores[f"edge_{key}"] = float(val["score"])
    scores["surface_front"] = float(data["surface"]["front"]["score"])
    scores["surface_back"] = float(data["surface"]["back"]["score"])
    return scores


def _average_passes(pass1: Dict, pass2: Dict) -> Dict:
    """Average numeric scores; union defect lists; average confidences."""
    result = {
        "corners": {},
        "edges": {},
        "surface": {"front": {}, "back": {}},
    }

    for key in pass1["corners"]:
        s1 = float(pass1["corners"][key]["score"])
        s2 = float(pass2["corners"][key]["score"])
        c1 = float(pass1["corners"][key].get("confidence", 1.0))
        c2 = float(pass2["corners"][key].get("confidence", 1.0))
        d1 = pass1["corners"][key].get("defects", [])
        d2 = pass2["corners"][key].get("defects", [])
        result["corners"][key] = {
            "score": round((s1 + s2) / 2, 1),
            "defects": list(dict.fromkeys(d1 + d2)),  # preserve order, deduplicate
            "confidence": round((c1 + c2) / 2, 3),
        }

    for key in pass1["edges"]:
        s1 = float(pass1["edges"][key]["score"])
        s2 = float(pass2["edges"][key]["score"])
        c1 = float(pass1["edges"][key].get("confidence", 1.0))
        c2 = float(pass2["edges"][key].get("confidence", 1.0))
        d1 = pass1["edges"][key].get("defects", [])
        d2 = pass2["edges"][key].get("defects", [])
        result["edges"][key] = {
            "score": round((s1 + s2) / 2, 1),
            "defects": list(dict.fromkeys(d1 + d2)),
            "confidence": round((c1 + c2) / 2, 3),
        }

    for side in ("front", "back"):
        s1 = float(pass1["surface"][side]["score"])
        s2 = float(pass2["surface"][side]["score"])
        c1 = float(pass1["surface"][side].get("confidence", 1.0))
        c2 = float(pass2["surface"][side].get("confidence", 1.0))
        d1 = pass1["surface"][side].get("defects", [])
        d2 = pass2["surface"][side].get("defects", [])
        # Use labels from the worse-scoring pass so they match the numeric direction.
        label_pass = pass1 if s1 <= s2 else pass2
        result["surface"][side] = {
            "score": round((s1 + s2) / 2, 1),
            "defects": list(dict.fromkeys(d1 + d2)),
            "staining": label_pass["surface"][side].get("staining", "none"),
            "gloss": label_pass["surface"][side].get("gloss", "original gloss intact"),
            "print_registration": label_pass["surface"][side].get("print_registration", "normal"),
            # For damage fields use "most severe wins" — we never want to average away real damage.
            "crease_depth": _most_severe(
                pass1["surface"][side].get("crease_depth"),
                pass2["surface"][side].get("crease_depth"),
                _CREASE_ORDER,
            ),
            "whitening_coverage": _most_severe(
                pass1["surface"][side].get("whitening_coverage"),
                pass2["surface"][side].get("whitening_coverage"),
                _WHITENING_ORDER,
            ),
            "confidence": round((c1 + c2) / 2, 3),
        }

    return result


def _median_of_three(pass1: Dict, pass2: Dict, pass3: Dict) -> Dict:
    """Take the median numeric score across 3 passes; use strings from the lowest-scoring pass."""
    result = {
        "corners": {},
        "edges": {},
        "surface": {"front": {}, "back": {}},
    }

    for key in pass1["corners"]:
        scores = [
            float(pass1["corners"][key]["score"]),
            float(pass2["corners"][key]["score"]),
            float(pass3["corners"][key]["score"]),
        ]
        confs = [
            float(pass1["corners"][key].get("confidence", 1.0)),
            float(pass2["corners"][key].get("confidence", 1.0)),
            float(pass3["corners"][key].get("confidence", 1.0)),
        ]
        defects = list(dict.fromkeys(
            pass1["corners"][key].get("defects", []) +
            pass2["corners"][key].get("defects", []) +
            pass3["corners"][key].get("defects", [])
        ))
        result["corners"][key] = {
            "score": statistics.median(scores),
            "defects": defects,
            "confidence": round(statistics.median(confs), 3),
        }

    for key in pass1["edges"]:
        scores = [
            float(pass1["edges"][key]["score"]),
            float(pass2["edges"][key]["score"]),
            float(pass3["edges"][key]["score"]),
        ]
        confs = [
            float(pass1["edges"][key].get("confidence", 1.0)),
            float(pass2["edges"][key].get("confidence", 1.0)),
            float(pass3["edges"][key].get("confidence", 1.0)),
        ]
        defects = list(dict.fromkeys(
            pass1["edges"][key].get("defects", []) +
            pass2["edges"][key].get("defects", []) +
            pass3["edges"][key].get("defects", [])
        ))
        result["edges"][key] = {
            "score": statistics.median(scores),
            "defects": defects,
            "confidence": round(statistics.median(confs), 3),
        }

    for side in ("front", "back"):
        passes = [pass1, pass2, pass3]
        scores = [float(p["surface"][side]["score"]) for p in passes]
        confs = [float(p["surface"][side].get("confidence", 1.0)) for p in passes]
        defects = list(dict.fromkeys(
            pass1["surface"][side].get("defects", []) +
            pass2["surface"][side].get("defects", []) +
            pass3["surface"][side].get("defects", [])
        ))
        # Use labels from the worst-scoring pass so they stay consistent with the numeric score.
        label_pass = passes[scores.index(min(scores))]
        result["surface"][side] = {
            "score": statistics.median(scores),
            "defects": defects,
            "staining": label_pass["surface"][side].get("staining", "none"),
            "gloss": label_pass["surface"][side].get("gloss", "original gloss intact"),
            "print_registration": label_pass["surface"][side].get("print_registration", "normal"),
            # Most severe wins across all three passes — real damage shouldn't be voted away.
            "crease_depth": _most_severe_of_three(
                pass1["surface"][side].get("crease_depth"),
                pass2["surface"][side].get("crease_depth"),
                pass3["surface"][side].get("crease_depth"),
                _CREASE_ORDER,
            ),
            "whitening_coverage": _most_severe_of_three(
                pass1["surface"][side].get("whitening_coverage"),
                pass2["surface"][side].get("whitening_coverage"),
                pass3["surface"][side].get("whitening_coverage"),
                _WHITENING_ORDER,
            ),
            "confidence": round(statistics.median(confs), 3),
        }

    return result


def _max_score_disagreement(pass1: Dict, pass2: Dict) -> float:
    """Return the maximum absolute difference in any score between two passes."""
    s1 = _extract_numeric_scores(pass1)
    s2 = _extract_numeric_scores(pass2)
    return max(abs(s1[k] - s2[k]) for k in s1)


# ---------------------------------------------------------------------------
# Confidence flagging
# ---------------------------------------------------------------------------

def _collect_low_confidence_flags(merged: Dict) -> List[str]:
    """Return list of location strings where confidence < LOW_CONFIDENCE_THRESHOLD."""
    flags = []
    for key, val in merged.get("corners", {}).items():
        if float(val.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD:
            flags.append(f"corner_{key}")
    for key, val in merged.get("edges", {}).items():
        if float(val.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD:
            flags.append(f"edge_{key}")
    for side in ("front", "back"):
        if float(merged["surface"][side].get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD:
            flags.append(f"surface_{side}")
    return flags


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def assess_card(
    front_img: np.ndarray,
    back_img: np.ndarray,
    api_key: Optional[str] = None,
) -> Dict:
    """
    Run Vision AI assessment on both card sides.

    Performs dual-pass averaging. If any score disagrees by > 1.5 between
    passes, a third pass is run and the median is taken.

    Returns a dict with:
      - corners: {key: {score, defects, confidence}, ...}  (8 entries)
      - edges:   {key: {score, defects, confidence}, ...}  (8 entries)
      - surface: {front: {...}, back: {...}}
      - low_confidence_flags: [str]

    Raises VisionAssessorError on unrecoverable failure.
    """
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise VisionAssessorError("ANTHROPIC_API_KEY not set")

    images = prepare_images(front_img, back_img)

    logger.info("Vision AI grading: starting pass 1")
    pass1 = _call_api_sync(images, key)

    logger.info("Vision AI grading: starting pass 2")
    pass2 = _call_api_sync(images, key)

    max_diff = _max_score_disagreement(pass1, pass2)
    logger.info(f"Vision AI passes 1/2 max disagreement: {max_diff:.2f}")

    if max_diff > PASS_DISAGREEMENT_THRESHOLD:
        logger.info(f"Disagreement {max_diff:.2f} > {PASS_DISAGREEMENT_THRESHOLD} — running pass 3 for median")
        pass3 = _call_api_sync(images, key)
        merged = _median_of_three(pass1, pass2, pass3)
    else:
        merged = _average_passes(pass1, pass2)

    merged["low_confidence_flags"] = _collect_low_confidence_flags(merged)

    if merged["low_confidence_flags"]:
        logger.warning(f"Low confidence locations: {merged['low_confidence_flags']}")

    return merged
