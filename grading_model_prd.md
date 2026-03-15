# PRD: Grading Model Architecture Overhaul

## Document Purpose

This PRD defines the architectural changes required to overhaul the card grading model for a PSA pre-grading application. The current system relies heavily on OpenCV threshold-based analysis for all grading dimensions (centering, corners, edges, surface). This approach has proven fragile — thresholds break across card types, border colors, and lighting conditions, requiring constant recalibration.

The new architecture splits responsibilities: **OpenCV handles geometric precision tasks** (card detection, perspective correction, centering measurement), and **Vision AI handles qualitative visual assessment** (corners, edges, surface condition). PSA grading rules are encoded as pure logic in a separate grade assembly layer.

**This document is intended to be consumed by an AI coding assistant (Claude Code) to generate an implementation plan. Write your plan against the existing codebase structure, preserving working components and replacing only what this PRD specifies.**

---

## Current System Problems

### Problem 1: Threshold Fragility
The current system uses OpenCV pixel-level measurements to detect defects:
- Corner damage is detected via **whitening ratio** (counting light pixels against card border color)
- Edge damage uses similar whitening detection
- Surface analysis detects scratches via line detection and creases via contour analysis

**Why this fails:** A dark-bordered card can have visibly rounded corners with no whitening. Warm-toned card borders trip the stain detection LAB delta threshold. Single-corner damage slips through the 2-corner noise guard. Every new card type that breaks a threshold requires manual recalibration, which risks breaking previously working cases.

### Problem 2: Centering as Weighted Input
The current system folds centering into a **weighted average at 20%**, meaning exceptional corners/edges/surface can compensate for poor centering and push the grade above what PSA would allow. PSA treats centering as a **hard ceiling** — a 70/30 card cannot exceed PSA 7 regardless of condition.

### Problem 3: Floor/Ceiling Logic Inversion
The current floor constraint uses `max(final_score, min_corner - 0.5)` which is a floor (prevents over-punishment). But there is no **ceiling** to prevent strong components from lifting the grade too far above the weakest component. Both constraints are needed.

### Problem 4: Missing Defect Types
PSA evaluates defects the current system does not detect:
- **Corner rounding** (geometric deformation without whitening)
- **Edge fraying** (fibrous texture) and **notching** (small indentations)
- **Staining and discoloration** (wax stains, yellowing)
- **Loss of original gloss**
- **Print registration errors** (printed image shifted relative to card border)
- **Enamel chipping**

### Problem 5: Front/Back Asymmetry Not Handled
PSA treats front and back differently — certain defects matter more on one side (e.g., "slight wax stain on reverse" is tolerable at PSA 9 but a front stain is not). The current blending ratios are symmetric.

---

## New Architecture Overview

The system is restructured into 4 sequential stages:

```
Stage 1: Capture & Correction (OpenCV) — KEEP EXISTING
    ↓
Stage 2: Centering Measurement (OpenCV) — MODIFY EXISTING
    ↓
Stage 3: Visual Assessment (Vision AI) — REPLACE EXISTING
    ↓
Stage 4: Grade Assembly (Pure Logic) — REWRITE
```

---

## Stage 1: Capture & Correction (OpenCV)

**Status: KEEP EXISTING — no changes required.**

This stage handles:
- Card detection in the camera frame (live overlay + still capture)
- Perspective correction (4-point warp to standardized rectangle)
- CLAHE preprocessing for lighting normalization
- Aspect ratio validation

The output is a clean, standardized front image and back image at a fixed resolution (e.g., 500×700px).

**Note:** Any improvements from the prior card detection improvement plan (debounce tuning, confidence hysteresis, two-pass warp, etc.) are orthogonal to this PRD and should continue independently.

---

## Stage 2: Centering Measurement (OpenCV)

**Status: MODIFY EXISTING — change from weighted input to hard cap.**

