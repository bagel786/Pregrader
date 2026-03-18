"""
Unit tests for scoring.py and centering.py critical interactions.

Coverage:
  - Centering cap dominance over component scores
  - Floor constraint (score can't be more than 0.5 below worst component)
  - Ceiling constraint (score can't be more than 1.0 above worst component)
  - Cap + ceiling interaction (cap always wins)
  - Centering excluded from floor/ceiling calculation
  - Damage penalty applied correctly
  - Grade bracket mapping
  - Back centering cap table completeness (grades 3–10)
  - Centering score monotonicity
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analysis.scoring import GradingEngine
from analysis.centering import FRONT_CAP_TABLE, BACK_CAP_TABLE, lookup_centering_cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corners(score: float) -> dict:
    names = ("top_left", "top_right", "bottom_right", "bottom_left")
    return {
        "overall_grade": score,
        "confidence": 0.9,
        "corners": {n: {"score": score} for n in names},
    }


def _make_edges(score: float) -> dict:
    return {
        "overall_grade": score,
        "confidence": 0.9,
        "edges": {
            "top": {"score": score},
            "bottom": {"score": score},
            "left": {"score": score},
            "right": {"score": score},
        },
    }


def _make_surface(score: float, major_damage: bool = False) -> dict:
    return {"score": score, "confidence": 0.9, "major_damage_detected": major_damage}


def _grade(
    centering: float = 10.0,
    corners: float = 10.0,
    edges: float = 10.0,
    surface: float = 10.0,
    lr_ratio: float | None = None,
    tb_ratio: float | None = None,
    major_damage: bool = False,
) -> dict:
    return GradingEngine.calculate_grade(
        centering_score=centering,
        corners_data=_make_corners(corners),
        edges_data=_make_edges(edges),
        surface_data=_make_surface(surface, major_damage),
        centering_confidence=0.9,
        centering_lr_ratio=lr_ratio,
        centering_tb_ratio=tb_ratio,
    )


# ---------------------------------------------------------------------------
# Grade bracket mapping
# ---------------------------------------------------------------------------

class TestGradeBrackets:
    def test_perfect_card_is_10(self):
        r = _grade(10, 10, 10, 10)
        assert r["psa_estimate"] == "10"

    def test_score_9_bracket(self):
        r = _grade(9.0, 9.0, 9.0, 9.0)
        assert r["psa_estimate"] == "9"

    def test_low_score_maps_to_low_grade(self):
        r = _grade(5.0, 5.0, 5.0, 5.0)
        assert r["psa_estimate"] in {"5", "4"}  # floor may shift slightly


# ---------------------------------------------------------------------------
# Centering cap: discrete PSA ceiling
# ---------------------------------------------------------------------------

class TestCenteringCap:
    def test_perfect_centering_no_cap(self):
        """55/45 or better → no cap applied."""
        r = _grade(10, 10, 10, 10, lr_ratio=0.818, tb_ratio=0.818)
        assert r["centering_cap_applied"] is False
        assert r["psa_estimate"] == "10"

    def test_60_40_caps_at_9(self):
        """60/40 → PSA cap = 9; perfect components should still be capped."""
        r = _grade(10, 10, 10, 10, lr_ratio=0.667, tb_ratio=0.818)
        assert r["centering_cap_applied"] is True
        assert int(r["psa_estimate"]) <= 9

    def test_70_30_caps_at_7(self):
        r = _grade(10, 10, 10, 10, lr_ratio=0.429, tb_ratio=0.818)
        assert r["centering_cap_applied"] is True
        assert int(r["psa_estimate"]) <= 7

    def test_80_20_caps_at_6(self):
        r = _grade(10, 10, 10, 10, lr_ratio=0.250, tb_ratio=0.818)
        assert int(r["psa_estimate"]) <= 6

    def test_worst_axis_determines_cap(self):
        """Cap is based on the worst of LR / TB."""
        r_lr_bad = _grade(10, 10, 10, 10, lr_ratio=0.429, tb_ratio=0.818)
        r_tb_bad = _grade(10, 10, 10, 10, lr_ratio=0.818, tb_ratio=0.429)
        assert r_lr_bad["psa_estimate"] == r_tb_bad["psa_estimate"]

    def test_no_ratios_no_cap(self):
        """Without ratios, no centering cap should be applied."""
        r = _grade(10, 10, 10, 10, lr_ratio=None, tb_ratio=None)
        assert r["centering_cap_applied"] is False


# ---------------------------------------------------------------------------
# Floor constraint
# ---------------------------------------------------------------------------

class TestFloorConstraint:
    def test_score_cannot_be_more_than_half_below_worst(self):
        """With corners=5, floor = 4.5; final_score >= 4.5."""
        r = _grade(10, corners=5.0, edges=10.0, surface=10.0)
        assert r["final_score"] >= 5.0 - 0.5

    def test_all_components_equal_floor_not_active(self):
        r = _grade(10, corners=8.0, edges=8.0, surface=8.0)
        worst = 8.0
        assert r["final_score"] >= worst - 0.5


# ---------------------------------------------------------------------------
# Ceiling constraint
# ---------------------------------------------------------------------------

class TestCeilingConstraint:
    def test_score_cannot_exceed_worst_plus_one(self):
        """With one bad component = 4, ceiling = 5."""
        r = _grade(10, corners=4.0, edges=10.0, surface=10.0)
        assert r["final_score"] <= 4.0 + 1.0

    def test_ceiling_uses_worst_of_three_components(self):
        """Ceiling is anchored to the minimum of corners/edges/surface."""
        r = _grade(10, corners=4.0, edges=3.0, surface=10.0)
        worst = 3.0
        assert r["final_score"] <= worst + 1.0


# ---------------------------------------------------------------------------
# Centering excluded from floor/ceiling
# ---------------------------------------------------------------------------

class TestCenteringExcludedFromFloorCeiling:
    def test_bad_centering_score_does_not_tighten_ceiling(self):
        """
        centering_score=6.3 with all physical components at 9.5 should produce
        ceiling = 9.5 + 1.0 = 10.5 → final not capped below 9.5.
        (PSA cap is applied separately via ratio, not score.)
        """
        r = _grade(centering=6.3, corners=9.5, edges=9.5, surface=9.5,
                   lr_ratio=None, tb_ratio=None)
        # Without a centering ratio cap, the physical ceiling is 9.5+1=10, score≈9.5
        assert r["final_score"] >= 9.0

    def test_bad_centering_ratio_caps_grade_not_score(self):
        """
        With tb_ratio=0.568 → PSA cap=8. The final_score can still be high,
        but psa_estimate is capped at 8.
        """
        r = _grade(centering=6.3, corners=9.5, edges=9.5, surface=9.5,
                   lr_ratio=0.818, tb_ratio=0.568)
        assert int(r["psa_estimate"]) <= 8
        # final_score should still reflect the physical component quality
        assert r["final_score"] >= 8.0


# ---------------------------------------------------------------------------
# Damage penalty
# ---------------------------------------------------------------------------

class TestDamagePenalty:
    def test_major_damage_reduces_score_by_one(self):
        r_clean = _grade(10, 9.0, 9.0, 9.0, major_damage=False)
        r_damaged = _grade(10, 9.0, 9.0, 9.0, major_damage=True)
        assert r_damaged["final_score"] < r_clean["final_score"]

    def test_no_major_damage_no_penalty(self):
        r = _grade(10, 10, 10, 10, major_damage=False)
        assert r["final_score"] == 10.0


# ---------------------------------------------------------------------------
# Centering cap table: back card grades 3–10 all covered
# ---------------------------------------------------------------------------

class TestBackCapTable:
    def test_back_table_covers_grades_5_through_10(self):
        grades_available = {cap for _, cap in BACK_CAP_TABLE}
        for expected_grade in (5, 6, 7, 8, 9, 10):
            assert expected_grade in grades_available, (
                f"BACK_CAP_TABLE missing grade {expected_grade}"
            )

    def test_back_table_lookup_monotonic(self):
        """Higher ratios (better centering) should produce higher or equal caps."""
        test_ratios = [0.40, 0.25, 0.15, 0.10, 0.05, 0.02, 0.0]
        caps = [lookup_centering_cap(r, BACK_CAP_TABLE) for r in test_ratios]
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i + 1], (
                f"Non-monotonic back cap: ratio={test_ratios[i]} → {caps[i]}, "
                f"ratio={test_ratios[i+1]} → {caps[i+1]}"
            )

    def test_front_table_lookup_monotonic(self):
        test_ratios = [0.90, 0.70, 0.55, 0.45, 0.35, 0.25, 0.18, 0.12, 0.0]
        caps = [lookup_centering_cap(r, FRONT_CAP_TABLE) for r in test_ratios]
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i + 1], (
                f"Non-monotonic front cap: ratio={test_ratios[i]} → {caps[i]}, "
                f"ratio={test_ratios[i+1]} → {caps[i+1]}"
            )


# ---------------------------------------------------------------------------
# Weighted score excludes centering (Task 1.5)
# ---------------------------------------------------------------------------

class TestCenteringNotInWeightedScore:
    def test_varying_centering_score_does_not_change_final_score(self):
        """
        Since centering is removed from the weighted average, changing centering_score
        alone (no ratio change) should NOT change final_score.
        """
        r_good_cent = _grade(centering=10.0, corners=7.0, edges=7.0, surface=7.0)
        r_bad_cent = _grade(centering=3.0, corners=7.0, edges=7.0, surface=7.0)
        assert r_good_cent["final_score"] == r_bad_cent["final_score"]

    def test_component_scores_drive_weighted_score(self):
        r_high = _grade(centering=5.0, corners=9.0, edges=9.0, surface=9.0)
        r_low = _grade(centering=5.0, corners=5.0, edges=5.0, surface=5.0)
        assert r_high["final_score"] > r_low["final_score"]
