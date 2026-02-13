#!/usr/bin/env python3
"""
Pre-Deployment Test Script
Run this before deploying to Railway to verify everything works

Usage:
    python test_before_deploy.py
    python test_before_deploy.py path/to/test_card.jpg
"""
import sys
import os
from pathlib import Path
import json

# Color output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.RESET}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.RESET}")

def check_file_structure():
    """Check if all required files are in place"""
    print("\n" + "="*60)
    print("STEP 1: Checking File Structure")
    print("="*60)
    
    required_files = {
        "backend/analysis/vision/debugger.py": "Card detection debugger",
        "backend/analysis/enhanced_corners.py": "Enhanced corner detection",
        "backend/services/ai/vision_detector.py": "Vision AI detector",
        "backend/api/enhanced_detection.py": "Railway integration",
    }
    
    all_present = True
    for file_path, description in required_files.items():
        if Path(file_path).exists():
            print_success(f"{description}: {file_path}")
        else:
            print_error(f"Missing {description}: {file_path}")
            all_present = False
    
    return all_present

def check_dependencies():
    """Check if all required packages are installed"""
    print("\n" + "="*60)
    print("STEP 2: Checking Dependencies")
    print("="*60)
    
    required = {
        "cv2": "opencv-python-headless",
        "numpy": "numpy",
        "httpx": "httpx",
        "fastapi": "fastapi"
    }
    
    all_installed = True
    for module, package in required.items():
        try:
            __import__(module)
            print_success(f"{package} is installed")
        except ImportError:
            print_error(f"{package} is NOT installed")
            print_info(f"   Install with: pip install {package}")
            all_installed = False
    
    return all_installed

def check_environment_variables():
    """Check if environment variables are set"""
    print("\n" + "="*60)
    print("STEP 3: Checking Environment Variables")
    print("="*60)
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    if api_key:
        if api_key.startswith("sk-ant-"):
            print_success("ANTHROPIC_API_KEY is set and looks valid")
            print_info(f"   Key prefix: {api_key[:15]}...")
            return True
        else:
            print_error("ANTHROPIC_API_KEY is set but doesn't look like a Claude key")
            print_info("   Claude keys start with 'sk-ant-'")
            return False
    else:
        print_warning("ANTHROPIC_API_KEY is not set")
        print_info("   Set with: export ANTHROPIC_API_KEY='sk-ant-...'")
        print_info("   Get key from: https://console.anthropic.com/")
        print_info("   You can still test OpenCV detection without it")
        return False

def test_imports():
    """Test if modules can be imported"""
    print("\n" + "="*60)
    print("STEP 4: Testing Module Imports")
    print("="*60)
    
    all_success = True
    
    try:
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        
        # Test debugger
        try:
            from analysis.vision.debugger import CardDetectionDebugger
            print_success("CardDetectionDebugger imports successfully")
        except Exception as e:
            print_error(f"CardDetectionDebugger import failed: {e}")
            all_success = False
        
        # Test enhanced corners
        try:
            from analysis.enhanced_corners import analyze_corners_enhanced
            print_success("Enhanced corner detection imports successfully")
        except Exception as e:
            print_error(f"Enhanced corner detection import failed: {e}")
            all_success = False
        
        # Test vision detector
        try:
            from services.ai.vision_detector import VisionAIDetector
            print_success("VisionAIDetector imports successfully")
        except Exception as e:
            print_error(f"VisionAIDetector import failed: {e}")
            all_success = False
        
        # Test enhanced detection
        try:
            from api.enhanced_detection import router
            print_success("Enhanced detection router imports successfully")
        except Exception as e:
            print_error(f"Enhanced detection router import failed: {e}")
            all_success = False
            
    except Exception as e:
        print_error(f"Import test failed: {e}")
        all_success = False
    
    return all_success