### What To Keep
- The existing border width measurement logic (measuring pixel distances on all 4 sides of front and back)
- The existing front/back detection (HSV blue detection for identifying which side is front)

### What To Change

#### 2.1 Centering Ratio Calculation
Compute the centering ratio as `smaller_margin / larger_margin` for each axis (left/right and top/bottom) on both front and back.

```
worst_ratio_front = min(left_right_ratio_front, top_bottom_ratio_front)
worst_ratio_back = min(left_right_ratio_back, top_bottom_ratio_back)
```

#### 2.2 Centering Cap Table
Map centering ratios to PSA grade caps. These thresholds are derived from PSA's published centering standards.

**Front centering caps:**

| PSA Centering | Ratio (smaller/larger) | Max Grade |
|---------------|----------------------|-----------|
| 55/45         | 0.818                | 10        |
| 60/40         | 0.667                | 9         |
| 65/35         | 0.538                | 8         |
| 70/30         | 0.429                | 7         |
| 75/25         | 0.333                | 6         |
| 80/20         | 0.250                | 5         |
| 85/15         | 0.176                | 4         |
| 90/10         | 0.111                | 3         |
| Worse than 90/10 | < 0.111           | 2         |

**Back centering caps:**

| PSA Centering | Ratio (smaller/larger) | Max Grade |
|---------------|----------------------|-----------|
| 75/25         | 0.333                | 10        |
| 90/10         | 0.111                | 9         |
| Worse than 90/10 | < 0.111           | 5         |

PSA is more lenient on back centering. The back centering cap table has fewer tiers because PSA's published guidelines only specify 75/25 for a 10 and 90/10 for grades below that.

#### 2.3 Apply the Lower Cap
The effective centering cap is:
```
centering_cap = min(front_centering_cap, back_centering_cap)
```

This cap is passed to Stage 4 and applied as a hard clamp AFTER the weighted composite is computed. Centering is **NOT** included in the weighted average.

#### 2.4 Centering Score for Half-Point Logic
In addition to the cap, compute a continuous centering score (1-10 scale) based on where the ratio falls within the cap table ranges. This score is used in Stage 4 for half-point grade determination, NOT for the composite calculation.

**Implementation detail:** Use linear interpolation between cap table entries to produce a smooth score. For example, a front ratio of 0.74 falls between 0.818 (grade 10) and 0.667 (grade 9), so the centering score would be approximately 9.5.

---

## Stage 3: Visual Assessment (Vision AI)

**Status: REPLACE EXISTING OpenCV-based corner, edge, and surface analysis.**

This is the largest change. Instead of building separate OpenCV modules for each defect type with hand-tuned thresholds, send standardized card images to a Vision AI model with a structured grading prompt.

### 3.1 Image Preparation

From the Stage 1 output (standardized front and back images), prepare the following crops:

**Corner crops (8 total — 4 per side):**
- Crop a region around each corner of the card. Size: approximately 15% of card width × 15% of card height from each corner.
- Label each crop: `front_top_left`, `front_top_right`, `front_bottom_left`, `front_bottom_right`, `back_top_left`, `back_top_right`, `back_bottom_left`, `back_bottom_right`.

**Edge strips (8 total — 4 per side):**
- Crop a strip along each edge, excluding the corners (which are already captured). Width: approximately 10% of the perpendicular card dimension.
- Label each strip: `front_top_edge`, `front_bottom_edge`, `front_left_edge`, `front_right_edge`, `back_top_edge`, `back_bottom_edge`, `back_left_edge`, `back_right_edge`.

**Surface images (2 total):**
- The full front and full back images from Stage 1.
- Label: `front_surface`, `back_surface`.

**Total images sent to Vision AI per grade:** 18 images (8 corners + 8 edges + 2 surfaces).

**Optimization note:** To reduce API cost, the 8 corner crops and 8 edge strips can be composited into 4 summary images (one per card side per dimension type). For example, all 4 front corner crops arranged in a 2×2 grid as a single image. This reduces the total to 6 images while preserving all visual information. Implement whichever approach yields better accuracy during calibration.

