"""
Stage 4: Grade Assembly — pure logic, no image analysis.

Takes centering cap + vision AI scores and applies PSA grading rules to produce
a final grade. No OpenCV, no API calls.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CornerScores:
    front_top_left: float
    front_top_right: float
    front_bottom_left: float
    front_bottom_right: float
    back_top_left: float
    back_top_right: float
    back_bottom_left: float
    back_bottom_right: float

    def all_scores(self) -> List[float]:
        return [
            self.front_top_left, self.front_top_right,
            self.front_bottom_left, self.front_bottom_right,
            self.back_top_left, self.back_top_right,
            self.back_bottom_left, self.back_bottom_right,
        ]

    def front_avg(self) -> float:
        return (self.front_top_left + self.front_top_right +
                self.front_bottom_left + self.front_bottom_right) / 4.0

    def back_avg(self) -> float:
        return (self.back_top_left + self.back_top_right +
                self.back_bottom_left + self.back_bottom_right) / 4.0

    def front_worst(self) -> float:
        return min(self.front_top_left, self.front_top_right,
                   self.front_bottom_left, self.front_bottom_right)

    def back_worst(self) -> float:
        return min(self.back_top_left, self.back_top_right,
                   self.back_bottom_left, self.back_bottom_right)


@dataclass
class EdgeScores:
    front_top: float
    front_right: float
    front_bottom: float
    front_left: float
    back_top: float
    back_right: float
    back_bottom: float
    back_left: float

    def all_scores(self) -> List[float]:
        return [
            self.front_top, self.front_right, self.front_bottom, self.front_left,
            self.back_top, self.back_right, self.back_bottom, self.back_left,
        ]

    def front_avg(self) -> float:
        return (self.front_top + self.front_right +
                self.front_bottom + self.front_left) / 4.0

    def back_avg(self) -> float:
        return (self.back_top + self.back_right +
                self.back_bottom + self.back_left) / 4.0


@dataclass
class SurfaceScores:
    front: float
    back: float


@dataclass
class CenteringResult:
    centering_cap: int           # min(front_cap, back_cap) — integer PSA max grade
    front_centering_score: float # worst-axis continuous 1-10, front side (for cap enforcement)
    back_centering_score: float  # worst-axis continuous 1-10, back side (for cap enforcement)
    confidence: float            # from centering.py detection
    # Average-axis scores: fairer overall centering picture, used only for half-point gate.
    # Defaults to worst-axis values for backward compatibility.
    front_avg_centering_score: Optional[float] = None
    back_avg_centering_score: Optional[float] = None

    def __post_init__(self):
        if self.front_avg_centering_score is None:
            self.front_avg_centering_score = self.front_centering_score
        if self.back_avg_centering_score is None:
            self.back_avg_centering_score = self.back_centering_score


@dataclass
class AssemblyInput:
    corners: CornerScores
    edges: EdgeScores
    surface: SurfaceScores
    centering: CenteringResult
    corner_defects: Dict[str, List[str]] = field(default_factory=dict)
    edge_defects: Dict[str, List[str]] = field(default_factory=dict)
    surface_defects: Dict[str, List[str]] = field(default_factory=dict)
    corner_confidences: Dict[str, float] = field(default_factory=dict)
    edge_confidences: Dict[str, float] = field(default_factory=dict)
    surface_confidences: Dict[str, float] = field(default_factory=dict)
    # Raw surface Vision AI dict keyed by "front"/"back". Used only for damage cap
    # logic — not included in API response output.
    surface_raw: Optional[Dict] = field(default=None)


# ---------------------------------------------------------------------------
# Assembly sub-functions
# ---------------------------------------------------------------------------

def _blend_corners(corners: CornerScores) -> Tuple[float, float, float]:
    """
    PRD 4.1: corners 60/40 front-weighted.
    Each side score = 50% avg + 50% worst corner, so a single badly damaged corner
    meaningfully drags the score down rather than being averaged away.
    Returns (blended, front_avg, back_avg) — avgs are returned unchanged for display.
    """
    fa = corners.front_avg()
    ba = corners.back_avg()
    front_score = (fa * 0.5) + (corners.front_worst() * 0.5)
    back_score  = (ba * 0.5) + (corners.back_worst()  * 0.5)
    blended = (front_score * 0.60) + (back_score * 0.40)
    return blended, fa, ba


def _blend_edges(edges: EdgeScores) -> Tuple[float, float, float]:
    """PRD 4.1: edges 65/35 front-weighted. Returns (blended, front_avg, back_avg)."""
    fa = edges.front_avg()
    ba = edges.back_avg()
    blended = (fa * 0.65) + (ba * 0.35)
    return blended, fa, ba


def _blend_surface(surface: SurfaceScores) -> float:
    """PRD 4.1: surface 70/30 front-weighted."""
    return (surface.front * 0.70) + (surface.back * 0.30)


def _composite(corners_blended: float, edges_blended: float, surface_blended: float) -> float:
    """PRD 4.2: corners 37.5% + edges 37.5% + surface 25% (centering excluded, proportionally renormalized from 30/30/20)."""
    return (corners_blended * 0.375) + (edges_blended * 0.375) + (surface_blended * 0.25)


def _apply_floor_ceiling(
    composite: float,
    corners_blended: float,
    edges_blended: float,
    surface_blended: float,
) -> Tuple[float, bool, bool]:
    """
    PRD 4.3: dimension-level floor/ceiling.
    floor:   composite >= worst_dim - 0.5
    ceiling: composite <= worst_dim + 1.0
    Returns (constrained, floor_activated, ceiling_activated).
    """
    worst = min(corners_blended, edges_blended, surface_blended)
    floor_act = composite < (worst - 0.5)
    ceiling_act = composite > (worst + 1.0)
    # Clamp floor and ceiling to [1.0, 10.0] to prevent e.g. worst_dim=9.5 producing
    # a ceiling of 10.5, or worst_dim=0.5 producing a floor below 1.0.
    floor = max(worst - 0.5, 1.0)
    ceiling = min(worst + 1.0, 10.0)
    result = max(composite, floor)
    result = min(result, ceiling)
    return result, floor_act, ceiling_act


def _apply_damage_cap(
    composite: float,
    surface_raw: Optional[Dict],
    surface_confidences: Dict[str, float],
) -> Tuple[float, bool, Optional[str]]:
    """
    Hard cap for severe physical damage. Applied after floor/ceiling, before centering cap.
    Only activated when surface confidence >= 0.60 for that side.

    Cap rules (either side triggers):
      heavy crease     → cap at 3.0
      moderate crease  → cap at 5.0
      extensive whitening → cap at 5.0

    Returns (capped_composite, cap_activated, cap_reason).
    """
    if surface_raw is None:
        return composite, False, None

    CREASE_ORDER    = {"none": 0, "hairline": 1, "moderate": 2, "heavy": 3}
    WHITENING_ORDER = {"none": 0, "minor": 1, "moderate": 2, "extensive": 3}
    cap = None
    reason = None

    for side in ("front", "back"):
        data = surface_raw.get(side, {})
        if surface_confidences.get(side, 0.0) < 0.60:
            continue  # Not confident enough in this side's damage detection

        crease    = data.get("crease_depth")
        whitening = data.get("whitening_coverage")

        if crease and CREASE_ORDER.get(crease, 0) >= 3:     # heavy
            if cap is None or cap > 3.0:
                cap = 3.0
                reason = f"heavy crease on {side} surface"
        elif crease and CREASE_ORDER.get(crease, 0) >= 2:   # moderate
            if cap is None or cap > 5.0:
                cap = 5.0
                reason = f"moderate crease on {side} surface"

        if whitening and WHITENING_ORDER.get(whitening, 0) >= 3:  # extensive
            if cap is None or cap > 5.0:
                cap = 5.0
                reason = f"extensive whitening on {side} surface"

    if cap is not None and composite > cap:
        return cap, True, reason

    return composite, False, None


def _apply_centering_cap(
    composite: float,
    centering_cap: int,
    centering_confidence: float,
) -> Tuple[float, bool]:
    """
    PRD 4.5: hard clamp by centering cap, only when confidence >= 0.6.
    Returns (clamped, cap_activated).
    """
    if centering_confidence < 0.6:
        return composite, False
    cap_f = float(centering_cap)
    activated = composite > cap_f
    return min(composite, cap_f), activated


def _half_point_grade(final_score: float, centering: CenteringResult) -> Tuple[float, bool]:
    """
    PRD 4.6: half-point bump.
    Requires score fractional >= 0.3 AND worst AVERAGE-AXIS centering score >= base + 1.
    Uses average-axis centering (not worst-axis) because worst-axis already does its job
    as the hard cap upstream — applying it again here would double-penalise borderline cards.
    Returns (displayed_grade, qualified).
    """
    base = math.floor(final_score)
    fractional = final_score - base
    worst_avg_centering = min(
        centering.front_avg_centering_score,
        centering.back_avg_centering_score,
    )
    qualifies = (fractional >= 0.3) and (worst_avg_centering >= base + 1)
    displayed = base + 0.5 if qualifies else float(base)
    return displayed, qualifies


def _severity(score: float) -> str:
    if score >= 8.0:
        return "minor"
    elif score >= 6.0:
        return "moderate"
    return "severe"


def _collect_defects(
    corners: CornerScores,
    edges: EdgeScores,
    surface: SurfaceScores,
    corner_defects: Dict[str, List[str]],
    edge_defects: Dict[str, List[str]],
    surface_defects: Dict[str, List[str]],
) -> List[Dict]:
    """Build unified defect list for output. Only include locations scoring below 8.5."""
    result = []

    corner_score_map = {
        "front_top_left": corners.front_top_left,
        "front_top_right": corners.front_top_right,
        "front_bottom_left": corners.front_bottom_left,
        "front_bottom_right": corners.front_bottom_right,
        "back_top_left": corners.back_top_left,
        "back_top_right": corners.back_top_right,
        "back_bottom_left": corners.back_bottom_left,
        "back_bottom_right": corners.back_bottom_right,
    }
    for loc, score in corner_score_map.items():
        if score < 8.5:
            defects = corner_defects.get(loc, [])
            desc = ", ".join(defects) if defects else "wear detected"
            result.append({
                "location": f"{loc}_corner",
                "description": desc,
                "severity": _severity(score),
            })

    edge_score_map = {
        "front_top": edges.front_top,
        "front_right": edges.front_right,
        "front_bottom": edges.front_bottom,
        "front_left": edges.front_left,
        "back_top": edges.back_top,
        "back_right": edges.back_right,
        "back_bottom": edges.back_bottom,
        "back_left": edges.back_left,
    }
    for loc, score in edge_score_map.items():
        if score < 8.5:
            defects = edge_defects.get(loc, [])
            desc = ", ".join(defects) if defects else "wear detected"
            result.append({
                "location": f"{loc}_edge",
                "description": desc,
                "severity": _severity(score),
            })

    for side in ("front", "back"):
        score = surface.front if side == "front" else surface.back
        if score < 8.5:
            defects = surface_defects.get(side, [])
            desc = ", ".join(defects) if defects else "surface wear"
            result.append({
                "location": f"{side}_surface",
                "description": desc,
                "severity": _severity(score),
            })

    return result


def _calculate_confidence(
    corner_confidences: Dict[str, float],
    edge_confidences: Dict[str, float],
    surface_confidences: Dict[str, float],
) -> Tuple[float, List[str]]:
    """
    Average all per-location confidences. Flag any below 0.60.
    Returns (overall_confidence, low_confidence_flags).
    """
    all_confs: Dict[str, float] = {}
    all_confs.update({f"corner_{k}": v for k, v in corner_confidences.items()})
    all_confs.update({f"edge_{k}": v for k, v in edge_confidences.items()})
    all_confs.update({f"surface_{k}": v for k, v in surface_confidences.items()})

    if not all_confs:
        return 0.5, []

    overall = sum(all_confs.values()) / len(all_confs)
    flags = [loc for loc, conf in all_confs.items() if conf < 0.60]
    return round(overall, 3), flags


# ---------------------------------------------------------------------------
# Master orchestrator
# ---------------------------------------------------------------------------

def assemble_grade(inputs: AssemblyInput) -> Dict:
    """
    Apply PSA grading rules as pure logic.
    Pipeline order (must not be reordered):
      1. Front/back blend
      2. Composite
      3. Dimension floor/ceiling
      3.5. Damage cap (heavy crease / extensive whitening)
      4. Centering cap
      5. Half-point grade
    """
    # 1. Blend
    corners_blended, corners_fa, corners_ba = _blend_corners(inputs.corners)
    edges_blended, edges_fa, edges_ba = _blend_edges(inputs.edges)
    surface_blended = _blend_surface(inputs.surface)

    # 2. Composite
    composite = _composite(corners_blended, edges_blended, surface_blended)

    # 3. Dimension floor/ceiling
    composite, floor_act, ceiling_act = _apply_floor_ceiling(
        composite, corners_blended, edges_blended, surface_blended
    )

    # 3.5. Damage cap — must come before centering cap so that e.g. a heavy crease (cap=3)
    # always wins over a loose centering cap (e.g. cap=6).
    composite, damage_cap_act, damage_cap_reason = _apply_damage_cap(
        composite, inputs.surface_raw, inputs.surface_confidences
    )

    # 4. Centering cap (applied before half-point so capped scores naturally fail
    #    the 0.3 fractional threshold at grade boundaries)
    composite, cap_act = _apply_centering_cap(
        composite, inputs.centering.centering_cap, inputs.centering.confidence
    )

    # 5. Half-point grade
    displayed_grade, half_point_qualified = _half_point_grade(composite, inputs.centering)

    # Confidence + defects
    overall_conf, low_conf_flags = _calculate_confidence(
        inputs.corner_confidences,
        inputs.edge_confidences,
        inputs.surface_confidences,
    )
    defects = _collect_defects(
        inputs.corners, inputs.edges, inputs.surface,
        inputs.corner_defects, inputs.edge_defects, inputs.surface_defects,
    )

    # Use front centering score in the summary (worst of front/back was used for half-point;
    # expose the combined context via both)
    summary_centering_score = min(
        inputs.centering.front_centering_score,
        inputs.centering.back_centering_score,
    )

    return {
        "final_grade": displayed_grade,
        "composite_score": round(composite, 2),
        "centering_cap": inputs.centering.centering_cap,
        "centering_score": round(summary_centering_score, 2),
        "dimension_scores": {
            "corners": {
                "blended": round(corners_blended, 2),
                "front_avg": round(corners_fa, 2),
                "back_avg": round(corners_ba, 2),
            },
            "edges": {
                "blended": round(edges_blended, 2),
                "front_avg": round(edges_fa, 2),
                "back_avg": round(edges_ba, 2),
            },
            "surface": {
                "blended": round(surface_blended, 2),
                "front": inputs.surface.front,
                "back": inputs.surface.back,
            },
        },
        "individual_scores": {
            "corners": {
                "front_top_left": inputs.corners.front_top_left,
                "front_top_right": inputs.corners.front_top_right,
                "front_bottom_left": inputs.corners.front_bottom_left,
                "front_bottom_right": inputs.corners.front_bottom_right,
                "back_top_left": inputs.corners.back_top_left,
                "back_top_right": inputs.corners.back_top_right,
                "back_bottom_left": inputs.corners.back_bottom_left,
                "back_bottom_right": inputs.corners.back_bottom_right,
            },
            "edges": {
                "front_top": inputs.edges.front_top,
                "front_right": inputs.edges.front_right,
                "front_bottom": inputs.edges.front_bottom,
                "front_left": inputs.edges.front_left,
                "back_top": inputs.edges.back_top,
                "back_right": inputs.edges.back_right,
                "back_bottom": inputs.edges.back_bottom,
                "back_left": inputs.edges.back_left,
            },
            "surface": {
                "front": inputs.surface.front,
                "back": inputs.surface.back,
            },
        },
        "defects": defects,
        "constraints_applied": {
            "floor_activated": floor_act,
            "ceiling_activated": ceiling_act,
            "damage_cap_activated": damage_cap_act,
            "damage_cap_reason": damage_cap_reason,
            "centering_cap_activated": cap_act,
            "half_point_qualified": half_point_qualified,
        },
        "confidence": {
            "overall": overall_conf,
            "level": "High" if overall_conf >= 0.75 else "Medium" if overall_conf >= 0.55 else "Low",
            "low_confidence_flags": low_conf_flags,
        },
    }
