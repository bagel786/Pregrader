#!/usr/bin/env python3
"""
Startup check script to verify all dependencies are working correctly.
Run this before starting the server to catch configuration issues early.
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_opencv():
    """Check if OpenCV is properly installed and working."""
    try:
        import cv2
        logger.info(f"✓ OpenCV version: {cv2.__version__}")
        
        # Test basic OpenCV functionality
        import numpy as np
        test_img = np.zeros((100, 100, 3), dtype=np.uint8)
        gray = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)
        logger.info("✓ OpenCV basic operations working")
        return True
    except Exception as e:
        logger.error(f"✗ OpenCV check failed: {e}")
        return False

def check_numpy():
    """Check if NumPy is working."""
    try:
        import numpy as np
        logger.info(f"✓ NumPy version: {np.__version__}")
        return True
    except Exception as e:
        logger.error(f"✗ NumPy check failed: {e}")
        return False

def check_fastapi():
    """Check if FastAPI is installed."""
    try:
        import fastapi
        logger.info(f"✓ FastAPI version: {fastapi.__version__}")
        return True
    except Exception as e:
        logger.error(f"✗ FastAPI check failed: {e}")
        return False

def check_temp_directory():
    """Check if temp directory can be created."""
    try:
        from pathlib import Path
        temp_dir = Path(__file__).parent / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        logger.info(f"✓ Temp directory accessible: {temp_dir}")
        return True
    except Exception as e:
        logger.error(f"✗ Temp directory check failed: {e}")
        return False

def check_api_key():
    """Check if ANTHROPIC_API_KEY is set."""
    import os
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        logger.info(f"✓ ANTHROPIC_API_KEY is set ({len(key)} chars)")
        return True
    else:
        logger.error("✗ ANTHROPIC_API_KEY not set — Vision AI grading will fail")
        return False

def check_grading_prompt():
    """Check if grading_prompt.txt exists and is non-empty."""
    from pathlib import Path
    prompt_path = Path(__file__).parent / "grading" / "prompts" / "grading_prompt.txt"
    if not prompt_path.exists():
        logger.error(f"✗ Grading prompt not found at {prompt_path}")
        return False
    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        logger.error(f"✗ Grading prompt is empty at {prompt_path}")
        return False
    logger.info(f"✓ Grading prompt loaded ({len(content)} chars)")
    return True

def main():
    """Run all startup checks."""
    logger.info("=" * 50)
    logger.info("Running startup checks...")
    logger.info("=" * 50)

    checks = [
        ("NumPy", check_numpy),
        ("OpenCV", check_opencv),
        ("FastAPI", check_fastapi),
        ("Temp Directory", check_temp_directory),
        ("API Key", check_api_key),
        ("Grading Prompt", check_grading_prompt),
    ]
    
    results = []
    for name, check_func in checks:
        logger.info(f"\nChecking {name}...")
        results.append(check_func())
    
    logger.info("\n" + "=" * 50)
    if all(results):
        logger.info("✓ All checks passed! Server is ready to start.")
    else:
        logger.error("✗ Some checks failed. Please fix the issues above.")

    # Calibration disclaimer — always shown
    logger.info("")
    logger.warning(
        "NOTICE: Grading system has NOT been calibrated against professional "
        "PSA/BGS grades. All grades are AI estimates for informational purposes only."
    )
    logger.info("=" * 50)
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
