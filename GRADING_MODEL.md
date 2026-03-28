# Pregrader Grading Model — Complete Technical Reference

**Version:** As of March 2026 (post-Round-7 audit)
**Scope:** Backend only (`backend/`). Flutter frontend not covered here.
**Purpose:** Authoritative reference for the grading algorithm, pipeline architecture, Vision AI integration, and all constants. Intended for developers, auditors, and future calibration work.

---

## Table of Contents

1. [Pipeline Architecture Overview](#1-pipeline-architecture-overview)
2. [Stage-by-Stage Flow](#2-stage-by-stage-flow)
3. [Scoring Logic — grade_assembler.py](#3-scoring-logic--grade_assemblerpy)
4. [Centering Detection — centering.py](#4-centering-detection--centeringpy)
5. [Vision AI Integration — vision_assessor.py](#5-vision-ai-integration--vision_assessorpy)
6. [Damage Detection Deep Dive](#6-damage-detection-deep-dive)
7. [OpenCV Corner Analysis — corners.py](#7-opencv-corner-analysis--cornerspy)
8. [Front/Back Side Detection](#8-frontback-side-detection)
9. [Blending Logic Summary](#9-blending-logic-summary)
10. [Constants & Thresholds Reference](#10-constants--thresholds-reference)
11. [Session Management](#11-session-management)
12. [API Flow & Endpoints](#12-api-flow--endpoints)
13. [Edge Cases & Guards](#13-edge-cases--guards)
14. [Known Limitations & Deferred Work](#14-known-limitations--deferred-work)

---

## 1. Pipeline Architecture Overview

```
Flutter Client
    |
    v
POST /api/grading/start
    | creates GradingSession (UUID, 30-min TTL)
    v
POST /api/grading/{id}/upload-front
    |
    +-- Size check (15 MB)
    +-- Quality gate (check_image_quality)
    +-- Hybrid detection -> perspective-corrected image
    +-- OpenCV centering (Stage 2, front)
    +-- OpenCV corner analysis (stored for cross-check)
    +-- Store front_analysis in session
    v
POST /api/grading/{id}/upload-back
    |
    +-- Size check (15 MB)
    +-- Quality gate
    +-- Hybrid detection -> perspective-corrected image
    +-- OpenCV centering (Stage 2, back)
    +-- OpenCV corner analysis (stored for cross-check)
    +-- combine_front_back_analysis() [in asyncio.to_thread]
         |
         +-- Stage 3:  Vision AI assess_card()          [2-3 API calls]
         +-- Stage 3b: assess_damage_from_full_images() [1 API call]
         +-- Stage 3c: Enhanced preprocessing + assess_damage [1 API call, front only]
         +-- Stage 3d: detect_border_wear() [OpenCV only]
         +-- Stage 3e: detect_surface_creases() [OpenCV only]
         +-- Consistency check (crease -> whitening)
         +-- Surface score adjustment (sync scores to caps)
         +-- OpenCV corner cross-check (confidence reduction)
         +-- Stage 4: assemble_grade()                  [pure logic]
         +-- Stage 5: annotate_card_image()             [non-blocking]
    v
Response: grading dict + details + warnings
    v
GET /api/grading/{id}/result  (optional cache read)
```

**Key architectural decisions:**

- `combine_front_back_analysis()` is wrapped in `asyncio.to_thread` (`grading.py:266-268`) so synchronous OpenCV and httpx calls do not block the FastAPI event loop.
- All Vision AI calls in `vision_assessor.py` use synchronous `httpx.Client` (not async), which is correct inside `to_thread`.
- Stages 3 through 3e all operate upgrade-only on the shared `vision_result` dict. No stage can downgrade a prior stage's damage labels.
- `assemble_grade()` (Stage 4) is pure logic — no I/O, no image operations. This makes it fast, deterministic, and independently testable.

---

## 2. Stage-by-Stage Flow

### 2.1 Session & Upload

**Files:** `backend/api/routers/sessions.py`, `backend/api/routers/grading.py`

1. `POST /api/grading/start` creates a `GradingSession` (UUID4). Stored in the in-memory `_session_manager._sessions` dict. `expires_at = now + 30 min`.
2. `POST /api/grading/{id}/upload-front` saves bytes to `temp_uploads/{session_id}/front_{filename}`. Resets `back_analysis` and `combined_grade` to `None` (`grading.py:130-137`), preventing stale data when the front is re-uploaded.
3. `POST /api/grading/{id}/upload-back` saves bytes, runs the full analysis pipeline, and returns the combined grade.
4. `GET /api/grading/{id}/result` reads cached `session.combined_grade` without re-running analysis.

File size limit: `MAX_UPLOAD_BYTES = 15 * 1024 * 1024` (15 MB), enforced at `grading.py:44` and `grading.py:192` before any disk write.

### 2.2 Card Detection / Perspective Correction

**File:** `backend/api/hybrid_detect.py`

`detect_and_correct_card(image_path, session_id)` runs:

1. **OpenCV fast path:** Tries 4 OpenCV methods (standard contour, adaptive threshold, morphological, Hough). Returns on first success when `confidence >= OPENCV_THRESHOLD` (default 0.70).
2. **Vision AI fallback:** If all OpenCV methods fail or confidence is below threshold, calls Vision AI (gated by `_ai_semaphore`, max 5 concurrent requests) to detect card boundaries.

Returns: `{success, corrected_image (numpy array), method, confidence, border_fractions, quality_assessment}`.

`border_fractions` (Vision AI detection path only): left/right/top/bottom border fractions returned by the detection Vision AI call. Passed directly to `calculate_centering_ratios()` as Method 0 — the highest-priority centering detection path.

### 2.3 Quality Gate

**File:** `backend/analysis/vision/quality_checks.py`

`check_image_quality(path)` runs before any analysis. Returns `can_analyze: bool`. When `can_analyze=False`, the endpoint returns HTTP 400 with `issues` and `user_feedback` arrays (`grading.py:62-71`).

The quality check evaluates blur, lighting exposure, and card angle. Its minimum resolution threshold is 400px, which is below the Flutter-side 600px hard block — a small gap (400-600px) exists where the server accepts images that the client would reject.

### 2.4 OpenCV Centering (Stage 2)

**File:** `backend/analysis/centering.py`

Called via `analyze_single_side()` (`combined_grading.py:111-117`) for both front and back, using `detection_data` from the hybrid detector. The centering result is not used until Stage 4 — it is stored in `front_analysis["centering"]` and `back_analysis["centering"]` for later retrieval.

See Section 4 for the full detection chain.

### 2.5 Vision AI Assessment (Stage 3)

**File:** `backend/grading/vision_assessor.py`

`assess_card(front_img, back_img)` is the primary visual assessment. Sends 6 composite images to Claude Vision and receives per-corner, per-edge, and per-surface scores plus damage labels. See Section 5 for full detail.

### 2.6 Damage Assessment (Stage 3b)

**File:** `backend/grading/vision_assessor.py`, function `assess_damage_from_full_images()`

A second, separate Vision AI call using `damage_assessment_prompt.txt`. Uses full (non-cropped) card images at JPEG quality 95 to maximize damage detail. Focuses exclusively on `crease_depth` and `whitening_coverage`.

Merge logic (`combined_grading.py:483-507`):
- `heavy` crease from Stage 3b always overwrites Stage 3's crease label.
- `moderate` crease upgrades to `moderate` only if Stage 3 found `none` or `hairline`.
- `extensive` whitening always overwrites.
- `moderate` whitening upgrades if Stage 3 found `none` or `minor`.

This is a pure upgrade merge — Stage 3b can only make labels worse, never better.

### 2.7 Enhanced Damage Preprocessing (Stage 3c)

**Files:** `backend/analysis/damage_preprocessing.py`, `backend/grading/vision_assessor.py`

Runs `enhance_for_damage_detection(front_img)` on the front image, then calls `assess_damage_from_full_images()` again with the enhanced front and the original back.

**Why front only gets preprocessed:** Back cards (standard blue Pokeball design) have no holographic foil. Applying CLAHE and histogram equalization to them over-smoothed crease signals — back creases correctly detected in Stage 3b disappeared in Stage 3c when preprocessing was applied uniformly. Back cards now use the original image in Stage 3c.

`enhance_for_damage_detection()` applies:
- Grayscale conversion (removes holographic rainbow noise)
- Split-region CLAHE: `clipLimit=1.5` on card border region, `clipLimit=1.0` on interior artwork
- Histogram equalization on border only; skipped for white-dominant cards (border mean >= 200) to avoid compressing near-white histograms and masking wear signals
- Convert back to BGR for Vision AI input

Merge logic (`combined_grading.py:546-564`): upgrade-only across both `crease_depth` and `whitening_coverage`. When Stage 3c upgrades crease severity, it floors surface confidence to `max(current, 0.65)` to ensure the 0.60 damage-cap gate is met.

### 2.8 OpenCV Border Wear (Stage 3d)

**File:** `backend/analysis/texture.py`

`detect_border_wear(image)` runs multi-scale Sobel gradient plus local std dev on a 12%-margin border region. Returns `whitening_coverage` in `{none, minor, moderate, extensive}`.

Confidence is hardcoded to `0.55` — deliberately below the 0.60 damage cap gate. This means Stage 3d affects the `whitening_coverage` label (visible in UI) but cannot by itself trigger a grade cap. Vision AI confirmation is required to enforce a penalty.

Active flag: `STAGE_3D_ACTIVE = True` (`combined_grading.py:588`).

### 2.9 OpenCV Crease Detection (Stage 3e)

**File:** `backend/analysis/creases.py`

`detect_surface_creases(image, side)` runs HoughLinesP on the Stage 3c preprocessed image (for front) or original image (for back).

- Strips a 7% interior margin to avoid card border artifacts.
- Detects holofoil cards via short-line density (threshold: 120 lines). Applies tighter `MIN_LINE_FRACTION` for holo cards (0.22 vs 0.15).
- Angle filter: excludes lines within 10 degrees of horizontal or vertical axes (card frame lines).
- False positive filter: more than 20 lines indicates printing texture, not a crease — output is downgraded to `none`.

When Stage 3e upgrades a crease to `moderate` or `heavy`, it floors surface confidence to `max(current, 0.65)`.

Active flag: `STAGE_3E_ACTIVE = True` (`combined_grading.py:622`).

### 2.10 Surface Score Adjustment

**File:** `backend/api/combined_grading.py` (lines 662-687)

After all damage detection stages complete, surface scores are adjusted downward to be consistent with detected crease severity. Without this, a surface score of 8.5 alongside a `heavy` crease cap of 2.0 would confuse the UI.

| Crease Severity | Score Ceiling Applied |
|---|---|
| `heavy` | `min(current_score, 2.5)` |
| `moderate` | `min(current_score, 5.0)` |
| `hairline` | `min(current_score, 6.5)` |

This only caps scores downward — it never raises them.

### 2.11 Crease-Whitening Consistency Check

**File:** `backend/api/combined_grading.py` (lines 570-581)

Enforces the physical reality that a `moderate` or `heavy` crease always produces some surface stress whitening at the fold line. If any stage reported a crease at those severities but `whitening_coverage == "none"`, it is forced to `"minor"`.

This prevents a mismatch where the damage cap fires on crease while the whitening label shows clean, which would make the UI explanation confusing.

### 2.12 OpenCV Corner Cross-Check

**File:** `backend/api/combined_grading.py` (lines 369-406, `_apply_opencv_corner_cross_check`)

Compares the OpenCV `overall_grade` (from `analyze_corners()` in `corners.py`, stored during upload) against Vision AI's average corner score for the same side. If they diverge by more than 2.0:
- Per-location corner confidences are reduced by 0.2 (floored at 0.3) for that side.
- A warning flag is appended to `combined["warnings"]`.

This catches Vision AI hallucinating high corner scores on a visibly damaged card. Only confidence is modified — scores are never changed by this step.

### 2.13 Grade Assembly (Stage 4)

**File:** `backend/grading/grade_assembler.py`

Pure-logic function `assemble_grade(AssemblyInput)`. No I/O. See Section 3 for full detail.

### 2.14 Annotated Image (Stage 5)

**File:** `backend/analysis/annotation.py`

`annotate_card_image()` draws corner and edge scores onto the front card image and returns a base64-encoded JPEG. Non-blocking — failure is silently caught and logged. If it fails, the grading response is returned without an annotated image.

---

## 3. Scoring Logic — grade_assembler.py

### 3.1 Front/Back Blending

**Functions:** `_blend_corners`, `_blend_edges`, `_blend_surface` (`grade_assembler.py:126-151`)

#### Corners (60/40 front-weighted)

Each side score combines average and worst corner with equal weight:

```python
front_score = (front_avg * 0.5) + (front_worst * 0.5)
back_score  = (back_avg  * 0.5) + (back_worst  * 0.5)
blended     = (front_score * 0.60) + (back_score * 0.40)
```

**Why 50/50 avg+worst within a side:** Averaging 4 corners alone lets a single severely damaged corner get washed out by the other three. The 50% worst-corner component ensures one bad corner meaningfully drags the side score down. A card with three corners at 10.0 and one at 4.0 produces a side score of 7.0 (`(8.5 * 0.5) + (4.0 * 0.5)`) rather than 8.5.

**Why 60/40 front/back:** The front is the primary collector-facing side. PSA and BGS both weight front condition more heavily than back.

#### Edges (65/35 front-weighted)

```python
blended = (front_avg * 0.65) + (back_avg * 0.35)
```

No worst-edge component. Edges are continuous strips where averaging all 4 per side gives a reasonable picture without over-penalizing a single worn edge.

#### Surface (70/30 front-weighted)

```python
blended = (surface.front * 0.70) + (surface.back * 0.30)
```

Front surface is the primary collector-facing side. Back surface damage is visible but less impactful to grade perception.

### 3.2 Composite Formula

**Function:** `_composite` (`grade_assembler.py:154-156`)

```python
composite = (corners_blended * 0.375) + (edges_blended * 0.375) + (surface_blended * 0.25)
```

**Why these weights:** Centering is handled as a hard cap, not a composite component. The remaining three dimensions — corners (30%), edges (30%), surface (20%) — are renormalized to 1.0 by dividing by 0.80:
- `30 / 80 = 0.375` for corners
- `30 / 80 = 0.375` for edges
- `20 / 80 = 0.250` for surface

Centering is excluded from the composite entirely. A poorly centered card receives its full physical-damage grade first, then the centering cap is applied as a hard ceiling afterward.

### 3.3 Dimension Floor/Ceiling

**Function:** `_apply_floor_ceiling` (`grade_assembler.py:159-180`)

```python
worst = min(corners_blended, edges_blended, surface_blended)
floor   = max(worst - 0.5, 1.0)
ceiling = min(worst + 1.0, 10.0)
result  = clamp(composite, floor, ceiling)
```

**Why floor/ceiling:** The composite is a weighted average. Without a ceiling, a card with flawless corners and edges but a destroyed surface could achieve a misleadingly high composite score. The `worst + 1.0` ceiling prevents the composite from being more than one grade point above the weakest dimension. The `worst - 0.5` floor prevents the composite from falling too far below the worst dimension.

**Why centering is excluded:** Centering is enforced as a hard cap in Step 4.5. Including it in floor/ceiling would double-penalize off-center cards — once through the composite weights (if it were included) or floor/ceiling spread, and again through the cap. The documented algorithm explicitly excludes centering from floor/ceiling.

**Bounds guard:** Floor and ceiling are clamped to [1.0, 10.0] to prevent pathological edge cases (e.g., `worst = 0.5` producing a floor below 1.0, or `worst = 9.5` producing a ceiling above 10.0).

### 3.4 Damage Cap

**Function:** `_apply_damage_cap` (`grade_assembler.py:183-239`)

Applied after floor/ceiling (Step 3.5), before centering cap.

```
Gate: surface_confidence[side] >= 0.60 (checked per side independently)

heavy crease      -> cap = 2.0  (calibrated from TAG data)
moderate crease   -> cap = 5.0  (heuristic -- no TAG calibration yet)
extensive whitening -> cap = 5.0  (heuristic)

Either side (front or back) independently triggers its cap.
Most-severe-wins: if both sides trigger, the lower cap value wins.
```

**Why heavy crease = 2.0 (not 3.0):** Calibrated against a TAG grading report where a card with a single wrinkle/crease and otherwise perfect corners, edges, and centering received PSA 2. The original cap of 3.0 was too lenient.

**Why the 0.60 confidence gate:** Without a gate, low-quality image detections (blur, backlighting, angle) could falsely activate a cap and crush the grade. Stages 3c and 3e floor confidence to 0.65 when they detect damage, ensuring the gate is met for those signals. Stage 3d (OpenCV border texture) deliberately has confidence 0.55, below the gate.

**Pipeline ordering:** The damage cap must come before the centering cap. A heavy crease (cap=2.0) should always override a lenient centering cap (e.g., cap=6). Reversing the order would allow a clean-centering card with a crease to escape the 2.0 cap.

### 3.5 Centering Cap

**Function:** `_apply_centering_cap` (`grade_assembler.py:242-255`)

```python
if centering_confidence < 0.6:
    return composite, False   # cap not applied
result = min(composite, float(centering_cap))   # never raises the score
```

`centering_cap = min(front_cap, back_cap)` is computed in `_build_centering_result()` (`combined_grading.py:150-151`). The worse side's cap always wins.

Detection methods with confidence below 0.60 (gradient at 0.50, saturation at 0.40, all-methods-failed at 0.40) never activate the centering cap. Only `artwork_box` (0.90), `vision_ai` (0.90), and `hsv_border` (0.75) can trigger it. Gradient detection after symmetry correction caps to exactly 0.60 — just at the threshold.

### 3.6 Half-Point Gate

**Function:** `_half_point_grade` (`grade_assembler.py:258-274`)

```python
base       = math.floor(composite_after_caps)
fractional = composite - base
worst_avg_centering = min(front_avg_centering_score, back_avg_centering_score)
qualifies  = (fractional >= 0.3) and (worst_avg_centering >= base + 1)
displayed  = base + 0.5 if qualifies else float(base)
```

**Why average-axis centering (not worst-axis):** The worst-axis centering score is already used for the PSA centering cap (Step 3.5). Using it again in the half-point gate would double-penalize borderline-centered cards. The average-axis score (mean of LR and TB centering ratios mapped to 1-10) is a fairer representation for this secondary gate.

**What `centering_avg_score` is:** Computed in `calculate_centering_ratios()` as `calculate_centering_score(left, right, top, bottom)` using `avg_ratio = (lr_ratio + tb_ratio) / 2`. Stored separately from `centering_score` (which is the worst-axis cap-derived score).

**Why fractional >= 0.3:** A card scoring 7.3 has narrowly cleared the 7.0 integer threshold. Displaying it as 7.5 requires additional confidence that centering is not the limiting factor. The 0.3 threshold means the card must be comfortably into the higher bracket.

**Effect of centering cap on half-point:** When the centering cap fires at exactly an integer boundary (e.g., cap=7 and composite=7.0), `fractional = 0.0 < 0.3`, so the half-point gate never qualifies. A capped card does not receive a bonus half-point.

### 3.7 Grade Output & Defects

`assemble_grade()` returns (`grade_assembler.py:433-495`):

| Key | Type | Description |
|---|---|---|
| `final_grade` | float | Displayed grade (integer or .5) |
| `composite_score` | float | Post-caps continuous score (before half-point step) |
| `centering_cap` | int | Integer ceiling from centering detection |
| `centering_score` | float | Worst-axis centering score (for UI display) |
| `dimension_scores` | dict | `corners/edges/surface`: blended + front_avg + back_avg |
| `individual_scores` | dict | All 8 corners + 8 edges + 2 surface scores |
| `defects` | list | Per-location defect dicts for locations scoring below 8.5 |
| `constraints_applied` | dict | Boolean flags for each constraint stage that fired |
| `confidence` | dict | overall (0-1), level ("High"/"Medium"/"Low"), low_confidence_flags |

**Confidence levels:** `High` >= 0.75, `Medium` >= 0.55, `Low` < 0.55 (`grade_assembler.py:492`).

**Defect threshold:** Only locations scoring below 8.5 appear in the `defects` list. This avoids noise on near-mint cards.

---

## 4. Centering Detection — centering.py

### 4.1 Priority Chain

`calculate_centering_ratios()` (`centering.py:508-792`) tries methods in strict priority order:

| Priority | Method | Confidence Ceiling | Trigger Condition |
|---|---|---|---|
| 0 | Vision AI `border_fractions` | 0.90 | When hybrid detector returns `border_fractions` (Vision AI detection path only) |
| 1 | Artwork box (`detect_inner_artwork_box`) | 0.90 | Contour inside card with area 15-70%, not touching any edge |
| 2 | HSV outermost-colour (`detect_border_widths_hsv`) | 0.75 | When artwork box is None or gives extreme asymmetry |
| 3 | Gradient/Sobel (`detect_border_widths_gradient`) | 0.50 | When HSV returns None or extreme asymmetry |
| 4 | Saturation-based (`detect_border_widths`) | 0.40 | When gradient also gives extreme asymmetry |

**Fallback trigger:** Each method falls through if `min(lr_ratio, tb_ratio) < 0.3`. A ratio of 0.3 corresponds to roughly 77/23 off-center — extreme enough to signal a detection artifact rather than genuine centering.

**Method 0 sanity check:** `border_fractions` values must all be in [0.01, 0.30]. Values outside this range (0 = unknown, or > 30% = implausibly wide border) cause fallthrough to Method 1.

### 4.2 Cap Tables

Two separate tables encode PSA centering standards, one for front and one for back.

**FRONT_CAP_TABLE** (`centering.py:24-34`):

| Min Ratio | Max PSA Grade | Equivalent % Split |
|---|---|---|
| 0.818 | 10 | 55/45 |
| 0.667 | 9 | 60/40 |
| 0.538 | 8 | 65/35 |
| 0.429 | 7 | 70/30 |
| 0.333 | 6 | 75/25 |
| 0.250 | 5 | 80/20 |
| 0.176 | 4 | 85/15 |
| 0.111 | 3 | 90/10 |
| 0.000 | 2 | worse than 90/10 |

**BACK_CAP_TABLE** (`centering.py:42-49`): Significantly more lenient. A 75/25 back centering (ratio 0.333) still allows PSA 10. This mirrors observed PSA behavior — back centering is judged less strictly because the back design has less visual weight and the eye forgives asymmetry more readily on the reverse.

**Worst-axis rule:** `worst_ratio = min(lr_ratio, tb_ratio)`. The worse of the two axes (left/right vs. top/bottom) determines the cap. Good LR centering cannot offset bad TB centering.

### 4.3 Score Curves

Two separate scores are computed from the same border measurements:

**`centering_score` (worst-axis):** Uses `interpolate_centering_score(worst_ratio, table)` — linear interpolation between table breakpoints. Used for the PSA centering cap enforcement.

**`centering_avg_score` (average-axis):** Uses `calculate_centering_score(left, right, top, bottom)` which computes `avg_ratio = (lr_ratio + tb_ratio) / 2` and maps it through a dampened piecewise curve (`centering.py:488-505`):

```
avg_ratio >= 0.975        ->  10.0
avg_ratio >= 0.93         ->  9.0 + (ratio - 0.93) / 0.045
avg_ratio >= 0.90         ->  8.0 + (ratio - 0.90) / 0.03
avg_ratio >= 0.85         ->  7.0 + (ratio - 0.85) / 0.05
avg_ratio >= 0.75         ->  6.0 + (ratio - 0.75) / 0.10   (dampened)
avg_ratio >= 0.60         ->  5.0 + (ratio - 0.60) / 0.15   (dampened)
avg_ratio >= 0.45         ->  4.0 + (ratio - 0.45) / 0.15
else                      ->  max(2.0, 4.0 * avg_ratio / 0.45)
```

The "dampened" mid-range brackets (0.60-0.85) use wider ratio spans per grade point to reduce sensitivity to measurement noise on mid-quality cards.

### 4.4 Confidence Ceilings & Reliability Guards

After method selection, two signals can further reduce confidence (`centering.py:768-771`):

**Cross-axis flag (`cross_axis_unreliable`):** Set by gradient detection when `max(lr_fraction, tb_fraction) / min(lr_fraction, tb_fraction) > 3.0`. This means one axis is measuring borders more than 3x wider than the other axis — a strong signal that gradient fired on an inner frame (artwork box or text-box boundary) rather than the outer printed border. Confidence is capped to 0.50.

**Symmetry correction:** Set by gradient detection when one border is below 5% of dimension while its opposite is more than 3x larger. The small border is clamped to 10% of dimension. Confidence is capped to 0.60 (just at the threshold enabling cap enforcement). The measurement is usable but not fully trusted.

---

## 5. Vision AI Integration — vision_assessor.py

### 5.1 Image Preparation (COMPOSITE_MODE)

`COMPOSITE_MODE = True` (`vision_assessor.py:53`)

In composite mode, 6 images are sent instead of 18 individual crops:

| Image Label | Content | Max Dimension |
|---|---|---|
| `front_corners` | 2x2 grid: TL/TR/BL/BR corner crops | 512px |
| `back_corners` | 2x2 grid: TL/TR/BL/BR corner crops | 512px |
| `front_edges` | Composite: top / (left | right) / bottom strips | 512px |
| `back_edges` | Composite: top / (left | right) / bottom strips | 512px |
| `front_surface` | Full front card image | 1024px |
| `back_surface` | Full back card image | 1024px |

Corner crops: 15% of card dimension from each corner (`CORNER_FRACTION = 0.15`).
Edge strips: 10% of perpendicular dimension (`EDGE_FRACTION = 0.10`), excluding corner regions.
All images encoded as JPEG at `JPEG_QUALITY = 80`.

**Why composite mode despite hallucination risk:** Individual crop mode (18 images) costs approximately 3x more tokens. The hallucination guard (Section 5.4) catches the primary failure mode. The system prompt reinforcement adds a second defense layer. The cost-vs-accuracy tradeoff currently favors composite mode.

### 5.2 Prompt Architecture

Two separate prompts serve different purposes:

**`grading_prompt.txt`** — Used by `assess_card()` for full scoring assessment:
- PSA-grade criteria for corners (10 down to 1), edges, and surface.
- Requests `crease_depth` and `whitening_coverage` as enumerated fields.
- Opens with an early CRITICAL reminder to score each corner independently — an anti-hallucination measure added after the composite-mode grid confusion issue.
- Score rules: 1.0-10.0 in half-point increments only.
- Surface field guidance specifies that `crease_depth` and `whitening_coverage` are required fields (never null).
- Used with `"system"` API field (model-level instruction).
- `temperature: 0` to reduce non-determinism.

**`damage_assessment_prompt.txt`** — Used by `assess_damage_from_full_images()` for targeted damage detection:
- More aggressive posture: "if there's any doubt about damage, classify as the more severe option."
- Detailed crease visual anchors (shadow casting, card no longer lying flat).
- Detailed whitening anchors with percentage area references.
- Handles white-background cards (Mewtwo, Alakazam) explicitly.
- Returns only `{front: {crease_depth, whitening_coverage, ...}, back: {...}}`.
- Injected as `content[0]` (first user message element), not the `system` field. This is a structural difference — the system field provides stronger instruction priority.
- No explicit `temperature` parameter — uses model default.

### 5.3 API Call & Retry Logic

**Function:** `_call_api_sync` (`vision_assessor.py:365-435`)

| Parameter | Value | Notes |
|---|---|---|
| Model | `claude-sonnet-4-20250514` | Grading + damage |
| `max_tokens` | 2048 | Grading; 1024 for damage |
| `temperature` | 0 | Grading only; damage uses model default |
| Timeout | 30 seconds | Per request |
| Timeout retries | 1 | Second timeout raises VisionAssessorError |
| JSON parse retries | 2 (MAX_JSON_RETRIES) | Re-calls API on malformed output |

On JSON parse failure, the full API call is retried (not just the JSON parsing). Markdown fence stripping (` ``` ` lines) is applied before every parse attempt.

**Maximum API calls per grading request:** 2 (pass1, pass2) + optional 1 (pass3 if disagreement > 1.5) for Stage 3, plus 1 for Stage 3b, plus 1 for Stage 3c = **5-6 total Vision AI calls** per grading request.

### 5.4 Hallucination Guard

**Function:** `_validate_response` (`vision_assessor.py:284-363`)

Three guards against corner-score hallucination, all applied before accepting any API response:

| Guard | Condition | Reason |
|---|---|---|
| Guard 1 | All 8 corner scores identical | Strongest signal — real cards never have 8 identical corners |
| Guard 2 | 7 or more corners have identical score | Real cards rarely have 7 corners at exactly the same condition |
| Guard 3 | `stdev(corner_scores) < 0.2` | All scores within 0.4 of mean — unnatural uniformity |

When any guard fires, `_validate_response` raises `ValueError`. `_call_api_sync` treats this as a parse failure and retries the API call (up to `MAX_JSON_RETRIES + 1 = 3` total attempts). If all attempts fail the guard, `VisionAssessorError` is raised, failing the grade.

**Why Guard 3 specifically:** Holographic foil cards under composite-mode grid layout caused the model to return uniform-but-not-identical scores (e.g., 8.5, 8.5, 8.5, 9.0, 8.5, 9.0, 8.5, 8.5 — stdev 0.19). These pass Guards 1 and 2 but fail Guard 3. The 0.2 stdev threshold was empirically chosen as the boundary between suspicious uniformity and natural near-mint variance.

Corner score distribution is logged at DEBUG level for every response, including mean, stdev, unique count, and full distribution. This enables post-hoc analysis of hallucination patterns.

### 5.5 Dual-Pass / Triple-Pass Averaging

**Function:** `assess_card` (`vision_assessor.py:704-768`)

```
Pass 1 -> API call -> validated response
Pass 2 -> API call -> validated response
max_disagreement = max |score_pass1[k] - score_pass2[k]| across all 18 scores

if max_disagreement > 1.5:
    Pass 3 -> API call -> validated response
    result = _median_of_three(pass1, pass2, pass3)
else:
    result = _average_passes(pass1, pass2)
```

**Why dual-pass:** Vision AI has inherent non-determinism even at temperature=0. Two passes and averaging reduces variance. The 1.5-point disagreement threshold triggers a tiebreaker pass when the model is especially uncertain.

**`_average_passes` behavior** (`vision_assessor.py:520-583`):
- Numeric scores: arithmetic average.
- Defects: union with order-preserved deduplication.
- Confidences: arithmetic average.
- Damage labels (`crease_depth`, `whitening_coverage`): most-severe-wins (not averaged).
- String labels (staining, gloss, print_registration): taken from the worse-scoring pass to stay consistent with the numeric direction.

**`_median_of_three` behavior** (`vision_assessor.py:586-671`):
- Numeric scores: statistical median.
- Defects: union of all three passes.
- Damage labels: most-severe-wins across all three.
- String labels: from the worst-scoring pass.

### 5.6 "Most Severe Wins" Merge Logic

**Functions:** `_most_severe`, `_most_severe_of_three` (`vision_assessor.py:490-505`)

Both normalize labels first via `_normalize_label(label, order)`. The normalizer:
1. Returns the label unchanged if it is already in the canonical order list.
2. Maps via `_CREASE_SYNONYMS` or `_WHITENING_SYNONYMS` for known non-standard labels.
3. **Defaults unknown labels to the most severe** (`order[-1]`) with a warning log. This is intentional — an unexpected label (e.g., "extreme") must not silently downgrade to a clean reading.

Synonym tables (`vision_assessor.py:446-463`):

```python
_CREASE_SYNONYMS = {
    "light": "hairline", "slight": "hairline", "minor": "hairline",
    "severe": "heavy", "deep": "heavy",
    "significant": "moderate",
    "wrinkle": "heavy",    # TAG report label: "SURFACE / WRINKLE/CREASE" -> heavy
}

_WHITENING_SYNONYMS = {
    "light": "minor", "slight": "minor", "small": "minor",
    "severe": "extensive", "large": "extensive",
    "significant": "moderate",
}
```

`"wrinkle": "heavy"` was added after TAG report calibration showed that a "SURFACE / WRINKLE/CREASE" label corresponds to PSA 2 (heavy crease territory).

### 5.7 Confidence Flagging

After merging passes, `_collect_low_confidence_flags(merged)` (`vision_assessor.py:685-697`) lists all locations where `confidence < 0.60`. These are returned in `vision_result["low_confidence_flags"]` and forwarded to `combined["warnings"]`.

The grade assembler independently collects low-confidence flags in `_calculate_confidence()` (`grade_assembler.py:350-369`) from the per-location confidence values in `AssemblyInput`. These feed the `confidence.level` field in the API response.

### 5.8 Damage Assessment Call

**Function:** `assess_damage_from_full_images` (`vision_assessor.py:771-888`)

Sends full card images (no cropping) at JPEG quality 95. No dual-pass averaging — single API call only. No hallucination guard on corner scores (the damage prompt does not request corner scores). JSON extraction uses `{...}` bracket search rather than strict top-level parsing.

Key differences from `assess_card`:
- No `_validate_response` call.
- No `temperature` parameter set (uses model default, typically higher than 0 — intentional to increase recall on borderline damage cases).
- System prompt injected as `content[0]` (first user message element) rather than the `system` API field.

---

## 6. Damage Detection Deep Dive

### 6.1 Stage 3b: Full-Image Damage Pass

Stage 3 (`assess_card`) uses cropped images: corner crops at 15% of card dimension and edge strips at 10%. A crease running diagonally across the surface can be missed in all crops yet clearly visible in the full card image. Stage 3b corrects this by sending the full card directly to a damage-focused prompt.

### 6.2 Stage 3c: Holographic Foil Preprocessing

**Problem:** Holographic foil Pokemon cards (ex/EX rares, holo rares, Rainbow Rares) have rainbow sparkle patterns across the surface. When Vision AI looks for creases (breaks in surface continuity), the foil sparkle creates many apparent "breaks" in the surface. Cards with holographic foil and no actual damage can be misclassified as having hairline or moderate creases.

**Solution:** Convert to grayscale (eliminating colour-dependent sparkle) then apply CLAHE to re-expand contrast. Physical breaks (creases create a brightness discontinuity) survive the grayscale conversion while the colour-dependent foil pattern does not.

**Split-region rationale:** Different CLAHE parameters apply to different card regions because the goals differ:
- Card border region: moderate enhancement (`clipLimit=1.5` + histogram equalization) to reveal whitening and edge wear.
- Card interior artwork region: mild enhancement (`clipLimit=1.0`) to reveal surface creases without sharpening character art outlines, which would create false crease signals.

**White card protection:** Histogram equalization is skipped when `border_gray_mean >= 200`. On white-bordered cards (Mewtwo, Alakazam, etc.), `equalizeHist` compresses the near-white histogram, reducing contrast in exactly the region where wear appears as brightness variation. This would mask the very signals we are trying to detect.

**Why back cards skip preprocessing:** The standard Pokemon card back (blue oval + Pokeball design) has no holographic foil. CLAHE and histogram equalization applied to the dark-blue back design distort the histogram in ways that over-smooth crease signals. Testing confirmed that Stage 3b correctly detected back creases that Stage 3c lost when preprocessing was applied uniformly to both sides.

### 6.3 Stage 3d: OpenCV Border Texture

Multi-scale Sobel (ksize=3 fine, ksize=7 coarse) plus local 7x7 pixel std dev on a 12% border margin. The multi-scale approach captures both fine fraying (fine Sobel) and broad wear patterns (coarse Sobel). Taking the maximum across scales at each pixel avoids averaging away sharp wear signals.

The 80th percentile (not mean) of the border region values focuses on the worst-wear areas while ignoring uniform printing-texture gradients that appear across all cards.

**Deliberate confidence cap of 0.55:** This stage alone cannot trigger the damage cap gate (0.60). Requiring Vision AI confirmation to enforce a grade cap prevents OpenCV noise from penalizing clean cards — the OpenCV whitening thresholds were calibrated on a limited card set and carry calibration uncertainty.

### 6.4 Stage 3e: HoughLinesP Crease Detection

HoughLinesP finds long line segments in Canny edge space. Creases appear as bright lines because a fold creates a brightness discontinuity. Full filter chain:

1. **Interior mask (7% margin):** Removes card border edges, text box boundaries, and frame lines — the primary false-positive sources.
2. **Holofoil detection:** If the card produces more than 120 short lines (threshold `HOLO_SHORT_LINE_THRESHOLD`), it is flagged as holographic. The minimum line length for crease classification is raised from 15% to 22% of card diagonal for holo cards, reducing false positives from foil sparkle.
3. **Angle filter (10-degree exclusion zone):** Lines within 10 degrees of horizontal or vertical are excluded. Card frames and text boxes produce axis-aligned lines. Real creases are almost always diagonal or off-axis.
4. **False-positive filter (>20 lines):** More than 20 crease-candidate lines is characteristic of printing texture producing edge signals uniformly, not a single physical crease. Output is downgraded to `none`.

Severity thresholds (fraction of card diagonal):

| Metric | Hairline | Moderate | Heavy |
|---|---|---|---|
| `norm_max_length` | >= 0.08 | >= 0.16 | >= 0.40 |
| `norm_total_length` | — | >= 0.60 (confirms moderate) | >= 2.0 (OR trigger for heavy) |

The `heavy` OR condition (`norm_total >= 2.0`) catches cases where a crease is physically short but wide enough (or there are multiple parallel creases) to cover significant surface area.

### 6.5 Damage Label Normalization

`_normalize_label(label, order)` handles non-standard labels from any Vision AI response. The "unknown label defaults to most severe" safety net prevents a future model response variation (e.g., "extreme", "critical", "deep") from silently failing to trigger a grade cap it should trigger.

### 6.6 Why Holographic Cards Needed Special Handling — Root Cause

The root cause of holographic card hallucination: `COMPOSITE_MODE = True` sends a 2x2 corner grid. On a holographic card, the foil sparkle creates a visually uniform rainbow pattern across all four corners. When Vision AI processes the grid, it may perceive the consistent sparkle texture as consistent corner condition and return near-identical scores for all 8 corners (4 front, 4 back from both grids). This is the pattern Guard 3 (stdev < 0.2) was designed to detect.

The prompt reinforcement ("Score each corner independently... if you find yourself assigning the same score to 5+ corners, stop and re-evaluate") was added to push the model toward per-corner evaluation before it produces output. The hallucination guard is the safety net when the prompt reinforcement fails.

---

## 7. OpenCV Corner Analysis — corners.py

`CornerDetector.analyze_corners()` provides an independent OpenCV-based corner assessment used for:
1. **Cross-check signal:** `overall_grade` is stored in `front_analysis["opencv_corner_grade"]` and compared against Vision AI's average corner score in `_apply_opencv_corner_cross_check`.
2. **Potential score override:** If `confidence >= 0.7`, the enhanced result replaces `front_analysis["corners"]` (`grading.py:110-115`). However, this value is not used by `_vision_to_assembly_input` — the grade assembler reads corners from `vision_result["corners"]`, not from `front_analysis["corners"]`. The OpenCV override effectively has no effect on final scores.

**Corner scoring formula in corners.py** (whitening percentage to score, `corners.py:271-289`):

| White % Range | Score Formula |
|---|---|
| < 0.5% | 10.0 |
| 0.5-1.5% | 9.5 to 10.0 |
| 1.5-3.0% | 9.0 to 9.5 |
| 3.0-6.0% | 8.0 to 9.0 |
| 6.0-12.0% | 7.0 to 8.0 |
| 12.0-20.0% | 6.0 to 7.0 |
| 20.0-35.0% | 4.0 to 6.0 |
| 35.0-50.0% | 2.0 to 4.0 |
| > 50.0% | max(1.0, decaying from 2.0) |

**Overall grade formula in corners.py:** `0.7 * avg_score + 0.3 * min_score` (`corners.py:293-295`). This differs from the grade assembler (which uses 50/50 avg+worst for the within-side blend), but since corners.py output only feeds the cross-check signal (not final scoring), the formula difference is acceptable.

**False positive checks in corners.py:**
- Edge whitening ratio > 0.7 (more than 70% of white pixels are at the image edge, not the card corner tip)
- Uniform blob larger than 30% of corner area with square aspect ratio (likely background material, not corner wear)
- Nearly-pure-white pixels with mean > 240 (overexposed/glare, not damage)
- Whitening not concentrated in the expected corner zone (< 60% within inner 40% of corner crop)

---

## 8. Front/Back Side Detection

**Function:** `detect_card_side(image)` (`combined_grading.py:32-55`)

Used for front/back swap detection and for deciding preprocessing in Stage 3c:

```
Blue > 55% AND Yellow < 5% AND Red > 2%  ->  "back"  (Pokeball confirmed)
Blue < 20%                                ->  "front"
Otherwise                                 ->  "front"  (confidence 0.6)
```

The blue threshold was raised from 40% to 55% after false positives on blue-artwork fronts (Articuno, Vaporeon, Blastoise, water-type cards). The Pokeball red check (> 2%) was added as a second discriminator specific to the standard Pokemon card back design.

This function returns a string label and a confidence float. In Stage 3c, it is called on the back image to check if the "back" image was actually a front card (`combined_grading.py:527-533`) — an unlikely but possible scenario if the user uploaded both images from the front.

---

## 9. Blending Logic Summary

### Front/Back Dimension Weights

| Dimension | Front Weight | Back Weight | Within-Side Formula |
|---|---|---|---|
| Corners | 60% | 40% | `0.5 * avg + 0.5 * worst` |
| Edges | 65% | 35% | `avg` of 4 edges |
| Surface | 70% | 30% | Single score per side |

### Composite Weights

| Dimension | Composite Weight | Derivation |
|---|---|---|
| Corners | 37.5% | 30% renormalized: 30/80 |
| Edges | 37.5% | 30% renormalized: 30/80 |
| Surface | 25.0% | 20% renormalized: 20/80 |
| Centering | Hard cap only | Excluded from composite |

### Constraint Application Order

| Step | Constraint | Source | Gate |
|---|---|---|---|
| 1 | Blend | Front/back | None |
| 2 | Composite | Weighted sum | None |
| 3 | Floor/Ceiling | `worst_dim +/- spread` | None (always active) |
| 3.5 | Damage cap | Crease/whitening detection | surface_confidence >= 0.60 |
| 4 | Centering cap | Centering detection | centering_confidence >= 0.60 |
| 5 | Half-point gate | Fractional + avg-axis centering | fractional >= 0.3 AND centering >= base+1 |

---

## 10. Constants & Thresholds Reference

### Vision AI

| Constant | Value | File:Line | Purpose |
|---|---|---|---|
| `MODEL` | `claude-sonnet-4-20250514` | vision_assessor.py:29 | Model for all Vision AI calls |
| `TIMEOUT_SECONDS` | 30 | vision_assessor.py:31 | Per-request timeout |
| `MAX_JSON_RETRIES` | 2 | vision_assessor.py:32 | JSON parse retry count (3 total attempts) |
| `CORNER_MAX_PX` | 512 | vision_assessor.py:35 | Max dimension for corner grid images |
| `EDGE_MAX_PX` | 512 | vision_assessor.py:36 | Max dimension for edge composite images |
| `SURFACE_MAX_PX` | 1024 | vision_assessor.py:37 | Max dimension for surface images |
| `JPEG_QUALITY` | 80 | vision_assessor.py:38 | JPEG quality for grading images |
| `JPEG_QUALITY` (damage) | 95 | vision_assessor.py:807 | Higher quality preserves damage detail |
| `CORNER_FRACTION` | 0.15 | vision_assessor.py:41 | Corner crop size as fraction of card |
| `EDGE_FRACTION` | 0.10 | vision_assessor.py:43 | Edge strip width as fraction |
| `PASS_DISAGREEMENT_THRESHOLD` | 1.5 | vision_assessor.py:46 | Triggers 3rd pass |
| `LOW_CONFIDENCE_THRESHOLD` | 0.60 | vision_assessor.py:49 | Flags locations for warning |
| `COMPOSITE_MODE` | True | vision_assessor.py:53 | 6 vs 18 images per API call |
| Hallucination stdev threshold | 0.2 | vision_assessor.py:358 | Guard 3 threshold |

### Damage Caps

| Damage Label | Cap Value | File:Line | Calibration Status |
|---|---|---|---|
| Heavy crease | 2.0 | grade_assembler.py:222 | Calibrated from TAG report |
| Moderate crease | 5.0 | grade_assembler.py:226 | Heuristic — no TAG calibration |
| Extensive whitening | 5.0 | grade_assembler.py:230 | Heuristic |
| Damage cap gate | 0.60 | grade_assembler.py:212 | Confidence threshold per side |

### Centering

| Constant | Value | File:Line | Purpose |
|---|---|---|---|
| Vision AI confidence | 0.90 | centering.py:597 | `border_fractions` path |
| Artwork box confidence | 0.90 | centering.py:753 | Geometry-based detection |
| HSV border confidence | 0.75 | centering.py:755 | Color-based detection |
| Gradient confidence | 0.50 | centering.py:757 | Sobel-based (below gate) |
| Saturation/fallback confidence | 0.40 | centering.py:759-761 | All-methods-failed path |
| Cross-axis confidence cap | 0.50 | centering.py:769 | Gradient misfired on inner frame |
| Symmetry correction confidence cap | 0.60 | centering.py:771 | One border was clamped |
| Cap gate | 0.60 | grade_assembler.py:251 | Min confidence to enforce centering cap |

### Grade Assembly

| Constant | Value | File:Line | Purpose |
|---|---|---|---|
| Corners composite weight | 0.375 | grade_assembler.py:156 | Renormalized from 30/80 |
| Edges composite weight | 0.375 | grade_assembler.py:156 | Renormalized from 30/80 |
| Surface composite weight | 0.250 | grade_assembler.py:156 | Renormalized from 20/80 |
| Corners 60/40 | front 0.60, back 0.40 | grade_assembler.py:137 | Front-weighted blend |
| Edges 65/35 | front 0.65, back 0.35 | grade_assembler.py:145 | Front-weighted blend |
| Surface 70/30 | front 0.70, back 0.30 | grade_assembler.py:151 | Front-weighted blend |
| Within-corner avg/worst | 50/50 | grade_assembler.py:135-136 | Penalizes single bad corner |
| Floor spread | worst - 0.5 | grade_assembler.py:176 | Prevents excess composite drag |
| Ceiling spread | worst + 1.0 | grade_assembler.py:177 | Prevents misleadingly high composite |
| Half-point fractional gate | 0.3 | grade_assembler.py:272 | Minimum fractional for .5 display |
| Defect display threshold | 8.5 | grade_assembler.py:307 | Locations below this appear in defects |
| Confidence: High | >= 0.75 | grade_assembler.py:492 | UI chip label |
| Confidence: Medium | >= 0.55 | grade_assembler.py:492 | UI chip label |

### Grade Range Display

| Constant | Value | File:Line | Purpose |
|---|---|---|---|
| Grade range proximity | 0.3 | combined_grading.py:277 | Shows range when within 0.3 of next bracket |

### OpenCV Stage 3d (texture.py)

| Threshold | Value | Meaning |
|---|---|---|
| `THRESH_MINOR` | 40.0 | Below: definitely clean |
| `THRESH_MODERATE` | 100.0 | Below: minor wear only |
| `THRESH_EXTENSIVE` | 150.0 | Below: moderate; above: extensive |
| Fixed confidence | 0.55 | Below damage cap gate by design |

### OpenCV Stage 3e (creases.py)

| Constant | Value | Purpose |
|---|---|---|
| `INTERIOR_MARGIN_FRACTION` | 0.07 | Border strip excluded from crease search |
| `CANNY_LOW / CANNY_HIGH` | 20 / 80 | Low thresholds to catch faint creases |
| `HOUGH_THRESHOLD` | 40 | Min accumulator votes |
| `HOUGH_MAX_GAP` | 8 px | Gap bridging within a crease line |
| `MIN_LINE_FRACTION` | 0.15 | Min line length (normal cards) |
| `MIN_LINE_FRACTION_HOLO` | 0.22 | Min line length (holographic cards) |
| `AXIS_ANGLE_EXCLUSION_DEG` | 10 | Degrees from H/V axis excluded |
| `HOLO_SHORT_LINE_THRESHOLD` | 120 | Short lines above this -> holo card |
| `THRESHOLD_HAIRLINE_MAX` | 0.08 | norm_max_length for hairline |
| `THRESHOLD_MODERATE_MAX` | 0.16 | norm_max_length for moderate |
| `THRESHOLD_HEAVY_MAX` | 0.40 | norm_max_length for heavy |
| `THRESHOLD_HEAVY_TOTAL` | 2.0 | OR: norm_total_length for heavy |
| `THRESHOLD_MODERATE_TOTAL` | 0.60 | Confirms moderate when present |
| `MAX_LINE_COUNT_BEFORE_FALSE_POSITIVE` | 20 | Above: printing texture, not crease |

### Session & API

| Constant | Value | File:Line | Purpose |
|---|---|---|---|
| Session TTL | 30 min | session_manager.py:35 | Reset on each upload (idle-based) |
| Max upload | 15 MB | grading.py:20 | Both front and back enforced |
| Cleanup interval | 120 s | main.py:172 | Periodic session sweep |
| AI semaphore | 5 | hybrid_detect.py:36 | Max concurrent detection AI calls |
| OpenCV confidence threshold | 0.70 | hybrid_detect.py:27 | Below this -> Vision AI fallback for detection |

---

## 11. Session Management

**File:** `backend/api/session_manager.py`

### Lifecycle States

```
create_session()          -> status="created"
upload-front (success)    -> status="front_uploaded"
upload-back (success)     -> status="complete"
upload-back (Vision fail) -> status="error"
```

### TTL (Idle-Based)

Sessions expire 30 minutes after the last upload, not after creation. `touch()` is called inside `update_session()` (`session_manager.py:99`), which is invoked after every successful front or back upload. A session that receives a front upload but never a back upload expires 30 minutes after the front upload.

### Cleanup

`cleanup_expired()` runs every 120 seconds via `asyncio.create_task` (`main.py:163-173`). It acquires `asyncio.Lock` during the sweep and calls `_cleanup_session()` (which uses `shutil.rmtree`) for each expired session. `gc.collect()` is called after cleanup if any sessions were removed.

### Concurrency

`asyncio.Lock` protects `create_session()`, `delete_session()`, and `cleanup_expired()`. `get_session()` and `update_session()` are synchronous and lock-free — intentionally, as they only read from or mutate the in-memory dict without blocking I/O.

**Known race:** A session being actively analyzed (back upload in progress) can expire during analysis if the Vision AI calls exceed the remaining TTL. `update_session()` calls `touch()`, but this happens after analysis completes, not during it. In practice, the 30-minute TTL greatly exceeds Vision AI call time — the risk is low but non-zero.

---

## 12. API Flow & Endpoints

### Endpoints

| Method | Path | Purpose | HTTP Errors |
|---|---|---|---|
| POST | `/api/grading/start` | Create session | 500 |
| POST | `/api/grading/{id}/upload-front` | Upload + analyze front | 400 (size, quality), 404 (session), 500 |
| POST | `/api/grading/{id}/upload-back` | Upload + analyze back + grade | 400 (size, quality, no-front), 404, 500 |
| GET | `/api/grading/{id}/result` | Get cached result | 404 |
| DELETE | `/api/grading/{id}` | Delete session + files | 404 |
| GET | `/health` | Health check | — |
| GET | `/privacy-policy` | HTML privacy policy | — |

### upload-back Response Shape (success)

```json
{
  "session_id": "...",
  "status": "complete",
  "grading": {
    "final_grade": 8.5,
    "composite_score": 8.34,
    "estimated_grade": "8.5",
    "psa_estimate": "8.5",
    "is_estimate": true,
    "disclaimer": "...",
    "final_score": 8.34,
    "grading_status": "success",
    "grade_range": "8-8.5",
    "sub_scores": {
      "centering": 9.2,
      "corners": 8.5,
      "edges": 8.7,
      "surface": 7.8
    },
    "explanations": ["Excellent centering", "Minor corner wear", ...],
    "constraints_applied": {
      "floor_activated": false,
      "ceiling_activated": false,
      "damage_cap_activated": false,
      "damage_cap_reason": null,
      "centering_cap_activated": false,
      "half_point_qualified": true
    },
    "confidence": {
      "overall": 0.82,
      "level": "High",
      "low_confidence_flags": []
    },
    "dimension_scores": { "corners": {...}, "edges": {...}, "surface": {...} },
    "individual_scores": { "corners": {...}, "edges": {...}, "surface": {...} },
    "defects": [...]
  },
  "details": {
    "centering": { ... },
    "front_centering": { ... },
    "back_centering": { ... },
    "corners": { ... },
    "edges": { ... },
    "surface": { ... }
  },
  "warnings": [],
  "processing_time": "12.34s"
}
```

### upload-back Response Shape (Vision AI failure)

```json
{
  "session_id": "...",
  "status": "error",
  "error": "Vision AI call timed out twice — aborting grade",
  "warnings": [...],
  "processing_time": "62.01s"
}
```

The error response uses HTTP 200 with `status: "error"` (not HTTP 500) because the session itself succeeded in receiving the image — only the grading computation failed. Flutter checks `backResult['status'] == 'error'` to detect this path.

### Centering Display Logic

The primary `centering` field shows the worse side's centering data (lower cap), because the effective cap is always the minimum of front and back (`combined_grading.py:720-728`):

```python
if back_cap < front_cap:
    combined["centering"] = back_centering
else:
    combined["centering"] = front_centering
```

Both `front_centering` and `back_centering` are also exposed separately for the detail screen.

### `final_score` vs. `final_grade` Naming

`grade["final_score"]` = `assembler_result["composite_score"]` — the continuous score after all caps, before the half-point step (`combined_grading.py:248`). `grade["final_grade"]` = the displayed half-point or integer grade. The naming is a backward-compatibility alias. Flutter reads `final_grade` for display.

---

## 13. Edge Cases & Guards

### All-Methods Centering Failure

If all 4 centering methods produce `min(lr_ratio, tb_ratio) < 0.3`, the system uses a ratio-derived score rather than a fixed 5.0 (`centering.py:696`). This avoids artificially inflating severely off-center cards. Confidence falls to 0.40, below both the centering cap gate and half-point gate.

### Vision AI Empty System Prompt

`assess_card()` raises `VisionAssessorError` if `SYSTEM_PROMPT` is empty (`vision_assessor.py:727-731`). This is checked at startup via `check_grading_prompt()` (`main.py:152-153`). Prevents grading with a missing prompt file from silently producing unreliable results.

### Front Re-Upload Clearing Stale State

When `upload-front` succeeds, `session.back_analysis` and `session.combined_grade` are reset to `None` (`grading.py:130-137`). This prevents a re-uploaded front from being combined with a stale back analysis from the previous front upload.

### Front/Back Swap Warning

If `detected_as == "back"` for the front upload slot and vice versa, a warning is appended to `combined["warnings"]` (`combined_grading.py:456-460`). Grade processing continues — swapped images are not rejected, only warned about.

### Vision AI API Error

`VisionAssessorError` is caught in `combine_front_back_analysis()` (`combined_grading.py:469-476`) and returns an error dict rather than raising an exception. The grading router detects `combined_grade["grade"].get("error")` and returns a `status="error"` response (HTTP 200).

### Image Load Failure

If `cv2.imread()` returns `None` for either image path, `combine_front_back_analysis()` returns an error dict immediately (`combined_grading.py:444-451`) before any Vision AI calls.

### Hallucination Guard Retry Exhaustion

If all `MAX_JSON_RETRIES + 1 = 3` attempts fail validation, `VisionAssessorError` is raised (`vision_assessor.py:435`). This propagates up through `assess_card()`, is caught in `combine_front_back_analysis()`, and returns a `status="error"` API response.

### JPEG Encoding Failure

`_to_jpeg_b64()` raises `VisionAssessorError("Failed to JPEG-encode image")` if `cv2.imencode` returns False (`vision_assessor.py:88`). This prevents sending malformed images to the API.

### isinstance Guard in Damage Cap

`_apply_damage_cap()` checks `if not isinstance(data, dict): continue` (`grade_assembler.py:211`) before processing each side's surface data. This prevents a `TypeError` crash if `surface_raw` contains unexpected types — a defensive measure since `surface_raw` comes from the Vision AI response parsing path.

---

## 14. Known Limitations & Deferred Work

### Calibration Gap

No calibration study against professional PSA/BGS grades has been completed. All grade outputs are estimates. A calibration warning is logged at every startup (`main.py:154-157`) and included in the API response `disclaimer` field.

### Damage Cap Values

- `heavy crease -> 2.0`: Calibrated from a single TAG data point. More calibration points needed across different card types and crease profiles.
- `moderate crease -> 5.0`: Heuristic only. No TAG data exists yet for a moderate crease as the primary defect.
- `extensive whitening -> 5.0`: Heuristic. No direct TAG calibration.
- `floor/ceiling spread (worst + 1.0)`: Likely too generous for single-corner defects. Deferred pending more calibration data.

### Multi-Pass Vision AI Systematic Bias

Dual/triple-pass averaging reduces variance but reinforces systematic bias. If the model consistently over-grades a particular card type (e.g., full-art cards), averaging two or three passes will return the same biased result. This is a fundamental limitation of the approach — not fixable in code without external calibration or fine-tuning.

### OpenCV Corners Wasted CPU

`analyze_corners()` is called on both front and back corrected images (grading.py:104, 246). The result is stored in `front_analysis["corners"]` with a potential override at confidence >= 0.7. However, `_vision_to_assembly_input` reads corners from `vision_result["corners"]` (Vision AI output), not from `front_analysis["corners"]`. The OpenCV corner grade is used only for the cross-check signal.

### Full-Art Cards / Very Thin Borders

The centering sanity check gate `0.01 <= f <= 0.30` may reject valid `border_fractions` for full-art cards which have very thin printed borders (potentially < 1% of card dimension). These fall through to OpenCV methods with lower confidence.

### Session Cleanup Race

`cleanup_expired()` checks `session.is_expired()` then calls `shutil.rmtree`. Between the check and the filesystem delete, an in-flight analysis for that session could be writing to the directory. `shutil.rmtree(ignore_errors=True)` prevents a crash but the analysis will fail when it tries to write subsequent results.

### `refused` Status Dead Code

`result_screen.dart` in Flutter checks for `grading_status == "refused"` but the backend never produces this status. Dead client code.

### Debug Images Accumulation

`ENABLE_DEBUG_IMAGES = True` by default. Debug images may accumulate outside the session-specific subdirectory if written to non-standard paths, and would not be cleaned up by session cleanup.

### Flutter Timeout

Flutter's `receiveTimeout` is 60 seconds. Vision AI worst case (2-3 passes with possible JSON retries per pass) can approach 90 seconds. Long grading requests may time out on the client while still completing on the server.

### quality_checks.py Resolution Gap

`quality_checks.py` enforces a minimum resolution of 400px, while Flutter enforces 600px on the client. Images in the 400-600px range will pass the server quality gate but would have been rejected by the Flutter image validator. If images bypass the Flutter validator, the server will accept them.

---

*This document was generated from source code analysis as of March 28, 2026. All line numbers reference the codebase at that date. Update this document when algorithmic constants, blending weights, damage caps, or pipeline stages change.*
