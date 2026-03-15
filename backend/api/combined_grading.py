"""
Combined front + back card grading logic.

New pipeline (PRD architecture):
  Stage 2: Centering (OpenCV, modified to output cap + score)
  Stage 3: Visual Assessment (Vision AI via vision_assessor)
  Stage 4: Grade Assembly (pure logic via grade_assembler)
"""
import cv2
import numpy as np
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path

from analysis.centering import calculate_centering_ratios
from grading.vision_assessor import assess_card, VisionAssessorError
from grading.grade_assembler import (
    assemble_grade,
    AssemblyInput,
    CornerScores,
    EdgeScores,
    SurfaceScores,
    CenteringResult,
)

logger = logging.getLogger(__name__)


def detect_card_side(image: np.ndarray) -> Tuple[str, float]:
    """
    Detect if image shows card front or back based on blue hue dominance.
    Pokemon backs have >40% blue pixels; fronts have varied colors.
    (Inlined from analysis/deprecated/edges.py to remove dependency on deprecated module.)
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, np.array([90, 50, 30]), np.array([140, 255, 255]))
    blue_pct = cv2.countNonZero(blue_mask) / blue_mask.size * 100
    yellow_mask = cv2.inRange(hsv, np.array([20, 80, 100]), np.array([40, 255, 255]))
    yellow_pct = cv2.countNonZero(yellow_mask) / yellow_mask.size * 100

    if blue_pct > 40 and yellow_pct < 5:
        return "back", min(1.0, blue_pct / 60)
    if blue_pct < 20:
        return "front", min(1.0, (100 - blue_pct) / 80)
    return "front", 0.6


# PSA grade string formatter: 8.0 → "8", 8.5 → "8.5"
def _psa_label(grade: float) -> str:
    if grade == int(grade):
        return str(int(grade))
    return str(grade)


def analyze_single_side(
    image_path: str,
    side: str = "front",
    debug_output_dir: Optional[Path] = None,
    detection_data: Optional[Dict] = None,
) -> Dict:
    """
    Run analysis on a single card side.

    In the new architecture this only computes centering — corner/edge/surface
    assessment requires both sides and is done later in combine_front_back_analysis
    via the Vision AI assessor.

    Returns:
        Dict with centering, detected_as, image_path, and None placeholders for
        corners/edges/surface (for backward-compat with main.py preview).
    """
    results = {
        "side": side,
        "detected_as": None,
        "centering": None,
        "corners": None,    # populated later by vision assessor
        "edges": None,      # populated later by vision assessor
        "surface": None,    # populated later by vision assessor
        "image_path": image_path,
        "errors": [],
    }

    image = cv2.imread(image_path)
    if image is None:
        results["errors"].append("Failed to load image")
        return results

    # Auto-detect front vs back
    detected_side, side_confidence = detect_card_side(image)
    results["detected_as"] = detected_side
    results["side_detection_confidence"] = side_confidence

    # Centering — computed for both sides; is_front selects the cap table
    is_front = (side == "front") or (detected_side == "front")
    try:
        centering_path = None
        if debug_output_dir:
            centering_path = str(debug_output_dir / f"{side}_centering.jpg")
        vision_border_fractions = detection_data.get("border_fractions") if detection_data else None
        results["centering"] = calculate_centering_ratios(
            image_path,
            debug_output_path=centering_path,
            vision_border_fractions=vision_border_fractions,
            is_front=is_front,
        )
    except Exception as e:
        results["errors"].append(f"Centering failed: {str(e)}")
        results["centering"] = {
            "error": str(e),
            "grade_estimate": 5.0,
            "confidence": 0.3,
            "centering_cap": 10,
            "centering_score": 5.0,
        }

    return results


def _build_centering_result(
    front_centering: Dict,
    back_centering: Dict,
) -> CenteringResult:
    """
    Combine front and back centering into a CenteringResult for the assembler.
    The effective cap is min(front_cap, back_cap).
    Confidence is the minimum of the two (conservative).
    """
    front_cap = front_centering.get("centering_cap", 10)
    back_cap = back_centering.get("centering_cap", 10)
    front_score = float(front_centering.get("centering_score", 5.0))
    back_score = float(back_centering.get("centering_score", 5.0))
    front_conf = float(front_centering.get("confidence", 0.5))
    back_conf = float(back_centering.get("confidence", 0.5))

    return CenteringResult(
        centering_cap=min(front_cap, back_cap),
        front_centering_score=front_score,
        back_centering_score=back_score,
        confidence=min(front_conf, back_conf),
    )


def _vision_to_assembly_input(
    vision: Dict,
    centering: CenteringResult,
) -> AssemblyInput:
    """Build AssemblyInput from vision assessor output and centering result."""
    c = vision["corners"]
    e = vision["edges"]
    s = vision["surface"]

    corners = CornerScores(
        front_top_left=float(c["front_top_left"]["score"]),
        front_top_right=float(c["front_top_right"]["score"]),
        front_bottom_left=float(c["front_bottom_left"]["score"]),
        front_bottom_right=float(c["front_bottom_right"]["score"]),
        back_top_left=float(c["back_top_left"]["score"]),
        back_top_right=float(c["back_top_right"]["score"]),
        back_bottom_left=float(c["back_bottom_left"]["score"]),
        back_bottom_right=float(c["back_bottom_right"]["score"]),
    )

    edges = EdgeScores(
        front_top=float(e["front_top"]["score"]),
        front_right=float(e["front_right"]["score"]),
        front_bottom=float(e["front_bottom"]["score"]),
        front_left=float(e["front_left"]["score"]),
        back_top=float(e["back_top"]["score"]),
        back_right=float(e["back_right"]["score"]),
        back_bottom=float(e["back_bottom"]["score"]),
        back_left=float(e["back_left"]["score"]),
    )

    surface = SurfaceScores(
        front=float(s["front"]["score"]),
        back=float(s["back"]["score"]),
    )

    corner_defects = {k: v.get("defects", []) for k, v in c.items()}
    edge_defects = {k: v.get("defects", []) for k, v in e.items()}
    surface_defects = {
        "front": s["front"].get("defects", []),
        "back": s["back"].get("defects", []),
    }
    corner_confidences = {k: float(v.get("confidence", 1.0)) for k, v in c.items()}
    edge_confidences = {k: float(v.get("confidence", 1.0)) for k, v in e.items()}
    surface_confidences = {
        "front": float(s["front"].get("confidence", 1.0)),
        "back": float(s["back"].get("confidence", 1.0)),
    }

    return AssemblyInput(
        corners=corners,
        edges=edges,
        surface=surface,
        centering=centering,
        corner_defects=corner_defects,
        edge_defects=edge_defects,
        surface_defects=surface_defects,
        corner_confidences=corner_confidences,
        edge_confidences=edge_confidences,
        surface_confidences=surface_confidences,
    )


def _assemble_result_to_compat(assembler_result: Dict, vision: Dict) -> Dict:
    """
    Map grade_assembler output to a format compatible with main.py's expectations.

    main.py reads:
      combined["grade"]["psa_estimate"]  ← log + response
      combined["grade"]                  ← full grade response field
      combined["centering"]              ← details
      combined["corners"]                ← details
      combined["edges"]                  ← details
      combined["surface"]                ← details
    """
    final_grade = assembler_result["final_grade"]

    # Add backward-compat fields to the grade dict
    grade_out = dict(assembler_result)
    grade_out["psa_estimate"] = _psa_label(final_grade)
    grade_out["final_score"] = assembler_result["composite_score"]
    grade_out["grading_status"] = "success"

    # Build details sections from vision AI output for backward compat
    corners_out = {
        "corners": {
            k: {"score": v["score"], "defects": v.get("defects", [])}
            for k, v in vision["corners"].items()
        },
        "overall_grade": assembler_result["dimension_scores"]["corners"]["blended"],
    }
    edges_out = {
        "score": assembler_result["dimension_scores"]["edges"]["blended"],
        "overall_grade": assembler_result["dimension_scores"]["edges"]["blended"],
        "front_avg": assembler_result["dimension_scores"]["edges"]["front_avg"],
        "back_avg": assembler_result["dimension_scores"]["edges"]["back_avg"],
        "edge_details": {
            k: {"score": v["score"]}
            for k, v in vision["edges"].items()
        },
    }
    surface_out = {
        "surface": {
            "score": assembler_result["dimension_scores"]["surface"]["blended"],
            "front_score": vision["surface"]["front"]["score"],
            "back_score": vision["surface"]["back"]["score"],
            "front_defects": vision["surface"]["front"].get("defects", []),
            "back_defects": vision["surface"]["back"].get("defects", []),
            "front_staining": vision["surface"]["front"].get("staining", "none"),
            "back_staining": vision["surface"]["back"].get("staining", "none"),
            "front_gloss": vision["surface"]["front"].get("gloss", "original gloss intact"),
        }
    }

    return grade_out, corners_out, edges_out, surface_out


def combine_front_back_analysis(
    front_analysis: Dict,
    back_analysis: Dict,
) -> Dict:
    """
    Combine front and back analysis using the new Vision AI pipeline.

    Requires front_analysis["image_path"] and back_analysis["image_path"]
    to be set (done by analyze_single_side).
    """
    combined = {
        "analysis_type": "combined_front_back",
        "centering": None,
        "corners": None,
        "edges": None,
        "surface": None,
        "warnings": [],
    }

    # Load corrected card images
    front_path = front_analysis.get("image_path")
    back_path = back_analysis.get("image_path")

    if not front_path or not back_path:
        combined["grade"] = {
            "error": "Image paths missing from analysis",
            "psa_estimate": "?",
            "final_score": 0,
        }
        combined["warnings"].append("Could not load images for Vision AI assessment")
        return combined

    front_img = cv2.imread(front_path)
    back_img = cv2.imread(back_path)

    if front_img is None or back_img is None:
        combined["grade"] = {
            "error": "Could not read card images",
            "psa_estimate": "?",
            "final_score": 0,
        }
        combined["warnings"].append("Image load failed")
        return combined

    # Stage 3: Vision AI assessment
    try:
        vision_result = assess_card(front_img, back_img)
        if vision_result.get("low_confidence_flags"):
            combined["warnings"].append(
                f"Low confidence on: {', '.join(vision_result['low_confidence_flags'])}"
            )
    except VisionAssessorError as exc:
        combined["grade"] = {
            "error": str(exc),
            "psa_estimate": "?",
            "final_score": 0,
        }
        combined["warnings"].append(f"Vision AI assessment failed: {exc}")
        return combined

    # Stage 2: Build centering result from both sides
    front_centering = front_analysis.get("centering") or {
        "centering_cap": 10,
        "centering_score": 5.0,
        "confidence": 0.3,
    }
    back_centering = back_analysis.get("centering") or {
        "centering_cap": 10,
        "centering_score": 5.0,
        "confidence": 0.3,
    }
    centering_result = _build_centering_result(front_centering, back_centering)

    # Stage 4: Grade assembly
    inputs = _vision_to_assembly_input(vision_result, centering_result)
    assembler_out = assemble_grade(inputs)

    # Map to compat format
    grade_out, corners_out, edges_out, surface_out = _assemble_result_to_compat(
        assembler_out, vision_result
    )

    combined["grade"] = grade_out
    combined["centering"] = front_centering  # keep original centering data for details
    combined["corners"] = corners_out
    combined["edges"] = edges_out
    combined["surface"] = surface_out

    return combined


def grade_card_session(
    front_path: str,
    back_path: Optional[str] = None,
    debug_output_dir: Optional[Path] = None,
) -> Tuple[Dict, Dict]:
    """
    Grade a card with front and optional back image.

    Returns:
        Tuple of (combined_result, individual_sides_dict)
    """
    front_analysis = analyze_single_side(front_path, "front", debug_output_dir)

    if back_path:
        back_analysis = analyze_single_side(back_path, "back", debug_output_dir)
        combined = combine_front_back_analysis(front_analysis, back_analysis)
    else:
        # Front-only: run vision assessor with front image as both sides.
        # Centering uses front cap table for both (conservative default).
        try:
            front_img = cv2.imread(front_path)
            if front_img is None:
                raise VisionAssessorError("Could not load front image")
            vision_result = assess_card(front_img, front_img)
            centering_data = front_analysis.get("centering") or {
                "centering_cap": 10,
                "centering_score": 5.0,
                "confidence": 0.3,
            }
            centering_result = CenteringResult(
                centering_cap=centering_data.get("centering_cap", 10),
                front_centering_score=float(centering_data.get("centering_score", 5.0)),
                back_centering_score=float(centering_data.get("centering_score", 5.0)),
                confidence=float(centering_data.get("confidence", 0.3)),
            )
            inputs = _vision_to_assembly_input(vision_result, centering_result)
            assembler_out = assemble_grade(inputs)
            grade_out, corners_out, edges_out, surface_out = _assemble_result_to_compat(
                assembler_out, vision_result
            )
            combined = {
                "analysis_type": "front_only",
                "centering": centering_data,
                "corners": corners_out,
                "edges": edges_out,
                "surface": surface_out,
                "grade": grade_out,
                "warnings": ["Back not provided — front-only analysis (back side duplicated)"],
            }
        except VisionAssessorError as exc:
            combined = {
                "analysis_type": "front_only",
                "centering": front_analysis.get("centering"),
                "corners": None,
                "edges": None,
                "surface": None,
                "grade": {"error": str(exc), "psa_estimate": "?", "final_score": 0},
                "warnings": [f"Vision AI assessment failed: {exc}"],
            }

        back_analysis = None

    individual = {
        "front": front_analysis,
        "back": back_analysis,
    }

    return combined, individual
