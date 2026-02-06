"""
Debug utilities for visualizing analysis results.
"""
import cv2
import os
import numpy as np
from typing import Optional
from datetime import datetime


class DebugVisualizer:
    """Handles debug image output for analysis pipeline."""
    
    def __init__(self, session_id: str, enabled: bool = True):
        """
        Initialize debug visualizer.
        
        Args:
            session_id: Unique session identifier
            enabled: Whether to save debug images
        """
        self.session_id = session_id
        self.enabled = enabled
        self.debug_dir = "./debug"
        
        if enabled:
            os.makedirs(self.debug_dir, exist_ok=True)
    
    def save_image(self, image: np.ndarray, name: str) -> Optional[str]:
        """
        Save debug image with session prefix.
        
        Args:
            image: Image to save
            name: Descriptive name
            
        Returns:
            Path to saved image, or None if disabled
        """
        if not self.enabled:
            return None
        
        # Avoid timestamps in filenames to keep them consistent for a session if called multiple times?
        # Actually timestamps are good for sequence.
        timestamp = datetime.now().strftime("%H%M%S%f")[:9] # ms precision
        filename = f"{self.session_id}_{timestamp}_{name}.jpg"
        filepath = os.path.join(self.debug_dir, filename)
        
        cv2.imwrite(filepath, image)
        return filepath
    
    def draw_contours(
        self,
        image: np.ndarray,
        contours: list,
        name: str = "contours"
    ) -> Optional[str]:
        """Draw and save contours on image."""
        if not self.enabled:
            return None
        
        debug_img = image.copy()
        cv2.drawContours(debug_img, contours, -1, (0, 255, 0), 2)
        
        return self.save_image(debug_img, name)
    
    def draw_measurements(
        self,
        image: np.ndarray,
        measurements: dict,
        name: str = "measurements"
    ) -> Optional[str]:
        """Draw measurements on image."""
        if not self.enabled:
            return None
        
        debug_img = image.copy()
        y_offset = 30
        
        for key, value in measurements.items():
            text = f"{key}: {value}"
            cv2.putText(
                debug_img,
                text,
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )
            y_offset += 30
        
        return self.save_image(debug_img, name)
    
    def create_comparison_grid(
        self,
        images: list,
        labels: list,
        name: str = "comparison"
    ) -> Optional[str]:
        """Create side-by-side comparison of images."""
        if not self.enabled or len(images) == 0:
            return None
        
        # Resize all images to same height
        target_height = 400
        resized = []
        
        for img in images:
            h, w = img.shape[:2]
            new_w = int(w * target_height / h)
            resized.append(cv2.resize(img, (new_w, target_height)))
        
        # Add labels
        labeled = []
        for img, label in zip(resized, labels):
            img_copy = img.copy()
            cv2.putText(
                img_copy,
                label,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )
            labeled.append(img_copy)
        
        # Concatenate horizontally
        grid = np.hstack(labeled)
        
        return self.save_image(grid, name)
