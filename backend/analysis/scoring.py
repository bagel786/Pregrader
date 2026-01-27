from typing import Dict, Any, List, Optional
import math

class GradingEngine:
    """
    Implements the grading logic for Pokemon cards.
    Aggregates sub-scores and maps to a final grade.
    """
    
    # Grading Scale Mapping
    GRADE_BRACKETS = [
        (9.6, "10"),
        (9.0, "9"),
        (8.5, "8"),
        (8.0, "7"),
        (7.0, "6"),
        (6.0, "5"),
        (5.0, "4"),
        (4.0, "3"),
        (3.0, "2"),
        (2.0, "1"),
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
        Calculates the final grade based on sub-scores and strict capping rules.
        """
        
        explanations = []
        
        # 1. Extract Sub-scores
        score_centering = centering_score
        if score_centering < 10:
            explanations.append(f"Centering score {score_centering}: Ratio deviations detected.")
        
        # Corners: Avg of 4 corners
        corners_scores = [c["score"] for c in corners_data["corners"].values()]
        score_corners = sum(corners_scores) / 4.0
        min_corner = min(corners_scores)
        
        # Edges: Avg of 4 edges
        edges_scores = [e["score"] for e in edges_data["edges"].values()]
        score_edges = sum(edges_scores) / 4.0
        
        # Surface: Provided score
        score_surface = surface_data["score"]
        
        # 2. Weighted Calculation
        # Weights: Centering 30%, Corners 25%, Edges 25%, Surface 20%
        weighted_score = (
            score_centering * 0.30 +
            score_corners * 0.25 +
            score_edges * 0.25 +
            score_surface * 0.20
        )
        
        # 3. Apply Caps
        caps = []
        max_grade = 10.0
        
        # Cap Rule: Any single corner <= 7.5 -> Max 8
        if min_corner <= 7.5:
            max_grade = min(max_grade, 8.0)
            msg = "Max Grade capped at 8 due to significant corner damage (score <= 7.5)."
            caps.append(msg)
            explanations.append(msg)
            
        # Cap Rule: Whitening on > 2 edges -> Max 8
        edges_with_wear = len([s for s in edges_scores if s < 9.0])
        if edges_with_wear > 2:
            max_grade = min(max_grade, 8.0)
            msg = "Max Grade capped at 8 due to wear on more than 2 edges."
            caps.append(msg)
            explanations.append(msg)
            
        # Cap Rule: Crease or Dent -> Max 6
        if surface_data.get("major_damage_detected", False):
            max_grade = min(max_grade, 6.0)
            msg = "Max Grade capped at 6 due to detected crease, dent, or major surface damage."
            caps.append(msg)
            explanations.append(msg)
            
        # Final Score with Cap
        final_score = min(weighted_score, max_grade)
        final_score = round(final_score, 1)
        
        # 4. Map to Grade Label
        grade_label = "0"
        for threshold, label in GradingEngine.GRADE_BRACKETS:
            if final_score >= threshold:
                grade_label = label
                break
        
        # 5. Confidence
        confidence = "High"
        if final_score < 6 or surface_data.get("major_damage_detected", False):
             confidence = "Medium" # Harder to gauge severity of damage purely via CV
        
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
