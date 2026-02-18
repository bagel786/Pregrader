from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx
import os
import uuid
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
from analysis.centering import calculate_centering_ratios
from analysis.corners import analyze_corner_wear
from analysis.edges import analyze_edge_wear
from analysis.surface import analyze_surface_damage
from analysis.scoring import GradingEngine

from analysis.vision.quality_checks import check_image_quality
from analysis.vision.debug import DebugVisualizer

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("CORS middleware configured")

# Initialize the Pokemon TCG client
pokemon_client = PokemonTCGClient()
ENABLE_DEBUG = os.getenv("ENABLE_DEBUG", "false").lower() == "true"

logger.info(f"Pokemon TCG client initialized")
logger.info(f"Debug mode: {ENABLE_DEBUG}")

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

# In-memory storage for analysis sessions with TTL
# Sessions expire after 15 minutes, max 20 sessions to cap memory
MAX_LEGACY_SESSIONS = 20
SESSION_TTL_MINUTES = 15
analysis_sessions = {}  # {session_id: {"front_path": ..., "created_at": datetime, ...}}


def _cleanup_legacy_sessions():
    """Remove expired sessions and enforce max session limit."""
    now = datetime.now()
    expired = [
        sid for sid, data in analysis_sessions.items()
        if now - data.get("created_at", now) > timedelta(minutes=SESSION_TTL_MINUTES)
    ]
    for sid in expired:
        session_dir = UPLOAD_DIR / sid
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
        del analysis_sessions[sid]

    # Enforce max limit - remove oldest sessions
    if len(analysis_sessions) > MAX_LEGACY_SESSIONS:
        sorted_sessions = sorted(
            analysis_sessions.items(),
            key=lambda x: x[1].get("created_at", datetime.min)
        )
        for sid, _ in sorted_sessions[:len(analysis_sessions) - MAX_LEGACY_SESSIONS]:
            session_dir = UPLOAD_DIR / sid
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            del analysis_sessions[sid]

    if expired:
        gc.collect()
        logger.info(f"Cleaned up {len(expired)} expired legacy sessions")


@app.post("/analyze/upload")
async def upload_card_images(
    front_image: UploadFile = File(..., description="Front side of the card"),
    back_image: Optional[UploadFile] = File(None, description="Back side of the card (optional)")
):
    """
    Upload card images for analysis.
    
    Args:
        front_image: Front side of the Pokemon card (required)
        back_image: Back side of the Pokemon card (optional)
        
    Returns:
        Session ID and upload status
    """
    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(exist_ok=True)
    
    logger.info(f"Upload started - Session ID: {session_id}")
    
    try:
        # Save front image
        front_path = session_dir / f"front_{front_image.filename}"
        with open(front_path, "wb") as f:
            shutil.copyfileobj(front_image.file, f)
        
        # Save back image if provided
        back_path = None
        if back_image:
            back_path = session_dir / f"back_{back_image.filename}"
            with open(back_path, "wb") as f:
                shutil.copyfileobj(back_image.file, f)
        
        # Cleanup before adding new session
        _cleanup_legacy_sessions()

        # Store session info
        analysis_sessions[session_id] = {
            "front_path": str(front_path),
            "back_path": str(back_path) if back_path else None,
            "status": "uploaded",
            "results": None,
            "created_at": datetime.now()
        }
        
        logger.info(f"Upload successful - Session ID: {session_id}")
        
        return {
            "session_id": session_id,
            "status": "uploaded",
            "front_image": front_image.filename,
            "back_image": back_image.filename if back_image else None
        }
        
    except Exception as e:
        # Cleanup on error
        logger.error(f"Upload failed - Session ID: {session_id}, Error: {str(e)}")
        if session_dir.exists():
            shutil.rmtree(session_dir)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/analyze/{session_id}")