def test_debugger(image_path=None):
    """Test the debugger with an image"""
    print("\n" + "="*60)
    print("STEP 5: Testing Card Detection Debugger")
    print("="*60)
    
    if not image_path:
        print_warning("No test image provided, skipping debugger test")
        print_info("   Run with: python test_before_deploy.py path/to/card.jpg")
        return True
    
    if not Path(image_path).exists():
        print_error(f"Test image not found: {image_path}")
        return False
    
    try:
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from analysis.vision.debugger import CardDetectionDebugger
        
        debugger = CardDetectionDebugger(output_dir="./test_debug_output")
        
        print_info(f"Running debugger on: {image_path}")
        results = debugger.visualize_full_pipeline(image_path)
        
        print_success(f"Debugger completed successfully")
        print_info(f"   Candidates found: {results.get('candidates', 0)}")
        print_info(f"   Card detected: {results.get('corrected', False)}")
        print_info(f"   Debug images: test_debug_output/{results['session_id']}/")
        
        # Run diagnosis
        diagnosis = debugger.diagnose_detection_failure(image_path)
        if "✅" in diagnosis:
            print_success("Image quality appears good")
        else:
            print_warning("Image quality issues detected:")
            for line in diagnosis.split("\n"):
                if "⚠️" in line:
                    print(f"   {line}")
        
        return True
        
    except Exception as e:
        print_error(f"Debugger test failed: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def test_opencv_detection(image_path=None):
    """Test OpenCV detection"""
    print("\n" + "="*60)
    print("STEP 6: Testing OpenCV Detection")
    print("="*60)
    
    if not image_path:
        print_warning("No test image provided, skipping OpenCV test")
        return True
    
    try:
        import cv2
        import numpy as np
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            print_error(f"Could not load image: {image_path}")
            return False
        
        print_success(f"Image loaded: {img.shape[1]}x{img.shape[0]}")
        
        # Try basic detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        print_success(f"Found {len(contours)} contours")
        
        # Check for card-sized contours
        h, w = img.shape[:2]
        valid_contours = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 0.2 * (w * h) <= area <= 0.9 * (w * h):
                valid_contours += 1
        
        if valid_contours > 0:
            print_success(f"Found {valid_contours} card-sized contours")
        else:
            print_warning("No card-sized contours found")
            print_info("   This might need Vision AI fallback")
        
        return True
        
    except Exception as e:
        print_error(f"OpenCV test failed: {e}")
        return False

def test_ai_detection(image_path=None):
    """Test Vision AI detection"""
    print("\n" + "="*60)
    print("STEP 7: Testing Vision AI Detection")
    print("="*60)
    
    if not os.getenv("ANTHROPIC_API_KEY"):
        print_warning("ANTHROPIC_API_KEY not set, skipping AI test")
        print_info("   Set with: export ANTHROPIC_API_KEY='sk-ant-...'")
        return True
    
    if not image_path:
        print_warning("No test image provided, skipping AI test")
        return True
    
    try:
        import asyncio
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from services.ai.vision_detector import VisionAIDetector
        
        async def test():
            detector = VisionAIDetector(provider='claude')
            
            print_info("Calling Claude API (this may take 2-5 seconds)...")
            result = await detector.detect_card_with_llm(image_path)
            
            if result.get("card_detected"):
                print_success("Card detected by Vision AI")
                print_info(f"   Confidence: {result.get('confidence', 0):.2%}")
                print_info(f"   Card type: {result.get('card_type', 'unknown')}")
                
                quality = result.get('quality_assessment', {})
                if quality:
                    print_info(f"   Lighting: {quality.get('lighting', 'unknown')}")
                    print_info(f"   Blur: {quality.get('blur', 'unknown')}")
                    print_info(f"   Angle: {quality.get('angle', 'unknown')}")
                
                return True
            else:
                print_error("Card not detected by Vision AI")
                print_info(f"   Reasoning: {result.get('reasoning', 'unknown')}")
                return False
        
        result = asyncio.run(test())
        return result
        
    except Exception as e:
        print_error(f"Vision AI test failed: {e}")
        if "API key" in str(e):
            print_info("   Check your ANTHROPIC_API_KEY is correct")
        elif "timeout" in str(e).lower():
            print_info("   API call timed out - check your internet connection")
        else:
            import traceback
            print(traceback.format_exc())
        return False

def test_enhanced_corners(image_path=None):
    """Test enhanced corner detection"""
    print("\n" + "="*60)
    print("STEP 8: Testing Enhanced Corner Detection")
    print("="*60)
    
    if not image_path:
        print_warning("No test image provided, skipping corner test")
        return True
    
    try:
        import cv2
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from analysis.enhanced_corners import analyze_corners_enhanced
        
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            print_error(f"Could not load image: {image_path}")
            return False
        
        # Analyze corners
        result = analyze_corners_enhanced(img, side="front", debug=True)
        
        print_success("Corner analysis completed")
        print_info(f"   Overall grade: {result['overall_grade']:.1f}")
        print_info(f"   Individual scores: {[f'{s:.1f}' for s in result['individual_scores']]}")
        print_info(f"   False positives filtered: {result.get('false_positives_filtered', 0)}")
        print_info(f"   Confidence: {result.get('confidence', 0):.2%}")
        
        if result.get('false_positives_filtered', 0) > 0:
            print_success(f"Filtered {result['false_positives_filtered']} false positives!")
        
        return True
        
    except Exception as e:
        print_error(f"Enhanced corner test failed: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def generate_report(results):
    """Generate final test report"""
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for r in results.values() if r)
    
    for test_name, result in results.items():
        if result:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print_success("\n🎉 All tests passed! Ready to deploy to Railway")
        print_info("\nNext steps:")
        print_info("1. Commit your changes: git add . && git commit -m 'Add enhanced detection'")
        print_info("2. Set Railway environment variables (see RAILWAY_DEPLOYMENT.md)")
        print_info("3. Deploy: git push origin main")
        print_info("4. Monitor: railway logs -f")
        return True
    else:
        print_error("\n⚠️  Some tests failed. Fix issues before deploying")
        print_info("\nCommon fixes:")
        print_info("- Missing files: Check file placement in MIGRATION_GUIDE.md Step 1")
        print_info("- Import errors: Check requirements.txt has all dependencies")
        print_info("- API key issues: Set ANTHROPIC_API_KEY environment variable")
        return False

def main():
    """Run all tests"""
    print(f"{Colors.BLUE}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║     Pokemon Card Pregrader - Pre-Deployment Tests          ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"{Colors.RESET}")
    
    # Get test image path from command line
    test_image = sys.argv[1] if len(sys.argv) > 1 else None
    
    if test_image and not Path(test_image).exists():
        print_error(f"Test image not found: {test_image}")
        print_info("Usage: python test_before_deploy.py [path/to/card.jpg]")
        return False
    
    if test_image:
        print_info(f"Using test image: {test_image}")
    else:
        print_warning("No test image provided - some tests will be skipped")
        print_info("For full testing, run: python test_before_deploy.py path/to/card.jpg")
    
    # Run tests
    results = {
        "File Structure": check_file_structure(),
        "Dependencies": check_dependencies(),
        "Environment Variables": check_environment_variables(),
        "Module Imports": test_imports(),
    }
    
    # Only run these if basic tests pass
    if all([results["File Structure"], results["Dependencies"], results["Module Imports"]]):
        results["Debugger"] = test_debugger(test_image)
        results["OpenCV Detection"] = test_opencv_detection(test_image)
        results["Enhanced Corners"] = test_enhanced_corners(test_image)
        results["Vision AI"] = test_ai_detection(test_image)
    
    # Generate report
    return generate_report(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