### 3.2 Vision AI Prompt Structure

The Vision AI call uses a structured system prompt that:
1. Establishes the grading context (PSA grading standards)
2. Defines the scoring scale for each dimension
3. Requests structured JSON output
4. Includes PSA's actual descriptive language at each grade level

**The prompt must request the following output structure:**

```json
{
  "corners": {
    "front_top_left": { "score": 9.0, "defects": ["minor whitening at tip"], "confidence": 0.85 },
    "front_top_right": { "score": 9.5, "defects": [], "confidence": 0.90 },
    "front_bottom_left": { "score": 8.0, "defects": ["visible rounding", "light fiber exposure"], "confidence": 0.80 },
    "front_bottom_right": { "score": 9.0, "defects": ["minor whitening"], "confidence": 0.85 },
    "back_top_left": { "score": 9.5, "defects": [], "confidence": 0.88 },
    "back_top_right": { "score": 9.5, "defects": [], "confidence": 0.90 },
    "back_bottom_left": { "score": 9.0, "defects": ["slight softening"], "confidence": 0.82 },
    "back_bottom_right": { "score": 9.5, "defects": [], "confidence": 0.88 }
  },
  "edges": {
    "front_top": { "score": 9.0, "defects": ["minor chipping"], "confidence": 0.85 },
    "front_bottom": { "score": 9.5, "defects": [], "confidence": 0.90 },
    "front_left": { "score": 9.0, "defects": ["slight roughness"], "confidence": 0.82 },
    "front_right": { "score": 9.5, "defects": [], "confidence": 0.88 },
    "back_top": { "score": 9.5, "defects": [], "confidence": 0.90 },
    "back_bottom": { "score": 9.0, "defects": ["minor whitening"], "confidence": 0.85 },
    "back_left": { "score": 9.5, "defects": [], "confidence": 0.88 },
    "back_right": { "score": 9.5, "defects": [], "confidence": 0.90 }
  },
  "surface": {
    "front": {
      "score": 8.5,
      "defects": ["light surface scratch across center", "minor print line near bottom"],
      "staining": "none",
      "gloss": "original gloss intact",
      "print_registration": "well-centered print",
      "confidence": 0.78
    },
    "back": {
      "score": 9.0,
      "defects": ["slight wax residue near top edge"],
      "staining": "minor wax residue",
      "gloss": "original gloss intact",
      "print_registration": "normal",
      "confidence": 0.82
    }
  }
}
```

### 3.3 PSA Grade Descriptors for the Prompt

The Vision AI prompt must include PSA's descriptive criteria at each grade level so the model can calibrate its scores against the correct standard. These should be embedded in the system prompt, NOT generated dynamically.

**Corner scoring guidance for the prompt:**
- **10 (Gem Mint):** Four perfectly sharp corners with no visible wear, whitening, or rounding under magnification.
- **9 (Mint):** Four sharp corners with only the most minor, barely perceptible imperfection allowed on one corner.
- **8 (NM-MT):** Minor wear visible on no more than two corners. Slight whitening or softening acceptable.
- **7 (Near Mint):** Slight rounding or minor wear on multiple corners. Slightly fuzzy corners allowed.
- **6 (EX-MT):** Fuzzy corners with moderate whitening. Visible rounding on most corners.
- **5 (Excellent):** Moderate rounding on all corners with noticeable wear.
- **4 (VG-EX):** Well-rounded corners with moderate to heavy wear.
- **3 (Very Good):** Significant rounding and wear on all corners.
- **2 (Good):** Extreme rounding, possible creasing at corners.
- **1 (Poor):** Severe damage, corners may be missing or torn.

