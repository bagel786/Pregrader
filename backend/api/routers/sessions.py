"""
Session lifecycle routes: create and delete grading sessions.
"""
import logging
from fastapi import APIRouter, HTTPException

from api.session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/grading", tags=["sessions"])


@router.post("/start")
async def start_grading_session():
    """
    Start a new grading session for front + back photo workflow.

    Returns:
        Session ID and status for tracking the grading process
    """
    try:
        session = await get_session_manager().create_session()
        logger.info(f"Started new grading session: {session.session_id}")
        return {
            "session_id": session.session_id,
            "status": "created",
            "message": "Session created. Upload front image first.",
            "next_step": "/api/grading/{session_id}/upload-front",
        }
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")


@router.delete("/{session_id}")
async def delete_grading_session(session_id: str):
    """Delete a grading session and clean up files."""
    success = await get_session_manager().delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}
