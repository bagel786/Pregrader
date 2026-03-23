"""
Grading workflow routes: upload front/back images and retrieve results.
"""
import time
import logging
import cv2
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File

from api.session_manager import get_session_manager
from api.combined_grading import analyze_single_side, combine_front_back_analysis
from api.hybrid_detect import detect_and_correct_card
from analysis.corners import analyze_corners as analyze_corners_enhanced
from analysis.vision.quality_checks import check_image_quality
from utils.serialization import convert_numpy_types

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

router = APIRouter(prefix="/api/grading", tags=["grading"])


@router.post("/{session_id}/upload-front")
async def upload_front_image(
    session_id: str,
    file: UploadFile = File(..., description="Front side of the Pokemon card"),
):
    """
    Upload, detect, and analyze the front image of a card.
    Uses hybrid detection: multi-method OpenCV + Vision AI fallback.
    """
    start_time = time.time()
    logger.info(f"[{session_id}] Starting front image upload and analysis")

    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum 15MB per image.")

        session_dir = session_manager.get_session_dir(session_id)
        front_path = session_dir / f"front_{Path(file.filename).name}"
        with open(front_path, "wb") as f:
            f.write(content)
        del content
        logger.info(f"[{session_id}] Front image saved")

        quality_result = check_image_quality(str(front_path))
        logger.info(
            f"[{session_id}] Quality check: {quality_result.get('quality', 'unknown')} - "
            f"metrics={quality_result.get('metrics', {})} "
            f"issues={quality_result.get('issues', [])} "
            f"warnings={quality_result.get('warnings', [])}"
        )

        if not quality_result.get("can_analyze", True):
            front_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Image quality too poor for accurate grading",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"]),
                },
            )

        detection = await detect_and_correct_card(str(front_path), session_id=session_id)
        detection_method = detection["method"]
        detection_confidence = detection["confidence"]

        if detection["success"] and detection["corrected_image"] is not None:
            corrected_path = session_dir / "front_corrected.jpg"
            cv2.imwrite(str(corrected_path), detection["corrected_image"])
            analysis_image_path = str(corrected_path)
            detection_succeeded = True
            logger.info(
                f"[{session_id}] Card detected via {detection_method} "
                f"(confidence={detection_confidence:.2f})"
            )
        else:
            analysis_image_path = str(front_path)
            detection_succeeded = False
            logger.info(f"[{session_id}] Detection failed, analyzing raw image")

        logger.info(f"[{session_id}] Starting front side analysis")
        front_analysis = analyze_single_side(
            analysis_image_path,
            "front",
            detection_data={
                "border_fractions": detection.get("border_fractions"),
                "already_corrected": detection_succeeded,
            },
        )

        if detection["success"]:
            try:
                corrected_img = detection["corrected_image"]
                enhanced = analyze_corners_enhanced(corrected_img, side="front")
                enhanced_confidence = (enhanced or {}).get("confidence", 0.0)
                basic_grade = (front_analysis.get("corners") or {}).get("overall_grade", 5.0)
                # Always store the OpenCV grade for Vision AI cross-check in combine step,
                # even when confidence is too low to replace the Vision AI scores outright.
                front_analysis["opencv_corner_grade"] = (enhanced or {}).get("overall_grade")
                if enhanced_confidence >= 0.7:
                    front_analysis["corners"] = enhanced
                    logger.info(
                        f"[{session_id}] Enhanced corners accepted: "
                        f"{enhanced.get('overall_grade', 0):.1f} (conf={enhanced_confidence:.2f})"
                    )
                else:
                    logger.info(
                        f"[{session_id}] Enhanced corners rejected "
                        f"(conf={enhanced_confidence:.2f} < 0.7), keeping basic: {basic_grade:.1f}"
                    )
            except Exception as e:
                logger.warning(f"[{session_id}] Enhanced corners failed, keeping basic: {e}")

        front_analysis["detection"] = {
            "method": detection_method,
            "confidence": detection_confidence,
            "quality_assessment": detection.get("quality_assessment"),
        }

        session_manager.update_session(
            session_id,
            front_image_path=str(front_path),
            front_analysis=front_analysis,
            status="front_uploaded",
        )

        total_time = time.time() - start_time
        logger.info(f"[{session_id}] Front upload complete in {total_time:.2f}s")

        return {
            "session_id": session_id,
            "status": "front_uploaded",
            "front_analysis_preview": {
                "centering": (front_analysis.get("centering") or {}).get("grade_estimate"),
                "surface": ((front_analysis.get("surface") or {}).get("surface") or {}).get("score"),
                "corners": (front_analysis.get("corners") or {}).get("overall_grade"),
                "edges": (front_analysis.get("edges") or {}).get("score"),
                "detected_as": front_analysis.get("detected_as"),
            },
            "detection": {
                "method": detection_method,
                "confidence": detection_confidence,
            },
            "image_quality": quality_result,
            "message": "Front image analyzed. Upload back image to complete grading.",
            "next_step": f"/api/grading/{session_id}/upload-back",
            "processing_time": f"{total_time:.2f}s",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Front upload failed: {e}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Front image analysis failed: {e}")


@router.post("/{session_id}/upload-back")
async def upload_back_image(
    session_id: str,
    file: UploadFile = File(..., description="Back side of the Pokemon card"),
):
    """
    Upload, detect, and analyze the back image, then combine with front for final grade.
    Uses hybrid detection: multi-method OpenCV + Vision AI fallback.
    """
    start_time = time.time()
    logger.info(f"[{session_id}] Starting back image upload and analysis")

    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if not session.front_analysis:
        raise HTTPException(status_code=400, detail="Front image not uploaded. Upload front first.")

    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum 15MB per image.")

        session_dir = session_manager.get_session_dir(session_id)
        back_path = session_dir / f"back_{Path(file.filename).name}"
        with open(back_path, "wb") as f:
            f.write(content)
        del content
        logger.info(f"[{session_id}] Back image saved")

        quality_result = check_image_quality(str(back_path))
        logger.info(
            f"[{session_id}] Back quality check: {quality_result.get('quality', 'unknown')} - "
            f"metrics={quality_result.get('metrics', {})} "
            f"issues={quality_result.get('issues', [])} "
            f"warnings={quality_result.get('warnings', [])}"
        )

        if not quality_result.get("can_analyze", True):
            back_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Image quality too poor for accurate grading",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"]),
                },
            )

        detection = await detect_and_correct_card(str(back_path), session_id=session_id)

        if detection["success"] and detection["corrected_image"] is not None:
            corrected_path = session_dir / "back_corrected.jpg"
            cv2.imwrite(str(corrected_path), detection["corrected_image"])
            analysis_image_path = str(corrected_path)
            back_detection_succeeded = True
            logger.info(f"[{session_id}] Back card detected via {detection['method']}")
        else:
            analysis_image_path = str(back_path)
            back_detection_succeeded = False
            logger.info(f"[{session_id}] Back detection failed, analyzing raw image")

        logger.info(f"[{session_id}] Starting back side analysis")
        back_analysis = analyze_single_side(
            analysis_image_path,
            "back",
            detection_data={
                "border_fractions": detection.get("border_fractions"),
                "already_corrected": back_detection_succeeded,
            },
        )

        if detection["success"]:
            try:
                enhanced = analyze_corners_enhanced(detection["corrected_image"], side="back")
                enhanced_confidence = (enhanced or {}).get("confidence", 0.0)
                basic_grade = (back_analysis.get("corners") or {}).get("overall_grade", 5.0)
                # Always store the OpenCV grade for Vision AI cross-check in combine step.
                back_analysis["opencv_corner_grade"] = (enhanced or {}).get("overall_grade")
                if enhanced_confidence >= 0.7:
                    back_analysis["corners"] = enhanced
                    logger.info(
                        f"[{session_id}] Enhanced back corners accepted: "
                        f"{enhanced.get('overall_grade', 0):.1f} (conf={enhanced_confidence:.2f})"
                    )
                else:
                    logger.info(
                        f"[{session_id}] Enhanced back corners rejected "
                        f"(conf={enhanced_confidence:.2f} < 0.7), keeping basic: {basic_grade:.1f}"
                    )
            except Exception as e:
                logger.warning(f"[{session_id}] Enhanced back corners failed, keeping basic: {e}")

        logger.info(f"[{session_id}] Combining front and back analysis")
        combined_grade = combine_front_back_analysis(session.front_analysis, back_analysis)

        session_manager.update_session(
            session_id,
            back_image_path=str(back_path),
            back_analysis=back_analysis,
            combined_grade=combined_grade,
            status="complete",
        )

        total_time = time.time() - start_time
        grade_estimate = combined_grade.get("grade", {}).get("psa_estimate", "N/A")
        logger.info(f"[{session_id}] Grading complete in {total_time:.2f}s - Grade: {grade_estimate}")

        return {
            "session_id": session_id,
            "status": "complete",
            "grading": combined_grade.get("grade"),
            "details": {
                "centering": combined_grade.get("centering"),
                "corners": combined_grade.get("corners"),
                "edges": combined_grade.get("edges"),
                "surface": combined_grade.get("surface"),
            },
            "warnings": combined_grade.get("warnings", []),
            "processing_time": f"{total_time:.2f}s",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Back upload failed: {e}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Back image analysis failed: {e}")


@router.get("/{session_id}/result")
async def get_grading_result(session_id: str):
    """Get the cached grading result for a completed session."""
    session = get_session_manager().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.status != "complete":
        return {
            "session_id": session_id,
            "status": session.status,
            "message": f"Grading not complete. Current status: {session.status}",
            "has_front": session.front_image_path is not None,
            "has_back": session.back_image_path is not None,
        }

    response_data = {
        "session_id": session_id,
        "status": "complete",
        "grading": session.combined_grade.get("grade") if session.combined_grade else None,
        "front_analysis": session.front_analysis,
        "back_analysis": session.back_analysis,
        "combined_grade": session.combined_grade,
    }
    return convert_numpy_types(response_data)
