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
import logging
import asyncio

_logger = logging.getLogger(__name__)


class VisionAIDetector:
    """
    AI-powered card detection using Claude Vision API
    Falls back to OpenCV for refinement
    """
    
    def __init__(
        self,
        provider: str = "claude",
        api_key: Optional[str] = None,
        timeout: int = 10
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
    
    def _prepare_image_for_api(self, image_path: str) -> tuple:
        """Read and compress image to stay under the 5MB Claude API limit."""
        _MAX_BYTES = 4 * 1024 * 1024  # 4MB — leave headroom below 5MB

        with open(image_path, "rb") as f:
            raw_bytes = f.read()

        ext = Path(image_path).suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "image/jpeg")

        if len(raw_bytes) <= _MAX_BYTES:
            return raw_bytes, media_type

        _logger.info(
            f"Image is {len(raw_bytes) / 1024 / 1024:.1f} MB — compressing before API call"
        )

        img_array = np.frombuffer(raw_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            return raw_bytes, media_type  # fall through; API will reject

        # Try quality reduction first (preserves resolution)
        for quality in (80, 65, 50):
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if len(buf.tobytes()) <= _MAX_BYTES:
                _logger.info(f"Compressed to {len(buf.tobytes()) / 1024:.0f} KB (quality={quality})")
                return buf.tobytes(), "image/jpeg"

        # If quality alone isn't enough, also downscale
        h, w = img.shape[:2]
        for scale in (0.75, 0.60, 0.50):
            resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if len(buf.tobytes()) <= _MAX_BYTES:
                _logger.info(
                    f"Compressed to {len(buf.tobytes()) / 1024:.0f} KB (scale={scale}, quality=65)"
                )
                return buf.tobytes(), "image/jpeg"

        # Last resort — return whatever we have (smallest version)
        return buf.tobytes(), "image/jpeg"

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

        # Read and compress image to stay under 5MB Claude API limit
        raw_bytes, media_type = self._prepare_image_for_api(image_path)
        image_data = base64.standard_b64encode(raw_bytes).decode("utf-8")
        
        # Prepare prompt
        prompt = """Analyze this image and detect if there's a Pokemon trading card present.

Your task:
1. Determine if a Pokemon card is visible
2. If yes, identify the 4 corner points of the card (top-left, top-right, bottom-right, bottom-left)
3. Assess image quality (lighting, blur, angle)
4. Provide confidence score
5. Measure the printed colored border of the Pokemon card on each side.
   The border is the uniform flat-colored frame between the physical card edge and
   the artwork/content area (name bar, illustration box, text box).
   Express each as a fraction of the card's own dimension (not the image dimension):
   - left: fraction of card width  (e.g. 0.07 = border is 7% of card width)
   - right: fraction of card width
   - top: fraction of card height
   - bottom: fraction of card height

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
    },
    "border_fractions": {
        "left": 0.07,
        "right": 0.07,
        "top": 0.08,
        "bottom": 0.07
    }
}

Important:
- Corners should be in pixels relative to image dimensions
- Top-left is [0, 0]
- Confidence should reflect how certain you are
- If card is rotated/angled, still provide corners
- If multiple cards, choose the most prominent one
- border_fractions are relative to the card dimensions, not the full image
- Typical Pokemon card border is 5-10% per side; full-art cards may have no distinct border
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
                
                # Parse JSON from response — Claude may wrap it in markdown blocks
                # Try multiple extraction strategies before failing
                json_str = None
                if "```json" in text_content:
                    json_str = text_content.split("```json")[1].split("```")[0].strip()
                elif "```" in text_content:
                    json_str = text_content.split("```")[1].split("```")[0].strip()
                else:
                    # Try to extract a JSON object directly from the text
                    brace_start = text_content.find("{")
                    brace_end = text_content.rfind("}")
                    if brace_start != -1 and brace_end > brace_start:
                        json_str = text_content[brace_start:brace_end + 1]
                    else:
                        json_str = text_content.strip()

                try:
                    llm_result = json.loads(json_str)
                except json.JSONDecodeError:
                    raise Exception(
                        f"Claude returned a non-JSON response: {text_content[:200]}"
                    )

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
                "method": "failed",
                "border_fractions": None,
            }

        # Extract border_fractions if the model returned them
        border_fractions = llm_result.get("border_fractions")

        corners = llm_result.get("corners", [])
        if not corners or len(corners) != 4:
            return {
                "llm_result": llm_result,
                "final_corners": None,
                "confidence": 0.0,
                "method": "failed",
                "border_fractions": border_fractions,
            }

        ai_corners = np.array(corners, dtype=np.float32)

        # Step 2: Refine with OpenCV
        refined_corners = self._refine_corners_with_opencv(image_path, ai_corners)

        if refined_corners is not None:
            return {
                "llm_result": llm_result,
                "final_corners": refined_corners,
                "confidence": min(llm_result["confidence"] * 1.1, 1.0),  # Boost confidence
                "method": "ai_refined",
                "border_fractions": border_fractions,
            }
        else:
            return {
                "llm_result": llm_result,
                "final_corners": ai_corners,
                "confidence": llm_result["confidence"],
                "method": "ai_only",
                "border_fractions": border_fractions,
            }
    
    def _refine_corners_with_opencv(
        self,
        image_path: str,
        ai_corners: np.ndarray,
        search_radius: int = 50
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

    _logger.info(f"Testing detection on: {image_path}")
    _logger.info("Calling Claude Vision API...")

    result = await detector.hybrid_detection(image_path)

    _logger.info(f"Card detected: {result['llm_result'].get('card_detected')}")
    _logger.info(f"Confidence: {result['confidence']:.2%}")
    _logger.info(f"Method: {result['method']}")

    if result['final_corners'] is not None:
        _logger.info(f"Corners: {result['final_corners'].tolist()}")

        corrected = detector.apply_perspective_correction(
            image_path,
            result['final_corners']
        )
        output_path = "test_corrected.jpg"
        cv2.imwrite(output_path, corrected)
        _logger.info(f"Corrected image saved to: {output_path}")

    return result


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        asyncio.run(test_detection(image_path))
    else:
        print("Usage: python vision_detector.py <image_path>")
