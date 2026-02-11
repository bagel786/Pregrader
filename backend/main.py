from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx
import os
import uuid
import shutil
from pathlib import Path
from typing import Optional
import logging

from services.pokemon_tcg import PokemonTCGClient
from analysis.centering import calculate_centering_ratios
from analysis.corners import analyze_corner_wear
from analysis.edges import analyze_edge_wear
from analysis.surface import analyze_surface_damage
from analysis.scoring import GradingEngine

from analysis.vision.quality_checks import check_image_quality
from analysis.vision.debug import DebugVisualizer

# Import enhanced detection router
from api.enhanced_detection import router as enhanced_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Pokemon Pregrader API",
    description="Backend API for Pokemon card pre-grading application",
    version="1.0.0"
)

# Configure CORS for Flutter app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the Pokemon TCG client
pokemon_client = PokemonTCGClient()
ENABLE_DEBUG = os.getenv("ENABLE_DEBUG", "false").lower() == "true"

# Register enhanced detection router (v2 API with hybrid detection)
app.include_router(
    enhanced_router,
    prefix="/api/v2",
    tags=["enhanced-detection"]
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    logger.info("Health check called")
    return {
        "status": "ok", 
        "message": "Backend is running",
        "version": "2.1.0",  # Updated version to verify deployment
        "timestamp": "2026-02-05T15:35:00Z"
    }


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

# In-memory storage for analysis sessions (in production, use Redis/DB)
analysis_sessions = {}


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
        
        # Store session info
        analysis_sessions[session_id] = {
            "front_path": str(front_path),
            "back_path": str(back_path) if back_path else None,
            "status": "uploaded",
            "results": None
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
    
    return {"status": "deleted", "session_id": session_id}


# =============================================================================
# NEW SESSION-BASED GRADING API (Front + Back Workflow)
# =============================================================================

from api.session_manager import get_session_manager
from api.combined_grading import analyze_single_side, combine_front_back_analysis

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
    image: UploadFile = File(..., description="Front side of the Pokemon card")
):
    """
    Upload and analyze the front image of a card.
    
    Args:
        session_id: The session ID from start_grading_session
        image: Front image file
        
    Returns:
        Front analysis results and next step instructions
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    try:
        # Save front image
        session_dir = session_manager.get_session_dir(session_id)
        front_path = session_dir / f"front_{image.filename}"
        
        with open(front_path, "wb") as f:
            shutil.copyfileobj(image.file, f)
        
        # Quality check
        quality_result = check_image_quality(str(front_path))
        if not quality_result.get("can_analyze", False):
            # Clean up bad image
            front_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Image quality too low",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"])
                }
            )
        
        # Run front analysis
        front_analysis = analyze_single_side(str(front_path), "front")
        
        # Update session
        session_manager.update_session(
            session_id,
            front_image_path=str(front_path),
            front_analysis=front_analysis,
            status="front_uploaded"
        )
        
        logger.info(f"Front image uploaded for session: {session_id}")
        
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
            "image_quality": quality_result,
            "message": "Front image analyzed. Upload back image to complete grading.",
            "next_step": f"/api/grading/{session_id}/upload-back"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Front upload failed for session {session_id}: {str(e)}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Front image analysis failed: {str(e)}")


@app.post("/api/grading/{session_id}/upload-back")
async def upload_back_image(
    session_id: str,
    image: UploadFile = File(..., description="Back side of the Pokemon card")
):
    """
    Upload and analyze the back image, then combine with front for final grade.
    
    Args:
        session_id: The session ID
        image: Back image file
        
    Returns:
        Combined grading results
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if not session.front_analysis:
        raise HTTPException(status_code=400, detail="Front image not uploaded. Upload front first.")
    
    try:
        # Save back image
        session_dir = session_manager.get_session_dir(session_id)
        back_path = session_dir / f"back_{image.filename}"
        
        with open(back_path, "wb") as f:
            shutil.copyfileobj(image.file, f)
        
        # Quality check
        quality_result = check_image_quality(str(back_path))
        if not quality_result.get("can_analyze", False):
            back_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Back image quality too low",
                    "issues": quality_result.get("issues", []),
                    "user_feedback": quality_result.get("user_feedback", ["Please retake the photo"])
                }
            )
        
        # Run back analysis
        back_analysis = analyze_single_side(str(back_path), "back")
        
        # Combine front + back
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
        
        logger.info(f"Grading complete for session: {session_id}, Grade: {combined_grade.get('grade', {}).get('psa_estimate', 'N/A')}")
        
        return {
            "session_id": session_id,
            "status": "complete",
            "grade": combined_grade.get("grade"),
            "details": {
                "centering": combined_grade.get("centering"),
                "corners": combined_grade.get("corners"),
                "edges": combined_grade.get("edges"),
                "surface": combined_grade.get("surface")
            },
            "warnings": combined_grade.get("warnings", [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Back upload failed for session {session_id}: {str(e)}")
        session_manager.update_session(session_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"Back image analysis failed: {str(e)}")


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
    
    return {
        "session_id": session_id,
        "status": "complete",
        "grade": session.combined_grade.get("grade") if session.combined_grade else None,
        "front_analysis": session.front_analysis,
        "back_analysis": session.back_analysis,
        "combined_grade": session.combined_grade
    }


@app.delete("/api/grading/{session_id}")
async def delete_grading_session(session_id: str):
    """Delete a grading session and clean up files."""
    success = session_manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "deleted", "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


