from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import gc
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

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

# Initialise session manager with upload directory (singleton, used by routers too)
from api.session_manager import get_session_manager
UPLOAD_DIR = Path(__file__).parent / "temp_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
get_session_manager(UPLOAD_DIR)  # prime the singleton

# Register routers
from api.routers import sessions, grading, admin
app.include_router(sessions.router)
app.include_router(grading.router)
app.include_router(admin.router)

logger.info("Routers registered")
logger.info("Backend initialization complete")
logger.info("="*60)


# =============================================================================
# STATIC / SYSTEM ENDPOINTS
# =============================================================================

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
<p>When you scan a card, your photo is uploaded to our server for analysis. Images are stored temporarily for up to 30 minutes to complete the grading process, then automatically and permanently deleted. Images are never saved to a database, shared with other users, or used for any purpose other than generating your grade.</p>

<h2>Third-Party Services</h2>
<p>In some cases, if our primary image analysis cannot confidently detect your card, your image may be sent to Anthropic's Claude Vision API as a fallback for improved detection. Anthropic's use of this data is governed by their own privacy policy. We also query the Pokemon TCG API (pokemontcg.io) for card metadata — no user data or images are sent to this service.</p>

<h2>Logging</h2>
<p>Our server maintains technical diagnostic logs (processing times, error messages, detection methods used). These logs do not contain any personally identifiable information such as IP addresses, device identifiers, or user data.</p>

<h2>Analytics &amp; Tracking</h2>
<p>Pokemon Pregrader does not use any analytics services, advertising frameworks, cookies, or user tracking of any kind. We do not track you across apps or websites.</p>

<h2>Data Retention</h2>
<p>All session data is held in memory only and is not persisted to any database. Sessions and associated images are automatically deleted after 30 minutes. When the server restarts, all session data is cleared.</p>

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
            "corner_detection": True,
            "visual_debugging": True,
            "ai_enabled": bool(os.getenv("ANTHROPIC_API_KEY")),
        },
    }
    logger.info(f"Health check response: {health_status}")
    return health_status


# =============================================================================
# STARTUP TASKS
# =============================================================================

@app.on_event("startup")
async def run_startup_checks():
    """Validate critical dependencies at server startup."""
    from startup_check import check_api_key, check_grading_prompt
    if not check_api_key():
        logger.error("ANTHROPIC_API_KEY missing — grading will fail on first request")
    if not check_grading_prompt():
        logger.error("grading_prompt.txt missing or empty — grading will fail on first request")
    logger.warning(
        "NOTICE: Grading system has NOT been calibrated against professional "
        "PSA/BGS grades. All grades are AI estimates for informational purposes only."
    )


@app.on_event("startup")
async def start_session_cleanup():
    """Periodic cleanup of expired sessions to prevent memory leaks."""
    async def cleanup_loop():
        while True:
            try:
                cleaned = await get_session_manager().cleanup_expired()
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