**Edge scoring guidance for the prompt:**
- **10:** Pristine edges with no visible chipping, whitening, or roughness.
- **9:** Near-perfect edges with only the slightest imperfection.
- **8:** Minor chipping or whitening on one or two edges.
- **7:** Slight roughness or chipping noticeable on multiple edges.
- **6:** Moderate chipping, notching, or whitening along edges.
- **5:** Noticeable edge wear with moderate chipping throughout.
- **4:** Heavy chipping and roughness along most edges.
- **3:** Significant edge damage, possible delamination.
- **2:** Severe edge damage throughout.
- **1:** Extreme edge deterioration.

**Surface scoring guidance for the prompt:**
- **10:** No scratches, staining, print defects, or loss of gloss. A slight printing imperfection (not caused by handling) is allowed.
- **9:** One minor surface flaw allowed. No staining. Original gloss retained. Slight wax stain on reverse is tolerable.
- **8:** Minor surface wear visible. Slight loss of original gloss allowed. No heavy staining.
- **7:** Moderate surface wear. Slight gloss loss. Minor staining may be present.
- **6:** Noticeable surface wear, scratches, or print line disturbance. Moderate gloss loss.
- **5:** Moderate scratches, possible light crease not breaking the surface. Noticeable gloss loss.
- **4:** Heavy surface wear. Possible creases. Significant gloss loss.
- **3:** Heavy creasing, staining, or loss of surface integrity.
- **2:** Severe surface damage, major creases, heavy staining.
- **1:** Extreme damage, card may be torn or heavily water-damaged.

### 3.4 Consistency Controls

Vision model outputs can vary between calls. Implement the following controls:

1. **Temperature:** Set to 0 for deterministic output.
2. **Dual-pass averaging:** Run the assessment twice and average the numeric scores. If any individual score differs by more than 1.5 points between passes, run a third pass and take the median.
3. **Structured output enforcement:** The prompt must require JSON-only output with no preamble. Parse with error handling and retry on malformed responses (max 2 retries).
4. **Confidence thresholds:** If any score has confidence below 0.60, flag it in the output for potential manual review. Do not block the grade — just annotate it.

### 3.5 Model Selection

Use the most cost-effective model that can reliably assess card condition from cropped images:
- **Primary:** Claude Sonnet (claude-sonnet-4-20250514) — good balance of visual reasoning and cost.
- **Fallback:** If Sonnet proves insufficient during calibration testing, escalate to Claude Opus for the assessment call.

**Cost estimate per grade:** ~$0.02–0.06 per single pass depending on image count and resolution. With dual-pass: ~$0.04–0.12.

---

## Stage 4: Grade Assembly (Pure Logic)

**Status: REWRITE — no image analysis here, only rule application.**

This stage takes the centering cap from Stage 2 and the per-dimension scores from Stage 3 and applies PSA's grading rules as pure logic.

### 4.1 Front/Back Blending (Per Dimension)

For each dimension, compute a blended score from front and back scores with PSA-aligned asymmetric weights:

**Corners:**
```
front_corners_avg = average(front_TL, front_TR, front_BL, front_BR)
back_corners_avg = average(back_TL, back_TR, back_BL, back_BR)
corners_blended = (front_corners_avg * 0.60) + (back_corners_avg * 0.40)
```

**Edges:**
```
front_edges_avg = average(front_top, front_bottom, front_left, front_right)
back_edges_avg = average(back_top, back_bottom, back_left, back_right)
edges_blended = (front_edges_avg * 0.65) + (back_edges_avg * 0.35)
```

**Surface:**
```
surface_blended = (front_surface * 0.70) + (back_surface * 0.30)
```

The front is weighted more heavily across all dimensions because PSA weighs front presentation more heavily. Surface has the strongest asymmetry because PSA explicitly tolerates certain back-only defects (e.g., wax stains on reverse at PSA 9).

### 4.2 Weighted Composite Score

Compute the weighted composite from the three blended dimension scores. Centering is NOT included — it acts as a cap only.

