"""
Corner Detection Module
Validates that detected damage is actually on the card, reducing false positives
from background bleed, glare, and non-damage patterns.
"""
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional


class CornerDetector:
    """
    Corner detection with false-positive reduction via contextual validation.
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
        Analyze card corners with false-positive filtering.

        Returns:
            {
                "corners": {"top_left": {"score": float}, ...},
                "individual_scores": [float, float, float, float],
                "overall_grade": float,
                "worst_corner": int,
                "confidence": float,
                "false_positives_filtered": int,
                "analysis_method": str
            }
        """
        h, w = image.shape[:2]

        if not self._is_card_shaped(w, h):
            return {
                "individual_scores": [5.0, 5.0, 5.0, 5.0],
                "corners": {
                    n: {"score": 5.0}
                    for n in ("top_left", "top_right", "bottom_right", "bottom_left")
                },
                "overall_grade": 5.0,
                "confidence": 0.3,
                "error": "Image not card-shaped — using conservative scores",
            }

        card_mask = self._detect_card_region(image)
        corner_regions = self._extract_validated_corners(image, card_mask)

        corner_scores = []
        false_positives = 0

        for i, (corner_img, corner_mask, is_valid) in enumerate(corner_regions):
            if not is_valid:
                corner_scores.append(5.0)
                false_positives += 1
                continue

            score, is_false_positive = self._analyze_single_corner(
                corner_img, corner_mask, corner_index=i
            )
            if is_false_positive:
                score = min(10.0, score + 2.0)
                false_positives += 1
            corner_scores.append(score)

        overall = self._calculate_overall_grade(corner_scores)
        worst_corner = int(np.argmin(corner_scores))
        confidence = self._calculate_confidence(corner_scores, false_positives)

        corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]
        corners_dict = {
            name: {"score": corner_scores[i]}
            for i, name in enumerate(corner_names)
            if i < len(corner_scores)
        }

        result = {
            "individual_scores": corner_scores,
            "corners": corners_dict,
            "overall_grade": overall,
            "worst_corner": worst_corner,
            "confidence": confidence,
            "false_positives_filtered": false_positives,
            "analysis_method": "validated_corners",
        }

        if self.debug:
            result["debug_images"] = self.debug_images

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_card_shaped(self, width: int, height: int) -> bool:
        aspect = width / height if height > 0 else 0
        return 0.6 < aspect < 0.85 or 1.18 < aspect < 1.67

    def _detect_card_region(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        border = int(min(h, w) * 0.05)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[border:h - border, border:w - border] = 255

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > 0.5 * (w * h):
                refined = np.zeros((h, w), dtype=np.uint8)
                cv2.drawContours(refined, [largest], -1, 255, -1)
                kernel = np.ones((3, 3), np.uint8)
                return cv2.erode(refined, kernel, iterations=1)

        return mask

    def _extract_validated_corners(
        self,
        image: np.ndarray,
        card_mask: np.ndarray,
    ) -> List[Tuple[np.ndarray, np.ndarray, bool]]:
        h, w = image.shape[:2]
        corner_size = int(min(h, w) * 0.08)

        positions = [
            (0, 0),
            (w - corner_size, 0),
            (w - corner_size, h - corner_size),
            (0, h - corner_size),
        ]

        regions = []
        for x, y in positions:
            corner_img = image[y:y + corner_size, x:x + corner_size].copy()
            corner_mask = card_mask[y:y + corner_size, x:x + corner_size].copy()
            valid_pixels = np.sum(corner_mask > 0)
            total_pixels = corner_size * corner_size
            is_valid = (valid_pixels / total_pixels) > 0.2
            regions.append((corner_img, corner_mask, is_valid))

        return regions

    def _analyze_single_corner(
        self,
        corner_img: np.ndarray,
        corner_mask: np.ndarray,
        corner_index: int,
    ) -> Tuple[float, bool]:
        hsv = cv2.cvtColor(corner_img, cv2.COLOR_BGR2HSV)
        white_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 180]),
            np.array([180, 40, 255]),
        )
        white_mask = cv2.bitwise_and(white_mask, corner_mask)

        white_pixels = np.sum(white_mask > 0)
        valid_area = max(1, np.sum(corner_mask > 0))
        white_pct = (white_pixels / valid_area) * 100.0

        is_false_positive = self._is_false_positive(
            corner_img, white_mask, corner_mask, corner_index
        )
        score = self._calculate_corner_score(white_pct)

        if self.debug:
            debug_img = corner_img.copy()
            debug_img[white_mask > 0] = [0, 0, 255]
            self.debug_images.append({
                f"corner_{corner_index}": debug_img,
                "white_pixels": int(white_pixels),
                "score": float(score),
                "is_false_positive": is_false_positive,
            })

        return score, is_false_positive

    def _is_false_positive(
        self,
        corner_img: np.ndarray,
        white_mask: np.ndarray,
        card_mask: np.ndarray,
        corner_index: int,
    ) -> bool:
        white_pixels = np.sum(white_mask > 0)
        if white_pixels < 10:
            return False

        if self._check_edge_whitening(white_mask, corner_index) > 0.7:
            return True

        if self._check_uniformity(white_mask) and white_pixels > 100:
            return True

        gray = cv2.cvtColor(corner_img, cv2.COLOR_BGR2GRAY)
        if np.mean(gray[white_mask > 0]) > 240:
            return True

        if not self._is_in_corner_zone(white_mask, corner_index):
            return True

        return False

    def _check_edge_whitening(self, white_mask: np.ndarray, corner_index: int) -> float:
        h, w = white_mask.shape
        edge_width = max(3, min(h, w) // 10)
        edge_mask = np.zeros_like(white_mask)

        if corner_index == 0:
            edge_mask[:edge_width, :] = 255
            edge_mask[:, :edge_width] = 255
        elif corner_index == 1:
            edge_mask[:edge_width, :] = 255
            edge_mask[:, -edge_width:] = 255
        elif corner_index == 2:
            edge_mask[-edge_width:, :] = 255
            edge_mask[:, -edge_width:] = 255
        else:
            edge_mask[-edge_width:, :] = 255
            edge_mask[:, :edge_width] = 255

        edge_white = np.sum(cv2.bitwise_and(white_mask, edge_mask) > 0)
        total_white = np.sum(white_mask > 0)
        return edge_white / total_white if total_white > 0 else 0.0

    def _check_uniformity(self, white_mask: np.ndarray) -> bool:
        if np.sum(white_mask > 0) < 50:
            return False
        contours, _ = cv2.findContours(
            white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return False
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area > 0.3 * white_mask.size:
            _, _, w, h = cv2.boundingRect(largest)
            aspect = w / h if h > 0 else 0
            if 0.8 < aspect < 1.2:  # only square blobs are plausibly uniform material
                return True
        return False

    def _is_in_corner_zone(self, white_mask: np.ndarray, corner_index: int) -> bool:
        h, w = white_mask.shape
        zone_size = int(min(h, w) * 0.4)
        zone_mask = np.zeros_like(white_mask)

        if corner_index == 0:
            zone_mask[:zone_size, :zone_size] = 255
        elif corner_index == 1:
            zone_mask[:zone_size, -zone_size:] = 255
        elif corner_index == 2:
            zone_mask[-zone_size:, -zone_size:] = 255
        else:
            zone_mask[-zone_size:, :zone_size] = 255

        zone_white = np.sum(cv2.bitwise_and(white_mask, zone_mask) > 0)
        total_white = np.sum(white_mask > 0)
        return (zone_white / total_white) > 0.6 if total_white > 0 else True

    def _calculate_corner_score(self, white_pct: float) -> float:
        if white_pct < 0.5:
            return 10.0
        elif white_pct < 1.5:
            return 10.0 - (white_pct - 0.5) * 0.5
        elif white_pct < 3.0:
            return 9.5 - (white_pct - 1.5) * (0.5 / 1.5)
        elif white_pct < 6.0:
            return 9.0 - (white_pct - 3.0) * (1.0 / 3.0)
        elif white_pct < 12.0:
            return 8.0 - (white_pct - 6.0) * (1.0 / 6.0)
        elif white_pct < 20.0:
            return 7.0 - (white_pct - 12.0) * (1.0 / 8.0)
        elif white_pct < 35.0:
            return 6.0 - (white_pct - 20.0) * (2.0 / 15.0)
        elif white_pct < 50.0:
            return 4.0 - (white_pct - 35.0) * (2.0 / 15.0)
        else:
            return max(1.0, 2.0 - (white_pct - 50.0) * 0.02)

    def _calculate_overall_grade(self, corner_scores: List[float]) -> float:
        avg_score = float(np.mean(corner_scores))
        min_score = min(corner_scores)
        overall = 0.7 * avg_score + 0.3 * min_score
        return max(1.0, round(overall, 1))

    def _calculate_confidence(
        self, corner_scores: List[float], false_positives: int
    ) -> float:
        confidence = 0.9 - (false_positives * 0.1)
        if float(np.std(corner_scores)) > 2.0:
            confidence -= 0.1
        return max(0.3, min(1.0, confidence))


def analyze_corners(image: np.ndarray, side: str = "front", debug: bool = False) -> Dict:
    """Analyze card corners. Drop-in entry point for the grading pipeline."""
    return CornerDetector(debug=debug).analyze_corners(image, side)
