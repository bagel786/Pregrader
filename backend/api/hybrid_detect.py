"""
Hybrid card detection: multi-method OpenCV with Vision AI fallback.
Pure detection logic — no session management, no routes.

Usage:
    result = await detect_and_correct_card(image_path, session_id="abc")
    if result["success"]:
        corrected_image = result["corrected_image"]  # numpy array
"""
import os
import cv2
import json
import time
import asyncio
import logging
import threading
import numpy as np
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DetectionConfig:
    """Detection configuration from environment variables."""
    DEFAULT_METHOD = os.getenv("DEFAULT_DETECTION_METHOD", "hybrid")
    OPENCV_THRESHOLD = float(os.getenv("OPENCV_CONFIDENCE_THRESHOLD", "0.70"))
    AI_TIMEOUT = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))
    VISION_AI_PROVIDER = os.getenv("VISION_AI_PROVIDER", "claude")
    MAX_CONCURRENT_AI = int(os.getenv("MAX_CONCURRENT_AI_REQUESTS", "5"))
    ENABLE_DEBUG = os.getenv("ENABLE_DEBUG_IMAGES", "true").lower() == "true"
    DEBUG_RETENTION_HOURS = int(os.getenv("DEBUG_IMAGE_RETENTION_HOURS", "24"))


# Limit concurrent AI requests
_ai_semaphore = asyncio.Semaphore(DetectionConfig.MAX_CONCURRENT_AI)

# In-memory stats
_detection_stats = {
    "total": 0,
    "opencv_success": 0,
    "ai_success": 0,
    "failures": 0,
    "total_time_ms": 0,
}
_stats_lock = threading.Lock()


# ============================================================================
# PUBLIC API
# ============================================================================

async def detect_and_correct_card(
    image_path: str,
    session_id: str = "",
) -> Dict:
    """
    Detect a card in the image using hybrid approach.

    1. Tries 4 OpenCV methods (fast)
    2. Falls back to Vision AI if OpenCV confidence is too low

    Returns:
        {
            "success": bool,
            "corrected_image": np.ndarray | None,  # perspective-corrected card
            "method": str,          # e.g. "opencv_standard", "hybrid_ai"
            "confidence": float,
            "quality_assessment": dict | None,  # from AI, if used
            "recommendations": list[str],       # tips if detection failed
            "detection_log": dict,
        }
    """
    start_time = time.time()
    log = {"session_id": session_id, "file": image_path}

    # Step 1: OpenCV (fast path) -----------------------------------------------
    logger.info(f"[{session_id}] Attempting OpenCV detection…")
    opencv_result = _try_opencv_detection(image_path)
    opencv_ms = int((time.time() - start_time) * 1000)
    log["opencv_time_ms"] = opencv_ms
    log["opencv_confidence"] = opencv_result.get("confidence", 0)

    logger.info(
        f"[{session_id}] OpenCV: success={opencv_result['success']}, "
        f"confidence={opencv_result.get('confidence', 0):.2f}, time={opencv_ms}ms"
    )

    if opencv_result["success"] and opencv_result["confidence"] >= DetectionConfig.OPENCV_THRESHOLD:
        method = f"opencv_{opencv_result.get('method', 'unknown')}"
        total_ms = int((time.time() - start_time) * 1000)
        log["final_method"] = method
        log["total_time_ms"] = total_ms
        _record_stat(method, total_ms)
        logger.info(
            f"[BRANCH] session={session_id} branch=opencv sub={opencv_result.get('method')} "
            f"conf={opencv_result['confidence']:.2f} time={total_ms}ms"
        )

        return {
            "success": True,
            "corrected_image": opencv_result["corrected_image"],
            "method": method,
            "confidence": opencv_result["confidence"],
            "quality_assessment": None,
            "recommendations": [],
            "detection_log": log,
        }

    # Step 2: Vision AI fallback -----------------------------------------------
    logger.info(f"[{session_id}] OpenCV confidence too low, trying Vision AI…")
    ai_result = await _try_ai_fallback(image_path, session_id)

    total_ms = int((time.time() - start_time) * 1000)
    log["ai_attempted"] = True
    log["ai_confidence"] = ai_result.get("confidence", 0)
    log["total_time_ms"] = total_ms

    if ai_result.get("success"):
        log["final_method"] = "hybrid_ai"
        _record_stat("hybrid_ai", total_ms)
        logger.info(
            f"[BRANCH] session={session_id} branch=vision_ai "
            f"conf={ai_result['confidence']:.2f} time={total_ms}ms"
        )

        return {
            "success": True,
            "corrected_image": ai_result["corrected_image"],
            "method": "hybrid_ai",
            "confidence": ai_result["confidence"],
            "quality_assessment": ai_result.get("quality_assessment"),
            "border_fractions": ai_result.get("border_fractions"),
            "recommendations": [],
            "detection_log": log,
        }

    # Both failed — client falls back to static guide crop --------------------
    log["final_method"] = "failed"
    _record_stat("failed", total_ms)
    logger.warning(
        f"[BRANCH] session={session_id} branch=failed "
        f"opencv_conf={opencv_result.get('confidence', 0):.2f} "
        f"ai_conf={ai_result.get('confidence', 0):.2f} time={total_ms}ms"
    )

    return {
        "success": False,
        "corrected_image": None,
        "method": "failed",
        "confidence": 0.0,
        "quality_assessment": None,
        "recommendations": [
            "Ensure the card fills most of the frame",
            "Use a plain, contrasting background",
            "Ensure good, even lighting",
            "Hold the camera steady to avoid blur",
        ],
        "detection_log": log,
    }