```
composite = (corners_blended * 0.30) + (edges_blended * 0.30) + (surface_blended * 0.40)
```

Weight rationale:
- Surface at 40% because PSA descriptions reference surface defects more frequently as grade differentiators, and surface defects (scratches, creases, staining) have the widest impact on presentation.
- Corners and edges at 30% each because PSA treats them as roughly equivalent in importance, with corners perhaps slightly more scrutinized (but this is handled by the floor/ceiling constraints below).

### 4.3 Floor and Ceiling Constraints

Compute the worst individual blended dimension score:
```
worst_dimension = min(corners_blended, edges_blended, surface_blended)
```

Apply both constraints:
```
# Floor: don't over-punish beyond the worst dimension
composite = max(composite, worst_dimension - 0.5)

# Ceiling: don't over-reward above the worst dimension
composite = min(composite, worst_dimension + 1.0)
```

The floor prevents the weighted average from dragging the score more than 0.5 below the worst single dimension. The ceiling prevents strong dimensions from lifting the score more than 1.0 above the weakest dimension. The +1.0 ceiling offset is tunable during calibration.

### 4.4 Individual Component Floor

In addition to the dimension-level floor/ceiling, apply a component-level floor using the single worst individual score across all 16 scored components (8 corners + 4 front edges + 4 back edges — surface is already 2 scores):

```
worst_individual = min(all individual corner scores, all individual edge scores, front_surface, back_surface)
composite = min(composite, worst_individual + 1.5)
```

This catches the case where one badly damaged corner (e.g., 4.0) would be averaged away by three good corners. With this constraint, a single corner at 4.0 means the overall grade cannot exceed 5.5.

### 4.5 Centering Cap Application

Apply the centering cap from Stage 2 as a hard clamp:
```
final_score = min(composite, centering_cap)
```

This is applied AFTER all other adjustments. A card with perfect corners/edges/surface but 70/30 centering will be capped at 7.0.

### 4.6 Half-Point Grade Logic

PSA uses half-point grades (e.g., PSA 8.5, PSA 9.5) with specific emphasis on centering. Implement as follows:

```
base_grade = floor(final_score)  # e.g., 8 for a score of 8.7

# Determine if the card qualifies for the half-point bump
qualifies_for_half = (
    (final_score - base_grade) >= 0.3  # Score is in the upper range of the grade
    AND centering_score >= base_grade + 1  # Centering is strong enough for the next grade up
)

if qualifies_for_half:
    displayed_grade = base_grade + 0.5  # e.g., 8.5
else:
    displayed_grade = base_grade  # e.g., 8
```

The critical requirement is that centering must be a **strength** for the half-point bump — it must score at or above the next grade level. This matches PSA's stated emphasis that centering gets "clear focus" for half-point grades. A card with borderline centering should NOT get the half-point bump even if the composite score is high enough.

### 4.7 Grade Output Format

The final output includes:
```json
{
  "final_grade": 8.5,
  "composite_score": 8.72,
  "centering_cap": 10,
  "centering_score": 9.2,
  "dimension_scores": {
    "corners": { "blended": 8.6, "front_avg": 8.5, "back_avg": 8.8 },
    "edges": { "blended": 9.1, "front_avg": 9.0, "back_avg": 9.2 },
    "surface": { "blended": 8.5, "front": 8.2, "back": 9.0 }
  },
  "individual_scores": {
    "corners": {
      "front_top_left": 9.0,
      "front_top_right": 9.5,
      "front_bottom_left": 7.0,
      "front_bottom_right": 8.5,
      "back_top_left": 9.0,
      "back_top_right": 9.0,
      "back_bottom_left": 8.5,
      "back_bottom_right": 9.0
    },
    "edges": {
      "front_top": 9.0,
      "front_bottom": 9.5,
      "front_left": 8.5,
      "front_right": 9.0,
      "back_top": 9.5,
      "back_bottom": 9.0,
      "back_left": 9.0,
      "back_right": 9.5
    },
    "surface": {
      "front": 8.2,
      "back": 9.0
    }
  },
  "defects": [
    { "location": "front_bottom_left_corner", "description": "visible rounding with light fiber exposure", "severity": "moderate" },
    { "location": "front_surface", "description": "light surface scratch across center", "severity": "minor" },
    { "location": "front_surface", "description": "minor print line near bottom", "severity": "minor" },
    { "location": "back_surface", "description": "slight wax residue near top edge", "severity": "minor" }
  ],
  "constraints_applied": {
    "floor_activated": false,
    "ceiling_activated": false,
    "component_floor_activated": false,
    "centering_cap_activated": false,
    "half_point_qualified": true
  },
  "confidence": {
    "overall": 0.84,
    "low_confidence_flags": []
  }
}
```

