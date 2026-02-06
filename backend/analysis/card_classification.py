"""
Card type classification for adaptive analysis pipelines.
Detects standard, full-art, VMAX/VSTAR, trainer, and special card types.
"""
import cv2
import numpy as np
from enum import Enum
from typing import Tuple


class CardType(Enum):
    """Pokemon card type categories."""
    STANDARD = "standard"          # Regular Pokemon card with border
    FULL_ART = "full_art"          # Full-art Pokemon/Trainers
    VMAX_VSTAR = "vmax_vstar"      # Oversized artwork cards
    TRAINER = "trainer"            # Trainer/Supporter cards
    SPECIAL = "special"            # Rainbow rare, gold cards, etc.
    UNKNOWN = "unknown"


class CardClassifier:
    """
    Classifies Pokemon card type for routing to appropriate analysis pipeline.
    """
    
    def __init__(self, card_image: np.ndarray):
        """
        Initialize classifier with card image.
        
        Args:
            card_image: BGR image of the card (preferably perspective-corrected)
        """
        self.image = card_image
        self.height, self.width = card_image.shape[:2]
    
    def classify(self) -> Tuple[CardType, float]:
        """
        Classify the card type.
        
        Returns:
            Tuple of (CardType, confidence: 0.0-1.0)
        """
        # Strategy 1: Border Detection
        border_percentage = self.detect_border_percentage()
        
        if border_percentage > 8.0:
            # Standard cards have thick yellow/colored borders
            return CardType.STANDARD, 0.9
        
        elif border_percentage < 2.0:
            # Likely full-art or special
            has_texture = self.detect_texture_pattern()
            
            if has_texture:
                # Check for VMAX characteristics
                if self.has_oversized_artwork():
                    return CardType.VMAX_VSTAR, 0.85
                else:
                    return CardType.FULL_ART, 0.85
            else:
                # Might be trainer or basic energy
                return CardType.TRAINER, 0.75
        
        # Medium border - could be special edition
        if self.detect_special_finish():
            return CardType.SPECIAL, 0.80
        
        return CardType.UNKNOWN, 0.5
    
    def detect_border_percentage(self) -> float:
        """
        Calculate what percentage of card perimeter has saturated colored border.
        Standard Pokemon cards have ~10%+ border with distinct color.
        
        Returns:
            Percentage of border that is saturated (0-100)
        """
        # Create border region mask (outer 5% of card)
        border_width = int(self.width * 0.05)
        border_height = int(self.height * 0.05)
        
        mask = np.zeros((self.height, self.width), dtype=np.uint8)
        
        # Top edge
        mask[:border_height, :] = 255
        # Bottom edge
        mask[self.height - border_height:, :] = 255
        # Left edge
        mask[:, :border_width] = 255
        # Right edge
        mask[:, self.width - border_width:] = 255
        
        # Check for saturated colors (borders typically have high saturation)
        hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        
        # Count saturated pixels in border region
        border_pixels = cv2.countNonZero(mask)
        saturated_in_border = cv2.countNonZero(
            cv2.bitwise_and((saturation > 80).astype(np.uint8) * 255, mask)
        )
        
        if border_pixels == 0:
            return 0.0
        
        return (saturated_in_border / border_pixels) * 100
    
    def detect_texture_pattern(self) -> bool:
        """
        Detect holographic/textured patterns using frequency analysis.
        
        Returns:
            True if high-frequency texture patterns detected
        """
        gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        
        # Use Fourier Transform to detect repeating patterns
        f_transform = np.fft.fft2(gray)
        f_shift = np.fft.fftshift(f_transform)
        magnitude = np.abs(f_shift)
        
        # Calculate energy in different frequency bands
        center_y, center_x = self.height // 2, self.width // 2
        
        # High-frequency region (outer ring)
        y_quarter = self.height // 4
        x_quarter = self.width // 4
        
        high_freq_region = magnitude.copy()
        high_freq_region[center_y - y_quarter:center_y + y_quarter,
                        center_x - x_quarter:center_x + x_quarter] = 0
        
        high_freq_energy = np.sum(high_freq_region)
        total_energy = np.sum(magnitude)
        
        if total_energy == 0:
            return False
        
        return (high_freq_energy / total_energy) > 0.15
    
    def has_oversized_artwork(self) -> bool:
        """
        Check if artwork extends beyond normal bounds (VMAX/VSTAR pattern).
        These cards typically have Pokemon extending to edges.
        
        Returns:
            True if oversized artwork detected
        """
        # Check top 20% of card for high color variance
        # VMAX cards have complex artwork at the very top
        top_region = self.image[:int(self.height * 0.2), :]
        hsv_roi = cv2.cvtColor(top_region, cv2.COLOR_BGR2HSV)
        
        # High hue variance indicates complex multi-colored artwork
        hue_variance = np.var(hsv_roi[:, :, 0])
        
        return hue_variance > 800
    
    def detect_special_finish(self) -> bool:
        """
        Detect special finishes like rainbow rare or gold cards.
        These have distinctive color patterns.
        
        Returns:
            True if special finish detected
        """
        hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)
        
        # Rainbow cards have very high saturation variance
        saturation = hsv[:, :, 1]
        sat_variance = np.var(saturation)
        
        # Gold cards have specific hue range (yellow/gold)
        hue = hsv[:, :, 0]
        gold_mask = cv2.inRange(hue, 15, 35)  # Gold/yellow hue range
        gold_percentage = cv2.countNonZero(gold_mask) / gold_mask.size
        
        # High saturation variance OR mostly gold = special
        return sat_variance > 2000 or gold_percentage > 0.40


def classify_card(image: np.ndarray) -> dict:
    """
    Convenience function to classify a card image.
    
    Args:
        image: BGR card image
        
    Returns:
        Dict with card_type, confidence, and analysis recommendations
    """
    classifier = CardClassifier(image)
    card_type, confidence = classifier.classify()
    
    # Determine analysis recommendations based on type
    recommendations = {
        CardType.STANDARD: {
            "centering_method": "border_based",
            "surface_sensitivity": "normal",
            "notes": "Standard card - full analysis available"
        },
        CardType.FULL_ART: {
            "centering_method": "artwork_based",
            "surface_sensitivity": "reduced",  # Holo patterns
            "notes": "Full-art card - centering uses artwork bounds"
        },
        CardType.VMAX_VSTAR: {
            "centering_method": "artwork_based",
            "surface_sensitivity": "reduced",
            "notes": "VMAX/VSTAR card - oversized artwork detected"
        },
        CardType.TRAINER: {
            "centering_method": "text_based",
            "surface_sensitivity": "normal",
            "notes": "Trainer card - centering uses text box"
        },
        CardType.SPECIAL: {
            "centering_method": "border_based",
            "surface_sensitivity": "reduced",
            "notes": "Special finish card - rainbow/gold detected"
        },
        CardType.UNKNOWN: {
            "centering_method": "fallback",
            "surface_sensitivity": "normal",
            "notes": "Card type unclear - using default analysis"
        }
    }
    
    return {
        "card_type": card_type.value,
        "confidence": confidence,
        "analysis_config": recommendations[card_type]
    }
