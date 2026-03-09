from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx
import os
import gc
import shutil
from pathlib import Path
from typing import Optional
import logging
import sys
import asyncio
import cv2
from datetime import datetime, timedelta

from services.pokemon_tcg import PokemonTCGClient
from analysis.vision.quality_checks import check_image_quality

# Configure comprehensive logging FIRST (before any imports that use logger)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('server.log')
    ]
)
logger = logging.getLogger(__name__)

# Import enhanced detection router
try:
    from api.enhanced_detection import router as enhanced_router
    enhanced_router_available = True
    logger.info("Enhanced detection router imported successfully")
except Exception as e:
    logger.warning(f"Enhanced detection router import failed: {e}")
    logger.warning("V2 API will not be available")
    enhanced_router_available = False

# Log startup
logger.info("="*60)
logger.info("Pokemon Pregrader Backend Starting")
logger.info(f"Python Version: {sys.version}")
logger.info(f"Working Directory: {os.getcwd()}")
logger.info("="*60)

# Load environment variables
load_dotenv()

# Log environment configuration
logger.info("Environment Configuration:")
logger.info(f"  ANTHROPIC_API_KEY: {'SET' if os.getenv('ANTHROPIC_API_KEY') else 'NOT SET'}")
logger.info(f"  DEFAULT_DETECTION_METHOD: {os.getenv('DEFAULT_DETECTION_METHOD', 'hybrid')}")
logger.info(f"  OPENCV_CONFIDENCE_THRESHOLD: {os.getenv('OPENCV_CONFIDENCE_THRESHOLD', '0.70')}")
logger.info(f"  ENABLE_DEBUG_IMAGES: {os.getenv('ENABLE_DEBUG_IMAGES', 'true')}")

app = FastAPI(
    title="Pokemon Pregrader API",
    description="Backend API for Pokemon card pre-grading application with hybrid AI detection",
    version="2.0.0"
)

logger.info("FastAPI app initialized")

