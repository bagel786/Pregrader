from typing import Dict, Any, List, Optional
import math


class GradingResult:
    """Data class for grading results with confidence tracking."""
    def __init__(self):
        self.final_score = 0.0
        self.psa_estimate = "0"
        self.centering_score = 0.0
        self.centering_confidence = 0.0
        self.corners_score = 0.0
        self.corners_confidence = 0.0
        self.edges_score = 0.0
        self.edges_confidence = 0.0
        self.surface_score = 0.0
        self.surface_confidence = 0.0
        self.overall_confidence = 0.0
        self.explanations = []
        self.recommendations = []


class GradingEngine:
    """
    Implements the grading logic for Pokemon cards.
    Aggregates sub-scores and maps to a final grade.
    """
    
    # Recalibrated Grade Brackets (accounting for removed 1.25x boost)
    GRADE_BRACKETS = [
        (9.5, "10"),   # Was 9.2 - perfect cards
        (9.0, "9"),    # Was 8.5 - near mint
        (8.0, "8"),    # Was 7.5 - excellent
        (7.0, "7"),    # Was 6.8 - very good
        (6.0, "6"),    # Same - good
        (5.0, "5"),    # Same - fair
        (4.0, "4"),    # Same - poor
        (3.0, "3"),    # Same - very poor
        (2.0, "2"),    # Same - damaged
        (1.0, "1"),    # Same - heavily damaged
        (0.0, "0")     # Ungrade able
    ]
    
    @staticmethod
    def _calculate_grade_range(final_score: float, grade_label: str) -> str:
        """
        Return a grade range string when the score is near a PSA grade boundary.

        A score within 0.3 of a boundary (e.g. 9.3 near the 9.5 threshold)
        indicates measurement uncertainty; the true grade could be one step higher.
        This is most important near the PSA 9/10 boundary where value diverges sharply.
        """
        BOUNDARY_MARGIN = 0.3
        brackets = GradingEngine.GRADE_BRACKETS

        # Find the threshold that separates current grade from the grade above
        current_idx = next(
            (i for i, (thresh, lbl) in enumerate(brackets) if lbl == grade_label),
            None
        )

        if current_idx is not None and current_idx > 0:
            upper_threshold, upper_label = brackets[current_idx - 1]
            if final_score >= upper_threshold - BOUNDARY_MARGIN:
                return f"{grade_label}-{upper_label}"

        return grade_label

    @staticmethod
    def generate_explanations(result: GradingResult) -> List[str]:
        """Generate human-readable explanations for the grade."""
        explanations = []
        
        # Centering
        if result.centering_score >= 9.5:
            explanations.append("✓ Excellent centering")
        elif result.centering_score >= 8.5:
            explanations.append("⚠ Slightly off-center")
        else:
            explanations.append("✗ Poor centering - major grade impact")
        
        # Corners
        if result.corners_score >= 9.5:
            explanations.append("✓ Sharp corners")
        elif result.corners_score >= 8.0:
            explanations.append("⚠ Minor corner wear detected")
        else:
            explanations.append("✗ Significant corner damage")
        
        # Edges
        if result.edges_score >= 9.5:
            explanations.append("✓ Clean edges")
        elif result.edges_score >= 8.0:
            explanations.append("⚠ Minor edge wear")
        else:
            explanations.append("✗ Multiple edges show wear")
        
        # Surface
        if result.surface_score >= 9.5:
            explanations.append("✓ Pristine surface")
        elif result.surface_score >= 8.0:
            explanations.append("⚠ Minor surface imperfections")
        elif result.surface_score >= 6.0:
            explanations.append("⚠ Visible scratches detected")
        else:
            explanations.append("✗ Major surface damage (creases/dents)")
        
        # Confidence warning
        if result.overall_confidence < 0.6:
            explanations.append("⚠ Low confidence - consider retaking photo with better lighting")
        
        return explanations
    
    @staticmethod
    def generate_recommendations(result: GradingResult) -> List[str]:
        """Generate recommendations for improving image quality."""
        recommendations = []
        
        if result.overall_confidence < 0.7:
            if result.centering_confidence < 0.7:
                recommendations.append("Improve lighting to better detect card borders")
            if result.corners_confidence < 0.7:
                recommendations.append("Ensure all four corners are clearly visible")
            if result.edges_confidence < 0.7:
                recommendations.append("Make sure card edges are in focus")
            if result.surface_confidence < 0.7:
                recommendations.append("Reduce glare by adjusting lighting angle")
        
        return recommendations
    
    @staticmethod
    def calculate_grade(
        centering_score: float,
        corners_data: Dict[str, Any],
        edges_data: Dict[str, Any],
        surface_data: Dict[str, Any],
        centering_confidence: float = 0.5,
        quality_assessment: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Calculates the final grade with proper calibration and confidence tracking.
        NO MORE 1.25x BOOST - thresholds are properly calibrated.
        """
        result = GradingResult()
        
        # 1. Extract Sub-scores
        result.centering_score = centering_score
        result.centering_confidence = centering_confidence  # Propagated from centering.py
        
        # Corners: Use overall_grade if available, otherwise calculate from individual scores
        if "overall_grade" in corners_data:
            result.corners_score = corners_data["overall_grade"]
            result.corners_confidence = corners_data.get("confidence", 0.5)
        else:
            corners_scores = [c["score"] for c in corners_data["corners"].values()]
            result.corners_score = sum(corners_scores) / len(corners_scores) if corners_scores else 5.0
            result.corners_confidence = 0.5
        
        # Extract min corner score - handle both standard dict and enhanced list formats
        if corners_data.get("corners"):
            min_corner = min(c["score"] for c in corners_data["corners"].values())
        elif corners_data.get("individual_scores"):
            min_corner = min(corners_data["individual_scores"])
        else:
            min_corner = result.corners_score
        
        # Edges: Use overall_grade if available
        if "overall_grade" in edges_data:
            result.edges_score = edges_data["overall_grade"]
            result.edges_confidence = edges_data.get("confidence", 0.5)
        else:
            edges_scores = [e["score"] for e in edges_data["edges"].values()]
            result.edges_score = sum(edges_scores) / len(edges_scores) if edges_scores else 5.0
            result.edges_confidence = 0.5
        
        edges_scores = [e["score"] for e in edges_data["edges"].values()] if edges_data.get("edges") else [result.edges_score]
        
        # Surface: Provided score
        result.surface_score = surface_data["score"]
        result.surface_confidence = surface_data.get("confidence", 0.5)
        
        # 2. PSA-aligned Weighted Calculation
        # PSA weights corners and edges more heavily than centering and surface
        weighted_score = (
            result.centering_score * 0.20 +
            result.corners_score * 0.30 +
            result.edges_score * 0.30 +
            result.surface_score * 0.20
        )
        
        # 3. Damage penalties — only for damage not already captured by component scores.
        damage_penalty = 0.0

        # Surface damage penalty — creases/dents (additive damage not in scratch score)
        if surface_data.get("major_damage_detected", False):
            damage_penalty += 1.0  # Crease/dent detected

        # Apply penalty
        final_score = weighted_score - damage_penalty

        # Floor: final score cannot be more than 0.5 below the worst individual corner.
        # Corner scores already encode whitening damage; this prevents other components
        # from dragging the grade below what the worst corner warrants.
        final_score = max(final_score, min_corner - 0.5)

        # NO 1.25x BOOST - properly calibrated thresholds
        final_score = max(min(final_score, 10.0), 1.0)
        final_score = round(final_score, 1)
        
        result.final_score = final_score
        
        # 4. Map to Grade Label
        grade_label = "0"
        for threshold, label in GradingEngine.GRADE_BRACKETS:
            if final_score >= threshold:
                grade_label = label
                break
        
        result.psa_estimate = grade_label
        
        # 4b. Apply Claude Vision quality signal multipliers to per-component confidence.
        # These signals are discarded after detection otherwise; mapping them to
        # confidence adjustments propagates what the AI observed about image quality.
        if quality_assessment:
            blur = quality_assessment.get("blur", "sharp")
            lighting = quality_assessment.get("lighting", "good")
            angle = quality_assessment.get("angle", "straight")

            if blur == "heavy":
                result.centering_confidence *= 0.70
                result.corners_confidence *= 0.70
                result.edges_confidence *= 0.70
                result.surface_confidence *= 0.70
            elif blur == "slight":
                result.centering_confidence *= 0.85
                result.corners_confidence *= 0.85
                result.edges_confidence *= 0.85
                result.surface_confidence *= 0.85

            if lighting == "poor":
                result.edges_confidence *= 0.75
                result.surface_confidence *= 0.75
            elif lighting == "glare":
                result.surface_confidence *= 0.70

            if angle == "heavy":
                result.centering_confidence *= 0.60
            elif angle == "slight":
                result.centering_confidence *= 0.80

        # 5. Calculate Overall Confidence
        # Confidence weights are decoupled from score weights — they reflect how
        # reliably each component can be measured, not how much it affects the grade.
        # Surface has high measurement variance (lighting, holo, glare) → lower weight.
        # Corners whitening in a well-defined ROI is geometrically reliable → higher weight.
        # Centering measurement noise is moderate → slightly lower than corners.
        result.overall_confidence = (
            result.centering_confidence * 0.15 +
            result.corners_confidence * 0.35 +
            result.edges_confidence * 0.30 +
            result.surface_confidence * 0.20
        )
        
        # Determine confidence level
        if result.overall_confidence >= 0.8:
            confidence_level = "High"
        elif result.overall_confidence >= 0.6:
            confidence_level = "Medium"
        else:
            confidence_level = "Low"
        
        # 6. Determine grading status based on confidence
        if result.overall_confidence < 0.4:
            grading_status = "refused"
            grading_status_message = "Unable to grade — image quality too low for reliable analysis. Please retake photos with better lighting and ensure the card fills the frame."
        elif result.overall_confidence < 0.6:
            grading_status = "low_confidence"
            grading_status_message = "Grade provided with low confidence — consider retaking photos for a more accurate result."
        else:
            grading_status = "success"
            grading_status_message = None

        # 7. Generate explanations and recommendations
        result.explanations = GradingEngine.generate_explanations(result)
        result.recommendations = GradingEngine.generate_recommendations(result)

        return {
            "final_score": result.final_score,
            "psa_estimate": result.psa_estimate,
            "sub_scores": {
                "centering": round(result.centering_score, 1),
                "corners": round(result.corners_score, 1),
                "edges": round(result.edges_score, 1),
                "surface": round(result.surface_score, 1)
            },
            "confidence": {
                "overall": round(result.overall_confidence, 2),
                "level": confidence_level,
                "centering": round(result.centering_confidence, 2),
                "corners": round(result.corners_confidence, 2),
                "edges": round(result.edges_confidence, 2),
                "surface": round(result.surface_confidence, 2)
            },
            "grading_status": grading_status,
            "grading_status_message": grading_status_message,
            "explanations": result.explanations,
            "recommendations": result.recommendations,
            "grade_range": GradingEngine._calculate_grade_range(final_score, grade_label)
        }