def get_detection_stats() -> Dict:
    """Return current detection statistics."""
    total = _detection_stats["total"]
    if total == 0:
        return {"message": "No detections yet"}
    return {
        "total_detections": total,
        "success_rate": (_detection_stats["opencv_success"] + _detection_stats["ai_success"]) / total,
        "method_usage": {
            "opencv": _detection_stats["opencv_success"] / total,
            "hybrid_ai": _detection_stats["ai_success"] / total,
        },
        "avg_processing_time_ms": _detection_stats["total_time_ms"] / total,
    }


# ============================================================================
# OPENCV DETECTION (4 methods, best score wins)
# ============================================================================

def _try_opencv_detection(image_path: str) -> Dict:
    """Try multiple OpenCV card-detection methods, return best result."""
    img = cv2.imread(image_path)
    if img is None:
        return {"success": False, "confidence": 0.0, "error": "Could not load image"}

    methods = [
        ("standard", _opencv_standard),
        ("adaptive", _opencv_adaptive),
        ("morphological", _opencv_morphological),
        ("lab", _opencv_lab),
    ]

    best: Dict = {"success": False, "confidence": 0.0}
    for name, func in methods:
        result = func(img)
        if result["success"] and result["confidence"] > best["confidence"]:
            best = result
            best["method"] = name

    return best


def _opencv_standard(img: np.ndarray) -> Dict:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return _extract_card_from_edges(img, edges)


def _opencv_adaptive(img: np.ndarray) -> Dict:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    return _extract_card_from_edges(img, thresh)


def _opencv_morphological(img: np.ndarray) -> Dict:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = np.ones((3, 3), np.uint8)
    morph = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    return _extract_card_from_edges(img, morph)


def _opencv_lab(img: np.ndarray) -> Dict:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel = clahe.apply(lab[:, :, 0])
    blurred = cv2.GaussianBlur(l_channel, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 90)  # lower thresholds tuned for low-light L channel
    return _extract_card_from_edges(img, edges)


