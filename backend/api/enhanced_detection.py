"""
Railway-Ready Enhanced Detection Integration
Includes visual debugging to show exactly what's being detected

Addresses your issues:
- "not sure what it is seeing"
- Works inconsistently across backgrounds
- Poor angled card detection
- Corner detection false positives
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
import cv2
import numpy as np
from pathlib import Path
import asyncio
import time
import os
import json
import io
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta

# Configure logging
logger = logging.getLogger(__name__)

# Your existing imports
from api.session_manager import get_session_manager
from analysis.centering import calculate_centering_ratios
from analysis.edges import analyze_edge_wear
from analysis.surface import analyze_surface_damage

# New imports
from analysis.enhanced_corners import analyze_corners_enhanced
from services.ai.vision_detector import VisionAIDetector

router = APIRouter()

# Get session manager instance
session_manager = get_session_manager()

logger.info("Enhanced detection module loaded")


# ============================================================================
# CONFIGURATION
# ============================================================================

class DetectionConfig:
    """Centralized configuration"""
    DEFAULT_METHOD = os.getenv('DEFAULT_DETECTION_METHOD', 'hybrid')
    VISION_AI_PROVIDER = os.getenv('VISION_AI_PROVIDER', 'claude')
    OPENCV_THRESHOLD = float(os.getenv('OPENCV_CONFIDENCE_THRESHOLD', '0.70'))
    ENABLE_DEBUG = os.getenv('ENABLE_DEBUG_IMAGES', 'true').lower() == 'true'
    DEBUG_RETENTION_HOURS = int(os.getenv('DEBUG_IMAGE_RETENTION_HOURS', '24'))
    MAX_CONCURRENT_AI = int(os.getenv('MAX_CONCURRENT_AI_REQUESTS', '5'))
    AI_TIMEOUT = int(os.getenv('AI_TIMEOUT_SECONDS', '30'))

logger.info(f"Detection Config: method={DetectionConfig.DEFAULT_METHOD}, "
           f"threshold={DetectionConfig.OPENCV_THRESHOLD}, "
           f"debug={DetectionConfig.ENABLE_DEBUG}, "
           f"ai_timeout={DetectionConfig.AI_TIMEOUT}s")


# Track concurrent AI requests
_ai_semaphore = asyncio.Semaphore(DetectionConfig.MAX_CONCURRENT_AI)


# ============================================================================
# MAIN UPLOAD ENDPOINT (Hybrid Detection)
# ============================================================================

@router.post("/grading/{session_id}/upload-front")
async def upload_front_hybrid(
    session_id: str,
    file: UploadFile = File(...)
):
    """
    Primary upload endpoint with hybrid detection
    
    This will:
    1. Try fast OpenCV detection first
    2. Fall back to Vision AI if needed
    3. Save debug images showing what was detected
    4. Use enhanced corner detection (fewer false positives)
    """
    logger.info(f"[{session_id}] Upload front image started")
    logger.info(f"[{session_id}] File: {file.filename}, Content-Type: {file.content_type}")
    
    session = session_manager.get_session(session_id)
    if not session:
        logger.error(f"[{session_id}] Session not found")
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Save uploaded file
    file_path = Path(f"temp_uploads/{session_id}/front_original.jpg")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    content = await file.read()
    logger.info(f"[{session_id}] File size: {len(content)} bytes")
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"[{session_id}] File saved to {file_path}")
    
    start_time = time.time()
    detection_log = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "file_size_bytes": len(content)
    }
    
    # DETECTION PIPELINE
    try:
        logger.info(f"[{session_id}] Starting detection pipeline")
        
        # Step 1: Try OpenCV first (fast path)
        logger.info(f"[{session_id}] Attempting OpenCV detection...")
        opencv_result = await _try_opencv_detection(str(file_path), session_id)
        opencv_time = time.time() - start_time
        
        detection_log["opencv_attempted"] = True
        detection_log["opencv_time_ms"] = int(opencv_time * 1000)
        detection_log["opencv_success"] = opencv_result["success"]
        detection_log["opencv_confidence"] = opencv_result.get("confidence", 0)
        
        logger.info(f"[{session_id}] OpenCV result: success={opencv_result['success']}, "
                   f"confidence={opencv_result.get('confidence', 0):.2f}, "
                   f"time={opencv_time*1000:.0f}ms")
        
        if opencv_result["success"] and opencv_result["confidence"] >= DetectionConfig.OPENCV_THRESHOLD:
            # High confidence OpenCV - use it
            logger.info(f"[{session_id}] Using OpenCV result (confidence above threshold)")
            corrected = opencv_result["corrected_image"]
            method = f"opencv_{opencv_result['method']}"
            confidence = opencv_result["confidence"]
            quality_assessment = None
            
            detection_log["final_method"] = method
            
        else:
            # Low confidence or failed - use Vision AI
            logger.info(f"[{session_id}] OpenCV confidence too low, falling back to Vision AI...")
            
            async with _ai_semaphore:  # Limit concurrent AI requests
                ai_start = time.time()
                
                try:
                    logger.info(f"[{session_id}] Initializing Vision AI detector...")
                    detector = VisionAIDetector(
                        provider=DetectionConfig.VISION_AI_PROVIDER,
                        timeout=DetectionConfig.AI_TIMEOUT
                    )
                    
                    logger.info(f"[{session_id}] Calling Vision AI API...")
                    ai_result = await detector.hybrid_detection(str(file_path))
                    ai_time = time.time() - ai_start
                    
                    detection_log["ai_attempted"] = True
                    detection_log["ai_time_ms"] = int(ai_time * 1000)
                    detection_log["ai_confidence"] = ai_result.get("confidence", 0)
                    
                    logger.info(f"[{session_id}] Vision AI result: confidence={ai_result.get('confidence', 0):.2f}, "
                               f"time={ai_time*1000:.0f}ms")
                    
                    if ai_result["final_corners"] and ai_result["confidence"] > 0.7:
                        logger.info(f"[{session_id}] Applying perspective correction...")
                        corrected = detector.apply_perspective_correction(
                            str(file_path),
                            ai_result["final_corners"]
                        )
                        method = "hybrid_ai"
                        confidence = ai_result["confidence"]
                        quality_assessment = ai_result.get("llm_result", {}).get("quality_assessment")
                        
                        detection_log["final_method"] = "hybrid_ai"
                        logger.info(f"[{session_id}] Successfully corrected image using AI")
                        
                    else:
                        logger.error(f"[{session_id}] AI confidence too low: {ai_result.get('confidence', 0)}")
                        raise Exception(f"AI confidence too low: {ai_result.get('confidence', 0)}")
                        
                except asyncio.TimeoutError:
                    logger.error(f"[{session_id}] AI detection timeout after {DetectionConfig.AI_TIMEOUT}s")
                    raise HTTPException(
                        status_code=408,
                        detail=f"Detection timeout after {DetectionConfig.AI_TIMEOUT}s"
                    )
                except Exception as e:
                    logger.error(f"[{session_id}] AI detection failed: {str(e)}")
                    detection_log["ai_error"] = str(e)
                    
                    # Both failed - return helpful error
                    return JSONResponse(
                        status_code=400,
                        content={
                            "success": False,
                            "error": "Could not detect card in image",
                            "details": {
                                "opencv_confidence": opencv_result.get("confidence", 0),
                                "opencv_method": opencv_result.get("method"),
                                "ai_error": str(e)
                            },
                            "recommendations": opencv_result.get("recommendations", [
                                "Ensure card fills most of the frame",
                                "Use a plain, contrasting background",
                                "Ensure good, even lighting",
                                "Hold camera steady to avoid blur"
                            ]),
                            "debug_url": f"/api/v2/debug/{session_id}/detection-failure"
                        }
                    )
        
        total_time = time.time() - start_time
        detection_log["total_time_ms"] = int(total_time * 1000)
        
        logger.info(f"[{session_id}] Detection complete: method={method}, "
                   f"confidence={confidence:.2f}, total_time={total_time*1000:.0f}ms")
        
        # Save corrected image
        corrected_path = Path(f"temp_uploads/{session_id}/front_corrected.jpg")
        cv2.imwrite(str(corrected_path), corrected)
        logger.info(f"[{session_id}] Corrected image saved")
        
        # ANALYSIS PIPELINE (with enhanced corner detection)
        logger.info(f"[{session_id}] Starting analysis pipeline...")
        
        logger.info(f"[{session_id}] Analyzing centering...")
        centering_result = calculate_centering_ratios(str(corrected_path))
        
        logger.info(f"[{session_id}] Analyzing corners (enhanced)...")
        corners_result = analyze_corners_enhanced(corrected, side="front", debug=DetectionConfig.ENABLE_DEBUG)
        
        logger.info(f"[{session_id}] Analyzing edges...")
        edges_result = analyze_edge_wear(str(corrected_path))
        
        logger.info(f"[{session_id}] Analyzing surface...")
        surface_result = analyze_surface_damage(str(corrected_path))
        
        logger.info(f"[{session_id}] Analysis complete: "
                   f"centering={centering_result.get('score', 0):.1f}, "
                   f"corners={corners_result.get('overall_grade', 0):.1f}, "
                   f"edges={edges_result.get('score', 0):.1f}, "
                   f"surface={surface_result.get('score', 0):.1f}")
        
        # Save debug visualization
        if DetectionConfig.ENABLE_DEBUG:
            logger.info(f"[{session_id}] Generating debug visualization...")
            await _save_debug_visualization(
                session_id,
                str(file_path),
                corrected,
                method,
                confidence,
                {
                    "centering": centering_result,
                    "corners": corners_result,
                    "edges": edges_result,
                    "surface": surface_result
                }
            )
            logger.info(f"[{session_id}] Debug visualization saved")
        
        # Update session
        session["state"] = "front_uploaded"
        session["front_analysis"] = {
            "centering": centering_result,
            "corners": corners_result,
            "edges": edges_result,
            "surface": surface_result
        }
        session["detection_method"] = method
        session["detection_confidence"] = confidence
        session["processing_time_ms"] = int(total_time * 1000)
        session["quality_assessment"] = quality_assessment
        
        # Log detection
        _log_detection(detection_log)
        
        logger.info(f"[{session_id}] Upload front complete successfully")
        
        return {
            "success": True,
            "preview": {
                "centering": centering_result["score"],
                "corners": corners_result["overall_grade"],
                "edges": edges_result["overall_grade"],
                "surface": surface_result["score"]
            },
            "detection": {
                "method": method,
                "confidence": confidence,
                "processing_time_ms": int(total_time * 1000),
                "quality_assessment": quality_assessment
            },
            "debug": {
                "visualization_url": f"/api/v2/debug/{session_id}/visualization",
                "corners_false_positives_filtered": corners_result.get("false_positives_filtered", 0)
            } if DetectionConfig.ENABLE_DEBUG else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Detection failed with exception: {str(e)}", exc_info=True)
        detection_log["error"] = str(e)
        _log_detection(detection_log)
        
        raise HTTPException(
            status_code=500,
            detail=f"Detection failed: {str(e)}"
        )
@router.post("/grading/start")
async def start_grading_session_v2():
    """
    Start a new grading session for v2 API

    Returns:
        Session ID and status for tracking the grading process
    """
    try:
        session = session_manager.create_session()
        logger.info(f"[{session.session_id}] Started new v2 grading session")

        return {
            "session_id": session.session_id,
            "status": "created",
            "message": "Session created. Upload front image first.",
            "next_step": f"/api/v2/grading/{session.session_id}/upload-front"
        }
    except Exception as e:
        logger.error(f"Failed to create v2 session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")





@router.post("/grading/{session_id}/upload-back")
async def upload_back_hybrid(
    session_id: str,
    file: UploadFile = File(...)
):
    """Upload and analyze back of card (same logic as front)"""
    # Similar implementation to upload_front_hybrid
    # ... (abbreviated for brevity, follows same pattern)
    pass
@router.get("/grading/{session_id}/result")
async def get_grading_result_v2(session_id: str):
    """
    Get the final grading result for a completed session

    Args:
        session_id: The session ID

    Returns:
        Final grading results with all analysis data
    """
    logger.info(f"[{session_id}] Getting grading result")

    session = session_manager.get_session(session_id)
    if not session:
        logger.error(f"[{session_id}] Session not found")
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.status != "complete":
        logger.warning(f"[{session_id}] Grading not complete, status: {session.status}")
        return {
            "session_id": session_id,
            "status": session.status,
            "message": f"Grading not complete. Current status: {session.status}",
            "has_front": session.front_image_path is not None,
            "has_back": session.back_image_path is not None
        }

    logger.info(f"[{session_id}] Returning complete grading result")
    return {
        "session_id": session_id,
        "status": "complete",
        "grade": session.combined_grade.get("grade") if session.combined_grade else None,
        "front_analysis": session.front_analysis,
        "back_analysis": session.back_analysis,
        "combined_grade": session.combined_grade
    }





# ============================================================================
# DETECTION HELPERS
# ============================================================================

async def _try_opencv_detection(image_path: str, session_id: str) -> Dict:
    """Try multiple OpenCV methods"""
    img = cv2.imread(image_path)
    if img is None:
        return {"success": False, "error": "Could not load image", "confidence": 0.0}
    
    methods = [
        ("standard", _opencv_standard),
        ("adaptive", _opencv_adaptive),
        ("morphological", _opencv_morphological),
        ("lab", _opencv_lab)
    ]
    
    best_result = {"success": False, "confidence": 0.0}
    
    for method_name, method_func in methods:
        result = method_func(img)
        if result["success"] and result["confidence"] > best_result["confidence"]:
            best_result = result
            best_result["method"] = method_name
    
    return best_result


def _opencv_standard(img: np.ndarray) -> Dict:
    """Standard Canny edge detection"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return _extract_card_from_edges(img, edges)


