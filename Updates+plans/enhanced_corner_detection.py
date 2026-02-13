"""
Enhanced Corner Detection Module
Fixes false positives by validating detected damage is actually on the card

Your issue: "pretty bad at detecting cornering issues and will flag random things"
Solution: Add contextual validation to ensure detected damage is in expected corner regions
"""
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional


class EnhancedCornerDetector:
    """
    Improved corner detection with false positive reduction
    """
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.debug_images = []
    
    def analyze_corners(
        self, 
        image: np.ndarray, 
        side: str = "front"
    ) -> Dict:
        """
        Analyze card corners with enhanced false positive filtering
        
        Returns:
            {
                "individual_scores": [score1, score2, score3, score4],
                "overall_grade": float,
                "worst_corner": int,
                "confidence": float,
                "false_positives_filtered": int,
                "corner_regions": [...],  # Debug info
                "analysis_method": str
            }
        """
        h, w = image.shape[:2]
        
        # Step 1: Validate this is actually a card-shaped image
        if not self._is_card_shaped(w, h):
            return {
                "individual_scores": [5.0, 5.0, 5.0, 5.0],
                "overall_grade": 5.0,
                "confidence": 0.3,
                "error": "Image not card-shaped - using conservative scores"
            }
        
        # Step 2: Detect card boundaries to ensure we only check actual corners
        card_mask = self._detect_card_region(image)
        
        # Step 3: Extract corner regions with boundary validation
        corner_regions = self._extract_validated_corners(image, card_mask)
        
        # Step 4: Analyze each corner with false positive filtering
        corner_scores = []
        false_positives = 0
        
        for i, (corner_img, corner_mask, is_valid) in enumerate(corner_regions):
            if not is_valid:
                # Corner region extends beyond card - use conservative score
                corner_scores.append(7.0)
                false_positives += 1
                continue
            
            # Analyze this corner
            score, is_false_positive = self._analyze_single_corner(
                corner_img, 
                corner_mask,
                corner_index=i
            )
            
            if is_false_positive:
                # Detected damage is likely background/artifact
                score = max(score, 8.0)  # Override with higher score
                false_positives += 1
            
            corner_scores.append(score)
        
        # Step 5: Calculate overall grade with penalties
        overall = self._calculate_overall_grade(corner_scores)
        worst_corner = np.argmin(corner_scores)
        confidence = self._calculate_confidence(corner_scores, false_positives)
        
        result = {
            "individual_scores": corner_scores,
            "overall_grade": overall,
            "worst_corner": worst_corner,
            "confidence": confidence,
            "false_positives_filtered": false_positives,
            "analysis_method": "enhanced_validation"
        }
        
        if self.debug:
            result["corner_regions"] = corner_regions
            result["debug_images"] = self.debug_images
        
        return result
    
    def _is_card_shaped(self, width: int, height: int) -> bool:
        """Check if image has card-like aspect ratio"""
        aspect = width / height if height > 0 else 0
        target_aspect = 500 / 700  # Pokemon card ratio
        
        # Allow some tolerance
        return 0.6 < aspect < 0.85 or 1.18 < aspect < 1.67
    
    def _detect_card_region(self, image: np.ndarray) -> np.ndarray:
        """
        Detect the actual card region to avoid checking background
        Returns binary mask where card = 255, background = 0
        """
        h, w = image.shape[:2]
        
        # Method 1: Assume card fills most of image (after perspective correction)
        # Create initial mask with 5% border
        mask = np.zeros((h, w), dtype=np.uint8)
        border = int(min(h, w) * 0.05)
        mask[border:h-border, border:w-border] = 255
        
        # Method 2: Edge-based refinement
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            # Get largest contour (likely the card)
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            
            # If it's big enough, use it
            if area > 0.5 * (w * h):
                refined_mask = np.zeros((h, w), dtype=np.uint8)
                cv2.drawContours(refined_mask, [largest], -1, 255, -1)
                
                # Erode slightly to avoid edge artifacts
                kernel = np.ones((5, 5), np.uint8)
                refined_mask = cv2.erode(refined_mask, kernel, iterations=2)
                
                return refined_mask
        
        # Fallback to border mask
        return mask
    
    def _extract_validated_corners(
        self, 
        image: np.ndarray, 
        card_mask: np.ndarray
    ) -> List[Tuple[np.ndarray, np.ndarray, bool]]:
        """
        Extract corner regions and validate they're within card bounds
        
        Returns: [(corner_img, corner_mask, is_valid), ...]
        """
        h, w = image.shape[:2]
        
        # Corner size should be resolution-independent (4% of card dimension)
        corner_size = int(min(h, w) * 0.08)  # Increased from original for better detection
        
        # Define corner positions
        corners = [
            (0, 0),                    # Top-left
            (w - corner_size, 0),      # Top-right
            (w - corner_size, h - corner_size),  # Bottom-right
            (0, h - corner_size)       # Bottom-left
        ]
        
        corner_regions = []
        
        for x, y in corners:
            # Extract corner region
            corner_img = image[y:y+corner_size, x:x+corner_size].copy()
            corner_mask = card_mask[y:y+corner_size, x:x+corner_size].copy()
            
            # Validate: corner should be mostly within card
            valid_pixels = np.sum(corner_mask > 0)
            total_pixels = corner_size * corner_size
            validity_ratio = valid_pixels / total_pixels
            
            is_valid = validity_ratio > 0.7  # At least 70% of corner is on card
            
            corner_regions.append((corner_img, corner_mask, is_valid))
        
        return corner_regions
    
    def _analyze_single_corner(
        self, 
        corner_img: np.ndarray, 
        corner_mask: np.ndarray,
        corner_index: int
    ) -> Tuple[float, bool]:
        """
        Analyze single corner with false positive detection
        
        Returns: (score, is_false_positive)
        """
        # Convert to HSV for better color detection
        hsv = cv2.cvtColor(corner_img, cv2.COLOR_BGR2HSV)
        
        # Detect white pixels (exposed cardboard)
        # Hue: any (0-180), Saturation: low (0-40), Value: high (180-255)
        lower_white = np.array([0, 0, 180])
        upper_white = np.array([180, 40, 255])
        white_mask = cv2.inRange(hsv, lower_white, upper_white)
        
        # Apply card mask to only check valid regions
        white_mask = cv2.bitwise_and(white_mask, corner_mask)
        
        # Count white pixels
        white_pixels = np.sum(white_mask > 0)
        
        # Check for false positive patterns
        is_false_positive = self._is_false_positive(
            corner_img, 
            white_mask, 
            corner_mask,
            corner_index
        )
        
        # Score based on damage amount
        score = self._calculate_corner_score(white_pixels)
        
        if self.debug:
            debug_img = corner_img.copy()
            debug_img[white_mask > 0] = [0, 0, 255]  # Highlight detected damage in red
            self.debug_images.append({
                f"corner_{corner_index}": debug_img,
                "white_pixels": int(white_pixels),
                "score": float(score),
                "is_false_positive": is_false_positive
            })
        
        return score, is_false_positive
    
    def _is_false_positive(
        self, 
        corner_img: np.ndarray, 
        white_mask: np.ndarray,
        card_mask: np.ndarray,
        corner_index: int
    ) -> bool:
        """
        Detect if whitening is actually a false positive
        
        Common false positives:
        1. Background bleed-through
        2. Glare/reflection
        3. Print pattern (not damage)
        4. Card border (yellow border mistaken for damage)
        """
        white_pixels = np.sum(white_mask > 0)
        
        # No damage detected - definitely not false positive
        if white_pixels < 10:
            return False
        
        # Check 1: Is whitening at the very edge? (likely background)
        edge_whitening = self._check_edge_whitening(white_mask, corner_index)
        if edge_whitening > 0.7:  # More than 70% at edge
            return True
        
        # Check 2: Is whitening too uniform? (likely glare or border)
        is_uniform = self._check_uniformity(white_mask)
        if is_uniform and white_pixels > 100:
            return True
        
        # Check 3: Check brightness pattern
        gray = cv2.cvtColor(corner_img, cv2.COLOR_BGR2GRAY)
        avg_brightness = np.mean(gray[white_mask > 0])
        
        # If extremely bright (>240), likely glare not damage
        if avg_brightness > 240:
            return True
        
        # Check 4: Is this in the expected corner location?
        if not self._is_in_corner_zone(white_mask, corner_index):
            return True
        
        return False
    
    def _check_edge_whitening(self, white_mask: np.ndarray, corner_index: int) -> float:
        """Check if whitening is concentrated at the edge (likely background)"""
        h, w = white_mask.shape
        edge_width = max(3, min(h, w) // 10)
        
        # Define edge region based on corner position
        if corner_index == 0:  # Top-left
            edge_mask = np.zeros_like(white_mask)
            edge_mask[:edge_width, :] = 255  # Top edge
            edge_mask[:, :edge_width] = 255  # Left edge
        elif corner_index == 1:  # Top-right
            edge_mask = np.zeros_like(white_mask)
            edge_mask[:edge_width, :] = 255  # Top edge
            edge_mask[:, -edge_width:] = 255  # Right edge
        elif corner_index == 2:  # Bottom-right
            edge_mask = np.zeros_like(white_mask)
            edge_mask[-edge_width:, :] = 255  # Bottom edge
            edge_mask[:, -edge_width:] = 255  # Right edge
        else:  # Bottom-left
            edge_mask = np.zeros_like(white_mask)
            edge_mask[-edge_width:, :] = 255  # Bottom edge
            edge_mask[:, :edge_width] = 255  # Left edge
        
        edge_white = np.sum(cv2.bitwise_and(white_mask, edge_mask) > 0)
        total_white = np.sum(white_mask > 0)
        
        return edge_white / total_white if total_white > 0 else 0
    
    def _check_uniformity(self, white_mask: np.ndarray) -> bool:
        """Check if whitening is too uniform (likely glare/border, not damage)"""
        if np.sum(white_mask > 0) < 50:
            return False
        
        # Find contours of white regions
        contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return False
        
        # Get largest contour
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        
        # Check if it's a large uniform blob
        if area > 0.3 * white_mask.size:
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(largest)
            aspect = w / h if h > 0 else 0
            
            # Very rectangular = likely border or glare
            if 0.8 < aspect < 1.2 or aspect > 3 or aspect < 0.33:
                return True
        
        return False
    
    def _is_in_corner_zone(self, white_mask: np.ndarray, corner_index: int) -> bool:
        """Check if damage is in the expected corner zone"""
        h, w = white_mask.shape
        
        # Corner zone is outer 40% of the region
        zone_size = int(min(h, w) * 0.4)
        
        # Create corner zone mask
        zone_mask = np.zeros_like(white_mask)
        
        if corner_index == 0:  # Top-left
            zone_mask[:zone_size, :zone_size] = 255
        elif corner_index == 1:  # Top-right
            zone_mask[:zone_size, -zone_size:] = 255
        elif corner_index == 2:  # Bottom-right
            zone_mask[-zone_size:, -zone_size:] = 255
        else:  # Bottom-left
            zone_mask[-zone_size:, :zone_size] = 255
        
        # Check if most damage is in corner zone
        zone_white = np.sum(cv2.bitwise_and(white_mask, zone_mask) > 0)
        total_white = np.sum(white_mask > 0)
        
        # At least 60% should be in corner zone
        return (zone_white / total_white) > 0.6 if total_white > 0 else True
    
    def _calculate_corner_score(self, white_pixels: int) -> float:
        """Calculate score based on white pixel count (same as original but documented)"""
        if white_pixels < 10:
            return 10.0
        elif white_pixels < 30:
            # Linear interpolation: 10 pixels = 10.0, 30 pixels = 9.5
            return 10.0 - (white_pixels - 10) * 0.025
        elif white_pixels < 75:
            # 30-75: 9.5 to 9.0
            return 9.5 - (white_pixels - 30) * (0.5 / 45)
        elif white_pixels < 150:
            # 75-150: 9.0 to 8.5
            return 9.0 - (white_pixels - 75) * (0.5 / 75)
        elif white_pixels < 300:
            # 150-300: 8.5 to 7.0
            return 8.5 - (white_pixels - 150) * (1.5 / 150)
        else:
            # Heavy damage
            return max(5.0, 7.0 - (white_pixels - 300) * 0.01)
    
    def _calculate_overall_grade(self, corner_scores: List[float]) -> float:
        """Calculate overall grade with penalties for damaged corners"""
        avg_score = np.mean(corner_scores)
        min_score = min(corner_scores)
        
        # Apply penalty based on worst corner
        if min_score <= 5.0:
            penalty = 2.0
        elif min_score <= 6.5:
            penalty = 1.0
        elif min_score <= 7.5:
            penalty = 0.5
        else:
            penalty = 0.0
        
        overall = avg_score - penalty
        return max(5.0, overall)
    
    def _calculate_confidence(self, corner_scores: List[float], false_positives: int) -> float:
        """Calculate confidence in the analysis"""
        base_confidence = 0.9
        
        # Reduce confidence for each false positive filtered
        confidence = base_confidence - (false_positives * 0.1)
        
        # Reduce confidence if scores are very inconsistent
        score_std = np.std(corner_scores)
        if score_std > 2.0:
            confidence -= 0.1
        
        return max(0.5, min(1.0, confidence))


# Integration function for existing backend
def analyze_corners_enhanced(image: np.ndarray, side: str = "front", debug: bool = False) -> Dict:
    """
    Drop-in replacement for your existing analyze_corners function
    
    Use this instead of the old corner analysis to get:
    - Reduced false positives
    - Better validation of detected damage
    - Contextual understanding of corner regions
    """
    detector = EnhancedCornerDetector(debug=debug)
    return detector.analyze_corners(image, side)


# Comparison function for testing
def compare_corner_detection(image_path: str) -> Dict:
    """
    Compare old vs new corner detection
    Useful for testing improvements
    """
    import sys
    sys.path.append('..')
    
    # Load image
    image = cv2.imread(image_path)
    
    # Old method (your current one)
    try:
        from analysis.corners import analyze_corners as analyze_corners_old
        old_result = analyze_corners_old(image, side="front")
    except ImportError:
        old_result = {"error": "Old method not available"}
    
    # New method
    new_result = analyze_corners_enhanced(image, side="front", debug=True)
    
    return {
        "old_method": old_result,
        "new_method": new_result,
        "improvements": {
            "false_positives_filtered": new_result.get("false_positives_filtered", 0),
            "score_difference": new_result["overall_grade"] - old_result.get("overall_grade", 0),
            "confidence": new_result["confidence"]
        }
    }


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        comparison = compare_corner_detection(image_path)
        
        print("Old method:")
        print(f"  Overall grade: {comparison['old_method'].get('overall_grade', 'N/A')}")
        print(f"  Scores: {comparison['old_method'].get('individual_scores', [])}")
        
        print("\nNew method:")
        print(f"  Overall grade: {comparison['new_method']['overall_grade']}")
        print(f"  Scores: {comparison['new_method']['individual_scores']}")
        print(f"  False positives filtered: {comparison['new_method']['false_positives_filtered']}")
        print(f"  Confidence: {comparison['new_method']['confidence']:.2f}")
        
        print("\nImprovement:")
        print(f"  Score difference: {comparison['improvements']['score_difference']:+.2f}")
    else:
        print("Usage: python enhanced_corner_detection.py <image_path>")