---

## Calibration & Testing Plan

### Phase 1: Ground Truth Collection
Collect 30-50 cards where the actual PSA grade is known (cards that have been submitted and returned). This is the calibration dataset. It should include:
- Cards across the full grade range (PSA 4 through PSA 10)
- Multiple card types (different border colors, holofoil, full-art, vintage, modern)
- Cards with known centering issues
- Cards with known single-dimension weaknesses (e.g., great condition but poor centering)

### Phase 2: Vision AI Prompt Calibration
1. Run each calibration card through the Vision AI prompt (Stage 3).
2. Compare the AI's per-dimension scores against what the known PSA grade implies.
3. Iterate on prompt wording, PSA descriptor language, and scoring anchors until the AI's scores are directionally correct and consistent.
4. Key metric: For cards where a single dimension clearly anchored the PSA grade (e.g., a card with poor centering that got a PSA 7), verify that the system correctly identifies and constrains on that dimension.

### Phase 3: Grade Assembly Calibration
1. With AI scores stabilized, run the full Stage 4 logic.
2. Compare output grades against known PSA grades.
3. Tune the following parameters if needed:
   - Front/back blending weights (currently 60/40, 65/35, 70/30)
   - Dimension weights in composite (currently 30/30/40)
   - Floor offset (currently -0.5)
   - Ceiling offset (currently +1.0)
   - Component floor offset (currently +1.5)
   - Half-point qualification thresholds
4. Target: ±0.5 grade accuracy on 80%+ of calibration cards, ±1.0 on 95%+.

