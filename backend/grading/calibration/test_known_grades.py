"""
PRD Edge-Case Test Suite — all 7 cases from Section 4 Phase 4.

Tests 1–6 are pure unit tests against assemble_grade() with mock inputs.
Test 7 is an integration test requiring a real Vision AI call (marked with
@pytest.mark.integration).

Run: pytest backend/grading/calibration/test_known_grades.py -k "not integration"
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from grading.grade_assembler import (
    assemble_grade,
    AssemblyInput,
    CornerScores,
    EdgeScores,
    SurfaceScores,
    CenteringResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_corners(score: float) -> CornerScores:
    return CornerScores(
        front_top_left=score, front_top_right=score,
        front_bottom_left=score, front_bottom_right=score,
        back_top_left=score, back_top_right=score,
        back_bottom_left=score, back_bottom_right=score,
    )


def _uniform_edges(score: float) -> EdgeScores:
    return EdgeScores(
        front_top=score, front_right=score,
        front_bottom=score, front_left=score,
        back_top=score, back_right=score,
        back_bottom=score, back_left=score,
    )


def _perfect_centering(cap: int = 10, score: float = 10.0) -> CenteringResult:
    return CenteringResult(
        centering_cap=cap,
        front_centering_score=score,
        back_centering_score=score,
        confidence=0.9,
    )


def _make_input(
    corner_score: float = 9.5,
    edge_score: float = 9.5,
    surface_front: float = 9.5,
    surface_back: float = 9.5,
    centering_cap: int = 10,
    centering_score: float = 10.0,
    centering_confidence: float = 0.9,
    **corner_overrides,
) -> AssemblyInput:
    """Build an AssemblyInput with uniform scores, accepting per-corner overrides."""
    corners = _uniform_corners(corner_score)
    for attr, val in corner_overrides.items():
        setattr(corners, attr, val)
    return AssemblyInput(
        corners=corners,
        edges=_uniform_edges(edge_score),
        surface=SurfaceScores(front=surface_front, back=surface_back),
        centering=CenteringResult(
            centering_cap=centering_cap,
            front_centering_score=centering_score,
            back_centering_score=centering_score,
            confidence=centering_confidence,
        ),
    )


# ---------------------------------------------------------------------------
# Test 1: Centering cap dominance
# Front centering 70/30 → ratio 0.429 → front_cap=7
# All other dimensions at 9.5 → composite near 9.5, but cap=7 overrides
# ---------------------------------------------------------------------------

def test_centering_cap_dominance():
    """PRD case 1: 70/30 centering, all else 9.5 → must cap at 7.0."""
    inputs = _make_input(
        corner_score=9.5,
        edge_score=9.5,
        surface_front=9.5,
        surface_back=9.5,
        centering_cap=7,        # 70/30 front centering cap
        centering_score=7.0,    # continuous score for the 70/30 ratio
        centering_confidence=0.9,
    )
    result = assemble_grade(inputs)
    assert result["final_grade"] == 7.0, (
        f"Expected 7.0 (centering cap), got {result['final_grade']}"
    )
    assert result["constraints_applied"]["centering_cap_activated"] is True


# ---------------------------------------------------------------------------
# Test 2: Single destroyed corner
# Three corners at 9.5, one corner at 4.0, everything else at 9.5
# Component floor: min_individual=4.0, composite <= 4.0 + 1.5 = 5.5
# ---------------------------------------------------------------------------

def test_single_destroyed_corner():
    """PRD case 2: single bad corner at 4.0 → final_grade approx 5.0–5.5."""
    inputs = _make_input(
        corner_score=9.5,
        edge_score=9.5,
        surface_front=9.5,
        surface_back=9.5,
        centering_cap=10,
        centering_score=10.0,
        # Override one corner to 4.0
        front_bottom_left=4.0,
    )
    result = assemble_grade(inputs)
    assert 5.0 <= result["final_grade"] <= 5.5, (
        f"Expected 5.0–5.5 (component floor), got {result['final_grade']}"
    )
    assert result["constraints_applied"]["component_floor_activated"] is True


# ---------------------------------------------------------------------------
# Test 3: Centering cap + strong components
# centering_cap=7, corners/edges/surface all 9.5
# Floor must NOT push composite above the centering cap
# ---------------------------------------------------------------------------

def test_centering_cap_not_overridden_by_floor():
    """PRD case 3: centering_cap=7 with perfect other dims → exactly 7.0."""
    inputs = _make_input(
        corner_score=9.5,
        edge_score=9.5,
        surface_front=9.5,
        surface_back=9.5,
        centering_cap=7,
        centering_score=7.0,
        centering_confidence=0.9,
    )
    result = assemble_grade(inputs)
    # The composite will be ~9.5, capped to 7.0.
    # floor would want to push up, but cap is applied AFTER floor, so cap wins.
    assert result["final_grade"] == 7.0, (
        f"Expected 7.0 (cap overrides floor), got {result['final_grade']}"
    )
    assert result["constraints_applied"]["centering_cap_activated"] is True


# ---------------------------------------------------------------------------
# Test 4: Half-point NOT awarded when centering score is too low
# composite=8.7, centering_score=8.2 → base=8, need centering >= 9, not met
# ---------------------------------------------------------------------------

def test_no_half_point_when_centering_weak():
    """PRD case 4: composite 8.7, centering 8.2 → grade must be 8, NOT 8.5."""
    # Build inputs that produce a composite of approximately 8.7 with no constraints firing
    # Using slightly varied scores:  corners=8.7, edges=8.7, surface=8.7
    inputs = AssemblyInput(
        corners=_uniform_corners(8.7),
        edges=_uniform_edges(8.7),
        surface=SurfaceScores(front=8.7, back=8.7),
        centering=CenteringResult(
            centering_cap=10,
            front_centering_score=8.2,
            back_centering_score=8.2,
            confidence=0.9,
        ),
    )
    result = assemble_grade(inputs)
    # composite should be 8.7, base_grade=8, centering_score=8.2 < 9 → no half-point
    assert result["final_grade"] == 8.0, (
        f"Expected 8.0 (centering too weak for half-point), got {result['final_grade']}"
    )
    assert result["constraints_applied"]["half_point_qualified"] is False


# ---------------------------------------------------------------------------
# Test 5: Half-point awarded when centering is strong
# composite=8.7, centering_score=9.5 → base=8, need centering >= 9, met
# ---------------------------------------------------------------------------

def test_half_point_with_strong_centering():
    """PRD case 5: composite 8.7, centering 9.5 → grade must be 8.5."""
    inputs = AssemblyInput(
        corners=_uniform_corners(8.7),
        edges=_uniform_edges(8.7),
        surface=SurfaceScores(front=8.7, back=8.7),
        centering=CenteringResult(
            centering_cap=10,
            front_centering_score=9.5,
            back_centering_score=9.5,
            confidence=0.9,
        ),
    )
    result = assemble_grade(inputs)
    assert result["final_grade"] == 8.5, (
        f"Expected 8.5 (half-point qualified), got {result['final_grade']}"
    )
    assert result["constraints_applied"]["half_point_qualified"] is True


# ---------------------------------------------------------------------------
# Test 6: Back surface forgiveness
# Wax stain on back only → the blended surface score should be higher than
# the same stain on the front (front 70% weight vs back 30% weight).
# ---------------------------------------------------------------------------

def test_back_surface_more_forgiving():
    """PRD case 6: same defect severity on back scores better than on front."""
    # Stain on back: front=9.5, back=7.0
    inputs_back_stain = AssemblyInput(
        corners=_uniform_corners(9.5),
        edges=_uniform_edges(9.5),
        surface=SurfaceScores(front=9.5, back=7.0),
        centering=_perfect_centering(),
    )

    # Same stain on front: front=7.0, back=9.5
    inputs_front_stain = AssemblyInput(
        corners=_uniform_corners(9.5),
        edges=_uniform_edges(9.5),
        surface=SurfaceScores(front=7.0, back=9.5),
        centering=_perfect_centering(),
    )

    result_back = assemble_grade(inputs_back_stain)
    result_front = assemble_grade(inputs_front_stain)

    back_surface_blended = result_back["dimension_scores"]["surface"]["blended"]
    front_surface_blended = result_front["dimension_scores"]["surface"]["blended"]

    assert back_surface_blended > front_surface_blended, (
        f"Back stain ({back_surface_blended:.2f}) should score better than "
        f"front stain ({front_surface_blended:.2f})"
    )

    # Also verify the grade is better when stain is on back
    assert result_back["final_grade"] >= result_front["final_grade"], (
        f"Back stain grade ({result_back['final_grade']}) should be >= "
        f"front stain grade ({result_front['final_grade']})"
    )


# ---------------------------------------------------------------------------
# Test 7: Vision AI correctly detects corner rounding on dark-bordered cards
# (Integration test — requires ANTHROPIC_API_KEY and a real card image)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dark_border_corner_rounding_detected():
    """
    PRD case 7: Dark-bordered card with rounded corners (no whitening) should
    score corners < 9.0 from the Vision AI assessor.

    Requires:
    - ANTHROPIC_API_KEY set in environment
    - A test image at tests/fixtures/dark_border_rounded_corners.jpg
    """
    import cv2
    from grading.vision_assessor import assess_card

    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "tests", "fixtures",
        "dark_border_rounded_corners.jpg"
    )
    if not os.path.exists(fixture_path):
        pytest.skip(f"Test fixture not found: {fixture_path}")

    img = cv2.imread(fixture_path)
    if img is None:
        pytest.skip("Could not load fixture image")

    result = assess_card(img, img)  # Use same image for front and back
    corner_scores = [v["score"] for v in result["corners"].values()]
    assert any(s < 9.0 for s in corner_scores), (
        f"Expected at least one corner < 9.0, got scores: {corner_scores}"
    )


# ---------------------------------------------------------------------------
# Additional regression tests
# ---------------------------------------------------------------------------

def test_composite_weights_sum_to_one():
    """Sanity check: 30%+30%+40% = 100% — no score inflation."""
    # All components at 8.0 → composite must be exactly 8.0
    inputs = AssemblyInput(
        corners=_uniform_corners(8.0),
        edges=_uniform_edges(8.0),
        surface=SurfaceScores(front=8.0, back=8.0),
        centering=_perfect_centering(),
    )
    result = assemble_grade(inputs)
    assert result["composite_score"] == pytest.approx(8.0, abs=0.01), (
        f"All-8 composite should be 8.0, got {result['composite_score']}"
    )


def test_centering_cap_not_applied_below_confidence_threshold():
    """Centering cap is gated on confidence >= 0.6 — must not apply below threshold."""
    inputs = _make_input(
        corner_score=9.5,
        edge_score=9.5,
        surface_front=9.5,
        surface_back=9.5,
        centering_cap=7,
        centering_score=7.0,
        centering_confidence=0.4,   # below 0.6 → cap must NOT apply
    )
    result = assemble_grade(inputs)
    # Without the cap, composite ~9.5 and grade should be ~9 or 10
    assert result["final_grade"] >= 9.0, (
        f"Cap should not apply at confidence 0.4, got {result['final_grade']}"
    )
    assert result["constraints_applied"]["centering_cap_activated"] is False


def test_centering_interpolation_midpoint():
    """Linear interpolation: ratio between 60/40 and 55/45 should score between 9 and 10."""
    from grading.grade_assembler import CenteringResult
    from analysis.centering import interpolate_centering_score, FRONT_CAP_TABLE

    # ratio 0.74 — halfway between 0.667 (grade 9) and 0.818 (grade 10)
    score = interpolate_centering_score(0.74, FRONT_CAP_TABLE)
    assert 9.0 < score < 10.0, f"Expected score between 9 and 10, got {score}"


def test_floor_activates_for_uneven_dimensions():
    """Floor prevents composite from going more than 0.5 below worst dimension."""
    # Corners at 5.0, edges and surface at 9.5
    # composite = 5.0*0.30 + 9.5*0.30 + 9.5*0.40 = 1.5 + 2.85 + 3.8 = 8.15
    # worst_dim = 5.0, floor = 5.0 - 0.5 = 4.5 → composite already above floor
    # BUT ceiling = 5.0 + 1.0 = 6.0 → composite 8.15 > 6.0, ceiling fires
    inputs = AssemblyInput(
        corners=_uniform_corners(5.0),
        edges=_uniform_edges(9.5),
        surface=SurfaceScores(front=9.5, back=9.5),
        centering=_perfect_centering(),
    )
    result = assemble_grade(inputs)
    assert result["constraints_applied"]["ceiling_activated"] is True
    assert result["composite_score"] <= 6.0 + 0.01


def test_output_schema_complete():
    """Final output must contain all required top-level fields from PRD 4.7."""
    inputs = _make_input()
    result = assemble_grade(inputs)
    required_keys = [
        "final_grade", "composite_score", "centering_cap", "centering_score",
        "dimension_scores", "individual_scores", "defects",
        "constraints_applied", "confidence",
    ]
    for key in required_keys:
        assert key in result, f"Missing key: {key}"
    assert "corners" in result["dimension_scores"]
    assert "edges" in result["dimension_scores"]
    assert "surface" in result["dimension_scores"]
    assert "corners" in result["individual_scores"]
    assert "edges" in result["individual_scores"]
    assert "surface" in result["individual_scores"]