async def run_analysis(session_id: str):
    """
    Run full card analysis on uploaded images.
    
    Args:
        session_id: The session ID from the upload endpoint
        
    Returns:
        Complete analysis results including centering, corners, edges, and surface grades
    """
    try:
        logger.info(f"Analysis started - Session ID: {session_id}")
        
        if session_id not in analysis_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = analysis_sessions[session_id]
        front_path = session["front_path"]
        back_path = session.get("back_path")
        
        # Verify files exist
        if not os.path.exists(front_path):
            raise HTTPException(status_code=400, detail=f"Front image file not found: {front_path}")
        if back_path and not os.path.exists(back_path):
            raise HTTPException(status_code=400, detail=f"Back image file not found: {back_path}")
        
        # Initialize debug visualizer
        debugger = DebugVisualizer(session_id, enabled=ENABLE_DEBUG)
        
        # Quality Checks - Front
        front_quality = check_image_quality(front_path)
        if not front_quality["can_analyze"]:
            logger.warning(f"HTTP Exception in analysis - Session ID: {session_id}, Status: 400, Detail: Front image quality too low: {front_quality['issues']}")
            raise HTTPException(
                status_code=400, 
                detail=f"Front image quality too low: {'; '.join(front_quality['issues'])}"
            )
            
        # Quality Checks - Back
        if back_path:
            back_quality = check_image_quality(back_path)
            if not back_quality["can_analyze"]:
                logger.warning(f"HTTP Exception in analysis - Session ID: {session_id}, Status: 400, Detail: Back image quality too low: {back_quality['issues']}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Back image quality too low: {'; '.join(back_quality['issues'])}"
                )
        
        # Analyze front image with error handling
        try:
            front_results = {
                "centering": calculate_centering_ratios(
                    front_path, 
                    debug_output_path=str(Path(debugger.debug_dir) / f"{session_id}_front_centering.jpg") if ENABLE_DEBUG else None
                ),
                "corners": analyze_corner_wear(front_path),
                "edges": analyze_edge_wear(
                    front_path,
                    debug_output_path=str(Path(debugger.debug_dir) / f"{session_id}_front_edges.jpg") if ENABLE_DEBUG else None
                ),
                "surface": analyze_surface_damage(front_path)
            }
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Front image analysis failed: {str(e)}"
            )
        
        # Analyze back image if available with error handling
        back_results = None
        if back_path:
            try:
                back_results = {
                    "centering": calculate_centering_ratios(back_path), # We have centering for back now too if we want
                    "corners": analyze_corner_wear(back_path),
                    "edges": analyze_edge_wear(
                        back_path,
                        debug_output_path=str(Path(debugger.debug_dir) / f"{session_id}_back_edges.jpg") if ENABLE_DEBUG else None
                    ),
                    "surface": analyze_surface_damage(back_path)
                }
            except Exception as e:
                # Log but don't fail if back analysis fails
                print(f"Warning: Back image analysis failed: {str(e)}")
                back_results = None
        
        # Check for errors in analysis FIRST before using the data
        errors = []
        critical_errors = []
        
        # Centering errors are non-critical - we can use a default
        if "error" in front_results["centering"]:
             # Updated API returns success: False instead of error key often, but let's check both
             # My new implementation returns {success: False, error: ..., score: ...}
            errors.append(f"Centering: {front_results['centering'].get('error', 'Unknown error')}")
            # Ensure safe defaults exist
            if "grade_estimate" not in front_results["centering"]:
                 front_results["centering"]["grade_estimate"] = 5.0
        
        # These are critical - can't grade without them
        if "error" in front_results["corners"]: 
            critical_errors.append(f"Corners: {front_results['corners']['error']}")
        if "error" in front_results["edges"]: 
            critical_errors.append(f"Edges: {front_results['edges']['error']}")
        if "error" in front_results["surface"]: 
            critical_errors.append(f"Surface: {front_results['surface']['error']}")
        
        if critical_errors:
            raise HTTPException(
                status_code=400, 
                detail=f"Critical analysis errors: {'; '.join(critical_errors)}. Please retake photos with better lighting and card positioning."
            )
        
        # Log non-critical warnings
        if errors:
            logger.warning(f"Non-critical analysis warnings - Session ID: {session_id}: {'; '.join(errors)}")
        
        # Merging Logic (Conservative Bias)
        # 1. Centering (Weighted 70/30)
        front_centering = front_results["centering"].get("grade_estimate", 0)
        # Using front only for now as primary metric per plan conversation context
        final_centering_score = front_centering
        
        # 2. Corners (Worst Case)
        final_corners_data = front_results["corners"]
        if back_results and "corners" in back_results and "corners" in back_results["corners"]:
            # If back corners are worse (lower score), use them
            back_score = sum(c["score"] for c in back_results["corners"]["corners"].values())
            front_score = sum(c["score"] for c in front_results["corners"]["corners"].values())
            if back_score < front_score:
                final_corners_data = back_results["corners"]
                
        # 3. Edges (Worst Case)
        final_edges_data = front_results["edges"]
        if back_results and "edges" in back_results and "score" in back_results["edges"]:
            # Edges usually show wear on back more clearly
            # New edges API returns "score" directly and "detailed_edges"
            back_edge_score = back_results["edges"]["score"]
            front_edge_score = front_results["edges"]["score"]
            
            if back_edge_score < front_edge_score:
                final_edges_data = back_results["edges"]
        elif back_results and "edges" in back_results and "edges" in back_results["edges"]:
             # Legacy check
             pass

        # 4. Surface (Worst Case)
        final_surface_data = front_results["surface"]["surface"]
        if back_results and "surface" in back_results and "surface" in back_results["surface"]:
             # Check if back surface score is worse
             if back_results["surface"]["surface"]["score"] < final_surface_data["score"]:
                 final_surface_data = back_results["surface"]["surface"]
                
        # Calculate Final Grade with error handling
        try:
            grading_result = GradingEngine.calculate_grade(
                centering_score=final_centering_score,
                corners_data=final_corners_data,
                edges_data=final_edges_data,
                surface_data=final_surface_data
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Grading calculation failed: {str(e)}"
            )
        
        results = {
            "session_id": session_id,
            "front": front_results,
            "back": back_results,
            "grading": grading_result,
            "image_quality": {
                "front": front_quality,
                "back": back_quality if back_results else None
            }
        }
        
        # Cache results
        session["status"] = "complete"
        session["results"] = results
        
        logger.info(f"Analysis completed - Session ID: {session_id}, Grade: {grading_result.get('psa_estimate', 'N/A')}")
        
        return results
        
    except HTTPException as http_exc:
        # Re-raise HTTP exceptions without modification
        logger.warning(f"HTTP Exception in analysis - Session ID: {session_id}, Status: {http_exc.status_code}, Detail: {http_exc.detail}")
        raise http_exc
    except Exception as e:
        # Log the full error for debugging
        import traceback
        error_detail = f"Analysis failed: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"Analysis error - Session ID: {session_id}\n{error_detail}")
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail=f"Analysis failed: {str(e)}"
        )