# Configure CORS for Flutter app access
_ALLOWED_ORIGINS = [
    "https://pregrader-production.up.railway.app",
    "http://localhost:8000",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("CORS middleware configured")

# Initialize the Pokemon TCG client
pokemon_client = PokemonTCGClient()
logger.info(f"Pokemon TCG client initialized")

# Register enhanced detection router (v2 API with hybrid detection)
if enhanced_router_available:
    app.include_router(
        enhanced_router,
        prefix="/api/v2",
        tags=["enhanced-detection"]
    )
    logger.info("Enhanced detection router registered at /api/v2")
else:
    logger.warning("Enhanced detection router not registered - V2 API unavailable")

logger.info("Backend initialization complete")
logger.info("="*60)


@app.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy():
    """Privacy policy page for App Store Connect."""
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Policy - Pokemon Pregrader</title>
<style>body{font-family:-apple-system,sans-serif;max-width:700px;margin:0 auto;padding:20px;line-height:1.6;color:#333}
h1{color:#7B2CBF}h2{color:#9D4EDD;margin-top:24px}p{margin:8px 0}</style></head>
<body>
<h1>Privacy Policy</h1>
<p><em>Last updated: March 2026</em></p>

<h2>Data Collection</h2>
<p>Pokemon Pregrader does not require an account and does not collect any personal information. We do not ask for your name, email, location, or any other identifying data.</p>

<h2>Image Handling</h2>
<p>When you scan a card, your photo is uploaded to our server for analysis. Images are stored temporarily for up to 15 minutes to complete the grading process, then automatically and permanently deleted. Images are never saved to a database, shared with other users, or used for any purpose other than generating your grade.</p>

<h2>Third-Party Services</h2>
<p>In some cases, if our primary image analysis cannot confidently detect your card, your image may be sent to Anthropic's Claude Vision API as a fallback for improved detection. Anthropic's use of this data is governed by their own privacy policy. We also query the Pokemon TCG API (pokemontcg.io) for card metadata — no user data or images are sent to this service.</p>

<h2>Logging</h2>
<p>Our server maintains technical diagnostic logs (processing times, error messages, detection methods used). These logs do not contain any personally identifiable information such as IP addresses, device identifiers, or user data.</p>

<h2>Analytics &amp; Tracking</h2>
<p>Pokemon Pregrader does not use any analytics services, advertising frameworks, cookies, or user tracking of any kind. We do not track you across apps or websites.</p>

<h2>Data Retention</h2>
<p>All session data is held in memory only and is not persisted to any database. Sessions and associated images are automatically deleted after 15 minutes. When the server restarts, all session data is cleared.</p>

<h2>Your Rights</h2>
<p>Since we do not collect or store personal data, there is no personal data to access, correct, or delete. If you have questions or concerns about your privacy, please contact us using the support information in the App Store listing.</p>
</body></html>"""


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    logger.info("Health check called")
    health_status = {
        "status": "ok", 
        "message": "Backend is running",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "features": {
            "hybrid_detection": True,
            "enhanced_corners": True,
            "visual_debugging": True,
            "ai_enabled": bool(os.getenv("ANTHROPIC_API_KEY"))
        }
    }
    logger.info(f"Health check response: {health_status}")
    return health_status


@app.get("/cards/search")
async def search_cards(
    q: str = Query(..., description="Search query for card name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page")
):
    """
    Search for Pokemon cards by name.
    
    Args:
        q: Search query (card name)
        page: Page number for pagination
        page_size: Number of results per page (max 100)
        
    Returns:
        List of matching cards with metadata
    """
    try:
        result = await pokemon_client.search_cards(q, page, page_size)
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/cards/{card_id}")
async def get_card(card_id: str):
    """
    Get a specific card by its ID.
    
    Args:
        card_id: The unique identifier of the card
        
    Returns:
        Card data including images, prices, and metadata
    """
    try:
        result = await pokemon_client.get_card_by_id(card_id)
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Card not found")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/sets")
async def get_sets():
    """
    Get all available Pokemon card sets.
    
    Returns:
        List of all sets with metadata
    """
    try:
        result = await pokemon_client.get_sets()
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


# =============================================================================
# IMAGE ANALYSIS ENDPOINTS
# =============================================================================

# Temp upload directory
UPLOAD_DIR = Path(__file__).parent / "temp_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Maximum allowed upload size (15 MB)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024



# =============================================================================
# SESSION-BASED GRADING API (Front + Back Workflow)
# =============================================================================

from api.session_manager import get_session_manager
from api.combined_grading import analyze_single_side, combine_front_back_analysis
from api.hybrid_detect import detect_and_correct_card, get_detection_stats

try:
    from analysis.enhanced_corners import analyze_corners_enhanced
    _enhanced_corners_available = True
except ImportError:
    _enhanced_corners_available = False
    logger.warning("Enhanced corners not available, using basic corner analysis")

# Initialize session manager
session_manager = get_session_manager(UPLOAD_DIR)


@app.post("/api/grading/start")
async def start_grading_session():
    """
    Start a new grading session for front + back photo workflow.
    
    Returns:
        Session ID and status for tracking the grading process
    """
    try:
        session = session_manager.create_session()
        logger.info(f"Started new grading session: {session.session_id}")
        
        return {
            "session_id": session.session_id,
            "status": "created",
            "message": "Session created. Upload front image first.",
            "next_step": "/api/grading/{session_id}/upload-front"
        }
    except Exception as e:
        logger.error(f"Failed to create session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")


@app.post("/api/grading/{session_id}/upload-front")
async def upload_front_image(
    session_id: str,
    file: UploadFile = File(..., description="Front side of the Pokemon card")
):
    """
    Upload, detect, and analyze the front image of a card.
    Uses hybrid detection: multi-method OpenCV + Vision AI fallback.
    """
    import time as _time
    start_time = _time.time()
    logger.info(f"[{session_id}] Starting front image upload and analysis")
    
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    try:
        # Read file content and enforce size limit before saving
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum 15MB per image.")

        # Save uploaded image
        session_dir = session_manager.get_session_dir(session_id)
        front_path = session_dir / f"front_{file.filename}"
        with open(front_path, "wb") as f:
            f.write(content)
        del content  # Free memory immediately
        logger.info(f"[{session_id}] Front image saved")
        
        # Quality check (log metrics but only block truly unreadable images)
        quality_result = check_image_quality(str(front_path))
        logger.info(f"[{session_id}] Quality check: {quality_result.get('quality', 'unknown')} - "
                    f"metrics={quality_result.get('metrics', {})} "
                    f"issues={quality_result.get('issues', [])} "
                    f"warnings={quality_result.get('warnings', [])}")
        
        if not quality_result.get("valid", True):
            # Only block if image couldn't even be loaded
            front_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Image could not be loaded",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"])
                }
            )
        
        # Hybrid card detection (4 OpenCV methods + AI fallback)
        detection = await detect_and_correct_card(str(front_path), session_id=session_id)
        detection_method = detection["method"]
        detection_confidence = detection["confidence"]
        
        # Determine analysis path based on detection
        if detection["success"] and detection["corrected_image"] is not None:
            # Save corrected image and analyze it
            corrected_path = session_dir / "front_corrected.jpg"
            cv2.imwrite(str(corrected_path), detection["corrected_image"])
            analysis_image_path = str(corrected_path)
            logger.info(f"[{session_id}] Card detected via {detection_method} (confidence={detection_confidence:.2f})")
        else:
            # Detection failed — analyze raw image (pre-cropped photos)
            analysis_image_path = str(front_path)
            logger.info(f"[{session_id}] Detection failed, analyzing raw image")
        
        # Run analysis on the best available image
        logger.info(f"[{session_id}] Starting front side analysis")
        front_analysis = analyze_single_side(analysis_image_path, "front")
        
        # Use enhanced corners if available and we have a corrected image
        if _enhanced_corners_available and detection["success"]:
            try:
                corrected_img = detection["corrected_image"]
                enhanced = analyze_corners_enhanced(corrected_img, side="front")
                front_analysis["corners"] = enhanced
                logger.info(f"[{session_id}] Enhanced corners: {enhanced.get('overall_grade', 0):.1f}")
            except Exception as e:
                logger.warning(f"[{session_id}] Enhanced corners failed, keeping basic: {e}")
        
        # Add detection metadata to analysis
        front_analysis["detection"] = {
            "method": detection_method,
            "confidence": detection_confidence,
            "quality_assessment": detection.get("quality_assessment"),
        }
        
        # Update session
        session_manager.update_session(
            session_id,
            front_image_path=str(front_path),
            front_analysis=front_analysis,
            status="front_uploaded"
        )
        
        total_time = _time.time() - start_time
        logger.info(f"[{session_id}] Front upload complete in {total_time:.2f}s")
        
        return {
            "session_id": session_id,
            "status": "front_uploaded",
            "front_analysis_preview": {
                "centering": front_analysis.get("centering", {}).get("grade_estimate"),
                "surface": front_analysis.get("surface", {}).get("surface", {}).get("score"),
                "corners": front_analysis.get("corners", {}).get("overall_grade"),
                "edges": front_analysis.get("edges", {}).get("score"),
                "detected_as": front_analysis.get("detected_as")
            },
            "detection": {
                "method": detection_method,
                "confidence": detection_confidence,
            },
            "image_quality": quality_result,
            "message": "Front image analyzed. Upload back image to complete grading.",
            "next_step": f"/api/grading/{session_id}/upload-back",
            "processing_time": f"{total_time:.2f}s"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Front upload failed: {str(e)}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Front image analysis failed: {str(e)}")



@app.post("/api/grading/{session_id}/upload-back")
async def upload_back_image(
    session_id: str,
    file: UploadFile = File(..., description="Back side of the Pokemon card")
):
    """
    Upload, detect, and analyze the back image, then combine with front for final grade.
    Uses hybrid detection: multi-method OpenCV + Vision AI fallback.
    """
    import time as _time
    start_time = _time.time()
    logger.info(f"[{session_id}] Starting back image upload and analysis")
    
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if not session.front_analysis:
        raise HTTPException(status_code=400, detail="Front image not uploaded. Upload front first.")
    
    try:
        # Read file content and enforce size limit before saving
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum 15MB per image.")

        # Save uploaded image
        session_dir = session_manager.get_session_dir(session_id)
        back_path = session_dir / f"back_{file.filename}"
        with open(back_path, "wb") as f:
            f.write(content)
        del content  # Free memory immediately
        logger.info(f"[{session_id}] Back image saved")
        
        # Quality check (log metrics but only block truly unreadable images)
        quality_result = check_image_quality(str(back_path))
        logger.info(f"[{session_id}] Back quality check: {quality_result.get('quality', 'unknown')} - "
                    f"metrics={quality_result.get('metrics', {})} "
                    f"issues={quality_result.get('issues', [])} "
                    f"warnings={quality_result.get('warnings', [])}")
        
        if not quality_result.get("valid", True):
            # Only block if image couldn't even be loaded
            back_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Back image could not be loaded",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"])
                }
            )
        
        # Hybrid card detection
        detection = await detect_and_correct_card(str(back_path), session_id=session_id)
        
        if detection["success"] and detection["corrected_image"] is not None:
            corrected_path = session_dir / "back_corrected.jpg"
            cv2.imwrite(str(corrected_path), detection["corrected_image"])
            analysis_image_path = str(corrected_path)
            logger.info(f"[{session_id}] Back card detected via {detection['method']}")
        else:
            analysis_image_path = str(back_path)
            logger.info(f"[{session_id}] Back detection failed, analyzing raw image")
        
        # Run back analysis
        logger.info(f"[{session_id}] Starting back side analysis")
        back_analysis = analyze_single_side(analysis_image_path, "back")
        
        # Enhanced corners for back if available
        if _enhanced_corners_available and detection["success"]:
            try:
                enhanced = analyze_corners_enhanced(detection["corrected_image"], side="back")
                back_analysis["corners"] = enhanced
            except Exception as e:
                logger.warning(f"[{session_id}] Enhanced back corners failed: {e}")
        
        # Combine front + back
        logger.info(f"[{session_id}] Combining front and back analysis")
        combined_grade = combine_front_back_analysis(
            session.front_analysis,
            back_analysis
        )
        
        # Update session
        session_manager.update_session(
            session_id,
            back_image_path=str(back_path),
            back_analysis=back_analysis,
            combined_grade=combined_grade,
            status="complete"
        )
        
        total_time = _time.time() - start_time
        grade_estimate = combined_grade.get('grade', {}).get('psa_estimate', 'N/A')
        logger.info(f"[{session_id}] Grading complete in {total_time:.2f}s - Grade: {grade_estimate}")
        
        return {
            "session_id": session_id,
            "status": "complete",
            "grading": combined_grade.get("grade"),
            "details": {
                "centering": combined_grade.get("centering"),
                "corners": combined_grade.get("corners"),
                "edges": combined_grade.get("edges"),
                "surface": combined_grade.get("surface")
            },
            "warnings": combined_grade.get("warnings", []),
            "processing_time": f"{total_time:.2f}s"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{session_id}] Back upload failed: {str(e)}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Back image analysis failed: {str(e)}")




from utils.serialization import convert_numpy_types

@app.get("/api/grading/{session_id}/result")
async def get_grading_result(session_id: str):
    """
    Get the cached grading result for a completed session.
    
    Args:
        session_id: The session ID
        
    Returns:
        Final grading results
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if session.status != "complete":
        return {
            "session_id": session_id,
            "status": session.status,
            "message": f"Grading not complete. Current status: {session.status}",
            "has_front": session.front_image_path is not None,
            "has_back": session.back_image_path is not None
        }
    
    response_data = {
        "session_id": session_id,
        "status": "complete",
        "grading": session.combined_grade.get("grade") if session.combined_grade else None,
        "front_analysis": session.front_analysis,
        "back_analysis": session.back_analysis,
        "combined_grade": session.combined_grade
    }
    
    # Ensure no numpy types leak into JSON response
    return convert_numpy_types(response_data)


@app.delete("/api/grading/{session_id}")
async def delete_grading_session(session_id: str):
    """Delete a grading session and clean up files."""
    success = session_manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/admin/detection-stats")
async def detection_stats():
    """Get hybrid detection statistics."""
    return get_detection_stats()


@app.on_event("startup")
async def start_session_cleanup():
    """Periodic cleanup of expired sessions to prevent memory leaks."""
    async def cleanup_loop():
        while True:
            try:
                cleaned = session_manager.cleanup_expired()
                if cleaned > 0:
                    gc.collect()
                    logger.info(f"Periodic cleanup: removed {cleaned} expired sessions")
            except Exception as e:
                logger.error(f"Session cleanup error: {e}")
            await asyncio.sleep(120)  # Run every 2 minutes
    asyncio.create_task(cleanup_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
