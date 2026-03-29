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
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from analysis.centering import calculate_centering_ratios
from analysis.damage_preprocessing import enhance_for_damage_detection
from analysis.texture import detect_border_wear
from analysis.creases import detect_surface_creases
from grading.vision_assessor import assess_card, assess_damage_from_full_images, VisionAssessorError
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
    Pokemon backs have heavy blue with a specific red Pokeball center.
    Threshold raised from 40% to 55% to avoid false positives on blue-artwork
    fronts (Articuno, Vaporeon, Blastoise, water-type cards).
    (Inlined from analysis/deprecated/edges.py to remove dependency on deprecated module.)
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, np.array([90, 50, 30]), np.array([140, 255, 255]))
    blue_pct = cv2.countNonZero(blue_mask) / blue_mask.size * 100
    yellow_mask = cv2.inRange(hsv, np.array([20, 80, 100]), np.array([40, 255, 255]))
    yellow_pct = cv2.countNonZero(yellow_mask) / yellow_mask.size * 100
    # Red mask for Pokeball detection (backs have a red Pokeball center)
    red_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([10, 255, 255]))
    red_mask2 = cv2.inRange(hsv, np.array([160, 80, 80]), np.array([180, 255, 255]))
    red_pct = (cv2.countNonZero(red_mask1) + cv2.countNonZero(red_mask2)) / blue_mask.size * 100

    # Backs require both high blue AND some red (Pokeball) — reduces false positives
    if blue_pct > 55 and yellow_pct < 5 and red_pct > 2:
        return "back", min(1.0, blue_pct / 70)
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
    is_front = (side == "front")
    try:
        centering_path = None
        if debug_output_dir:
            centering_path = str(debug_output_dir / f"{side}_centering.jpg")
        vision_border_fractions = detection_data.get("border_fractions") if detection_data else None
        already_corrected = bool(detection_data.get("already_corrected")) if detection_data else False
        results["centering"] = calculate_centering_ratios(
            image_path,
            debug_output_path=centering_path,
            vision_border_fractions=vision_border_fractions,
            is_front=is_front,
            already_corrected=already_corrected,
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
    # Average-axis scores for half-point gate; fall back to worst-axis if absent.
    front_avg = float(front_centering.get("centering_avg_score", front_score))
    back_avg = float(back_centering.get("centering_avg_score", back_score))
    front_conf = float(front_centering.get("confidence", 0.5))
    back_conf = float(back_centering.get("confidence", 0.5))

    return CenteringResult(
        centering_cap=min(front_cap, back_cap),
        front_centering_score=front_score,
        back_centering_score=back_score,
        confidence=min(front_conf, back_conf),
        front_avg_centering_score=front_avg,
        back_avg_centering_score=back_avg,
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
        surface_raw=vision["surface"],  # For damage cap — not exposed in API response
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
    grade_out["estimated_grade"] = _psa_label(final_grade)
    grade_out["psa_estimate"] = grade_out["estimated_grade"]  # backward compat alias
    grade_out["is_estimate"] = True
    grade_out["disclaimer"] = (
        "This is an AI-generated estimate, not an official PSA grade. "
        "Actual professional grades may differ. This tool is for "
        "informational purposes only."
    )
    grade_out["final_score"] = assembler_result["composite_score"]
    grade_out["grading_status"] = "success"

    # Sub-scores for the 4-tile UI grid
    grade_out["sub_scores"] = {
        "centering": assembler_result["centering_score"],
        "corners": round(assembler_result["dimension_scores"]["corners"]["blended"], 1),
        "edges": round(assembler_result["dimension_scores"]["edges"]["blended"], 1),
        "surface": round(assembler_result["dimension_scores"]["surface"]["blended"], 1),
    }

    # PSA grade bracket thresholds: composite_score >= thresh maps to that PSA label.
    # Grade range (e.g. "8-9") is shown only when the composite is within 0.3 of the
    # *next higher* bracket — meaning a small measurement error could push the card
    # into the higher grade band. 0.3 avoids showing ranges on clear mid-grade cards
    # while alerting on genuine boundary cases.
    _GRADE_BRACKETS = [
        (9.5, "10"), (9.0, "9"), (8.5, "8.5"), (8.0, "8"),
        (7.5, "7.5"), (7.0, "7"), (6.5, "6.5"), (6.0, "6"),
        (5.5, "5.5"), (5.0, "5"), (4.5, "4.5"), (4.0, "4"),
        (3.5, "3.5"), (3.0, "3"), (2.5, "2.5"), (2.0, "2"),
        (1.5, "1.5"), (1.0, "1"),
    ]
    psa_label = grade_out["psa_estimate"]
    composite = assembler_result["composite_score"]
    grade_range = psa_label
    for i, (thresh, label) in enumerate(_GRADE_BRACKETS):
        if label == psa_label and i > 0:
            upper_thresh, upper_label = _GRADE_BRACKETS[i - 1]
            if composite >= upper_thresh - 0.3:
                grade_range = f"{psa_label}-{upper_label}"
            break
    grade_out["grade_range"] = grade_range

    # Explanations: human-readable summary for the Analysis Details section
    sub = grade_out["sub_scores"]
    constraints = assembler_result["constraints_applied"]
    explanations = []

    if constraints["centering_cap_activated"]:
        explanations.append(f"⚠ Centering limited grade to PSA {assembler_result['centering_cap']}")
    elif sub["centering"] >= 9.5:
        explanations.append("✓ Excellent centering")
    elif sub["centering"] >= 7.5:
        explanations.append("⚠ Slightly off-center")
    else:
        explanations.append("✗ Poor centering")

    if sub["corners"] >= 9.5:
        explanations.append("✓ Sharp corners")
    elif sub["corners"] >= 8.0:
        explanations.append("⚠ Minor corner wear")
    else:
        explanations.append("✗ Significant corner damage")

    if sub["edges"] >= 9.5:
        explanations.append("✓ Clean edges")
    elif sub["edges"] >= 8.0:
        explanations.append("⚠ Minor edge wear")
    else:
        explanations.append("✗ Multiple edges show wear")

    if sub["surface"] >= 9.5:
        explanations.append("✓ Pristine surface")
    elif sub["surface"] >= 8.5:
        explanations.append("⚠ Minor surface imperfections")
    elif sub["surface"] >= 7.0:
        explanations.append("⚠ Visible surface wear")
    else:
        explanations.append("✗ Significant surface damage")

    for defect in assembler_result.get("defects", []):
        if defect.get("severity") in ("moderate", "severe"):
            loc = defect["location"].replace("_", " ").title()
            desc = defect.get("description", "damage detected")
            explanations.append(f"⚠ {loc}: {desc}")

    if constraints.get("damage_cap_activated"):
        reason = constraints.get("damage_cap_reason", "severe damage detected")
        explanations.append(f"✗ Grade capped: {reason}")
    if constraints["floor_activated"]:
        explanations.append("⚠ Grade floor applied (worst dimension drag)")
    if constraints["ceiling_activated"]:
        explanations.append("⚠ Grade ceiling applied")

    grade_out["explanations"] = explanations

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


def _apply_opencv_corner_cross_check(
    vision: Dict,
    front_analysis: Dict,
    back_analysis: Dict,
) -> Tuple[Dict, List[str]]:
    """
    Compare OpenCV corner overall_grade to Vision AI corner average for each side.
    If they diverge by > 2.0, reduce all per-location corner confidences by 0.2
    for that side and return a flag. Only reduces confidence — never changes scores.
    This catches Vision AI hallucinating high corner scores on a visibly damaged card.
    """
    DIVERGE_THRESHOLD = 2.0
    CONFIDENCE_PENALTY = 0.2
    flags: List[str] = []

    for side, analysis in [("front", front_analysis), ("back", back_analysis)]:
        opencv_grade = analysis.get("opencv_corner_grade")
        if opencv_grade is None:
            continue
        keys = [f"{side}_{c}" for c in ("top_left", "top_right", "bottom_left", "bottom_right")]
        vision_scores = [
            float(vision["corners"][k].get("score", 5.0))
            for k in keys if k in vision["corners"]
        ]
        if not vision_scores:
            continue
        vision_avg = sum(vision_scores) / len(vision_scores)
        divergence = abs(vision_avg - opencv_grade)
        if divergence > DIVERGE_THRESHOLD:
            flags.append(f"corner_{side}_opencv_divergence_{divergence:.1f}")
            for k in keys:
                if k in vision["corners"]:
                    orig = float(vision["corners"][k].get("confidence", 1.0))
                    vision["corners"][k]["confidence"] = round(
                        max(0.3, orig - CONFIDENCE_PENALTY), 3
                    )

    return vision, flags


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

    # Check for possible front/back swap
    detected_front = front_analysis.get("detected_as")
    detected_back = back_analysis.get("detected_as")
    if detected_front == "back" and detected_back == "front":
        combined["warnings"].append(
            "Images may have been uploaded in the wrong order "
            "(front detected as back, back detected as front)"
        )

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

    # Stage 3b: Damage assessment with full images (to catch damage missed in cropped analysis)
    _CREASE_SEVERITY_ORDER = ["none", "hairline", "moderate", "heavy"]
    try:
        damage_result = assess_damage_from_full_images(front_img, back_img)
        # Merge damage assessment into vision results, using damage as override for severe cases
        for side in ["front", "back"]:
            if side in vision_result.get("surface", {}):
                damage_side = damage_result.get(side, {})
                damage_crease = damage_side.get("crease_depth", "none")
                damage_whitening = damage_side.get("whitening_coverage", "none")

                # If damage assessment found heavy/extensive damage, use it (more reliable on full images)
                if damage_crease in ["heavy"]:
                    vision_result["surface"][side]["crease_depth"] = damage_crease
                    logger.info(f"Damage assessment upgraded {side} crease to '{damage_crease}'")
                elif damage_crease in ["moderate"]:
                    # Upgrade to moderate if current is less severe (none or hairline)
                    current_crease = vision_result["surface"][side].get("crease_depth", "none")
                    current_rank = _CREASE_SEVERITY_ORDER.index(current_crease) if current_crease in _CREASE_SEVERITY_ORDER else 0
                    moderate_rank = _CREASE_SEVERITY_ORDER.index("moderate")
                    if current_rank < moderate_rank:
                        vision_result["surface"][side]["crease_depth"] = damage_crease
                        logger.info(f"Damage assessment detected {side} crease as '{damage_crease}'")

                if damage_whitening in ["extensive"]:
                    vision_result["surface"][side]["whitening_coverage"] = damage_whitening
                    logger.info(f"Damage assessment upgraded {side} whitening to '{damage_whitening}'")
                elif damage_whitening in ["moderate"] and vision_result["surface"][side].get("whitening_coverage") in ["none", "minor"]:
                    vision_result["surface"][side]["whitening_coverage"] = damage_whitening
                    logger.info(f"Damage assessment detected {side} whitening as '{damage_whitening}'")

    except VisionAssessorError as exc:
        logger.warning(f"Damage assessment failed (non-critical): {exc}")
        # Don't fail the entire grading, but log the issue

    # Stage 3c: Enhanced damage assessment on preprocessed images (upgrade-only)
    # Removes holographic foil noise via split-region grayscale+CLAHE preprocessing on FRONT only.
    # Back cards are simple blue pattern without foil noise, so skip preprocessing to avoid
    # over-smoothing crease signals. Re-assesses with Vision AI. Only upgrades severity, never downgrades.
    _WH_ORDER = ["none", "minor", "moderate", "extensive"]
    # Safe defaults so Stage 3e always has images even if Stage 3c raises an exception
    front_enhanced = front_img
    back_enhanced = back_img
    try:
        # Front: apply preprocessing to strip holographic foil noise
        front_enhanced = enhance_for_damage_detection(front_img)

        # Back: detect actual side to decide preprocessing
        # Back cards (blue + Pokeball) don't have holographic foil noise, so skip preprocessing
        # to preserve crease signal visibility.
        back_enhanced = None
        if back_img is not None:
            back_side, _ = detect_card_side(back_img)
            if back_side == "front":
                # Unlikely but possible: back uploaded as front. Preprocess it anyway.
                back_enhanced = enhance_for_damage_detection(back_img)
            else:
                # Back card: skip preprocessing, use original image
                back_enhanced = back_img

        enhanced_damage = assess_damage_from_full_images(front_enhanced, back_enhanced)

        for side in ["front", "back"]:
            if side not in vision_result.get("surface", {}):
                continue
            enh = enhanced_damage.get(side, {})
            enh_crease = enh.get("crease_depth", "none")
            enh_white = enh.get("whitening_coverage", "none")
            cur_crease = vision_result["surface"][side].get("crease_depth", "none")
            cur_white = vision_result["surface"][side].get("whitening_coverage", "none")

            # Upgrade crease if enhanced detection found worse severity.
            # Cap upgrade to at most 1 severity level above Stage 3b baseline:
            # CLAHE preprocessing can create visual artifacts (e.g. foil sparkle → fake crease lines),
            # so none→heavy jumps are false positives. A 1-level cap means Stage 3c
            # can flag subtle creases Stage 3b missed (none→hairline) but can't catastrophically
            # misgrade a clean card (none→heavy).
            if _CREASE_SEVERITY_ORDER.index(enh_crease) > _CREASE_SEVERITY_ORDER.index(cur_crease):
                cur_idx = _CREASE_SEVERITY_ORDER.index(cur_crease)
                max_allowed_idx = min(cur_idx + 1, len(_CREASE_SEVERITY_ORDER) - 1)
                capped_crease = _CREASE_SEVERITY_ORDER[min(_CREASE_SEVERITY_ORDER.index(enh_crease), max_allowed_idx)]
                vision_result["surface"][side]["crease_depth"] = capped_crease
                # Floor confidence to ensure damage cap gate (0.60) is met
                vision_result["surface"][side]["confidence"] = max(
                    float(vision_result["surface"][side].get("confidence", 0.0)), 0.65
                )
                if capped_crease != enh_crease:
                    logger.info(
                        f"[Stage 3c] Enhanced preprocessing upgraded {side} crease: "
                        f"'{cur_crease}' → '{capped_crease}' (capped from '{enh_crease}' — 1-level limit)"
                    )
                else:
                    logger.info(
                        f"[Stage 3c] Enhanced preprocessing upgraded {side} crease: "
                        f"'{cur_crease}' → '{capped_crease}'"
                    )

            # Upgrade whitening if enhanced detection found worse severity.
            # Same 1-level cap as crease: prevents CLAHE artifacts from inflating whitening.
            if _WH_ORDER.index(enh_white) > _WH_ORDER.index(cur_white):
                cur_wh_idx = _WH_ORDER.index(cur_white)
                max_wh_idx = min(cur_wh_idx + 1, len(_WH_ORDER) - 1)
                capped_white = _WH_ORDER[min(_WH_ORDER.index(enh_white), max_wh_idx)]
                vision_result["surface"][side]["whitening_coverage"] = capped_white
                if capped_white != enh_white:
                    logger.info(
                        f"[Stage 3c] Enhanced preprocessing upgraded {side} whitening: "
                        f"'{cur_white}' → '{capped_white}' (capped from '{enh_white}' — 1-level limit)"
                    )
                else:
                    logger.info(
                        f"[Stage 3c] Enhanced preprocessing upgraded {side} whitening: "
                        f"'{cur_white}' → '{capped_white}'"
                    )
    except Exception as exc:
        logger.warning(f"[Stage 3c] Enhanced damage assessment failed (non-critical): {exc}")

    # ── Stage 3d: OpenCV border texture analysis ──────────────────────────────
    # Multi-scale Sobel gradient + local std dev on border region.
    # Upgrade-only (never downgrades). Confidence deliberately 0.55 → below
    # 0.60 damage-cap gate, so this stage affects label display only.
    # Set STAGE_3D_ACTIVE = True after validating thresholds on real cards.
    STAGE_3D_ACTIVE = True  # ACTIVE: OpenCV-based whitening detection enabled
    try:
        for _img, _side in [(front_img, "front"), (back_img, "back")]:
            if _img is None:
                continue
            wear = detect_border_wear(_img)
            ocv_white = wear.get("whitening_coverage", "none")
            ocv_score = wear.get("score", 0.0)
            cur_white = vision_result.get("surface", {}).get(_side, {}).get("whitening_coverage", "none")
            if _WH_ORDER.index(ocv_white) > _WH_ORDER.index(cur_white):
                if STAGE_3D_ACTIVE:
                    vision_result["surface"][_side]["whitening_coverage"] = ocv_white
                    logger.info(
                        f"[stage3d] {_side} whitening upgraded: '{cur_white}' → '{ocv_white}' "
                        f"(score={ocv_score:.1f})"
                    )
                else:
                    logger.debug(
                        f"[stage3d DRY-RUN] {_side} would upgrade whitening: "
                        f"'{cur_white}' → '{ocv_white}' (score={ocv_score:.1f})"
                    )
            else:
                logger.debug(
                    f"[stage3d] {_side} whitening unchanged: OpenCV='{ocv_white}' "
                    f"(score={ocv_score:.1f}), Vision='{cur_white}'"
                )
    except Exception as exc:
        logger.warning(f"[stage3d] Border texture analysis failed: {exc}")

    # ── Stage 3e: OpenCV HoughLinesP crease detection ────────────────────────
    # Runs detect_surface_creases() on the Stage 3c preprocessed image
    # (grayscale + CLAHE, foil noise stripped) — upgrade-only, never downgrades.
    # Confidence 0.65 for moderate/heavy (triggers damage cap gate at 0.60).
    # Confidence 0.55 for hairline (shows label, no grade cap enforcement).
    STAGE_3E_ACTIVE = True
    try:
        for _enh_img, _side in [(front_enhanced, "front"), (back_enhanced, "back")]:
            if _enh_img is None:
                continue
            crease_result = detect_surface_creases(_enh_img, side=_side)
            ocv_crease = crease_result.get("severity", "none")
            ocv_conf = crease_result.get("confidence", 0.65)
            cur_crease = vision_result.get("surface", {}).get(_side, {}).get("crease_depth", "none")

            if _CREASE_SEVERITY_ORDER.index(ocv_crease) > _CREASE_SEVERITY_ORDER.index(cur_crease):
                if STAGE_3E_ACTIVE:
                    # Cap upgrade to at most 1 severity level above current baseline.
                    # HoughLinesP can produce false positives on card textures/borders;
                    # multi-level jumps (none→moderate, none→heavy) are unreliable.
                    cur_idx = _CREASE_SEVERITY_ORDER.index(cur_crease)
                    max_allowed_idx = min(cur_idx + 1, len(_CREASE_SEVERITY_ORDER) - 1)
                    capped_crease = _CREASE_SEVERITY_ORDER[
                        min(_CREASE_SEVERITY_ORDER.index(ocv_crease), max_allowed_idx)
                    ]
                    vision_result["surface"][_side]["crease_depth"] = capped_crease
                    # Floor confidence above damage-cap gate for moderate/heavy
                    if capped_crease in ("moderate", "heavy"):
                        vision_result["surface"][_side]["confidence"] = max(
                            float(vision_result["surface"][_side].get("confidence", 0.0)),
                            0.65,
                        )
                    cap_note = f" (capped from '{ocv_crease}')" if capped_crease != ocv_crease else ""
                    logger.info(
                        f"[stage3e] {_side} crease upgraded: '{cur_crease}' → '{capped_crease}'{cap_note} "
                        f"(norm_max={crease_result.get('normalized_max_length', 0):.3f}, "
                        f"lines={crease_result.get('line_count', 0)}, "
                        f"holo={crease_result.get('is_likely_holo', False)})"
                    )
                else:
                    logger.debug(
                        f"[stage3e DRY-RUN] {_side} would upgrade crease: "
                        f"'{cur_crease}' → '{ocv_crease}'"
                    )
            else:
                logger.debug(
                    f"[stage3e] {_side} crease unchanged: OpenCV='{ocv_crease}', "
                    f"Vision='{cur_crease}'"
                )
    except Exception as exc:
        logger.warning(f"[stage3e] Crease detection failed: {exc}")

    # Consistency check: creases always cause stress whitening at the fold line.
    # Runs after ALL stages (3c/3d/3e) so any late crease upgrades are covered.
    # If moderate/heavy crease was detected but no whitening, escalate to minor.
    for side in ["front", "back"]:
        surf = vision_result.get("surface", {}).get(side, {})
        crease = surf.get("crease_depth", "none")
        whitening = surf.get("whitening_coverage", "none")
        if crease in ("heavy", "moderate") and whitening == "none":
            vision_result["surface"][side]["whitening_coverage"] = "minor"
            logger.info(
                f"[consistency] {side} crease='{crease}' forces whitening 'none' → 'minor' "
                f"(stress whitening always accompanies crease)"
            )

    # Adjust surface score when creases are detected to match damage cap
    # (surface score of 8.5 with heavy crease capped to 2.0 is confusing)
    for side in ["front", "back"]:
        crease = vision_result.get("surface", {}).get(side, {}).get("crease_depth", "none")
        if crease == "heavy":
            old_score = vision_result["surface"][side].get("score", 8.0)
            vision_result["surface"][side]["score"] = min(2.5, old_score)
            if old_score > 2.5:
                logger.info(
                    f"[surface-adjustment] {side} surface score lowered: {old_score:.1f} → {vision_result['surface'][side]['score']:.1f} "
                    f"(heavy crease detected)"
                )
        elif crease == "moderate":
            old_score = vision_result["surface"][side].get("score", 8.0)
            vision_result["surface"][side]["score"] = min(5.0, old_score)
            if old_score > 5.0:
                logger.info(
                    f"[surface-adjustment] {side} surface score lowered: {old_score:.1f} → {vision_result['surface'][side]['score']:.1f} "
                    f"(moderate crease detected)"
                )
        elif crease == "hairline":
            old_score = vision_result["surface"][side].get("score", 8.0)
            vision_result["surface"][side]["score"] = min(6.5, old_score)
            if old_score > 6.5:
                logger.info(
                    f"[surface-adjustment] {side} surface score lowered: {old_score:.1f} → {vision_result['surface'][side]['score']:.1f} "
                    f"(hairline crease detected)"
                )

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

    # OpenCV corner cross-check: reduce confidence when Vision AI and OpenCV diverge > 2.0
    vision_result, opencv_flags = _apply_opencv_corner_cross_check(
        vision_result, front_analysis, back_analysis
    )
    if opencv_flags:
        combined["warnings"].extend(opencv_flags)

    # Stage 4: Grade assembly
    inputs = _vision_to_assembly_input(vision_result, centering_result)
    assembler_out = assemble_grade(inputs)

    # Map to compat format
    grade_out, corners_out, edges_out, surface_out = _assemble_result_to_compat(
        assembler_out, vision_result
    )

    combined["grade"] = grade_out
    # Show the worse centering side in the primary field (drives the cap),
    # and expose both sides for the detail screen.
    front_cap = front_centering.get("centering_cap", 10)
    back_cap = back_centering.get("centering_cap", 10)
    if back_cap < front_cap:
        combined["centering"] = back_centering
    else:
        combined["centering"] = front_centering
    combined["front_centering"] = front_centering
    combined["back_centering"] = back_centering
    combined["corners"] = corners_out
    combined["edges"] = edges_out
    combined["surface"] = surface_out

    # Stage 5: Annotated image (non-blocking — failure is silent)
    try:
        from analysis.annotation import annotate_card_image
        individual = assembler_out.get("individual_scores", {})
        annotated_b64 = annotate_card_image(
            image_path=front_path,
            corner_scores=individual.get("corners", {}),
            edge_scores=individual.get("edges", {}),
            centering_data=front_centering,
        )
        if annotated_b64:
            combined["annotated_front_image"] = annotated_b64
    except Exception as exc:
        logger.warning(f"Annotation failed (non-critical): {exc}")

    return combined
