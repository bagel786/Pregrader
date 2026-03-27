# Pregrader Grading Model — Technical Reference

This document describes the complete grading pipeline as implemented: how a card image becomes a PSA-aligned numeric grade.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Stage 1: Card Detection & Perspective Correction](#2-stage-1-card-detection--perspective-correction)
3. [Stage 2: Component Analysis (Centering, Corners, Edges)](#3-stage-2-component-analysis)
4. [Stage 3: Vision AI Assessment](#4-stage-3-vision-ai-assessment)
5. [Stage 3b: Damage Assessment (Full Images)](#5-stage-3b-damage-assessment-full-images)
6. [Stage 3c: Enhanced Damage Assessment](#6-stage-3c-enhanced-damage-assessment)
7. [Stage 4: Grade Assembly & Damage Cap](#7-stage-4-grade-assembly--damage-cap)
8. [Final Grade Calculation](#8-final-grade-calculation)
9. [Front + Back Blending](#9-front--back-blending)
10. [Confidence System](#10-confidence-system)
11. [API Session Flow](#11-api-session-flow)
12. [Constants Reference](#12-constants-reference)

---

## 1. Pipeline Overview

```
User uploads front image
         │
         ▼
Stage 1: Card Detection (OpenCV → Claude Vision fallback)
         │
         ▼
     Perspective Correction (500×700 px canonical)
         │
         ├──► Stage 2: Centering Analysis
         ├──► Stage 2: Corners Analysis (basic + enhanced)
         ├──► Stage 2: Edges Analysis
         │
         ├──► (optional) User uploads back image
         ├──► Card Detection + Perspective Correction (back)
         │
         │
         ├──► Stage 3: Vision AI Assessment (both sides)
         │           → corners, edges, surface scores
         │           → crease_depth, whitening_coverage (damage signals)
         │
         ├──► Stage 3b: Full-Image Damage Assessment (both sides)
         │            → direct Vision AI on full images
         │            → upgrades crease/whitening if worse detected
         │
         ├──► Stage 3c: Enhanced Damage Assessment (preprocessed images)
         │            → removes holographic noise, re-assesses
         │            → upgrade-only, merges with Stage 3b
         │
         ├──► Front + Back Blending (if both sides provided)
         │
         ▼
Stage 4: Grade Assembly & Damage Cap
         → composite_score = weighted(corners, edges, surface)
         → apply damage penalties (heavy crease → 2.0, moderate/extensive → 5.0)
         → apply centering PSA cap
         → floor/ceiling bounds
         → half-point gate
         │
         ▼
Final Grade: PSA bracket lookup + rounding
```

All image analysis runs on the 500×700 px perspective-corrected card image — never on the raw phone photo.

---

## 2. Stage 1: Card Detection & Perspective Correction

**Files:** `backend/api/hybrid_detect.py`, `backend/services/ai/vision_detector.py`

Four independent OpenCV methods attempt detection. If max confidence < 0.70, falls back to Claude Vision API.

**Output:** 4 corner points of the card, which are then used for perspective transformation to a canonical 500×700 px rectangle.

All subsequent analysis operates on this corrected image.

---

## 3. Stage 2: Component Analysis

### Centering Analysis

**File:** `backend/analysis/centering.py`

Measures how evenly artwork is positioned. Contributes **20%** to final composite (or operates as hard PSA cap if centering cap is stricter than composite).

Uses a fallback chain: Artwork box detection → Gradient-based → HSV/Saturation.

Produces: `centering_score` (1.0–10.0) and `centering_cap` (hard upper bound for final grade).

### Corners Analysis

**File:** `backend/analysis/corners.py`

Detects whitening at the 4 corners. Contributes **37.5%** to final composite.

- Basic corners: 4 ROIs, HSV whitening detection, confidence up to 1.0
- Enhanced corners (optional): false positive filtering, confidence up to 0.9 (gated at 0.5 to override basic)

Produces: 4 individual corner scores, blended into a single "corners" component score.

### Edges Analysis

**File:** `backend/analysis/edges.py`

Detects whitening/wear along all 4 edges. Contributes **37.5%** to final composite.

Tests per edge (top, bottom, left, right) and combines into an "edges" component score.

---

## 4. Stage 3: Vision AI Assessment

**File:** `backend/grading/vision_assessor.py`, function `assess_card()`

Two passes of Vision AI grading (averaged or median-of-three if disagreement > 1.5):

**Input:** Front and back images (500×700 px BGR uint8)

**Processing:**
1. Prepares 6 cropped/composite views:
   - Front/back corner grids (2×2 layout)
   - Front/back edge composites (top/bottom/left/right strips)
   - Front/back surface (full card)
2. Encodes all as JPEG (quality 80), base64
3. Sends to Claude Vision with system prompt (`backend/grading/prompts/grading_prompt.txt`)
4. Extracts scores + quality assessment for each component

**Return structure:**
```python
{
  "corners": {
    "front_top_left": {"score": 8.5, "confidence": 0.95, ...},
    # ... 8 total (4 front, 4 back)
  },
  "edges": {
    "front_top": {"score": 8.0, "confidence": 0.90, ...},
    # ... 8 total (4 front, 4 back)
  },
  "surface": {
    "front": {
      "score": 8.5,
      "confidence": 0.9,
      "crease_depth": "none" | "hairline" | "moderate" | "heavy",
      "whitening_coverage": "none" | "minor" | "moderate" | "extensive",
    },
    "back": { ... },
  },
  "low_confidence_flags": [...],
}
```

The `crease_depth` and `whitening_coverage` fields are the **primary damage signals** that drive the damage cap in Stage 4.

---

## 5. Stage 3b: Damage Assessment (Full Images)

**File:** `backend/grading/vision_assessor.py`, function `assess_damage_from_full_images()`

Dedicated damage detection pass using full card images at higher JPEG quality (95%).

**Purpose:** Catch surface damage missed by the cropped-image analysis in Stage 3.

**Processing:**
1. Encodes front and back images as JPEG quality 95 (full images, no cropping)
2. Sends to Claude Vision with `damage_assessment_prompt.txt`
3. Extracts damage assessments per side

**Return structure:**
```python
{
  "front": {
    "crease_depth": "none" | "hairline" | "moderate" | "heavy",
    "whitening_coverage": "none" | "minor" | "moderate" | "extensive",
    "confidence": float,
    "notes": "...",
  },
  "back": { ... },
}
```

**Merge logic** (in `combined_grading.py` lines 475–508):
- If Stage 3b damage is **more severe** than Stage 3, upgrade the `vision_result` surface damage fields
- Never downgrades (upgrade-only)
- Uses "most severe wins" semantics for `crease_depth` and `whitening_coverage`

---

## 6. Stage 3c: Enhanced Damage Assessment

**File:** `backend/api/combined_grading.py` (Stage 3c block, lines 511–550), called with `enhance_for_damage_detection()` from `backend/analysis/damage_preprocessing.py`

**Purpose:** Detect creases on holographic cards where Vision AI struggles due to foil colour noise.

**Problem addressed:**
- Holographic foil creates rainbow colour patterns that mask surface creases in raw RGB images
- Vision AI interprets foil sparkle as "normal" and returns `crease_depth=none` even on visibly damaged cards

**Solution: Split-Region Preprocessing**

Apply different enhancement levels to different card regions:

1. **Border region** (outside artwork box):
   - Grayscale (removes colour-dependent foil noise)
   - CLAHE with clipLimit=3.0 (amplifies local contrast)
   - Histogram equalization (normalizes brightness)
   - **Result:** Whitening/wear bright spots stand out clearly

2. **Artwork interior** (inside artwork box):
   - Grayscale
   - CLAHE with clipLimit=2.0 only (mild contrast boost)
   - **Result:** Crease dark lines visible, but artwork character edges not over-sharpened

3. **Convert back to BGR** for Vision AI compatibility

**Processing:**
1. Call `enhance_for_damage_detection(front_img)` → preprocessed BGR image
2. Call `assess_damage_from_full_images(front_enhanced, back_enhanced)` → damage assessment on preprocessed
3. Merge with Stage 3b result using upgrade-only logic

**Why this avoids false positives:**
- No unsharp masking globally (which would sharpen artwork character edges)
- Split-region approach gives artwork interior only mild enhancement
- Grayscale removes the holographic colour noise that was the root cause

---

## 7. Stage 4: Grade Assembly & Damage Cap

**File:** `backend/grading/grade_assembler.py`

### Composite Score Calculation

Weighted average of the 4 component scores:

```
composite = (corners × 0.375) + (edges × 0.375) + (surface × 0.25)
```

Note: Centering is NOT included in the composite. Centering operates as a hard PSA cap (see below).

### Blending Front + Back (if both provided)

**Corners:**
```
blended = (min_score × 0.55) + (max_score × 0.45)
```
Worse side weighted more heavily.

**Edges:**
```
blended = (min_score × 0.60) + (max_score × 0.40)
```

**Surface:**
```
blended = min(front_surface, back_surface)   # worst case only
```

Then the blended scores feed into the composite formula above.

### Damage Penalties

Applied after composite score:

| Damage Type | Condition | Penalty |
|---|---|---|
| Crease | `crease_depth == "heavy"` | Cap final score at **2.0** |
| Crease/Whitening | `crease_depth == "moderate"` OR `whitening_coverage == "extensive"` | Cap final score at **5.0** |

**Gate:** Damage penalties only apply if the damage assessment confidence ≥ 0.60 (ensures false positives don't crash the grade).

### Floor/Ceiling Bounds

```
final_score = clamp(composite,
                    max(worst_component - 0.5, 1.0),      # floor
                    min(worst_component + 1.0, 10.0))     # ceiling
```

Prevents the composite from diverging too far from the worst single component.

### Centering PSA Cap

If `centering_cap` (from centering analysis) is stricter than current grade:
```
final_score = min(final_score, centering_cap)
```

### Half-Point Rounding Gate

Only applies half-point rounding (e.g., 7.5) if:
- Fractional part ≥ 0.3, AND
- Centering average-axis score ≥ base_grade + 1

Otherwise rounds to nearest integer.

---

## 8. Final Grade Calculation

**PSA Grade Brackets:**

| Score range | Grade | Label |
|---|---|---|
| ≥ 9.5 | 10 | Gem Mint |
| ≥ 9.0 | 9 | Near Mint |
| ≥ 8.0 | 8 | Mint |
| ≥ 7.0 | 7 | Near Mint-Mint |
| ≥ 6.0 | 6 | Excellent-Mint |
| ≥ 5.0 | 5 | Excellent |
| ≥ 4.0 | 4 | Very Good-Excellent |
| ≥ 3.0 | 3 | Very Good |
| ≥ 2.0 | 2 | Good-Very Good |
| ≥ 1.0 | 1 | Good |
| < 1.0 | 0 | Poor |

---

## 9. Front + Back Blending

When user uploads both front and back, scores are combined with front-weighting (front condition matters slightly more).

See **Stage 4: Blending Front + Back** section above for blend formulas.

---

## 10. Confidence System

**Overall confidence** (weighted average of component confidences):

```
confidence = (centering_conf × 0.20)
           + (corners_conf   × 0.375)
           + (edges_conf     × 0.375)
           + (surface_conf   × 0.125)
```

**Grading status:**

| Confidence | Status | Meaning |
|---|---|---|
| < 0.4 | `refused` | Image too poor quality to grade |
| 0.4–0.6 | `low_confidence` | Grade provided with caveat |
| ≥ 0.6 | `success` | Normal grading |

**Damage confidence gate:** Damage cap penalties only trigger if `surface_confidence ≥ 0.60`, preventing false positives from cascading into grade destruction.

---

## 11. API Session Flow

**Endpoints:**

```
POST   /api/grading/start
POST   /api/grading/{session_id}/upload-front
POST   /api/grading/{session_id}/upload-back
GET    /api/grading/{session_id}/result
DELETE /api/grading/{session_id}
```

**Session lifecycle:**

- **TTL:** 30 minutes (idle-based; resets on every upload)
- **Cleanup:** Background task every 120 seconds

**Upload processing (front or back):**

1. Size check (max 15 MB)
2. Quality check (basic metrics)
3. Hybrid card detection (OpenCV → Claude Vision fallback)
4. Perspective correction (500×700 px)
5. Stage 2: Centering, Corners, Edges analysis
6. (If back): Stage 3, 3b, 3c assessments on front + back combined
7. Return grade result

---

## 12. Constants Reference

### Component Weights (Composite Calculation)

| Component | Weight | Note |
|---|---|---|
| Corners | 0.375 | Includes both basic and enhanced |
| Edges | 0.375 | Includes all 4 edges |
| Surface | 0.25 | Includes crease + whitening + scratches |
| Centering | — | Excluded; operates as hard PSA cap only |

### Blending Weights (Front + Back)

| Component | Worse Side | Better Side |
|---|---|---|
| Corners | 0.55 | 0.45 |
| Edges | 0.60 | 0.40 |
| Surface | 1.00 | — (worst-case only) |

### Damage Caps

| Damage Type | Condition | Final Score Cap |
|---|---|---|
| Heavy Crease | `crease_depth == "heavy"` | 2.0 |
| Moderate Crease or Extensive Whitening | `crease_depth == "moderate"` OR `whitening_coverage == "extensive"` | 5.0 |
| Gate | Damage assessment confidence ≥ 0.60 | (confidence must be above gate for cap to apply) |

### Vision AI API

| Setting | Value |
|---|---|
| Model | claude-sonnet-4-20250514 |
| Max tokens | 2048 |
| JPEG quality (Stage 3) | 80 |
| JPEG quality (Stage 3b/3c) | 95 |
| System prompt | `backend/grading/prompts/grading_prompt.txt` |
| Damage prompt | `backend/grading/prompts/damage_assessment_prompt.txt` |

### File Upload Limits

| Setting | Value |
|---|---|
| Max file size | 15 MB |
| Allowed origins | Railway production URL, localhost:8000, localhost:3000 |

---

## Known Limitations & Future Work

- **No live calibration against professional PSA grades** — grades are AI estimates only
- **Vision AI damage detection on holographic cards** — Stage 3c mitigates but doesn't completely solve
- **Flutter camera timeout (60s)** may be shorter than Vision AI worst-case latency (~90s)
- **Debug images accumulate on disk** — cleanup config exists but not implemented
- **OpenCV corner confidence** computed but unused; wasted CPU

---

*Document updated March 27, 2026 — reflects actual running code in backend/grading/ and backend/api/combined_grading.py*