@app.post("/grade")
async def grade_card_session(session_id: str = Query(..., description="Session ID to grade")):
    """
    Grading API Endpoint (Task 4.2).
    Runs the full analysis pipeline and returns the grading result.
    This is an alias for /analyze/{session_id} to satisfy specific naming deliverables.
    
    Args:
        session_id: The session ID from the upload
        
    Returns:
        Full grading result with sub-scores and explanations.
    """
    return await run_analysis(session_id)


@app.get("/analyze/{session_id}/results")
async def get_analysis_results(session_id: str):
    """
    Get cached analysis results for a session.
    
    Args:
        session_id: The session ID from the upload endpoint
        
    Returns:
        Previously computed analysis results
    """
    if session_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = analysis_sessions[session_id]
    
    if session["status"] != "complete":
        raise HTTPException(status_code=400, detail="Analysis not yet complete. Run POST /analyze/{session_id} first.")
    
    return session["results"]


@app.delete("/analyze/{session_id}")
async def delete_session(session_id: str):
    """
    Delete analysis session and cleanup temporary files.
    
    Args:
        session_id: The session ID to delete
        
    Returns:
        Deletion confirmation
    """
    if session_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Cleanup files
    session_dir = UPLOAD_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    
    del analysis_sessions[session_id]
    gc.collect()  # Free numpy arrays from analysis results
    
    return {"status": "deleted", "session_id": session_id}


# =============================================================================
# NEW SESSION-BASED GRADING API (Front + Back Workflow)
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
        # Save uploaded image
        session_dir = session_manager.get_session_dir(session_id)
        front_path = session_dir / f"front_{file.filename}"
        with open(front_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
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
        # Save uploaded image
        session_dir = session_manager.get_session_dir(session_id)
        back_path = session_dir / f"back_{file.filename}"
        with open(back_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
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
                _cleanup_legacy_sessions()
                cleaned = session_manager.cleanup_expired()
                if cleaned > 0:
                    gc.collect()
                    logger.info(f"Periodic cleanup: removed {cleaned} expired managed sessions")
            except Exception as e:
                logger.error(f"Session cleanup error: {e}")
            await asyncio.sleep(120)  # Run every 2 minutes
    asyncio.create_task(cleanup_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
