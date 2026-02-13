"""
Combined front + back card grading logic.
Combines analysis from both sides using conservative (worst-case) approach.
"""
import cv2
import numpy as np
from typing import Dict, Optional, Tuple
from pathlib import Path

from analysis.centering import calculate_centering_ratios
from analysis.corners import analyze_corner_wear
from analysis.edges import analyze_edge_wear, detect_card_side
from analysis.surface import analyze_surface_damage
from analysis.scoring import GradingEngine


def analyze_single_side(
    image_path: str,
    side: str = "front",
    debug_output_dir: Optional[Path] = None
) -> Dict:
    """
    Run full analysis on a single card side.
    Sequential processing to minimize memory usage.
    
    Args:
        image_path: Path to card image
        side: "front" or "back"
        debug_output_dir: Optional directory for debug images
        
    Returns:
        Dict with all analysis results for this side
    """
    debug_suffix = f"_{side}_" if debug_output_dir else None
    
    results = {
        "side": side,
        "detected_as": None,
        "centering": None,
        "corners": None,
        "edges": None,
        "surface": None,
        "errors": []
    }
    
    # Load image once and reuse
    image = cv2.imread(image_path)
    if image is None:
        results["errors"].append("Failed to load image")
        return results
    
    # Auto-detect front vs back
    detected_side, side_confidence = detect_card_side(image)
    results["detected_as"] = detected_side
    results["side_detection_confidence"] = side_confidence
    
    # Centering: only on front (or if user said front)
    if side == "front" or detected_side == "front":
        try:
            centering_path = None
            if debug_output_dir:
                centering_path = str(debug_output_dir / f"{side}_centering.jpg")
            results["centering"] = calculate_centering_ratios(image_path, debug_output_path=centering_path)
        except Exception as e:
            results["errors"].append(f"Centering failed: {str(e)}")
            results["centering"] = {"error": str(e), "grade_estimate": 5.0}
    
    # Corners
    try:
        results["corners"] = analyze_corner_wear(image_path)
    except Exception as e:
        results["errors"].append(f"Corners failed: {str(e)}")
        results["corners"] = {"error": str(e)}
    
    # Edges
    try:
        edges_path = None
        if debug_output_dir:
            edges_path = str(debug_output_dir / f"{side}_edges.jpg")
        results["edges"] = analyze_edge_wear(image_path, debug_output_path=edges_path)
    except Exception as e:
        results["errors"].append(f"Edges failed: {str(e)}")
        results["edges"] = {"error": str(e)}
    
    # Surface
    try:
        results["surface"] = analyze_surface_damage(image_path)
    except Exception as e:
        results["errors"].append(f"Surface failed: {str(e)}")
        results["surface"] = {"error": str(e)}
    
    return results


