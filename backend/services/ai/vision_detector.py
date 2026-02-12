"""
Vision AI Card Detector
Uses Claude Vision API to detect cards in challenging conditions

Solves:
- Works on ANY background (wood, carpet, fabric, etc.)
- Handles cards at ANY angle (up to 45°)
- Finds correct boundaries even when unclear
"""
import os
import base64
import httpx
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import json
import asyncio


class VisionAIDetector:
    """
    AI-powered card detection using Claude Vision API
    Falls back to OpenCV for refinement
    """
    
    def __init__(
        self,
        provider: str = "claude",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        self.provider = provider
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.timeout = timeout
        
        if not self.api_key:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("ANTHROPIC_API_KEY not set - Vision AI detection will not be available")
            # Don't raise error, just log warning
            # This allows the module to import even without API key
    
    async def detect_card_with_llm(self, image_path: str) -> Dict:
        """
        Use Claude Vision to detect card in image
        
        Returns:
            {
                "card_detected": bool,
                "corners": [[x, y], ...],  # 4 corners if detected
                "confidence": float,
                "reasoning": str,
                "card_type": str,
                "quality_assessment": {...}
            }
        """
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set - cannot use Vision AI detection")
        
        # Encode image
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        # Determine media type
        ext = Path(image_path).suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }.get(ext, "image/jpeg")
        
        # Prepare prompt
        prompt = """Analyze this image and detect if there's a Pokemon trading card present.

Your task:
1. Determine if a Pokemon card is visible
2. If yes, identify the 4 corner points of the card (top-left, top-right, bottom-right, bottom-left)
3. Assess image quality (lighting, blur, angle)
4. Provide confidence score

Respond in JSON format:
{
    "card_detected": true/false,
    "corners": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
    "confidence": 0.0-1.0,
    "reasoning": "why you made this determination",
    "card_type": "pokemon/other/none",
    "quality_assessment": {
        "lighting": "good/poor/glare",
        "blur": "sharp/slight/heavy",
        "angle": "straight/slight/heavy",
        "background": "plain/busy/unclear"
    }
}

Important:
- Corners should be in pixels relative to image dimensions
- Top-left is [0, 0]
- Confidence should reflect how certain you are
- If card is rotated/angled, still provide corners
- If multiple cards, choose the most prominent one
"""
        
        # Call Claude API
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1024,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": image_data
                                        }
                                    },
                                    {
                                        "type": "text",
                                        "text": prompt
                                    }
                                ]
                            }
                        ]
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Extract text response
                text_content = result["content"][0]["text"]
                
                # Parse JSON from response
                # Claude might wrap it in markdown code blocks
                if "```json" in text_content:
                    json_str = text_content.split("```json")[1].split("```")[0].strip()
                elif "```" in text_content:
                    json_str = text_content.split("```")[1].split("```")[0].strip()
                else:
                    json_str = text_content.strip()
                
                llm_result = json.loads(json_str)
                
                return llm_result
                
            except httpx.TimeoutException:
                raise TimeoutError(f"Claude API timeout after {self.timeout}s")
            except httpx.HTTPStatusError as e:
                raise Exception(f"Claude API error: {e.response.status_code} - {e.response.text}")
            except json.JSONDecodeError as e:
                raise Exception(f"Failed to parse Claude response: {text_content}")
            except Exception as e:
                raise Exception(f"Vision AI detection failed: {str(e)}")
    
    async def hybrid_detection(self, image_path: str) -> Dict:
        """
        Hybrid approach: Use AI to find card, OpenCV to refine corners
        
        Returns:
            {
                "llm_result": {...},
                "final_corners": [[x, y], ...],
                "confidence": float,
                "method": "ai_only" | "ai_refined"
            }
        """
        # Step 1: Get AI detection
        llm_result = await self.detect_card_with_llm(image_path)
        
        if not llm_result.get("card_detected"):
            return {
                "llm_result": llm_result,
                "final_corners": None,
                "confidence": 0.0,
                "method": "failed"
            }
        
        ai_corners = np.array(llm_result["corners"], dtype=np.float32)
        
        # Step 2: Refine with OpenCV
        refined_corners = self._refine_corners_with_opencv(image_path, ai_corners)
        
        if refined_corners is not None:
            return {
                "llm_result": llm_result,
                "final_corners": refined_corners,
                "confidence": min(llm_result["confidence"] * 1.1, 1.0),  # Boost confidence
                "method": "ai_refined"
            }
        else:
            return {
                "llm_result": llm_result,
                "final_corners": ai_corners,
                "confidence": llm_result["confidence"],
                "method": "ai_only"
            }
    
    def _refine_corners_with_opencv(
        self,
        image_path: str,
        ai_corners: np.ndarray,
        search_radius: int = 30
    ) -> Optional[np.ndarray]:
        """
        Use OpenCV to refine AI-detected corners
        Searches around AI corners for actual edges
        """
        img = cv2.imread(image_path)
        if img is None:
            return None
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detect edges
        edges = cv2.Canny(gray, 50, 150)
        
        refined_corners = []
        
        for corner in ai_corners:
            x, y = int(corner[0]), int(corner[1])
            
            # Extract region around corner
            x1 = max(0, x - search_radius)
            y1 = max(0, y - search_radius)
            x2 = min(img.shape[1], x + search_radius)
            y2 = min(img.shape[0], y + search_radius)
            
            region = edges[y1:y2, x1:x2]
            
            # Find strongest edge point in region
            if region.size > 0:
                edge_points = np.argwhere(region > 0)
                
                if len(edge_points) > 0:
                    # Find point closest to center of region
                    center = np.array([search_radius, search_radius])
                    distances = np.linalg.norm(edge_points - center, axis=1)
                    closest_idx = np.argmin(distances)
                    best_point = edge_points[closest_idx]
                    
                    # Convert back to image coordinates
                    refined_x = x1 + best_point[1]
                    refined_y = y1 + best_point[0]
                    
                    refined_corners.append([refined_x, refined_y])
                else:
                    # No edges found, keep AI corner
                    refined_corners.append([x, y])
            else:
                refined_corners.append([x, y])
        
        return np.array(refined_corners, dtype=np.float32)
    
    def apply_perspective_correction(
        self,
        image_path: str,
        corners: np.ndarray,
        output_size: Tuple[int, int] = (500, 700)
    ) -> np.ndarray:
        """
        Apply perspective transform to straighten card
        
        Args:
            image_path: Path to image
            corners: 4 corner points [TL, TR, BR, BL]
            output_size: (width, height) of output
        
        Returns:
            Corrected image as numpy array
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")
        
        # Ensure corners are in correct order: TL, TR, BR, BL
        corners = self._order_points(corners)
        
        # Define destination points
        w, h = output_size
        dst_pts = np.array([
            [0, 0],
            [w - 1, 0],
            [w - 1, h - 1],
            [0, h - 1]
        ], dtype=np.float32)
        
        # Calculate perspective transform
        M = cv2.getPerspectiveTransform(corners, dst_pts)
        
        # Apply transform
        warped = cv2.warpPerspective(img, M, output_size)
        
        return warped
    
    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Order points as: top-left, top-right, bottom-right, bottom-left
        """
        # Initialize ordered points
        rect = np.zeros((4, 2), dtype=np.float32)
        
        # Sum and diff to find corners
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        
        # Top-left has smallest sum
        rect[0] = pts[np.argmin(s)]
        
        # Bottom-right has largest sum
        rect[2] = pts[np.argmax(s)]
        
        # Top-right has smallest diff
        rect[1] = pts[np.argmin(diff)]
        
        # Bottom-left has largest diff
        rect[3] = pts[np.argmax(diff)]
        
        return rect


# Convenience function for testing
async def test_detection(image_path: str):
    """Test the detector on an image"""
    detector = VisionAIDetector()
    
    print(f"Testing detection on: {image_path}")
    print("Calling Claude Vision API...")
    
    result = await detector.hybrid_detection(image_path)
    
    print("\nResults:")
    print(f"  Card detected: {result['llm_result'].get('card_detected')}")
    print(f"  Confidence: {result['confidence']:.2%}")
    print(f"  Method: {result['method']}")
    
    if result['final_corners'] is not None:
        print(f"  Corners: {result['final_corners'].tolist()}")
        
        # Apply correction
        corrected = detector.apply_perspective_correction(
            image_path,
            result['final_corners']
        )
        
        # Save result
        output_path = "test_corrected.jpg"
        cv2.imwrite(output_path, corrected)
        print(f"\nCorrected image saved to: {output_path}")
    
    return result


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        asyncio.run(test_detection(image_path))
    else:
        print("Usage: python vision_detector.py <image_path>")