def _extract_card_from_edges(img: np.ndarray, edges: np.ndarray) -> Dict:
    """Find the best card-shaped contour and perspective-correct it."""
    h, w = img.shape[:2]
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = 0.20 * w * h
    max_area = 0.90 * w * h
    target_aspect = 0.714  # standard trading card ratio

    best_score = 0.0
    best_cnt = None

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        rect = cv2.minAreaRect(cnt)
        box_w, box_h = rect[1]
        if box_h == 0:
            continue

        aspect = box_w / box_h
        aspect_diff = min(abs(aspect - target_aspect), abs(aspect - 1 / target_aspect))
        if aspect_diff > 0.08:
            continue

        score = (area / (w * h)) * (1 - aspect_diff)
        if score > best_score:
            best_score = score
            best_cnt = cnt

    if best_cnt is None:
        return {"success": False, "confidence": 0.0}

    peri = cv2.arcLength(best_cnt, True)
    approx = cv2.approxPolyDP(best_cnt, 0.02 * peri, True)
    if len(approx) < 4:
        return {"success": False, "confidence": best_score}

    corners = _order_points(approx.reshape(-1, 2))
    dst_pts = np.array([[0, 0], [499, 0], [499, 699], [0, 699]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst_pts)
    warped = cv2.warpPerspective(img, M, (500, 700))

    # Post-warp quality check: reject warps that captured background, not a card
    warp_quality = _check_warp_quality(warped)
    if warp_quality < 0.5:
        logger.warning(
            f"Post-warp quality check failed (score={warp_quality:.2f}) — "
            "border strips not uniform; likely a background crop"
        )
        return {"success": False, "confidence": best_score * warp_quality}

    return {
        "success": True,
        "confidence": best_score,
        "corners": corners.tolist(),
        "corrected_image": warped,
    }


def _check_warp_quality(warped: np.ndarray) -> float:
    """
    Verify the warped image looks like a card by checking border uniformity.

    Samples 10-pixel strips along all 4 edges.  A real card border (white,
    black, or any solid colour) has low pixel-to-pixel variation.  A misaligned
    warp capturing background/table/grass will have high variation and fail.

    Returns a score in [0.0, 1.0]: fraction of edges that pass (std < 45).
    A score < 0.5 means at least 3 edges look like background — reject the warp.
    """
    STRIP_W = 10
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    strips = [
        gray[:STRIP_W, :],    # top
        gray[-STRIP_W:, :],   # bottom
        gray[:, :STRIP_W],    # left
        gray[:, -STRIP_W:],   # right
    ]
    passes = sum(1 for s in strips if float(np.std(s)) < 45.0)
    return passes / len(strips)


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order points: TL, TR, BR, BL."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


# ============================================================================
# VISION AI FALLBACK
# ============================================================================

async def _try_ai_fallback(image_path: str, session_id: str) -> Dict:
    """Try Vision AI detection with concurrency limiting."""
    try:
        from services.ai.vision_detector import VisionAIDetector

        async with _ai_semaphore:
            detector = VisionAIDetector(
                provider=DetectionConfig.VISION_AI_PROVIDER,
                timeout=DetectionConfig.AI_TIMEOUT,
            )
            logger.info(f"[{session_id}] Calling Vision AI API…")
            ai_result = await detector.hybrid_detection(image_path)

            if ai_result.get("final_corners") is not None and ai_result.get("confidence", 0) > 0.7:
                corrected = detector.apply_perspective_correction(
                    image_path, ai_result["final_corners"]
                )
                return {
                    "success": True,
                    "corrected_image": corrected,
                    "confidence": ai_result["confidence"],
                    "quality_assessment": ai_result.get("llm_result", {}).get("quality_assessment"),
                    "border_fractions": ai_result.get("border_fractions"),
                }

        return {"success": False, "confidence": ai_result.get("confidence", 0), "border_fractions": None}

    except Exception as e:
        logger.error(f"[{session_id}] AI detection failed: {e}")
        return {"success": False, "confidence": 0.0, "error": str(e)}


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _record_stat(method: str, duration_ms: int = 0):
    with _stats_lock:
        _detection_stats["total"] += 1
        _detection_stats["total_time_ms"] += duration_ms
        if method.startswith("opencv"):
            _detection_stats["opencv_success"] += 1
        elif method == "hybrid_ai":
            _detection_stats["ai_success"] += 1
        else:
            _detection_stats["failures"] += 1
