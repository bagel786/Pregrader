from typing import Dict, Any, List, Optional
import math

class GradingEngine:
    """
    Implements the grading logic for Pokemon cards.
    Aggregates sub-scores and maps to a final grade.
    """
    
    # Grading Scale Mapping - Even more lenient
    GRADE_BRACKETS = [
        (9.2, "10"),
        (8.5, "9"),
        (7.5, "8"),
        (6.8, "7"),
        (6.0, "6"),
        (5.0, "5"),
        (4.0, "4"),
        (3.0, "3"),
        (2.0, "2"),
        (1.0, "1"),
        (0.0, "0")
    ]
    
    @staticmethod
    def calculate_grade(
        centering_score: float,
        corners_data: Dict[str, Any],
        edges_data: Dict[str, Any],
        surface_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculates the final grade based on sub-scores and more lenient capping rules.
        """
        
        explanations = []
        
        # 1. Extract Sub-scores
        score_centering = centering_score
        if score_centering < 9.5:
            explanations.append(f"Centering score {score_centering}: Minor centering issues detected.")
        
        # Corners: Avg of 4 corners
        corners_scores = [c["score"] for c in corners_data["corners"].values()]
        score_corners = sum(corners_scores) / 4.0
        min_corner = min(corners_scores)
        
        # Edges: Avg of 4 edges
        edges_scores = [e["score"] for e in edges_data["edges"].values()]
        score_edges = sum(edges_scores) / 4.0
        
        # Surface: Provided score
        score_surface = surface_data["score"]
        
        # 2. Weighted Calculation - Adjusted weights to be less harsh
        # Weights: Centering 25%, Corners 25%, Edges 25%, Surface 25%
        weighted_score = (
            score_centering * 0.25 +
            score_corners * 0.25 +
            score_edges * 0.25 +
            score_surface * 0.25
        )
        
        # 3. Apply More Lenient Caps
        caps = []
        max_grade = 10.0
        
        # Cap Rule: Any single corner <= 5.0 -> Max 6 (was 6.0 -> Max 7)
        if min_corner <= 5.0:
            max_grade = min(max_grade, 6.0)
            msg = "Max Grade capped at 6 due to severe corner damage (score <= 5.0)."
            caps.append(msg)
            explanations.append(msg)
        elif min_corner <= 6.5:
            max_grade = min(max_grade, 7.0)
            msg = "Max Grade capped at 7 due to significant corner damage (score <= 6.5)."
            caps.append(msg)
            explanations.append(msg)
            
        # Cap Rule: Whitening on all 4 edges -> Max 6 (was > 3 edges -> Max 7)
        edges_with_significant_wear = len([s for s in edges_scores if s < 7.0])
        if edges_with_significant_wear >= 4:
            max_grade = min(max_grade, 6.0)
            msg = "Max Grade capped at 6 due to significant wear on all edges."
            caps.append(msg)
            explanations.append(msg)
        elif edges_with_significant_wear > 2:
            max_grade = min(max_grade, 7.0)
            msg = "Max Grade capped at 7 due to wear on multiple edges."
            caps.append(msg)
            explanations.append(msg)
            
        # Cap Rule: Major surface damage -> Max 4 (was Max 5)
        if surface_data.get("major_damage_detected", False):
            max_grade = min(max_grade, 4.0)
            msg = "Max Grade capped at 4 due to detected crease, dent, or major surface damage."
            caps.append(msg)
            explanations.append(msg)
            
        # Final Score with Cap - Add a bigger boost to account for conservative analysis
        final_score = min(weighted_score * 1.25, max_grade)  # 25% boost instead of 10%
        final_score = min(final_score, 10.0)  # Cap at 10
        final_score = round(final_score, 1)
        
        # 4. Map to Grade Label
        grade_label = "0"
        for threshold, label in GradingEngine.GRADE_BRACKETS:
            if final_score >= threshold:
                grade_label = label
                break
        
        # 5. Confidence - More optimistic
        confidence = "High"
        if final_score < 5 or surface_data.get("major_damage_detected", False):
             confidence = "Medium" # Harder to gauge severity of damage purely via CV
        elif final_score < 7:
             confidence = "Medium"
        
        return {
            "final_score": final_score,
            "psa_estimate": grade_label,
            "sub_scores": {
                "centering": round(score_centering, 1),
                "corners": round(score_corners, 1),
                "edges": round(score_edges, 1),
                "surface": round(score_surface, 1)
            },
            "explanations": explanations,
            "caps_applied": caps,
            "confidence": confidence,
            "grade_range": f"{max(1, int(grade_label)-1)}-{grade_label}" if float(grade_label) > 1 else "1"
        }