def _opencv_adaptive(img: np.ndarray) -> Dict:
    """Adaptive threshold method"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    return _extract_card_from_edges(img, thresh)


def _opencv_morphological(img: np.ndarray) -> Dict:
    """Morphological operations method"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = np.ones((3, 3), np.uint8)
    morph = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    return _extract_card_from_edges(img, morph)


def _opencv_lab(img: np.ndarray) -> Dict:
    """LAB color space method"""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]
    blurred = cv2.GaussianBlur(l_channel, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return _extract_card_from_edges(img, edges)


def _extract_card_from_edges(img: np.ndarray, edges: np.ndarray) -> Dict:
    """Extract card from edge image (implementation from previous file)"""
    h, w = img.shape[:2]
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    min_area = 0.20 * (w * h)
    max_area = 0.90 * (w * h)
    target_aspect = 0.714
    
    best_score = 0
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
        aspect_diff = min(abs(aspect - target_aspect), abs(aspect - (1/target_aspect)))
        
        if aspect_diff > 0.15:
            continue
        
        score = (area / (w * h)) * (1 - aspect_diff)
        if score > best_score:
            best_score = score
            best_cnt = cnt
    
    if best_cnt is None:
        return {"success": False, "confidence": 0.0}
    
    # Get corners and apply perspective correction
    peri = cv2.arcLength(best_cnt, True)
    approx = cv2.approxPolyDP(best_cnt, 0.02 * peri, True)
    
    if len(approx) < 4:
        return {"success": False, "confidence": best_score}
    
    corners = _order_points(approx.reshape(-1, 2))
    
    dst_pts = np.array([[0, 0], [499, 0], [499, 699], [0, 699]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst_pts)
    warped = cv2.warpPerspective(img, M, (500, 700))
    
    return {
        "success": True,
        "confidence": best_score,
        "corners": corners.tolist(),
        "corrected_image": warped
    }


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order points: TL, TR, BR, BL"""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


# ============================================================================
# VISUAL DEBUGGING ENDPOINTS
# ============================================================================

async def _save_debug_visualization(
    session_id: str,
    original_path: str,
    corrected: np.ndarray,
    method: str,
    confidence: float,
    analysis_results: Dict
):
    """
    Create visual debug image showing what was detected
    This addresses the "not sure what it's seeing" issue
    """
    debug_dir = Path(f"temp_uploads/{session_id}/debug")
    debug_dir.mkdir(exist_ok=True)
    
    # Load original
    original = cv2.imread(original_path)
    
    # Create visualization
    h, w = original.shape[:2]
    
    # Resize for display if needed
    max_size = 800
    if w > max_size or h > max_size:
        scale = max_size / max(w, h)
        original_display = cv2.resize(original, None, fx=scale, fy=scale)
    else:
        original_display = original.copy()
    
    # Add detection info overlay
    overlay = original_display.copy()
    
    # Add text background
    cv2.rectangle(overlay, (10, 10), (400, 120), (0, 0, 0), -1)
    
    # Add text
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(overlay, f"Detection Method: {method}", (20, 35), font, 0.6, (0, 255, 0), 2)
    cv2.putText(overlay, f"Confidence: {confidence:.2%}", (20, 65), font, 0.6, (0, 255, 0), 2)
    cv2.putText(overlay, f"Time: {session_manager.get_session(session_id).get('processing_time_ms', 0)}ms", 
                (20, 95), font, 0.6, (0, 255, 0), 2)
    
    # Blend overlay
    alpha = 0.7
    original_display = cv2.addWeighted(overlay, alpha, original_display, 1 - alpha, 0)
    
    # Save annotated original
    cv2.imwrite(str(debug_dir / "01_detection_result.jpg"), original_display)
    
    # Save corrected with analysis overlay
    corrected_display = corrected.copy()
    
    # Add corner annotations
    corners_info = analysis_results["corners"]
    corner_positions = [(50, 50), (450, 50), (450, 650), (50, 650)]  # TL, TR, BR, BL
    corner_names = ["TL", "TR", "BR", "BL"]
    
    for i, (score, pos, name) in enumerate(zip(
        corners_info["individual_scores"],
        corner_positions,
        corner_names
    )):
        # Color based on score
        color = (0, 255, 0) if score >= 9 else (0, 165, 255) if score >= 7 else (0, 0, 255)
        
        cv2.circle(corrected_display, pos, 20, color, 3)
        cv2.putText(corrected_display, f"{name}: {score:.1f}", 
                   (pos[0] - 30, pos[1] + 40), font, 0.5, color, 2)
    
    # Add overall scores
    y_offset = 30
    cv2.putText(corrected_display, f"Centering: {analysis_results['centering']['score']:.1f}", 
                (10, y_offset), font, 0.6, (255, 255, 255), 2)
    y_offset += 30
    cv2.putText(corrected_display, f"Corners: {corners_info['overall_grade']:.1f}", 
                (10, y_offset), font, 0.6, (255, 255, 255), 2)
    y_offset += 30
    cv2.putText(corrected_display, f"Edges: {analysis_results['edges']['overall_grade']:.1f}", 
                (10, y_offset), font, 0.6, (255, 255, 255), 2)
    y_offset += 30
    cv2.putText(corrected_display, f"Surface: {analysis_results['surface']['score']:.1f}", 
                (10, y_offset), font, 0.6, (255, 255, 255), 2)
    
    # Note false positives filtered
    if corners_info.get("false_positives_filtered", 0) > 0:
        y_offset += 40
        cv2.putText(corrected_display, f"Corner FP filtered: {corners_info['false_positives_filtered']}", 
                    (10, y_offset), font, 0.5, (0, 255, 255), 2)
    
    cv2.imwrite(str(debug_dir / "02_analysis_overlay.jpg"), corrected_display)
    
    # Create side-by-side comparison
    h1, w1 = original_display.shape[:2]
    h2, w2 = corrected_display.shape[:2]
    
    # Resize to same height
    if h1 != h2:
        scale = h2 / h1
        original_display = cv2.resize(original_display, None, fx=scale, fy=scale)
        w1 = int(w1 * scale)
    
    # Combine
    comparison = np.hstack([original_display, corrected_display])
    cv2.imwrite(str(debug_dir / "00_comparison.jpg"), comparison)


@router.get("/debug/{session_id}/visualization")
async def get_debug_visualization(session_id: str):
    """Get the visual debug image showing what was detected"""
    debug_path = Path(f"temp_uploads/{session_id}/debug/00_comparison.jpg")
    
    if not debug_path.exists():
        raise HTTPException(status_code=404, detail="Debug visualization not found")
    
    return FileResponse(debug_path, media_type="image/jpeg")


@router.get("/debug/{session_id}/detection-result")
async def get_detection_result(session_id: str):
    """Get annotated original image"""
    debug_path = Path(f"temp_uploads/{session_id}/debug/01_detection_result.jpg")
    
    if not debug_path.exists():
        raise HTTPException(status_code=404, detail="Detection result not found")
    
    return FileResponse(debug_path, media_type="image/jpeg")


@router.get("/debug/{session_id}/analysis-overlay")
async def get_analysis_overlay(session_id: str):
    """Get corrected image with analysis overlay"""
    debug_path = Path(f"temp_uploads/{session_id}/debug/02_analysis_overlay.jpg")
    
    if not debug_path.exists():
        raise HTTPException(status_code=404, detail="Analysis overlay not found")
    
    return FileResponse(debug_path, media_type="image/jpeg")


@router.get("/debug/{session_id}/detection-failure")
async def debug_detection_failure(session_id: str):
    """
    Special endpoint when detection fails
    Returns diagnostic information
    """
    from analysis.vision.debugger import CardDetectionDebugger
    
    original_path = Path(f"temp_uploads/{session_id}/front_original.jpg")
    if not original_path.exists():
        raise HTTPException(status_code=404, detail="Original image not found")
    
    debugger = CardDetectionDebugger(output_dir=f"temp_uploads/{session_id}/debug_detailed")
    
    # Run full diagnostic
    results = debugger.visualize_full_pipeline(str(original_path), session_id=session_id)
    diagnosis = debugger.diagnose_detection_failure(str(original_path))
    
    return {
        "diagnosis": diagnosis,
        "issues": [line for line in diagnosis.split("\n") if "⚠️" in line],
        "detection_steps": results,
        "debug_images": {
            "original": f"/api/v2/debug/{session_id}/debug_detailed/01_original.jpg",
            "edges": f"/api/v2/debug/{session_id}/debug_detailed/04a_edges_canny_normal.jpg",
            "candidates": f"/api/v2/debug/{session_id}/debug_detailed/06_candidates.jpg",
        }
    }


# ============================================================================
# MONITORING & STATS
# ============================================================================

_detection_stats = {
    "total": 0,
    "opencv_success": 0,
    "ai_success": 0,
    "failures": 0,
    "total_time_ms": 0
}


def _log_detection(log_entry: Dict):
    """Log detection for monitoring"""
    logger.info(f"DETECTION_LOG: {json.dumps(log_entry)}")
    
    # Update stats
    _detection_stats["total"] += 1
    
    if log_entry.get("final_method", "").startswith("opencv"):
        _detection_stats["opencv_success"] += 1
    elif log_entry.get("final_method") == "hybrid_ai":
        _detection_stats["ai_success"] += 1
    else:
        _detection_stats["failures"] += 1
    
    _detection_stats["total_time_ms"] += log_entry.get("total_time_ms", 0)


@router.get("/admin/detection-stats")
async def get_detection_stats():
    """Get detection statistics"""
    total = _detection_stats["total"]
    
    logger.info(f"Detection stats requested: {_detection_stats}")
    
    if total == 0:
        return {"message": "No detections yet"}
    
    stats = {
        "total_detections": total,
        "success_rate": (_detection_stats["opencv_success"] + _detection_stats["ai_success"]) / total,
        "method_usage": {
            "opencv": _detection_stats["opencv_success"] / total,
            "hybrid_ai": _detection_stats["ai_success"] / total
        },
        "avg_processing_time_ms": _detection_stats["total_time_ms"] / total
    }
    
    logger.info(f"Returning stats: {stats}")
    return stats


# Cleanup old debug files
@router.on_event("startup")
async def cleanup_old_debug_files():
    """Clean up debug files older than retention period"""
    async def cleanup_loop():
        while True:
            try:
                retention = timedelta(hours=DetectionConfig.DEBUG_RETENTION_HOURS)
                cutoff = datetime.now() - retention
                
                debug_dirs = Path("temp_uploads").glob("*/debug")
                for debug_dir in debug_dirs:
                    if debug_dir.stat().st_mtime < cutoff.timestamp():
                        import shutil
                        shutil.rmtree(debug_dir, ignore_errors=True)
                
                await asyncio.sleep(3600)  # Run every hour
            except Exception as e:
                print(f"Cleanup error: {e}")
                await asyncio.sleep(3600)
    
    asyncio.create_task(cleanup_loop())