def combine_front_back_analysis(
    front_analysis: Dict,
    back_analysis: Dict
) -> Dict:
    """
    Combine front and back analysis using conservative approach.
    
    Strategy:
    - Centering: Front only (back centering not meaningful)
    - Surface: Worst of front/back scores
    - Corners: Average of all 8 corners
    - Edges: Worst of front/back scores
    
    Args:
        front_analysis: Results from analyze_single_side("front")
        back_analysis: Results from analyze_single_side("back")
        
    Returns:
        Dict with combined analysis and final grade
    """
    combined = {
        "analysis_type": "combined_front_back",
        "centering": None,
        "corners": None,
        "edges": None,
        "surface": None,
        "warnings": []
    }
    
    # 1. CENTERING - Front only
    if front_analysis.get("centering") and "error" not in front_analysis["centering"]:
        combined["centering"] = front_analysis["centering"]
    else:
        combined["centering"] = {"grade_estimate": 5.0, "error": "Could not analyze centering"}
        combined["warnings"].append("Centering could not be analyzed")
    
    # 2. CORNERS - Worst-case biased blend (70% worst side, 30% better side)
    front_corners = front_analysis.get("corners", {})
    back_corners = back_analysis.get("corners", {})
    
    all_corner_scores = []
    combined_corners = {"corners": {}}
    front_corner_scores = []
    back_corner_scores = []
    
    for side_name, side_corners, side_list in [
        ("front", front_corners, front_corner_scores),
        ("back", back_corners, back_corner_scores)
    ]:
        if "corners" in side_corners:
            for corner_name, corner_data in side_corners["corners"].items():
                key = f"{side_name}_{corner_name}"
                combined_corners["corners"][key] = corner_data
                score = corner_data.get("score", 5.0)
                all_corner_scores.append(score)
                side_list.append(score)
    
    if front_corner_scores and back_corner_scores:
        # 70% worst side / 30% better side
        front_avg = sum(front_corner_scores) / len(front_corner_scores)
        back_avg = sum(back_corner_scores) / len(back_corner_scores)
        worse = min(front_avg, back_avg)
        better = max(front_avg, back_avg)
        combined_corners["overall_grade"] = round(worse * 0.7 + better * 0.3, 1)
    elif all_corner_scores:
        combined_corners["overall_grade"] = round(sum(all_corner_scores) / len(all_corner_scores), 1)
    else:
        combined_corners["overall_grade"] = 5.0
        combined["warnings"].append("Corner analysis incomplete")
    
    combined["corners"] = combined_corners
    
    # 3. EDGES - Worst-case biased blend (70% worst side, 30% better side)
    front_edges = front_analysis.get("edges", {})
    back_edges = back_analysis.get("edges", {})
    
    front_edge_score = front_edges.get("score", front_edges.get("grade_estimate", 10.0))
    back_edge_score = back_edges.get("score", back_edges.get("grade_estimate", 10.0))
    
    worse_edge = min(front_edge_score, back_edge_score)
    better_edge = max(front_edge_score, back_edge_score)
    blended_edge_score = round(worse_edge * 0.7 + better_edge * 0.3, 1)
    
    if back_edge_score < front_edge_score:
        combined["edges"] = back_edges.copy()
        combined["edges"]["source"] = "back"
    else:
        combined["edges"] = front_edges.copy()
        combined["edges"]["source"] = "front"
    
    # Override the score with the blended value
    combined["edges"]["score"] = blended_edge_score
    combined["edges"]["overall_grade"] = blended_edge_score
    
    # 4. SURFACE - Worst case
    front_surface = front_analysis.get("surface", {}).get("surface", {})
    back_surface = back_analysis.get("surface", {}).get("surface", {})
    
    front_surface_score = front_surface.get("score", 10.0)
    back_surface_score = back_surface.get("score", 10.0)
    
    if back_surface_score < front_surface_score:
        combined["surface"] = {"surface": back_surface}
        combined["surface"]["source"] = "back"
    else:
        combined["surface"] = {"surface": front_surface}
        combined["surface"]["source"] = "front"
    
    # Calculate final grade
    try:
        grading_result = GradingEngine.calculate_grade(
            centering_score=combined["centering"].get("grade_estimate", 5.0),
            corners_data=combined["corners"],
            edges_data=combined["edges"],
            surface_data=combined["surface"].get("surface", {"score": 5.0})
        )
        combined["grade"] = grading_result
    except Exception as e:
        combined["grade"] = {
            "error": str(e),
            "psa_estimate": "?",
            "final_score": 0
        }
        combined["warnings"].append(f"Grading calculation failed: {str(e)}")
    
    return combined


def grade_card_session(
    front_path: str,
    back_path: Optional[str] = None,
    debug_output_dir: Optional[Path] = None
) -> Tuple[Dict, Dict]:
    """
    Convenience function to grade a card with front and optional back.
    
    Args:
        front_path: Path to front image
        back_path: Optional path to back image
        debug_output_dir: Optional directory for debug images
        
    Returns:
        Tuple of (combined_result, individual_sides_dict)
    """
    front_analysis = analyze_single_side(front_path, "front", debug_output_dir)
    
    if back_path:
        back_analysis = analyze_single_side(back_path, "back", debug_output_dir)
        combined = combine_front_back_analysis(front_analysis, back_analysis)
    else:
        # Single-side grading
        combined = {
            "analysis_type": "front_only",
            "centering": front_analysis.get("centering"),
            "corners": front_analysis.get("corners"),
            "edges": front_analysis.get("edges"),
            "surface": front_analysis.get("surface"),
            "warnings": ["Back not provided - single-side analysis"]
        }
        
        # Calculate grade
        try:
            grading_result = GradingEngine.calculate_grade(
                centering_score=combined["centering"].get("grade_estimate", 5.0) if combined["centering"] else 5.0,
                corners_data=combined["corners"] if combined["corners"] else {"corners": {}, "overall_grade": 5.0},
                edges_data=combined["edges"] if combined["edges"] else {"score": 5.0},
                surface_data=combined["surface"].get("surface", {"score": 5.0}) if combined["surface"] else {"score": 5.0}
            )
            combined["grade"] = grading_result
        except Exception as e:
            combined["grade"] = {"error": str(e), "psa_estimate": "?", "final_score": 0}
    
    individual = {
        "front": front_analysis,
        "back": back_analysis if back_path else None
    }
    
    return combined, individual
