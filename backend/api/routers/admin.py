"""
Admin / monitoring routes.
"""
from fastapi import APIRouter
from api.hybrid_detect import get_detection_stats

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/detection-stats")
async def detection_stats():
    """Get hybrid detection statistics."""
    return get_detection_stats()
