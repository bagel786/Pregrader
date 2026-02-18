
import asyncio
import sys
import os
import io
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import numpy as np

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "."))

# Mock modules that might rely on external services or files
sys.modules["cv2"] = MagicMock()
sys.modules["cv2"].imread.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
sys.modules["services.pokemon_tcg"] = MagicMock()

# Import the modules to test
from api.hybrid_detect import detect_and_correct_card, DetectionConfig
from api.combined_grading import combine_front_back_analysis

class TestHybridFeatures(unittest.IsolatedAsyncioTestCase):
    
    async def test_opencv_success(self):
        """Test standard OpenCV detection success path."""
        print("\nTesting OpenCV Success Path...")
        
        # Mock _try_opencv_detection to return success
        with patch("api.hybrid_detect._try_opencv_detection") as mock_opencv:
            mock_opencv.return_value = {
                "success": True,
                "confidence": 0.95,
                "method": "standard",
                "corrected_image": np.zeros((100, 100, 3), dtype=np.uint8)
            }
            
            result = await detect_and_correct_card("dummy_path.jpg", "test_session")
            
            self.assertTrue(result["success"])
            self.assertEqual(result["method"], "opencv_standard")
            self.assertEqual(result["confidence"], 0.95)
            print("✓ OpenCV success path verified")

    async def test_ai_fallback(self):
        """Test AI fallback when OpenCV fails."""
        print("\nTesting AI Fallback Path...")
        
        # Mock OpenCV to fail
        with patch("api.hybrid_detect._try_opencv_detection") as mock_opencv:
            mock_opencv.return_value = {"success": False, "confidence": 0.1}
            
            # Mock VisionAIDetector
            with patch("services.ai.vision_detector.VisionAIDetector") as MockDetector:
                instance = MockDetector.return_value
                instance.hybrid_detection = AsyncMock(return_value={
                    "final_corners": [[0,0], [10,0], [10,10], [0,10]],
                    "confidence": 0.98,
                    "llm_result": {"quality_assessment": "Good"}
                })
                instance.apply_perspective_correction.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
                
                # We need to ensure DetectionConfig uses our mock values if needed, 
                # but we can also just let it run since we mocked the detector.
                # However, detect_and_correct_card imports VisionAIDetector inside the function logic
                # so we need to patch it where it is imported or available.
                # Since it's inside the function, patching 'services.ai.vision_detector.VisionAIDetector'
                # should work if sys.modules cache is handled, but let's use patch.dict to be safe
                # or patch where it's used. 
                # Actually, the import is inside `_try_ai_fallback`.
                
                # Let's try mocking the _try_ai_fallback directly to verify logic flow first
                # But to test the integration, let's mock the class.
                
                # To make sure the import works inside the function:
                with patch.dict(sys.modules, {"services.ai.vision_detector": MagicMock()}):
                     sys.modules["services.ai.vision_detector"].VisionAIDetector = MockDetector
                     
                     result = await detect_and_correct_card("dummy_path.jpg", "test_session")
                     
                     self.assertTrue(result["success"])
                     self.assertEqual(result["method"], "hybrid_ai")
                     self.assertEqual(result["confidence"], 0.98)
                     print("✓ AI Fallback path verified")

    def test_combined_grading_logic(self):
        """Test the merging logic for front and back analysis."""
        print("\nTesting Combined Grading Logic...")
        
        front_data = {
            "centering": {"grade_estimate": 9.0},
            "corners": {
                "corners": {"tl": {"score": 9}, "tr": {"score": 9}, "bl": {"score": 9}, "br": {"score": 9}},
                "overall_grade": 9.0
            },
            "edges": {"score": 9.0},
            "surface": {"surface": {"score": 9.0}}
        }
        
        # Back has worse edges and surface
        back_data = {
            "centering": None, # Ignored
            "corners": {
                "corners": {"tl": {"score": 8}, "tr": {"score": 8}, "bl": {"score": 8}, "br": {"score": 8}},
                "overall_grade": 8.0
            },
            "edges": {"score": 6.0}, # Significantly worse
            "surface": {"surface": {"score": 7.0}} # Worse
        }
        
        with patch("analysis.scoring.GradingEngine.calculate_grade") as mock_calc:
            mock_calc.return_value = {"final_score": 7.5, "psa_estimate": "7"}
            
            combined = combine_front_back_analysis(front_data, back_data)
            
            # Check Centering (Front only)
            self.assertEqual(combined["centering"]["grade_estimate"], 9.0)
            
            # Check Edges (Should pick back score 6.0 -> actually weighted average in code)
            # Code: worse * 0.7 + better * 0.3
            # 6.0 * 0.7 + 9.0 * 0.3 = 4.2 + 2.7 = 6.9
            expected_edge = round(6.0 * 0.7 + 9.0 * 0.3, 1)
            self.assertEqual(combined["edges"]["score"], expected_edge)
            self.assertEqual(combined["edges"]["source"], "back")
            
            # Check Surface (Worst case logic - straight replacement)
            # Code: if back < front: use back
            self.assertEqual(combined["surface"]["surface"]["score"], 7.0)
            self.assertEqual(combined["surface"]["source"], "back")
            
            print("✓ Combined grading logic (worst-case/weighted) verified")

if __name__ == "__main__":
    unittest.main()