### Phase 4: Edge Case Testing
Specific test cases that MUST pass:
1. **Centering cap dominance:** Card with 70/30 front centering, all other dimensions at 9.5 → final grade MUST be 7.0 (not higher).
2. **Single destroyed corner:** Three corners at 9.5, one corner at 4.0, everything else at 9.5 → final grade should be approximately 5.0-5.5 (component floor prevents it from being higher).
3. **Centering cap + floor interaction:** Card with centering cap at 7, but corners at 9.5, edges at 9.5, surface at 9.5 → grade must be exactly 7.0. The floor must NOT push it above the centering cap.
4. **Half-point centering requirement:** Card scoring 8.7 composite with centering score of 8.2 → grade should be 8, NOT 8.5 (centering isn't strong enough for the bump).
5. **Half-point qualification:** Card scoring 8.7 composite with centering score of 9.5 → grade should be 8.5.
6. **Back surface forgiveness:** Card with wax stain on back but clean front → surface score should NOT be as penalized as same stain on front.
7. **Dark border corner rounding:** Card with dark borders and rounded corners (no whitening) → corners should still score below 9.

---

## Files and Modules Affected

This section maps the architecture changes to the expected codebase structure. Adjust paths as needed based on actual project layout.

### New Files to Create
- `backend/grading/vision_assessor.py` — Stage 3 Vision AI integration. Handles image cropping, prompt construction, API calls, response parsing, dual-pass averaging, and retry logic.
- `backend/grading/grade_assembler.py` — Stage 4 pure logic. Takes centering cap + vision scores, applies blending, composite, floor/ceiling, centering cap, half-point logic, produces final output.
- `backend/grading/prompts/grading_prompt.txt` — The system prompt for the Vision AI grading call. Separate file so it can be iterated without code changes.
- `backend/grading/calibration/` — Directory for calibration scripts and test fixtures.
- `backend/grading/calibration/test_known_grades.py` — Test suite that runs calibration cards through the full pipeline and compares against known PSA grades.

### Files to Modify
- `backend/grading/centering.py` — Modify to output a centering cap (from the cap table) and a continuous centering score, instead of a weighted-average-ready centering value. Remove any logic that feeds centering into a composite weight.
- `backend/api/grade_card.py` (or equivalent API endpoint) — Rewire to call the new pipeline: Stage 1 (existing) → Stage 2 (modified centering) → Stage 3 (new vision assessor) → Stage 4 (new grade assembler).

### Files to Deprecate (Do Not Delete Yet)
- `backend/grading/corners.py` — The existing OpenCV corner whitening analysis. Keep for reference but remove from the active pipeline.
- `backend/grading/edges.py` — The existing OpenCV edge whitening analysis. Same treatment.
- `backend/grading/surface.py` — The existing OpenCV surface scratch/crease detection. Same treatment.
- Any threshold constants, calibration values, or config entries that fed the old OpenCV-based corner/edge/surface modules.

**Important:** Do not delete deprecated files. Move them to a `deprecated/` directory or add a clear comment header marking them as superseded. They contain useful logic for reference and potential hybrid fallback if the Vision AI approach needs supplementing in specific cases.

---

## Environment and API Configuration

### Vision AI API Setup
- The Vision AI calls require an Anthropic API key configured as an environment variable: `ANTHROPIC_API_KEY`.
- API calls should use the Anthropic Python SDK (`anthropic` package).
- Timeout: 30 seconds per call. If a call times out, retry once. If the retry also times out, return an error state (do not fall back to OpenCV grading — a partial grade is worse than an explicit failure).
- Rate limiting: Implement a simple semaphore or queue if concurrent grading requests could exceed API rate limits. For MVP, a single-request-at-a-time model is acceptable.

### Image Format for API
- Images sent to the Vision AI should be JPEG at 80% quality to minimize token cost while preserving sufficient detail.
- Maximum resolution per crop: 512×512px for corners, 512×(variable) for edge strips, 1024×1024 for full surface images.
- Images are sent as base64-encoded content in the API request.

---

## Implementation Priority Order

1. **Stage 4 (Grade Assembly)** — Can be implemented and unit-tested immediately with mock vision scores. This is the most logic-dense stage and benefits from early testing.
2. **Stage 2 (Centering Modification)** — Small change to existing code. Implement the cap table and continuous score output.
3. **Stage 3 (Vision AI Assessor)** — Implement the image cropping, prompt, API integration, and response parsing.
4. **Pipeline Integration** — Wire all stages together in the API endpoint.
5. **Calibration** — Run against known-grade cards and tune parameters.

This ordering allows parallel work: Stage 4 can be developed and tested while Stage 3 is being built, since Stage 4 only needs score inputs (which can be mocked).

---

## Success Criteria

- The system produces a PSA-aligned grade within ±0.5 of the actual PSA grade for 80%+ of calibration cards.
- The system produces a grade within ±1.0 of the actual PSA grade for 95%+ of calibration cards.
- All 7 edge case tests in Phase 4 pass.
- The centering cap is never violated by any other constraint.
- A single badly damaged component (score ≤ 4) anchors the final grade within 1.5 points of that component's score.
- Per-grade API cost stays under $0.15 (dual-pass Vision AI with retries).
- Grading latency is under 15 seconds end-to-end (including two Vision AI passes).
- The system produces a human-readable defect list that explains the grade.
