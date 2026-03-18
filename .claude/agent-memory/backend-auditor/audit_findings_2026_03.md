---
name: March 2026 Comprehensive Backend Audit Findings
description: Critical bugs, verified invariants, architecture notes from the March 2026 full audit
type: project
---

## Architecture (confirmed current state)

The LIVE grading pipeline is:
1. grading.py (upload handlers) -> hybrid_detect.py (card detection/correction)
2. combined_grading.py (analyze_single_side for centering, then combine_front_back_analysis)
3. vision_assessor.py (assess_card -> Vision AI API for all scores)
4. grade_assembler.py (assemble_grade -> pure logic)

scoring.py GradingEngine is DEAD CODE — not imported by any live pipeline file.
corners.py analyze_corners IS CALLED in grading.py but its result is NEVER used by grade_assembler.py (dead CPU cost).

## Critical Bugs Found

### 1. Individual Floor Over-Penalization (grade_assembler.py _apply_individual_floor)
- worst_individual + 1.5 ceiling uses ALL 18 scores (8 corners, 8 edges, 2 surface)
- Single Vision AI outlier score (e.g., 5.0 on one back corner) caps composite at 6.5
- Even if 17/18 scores are 8.5, composite gets clamped from ~8.4 to 6.5
- This is the PRIMARY cause of grade 6 on a near-mint card with one harsh AI assessment
- File: backend/grading/grade_assembler.py, _apply_individual_floor()

### 2. Hallucination Guard False Positive (vision_assessor.py _validate_response)
- Guard fires when ALL 8 corner scores are identical
- A uniformly graded NM card (e.g., model returns 8.0 for all corners) triggers the guard
- All 3 API retries fail -> VisionAssessorError -> grade returns "?" with final_score=0
- File: backend/grading/vision_assessor.py, line ~312-313

### 3. Blending Semantics Mismatch (grade_assembler.py)
- Documented: corners 55/45 worse/better weighted, edges 60/40 worse/better, surface 65/35 worse/better
- Actual code: corners 60/40 FRONT-weighted (fixed), edges 65/35 FRONT-weighted, surface 70/30 FRONT-weighted
- Semantics are completely different: documented is adaptive, code is fixed front-biased
- Impact: when back is worse than front, grade is ~0.3 points higher than documented spec intends
- File: backend/grading/grade_assembler.py, _blend_corners/_blend_edges/_blend_surface

### 4. Conservative Prompt Bias + Busy Artwork (grading_prompt.txt)
- "Be conservative: if in doubt, choose the lower one" creates systematic downward bias
- For Rapidash (fire card with complex artwork), Claude may score surface 6.0-6.5 instead of 8.0
- Combined with individual floor: surface 6.0 -> ceiling 7.5, caps an otherwise 8+ card

### 5. Artwork Box Centering: Wrong Reference Frame
- detect_inner_artwork_box() returns the LARGEST contour in 15-70% of card area
- This detects the inner frame/border element, NOT the outer printed card border
- Centering measured relative to inner frame gives incorrect border measurements
- File: backend/analysis/centering.py, detect_inner_artwork_box()

## Logic Errors (Spec vs Implementation)

### Composite Weights (grade_assembler.py)
- Documented: centering 20%, corners 30%, edges 30%, surface 20%
- Code: corners 30%, edges 30%, surface 40% (centering excluded, its 20% redistributed to surface)
- Surface has double its documented weight (40% vs 20%)
- This is INTENTIONAL per code comments (centering operates as cap, not in composite)
- But the surface weight is 40% not 20%, undocumented redistribution

### Scoring.py vs Grade_Assembler.py Weight Divergence
- scoring.py uses corners 35%, edges 35%, surface 30%
- grade_assembler.py uses corners 30%, edges 30%, surface 40%
- scoring.py is dead code (never called in live pipeline), but creates confusion

## Verified-Correct Invariants

- Centering cap gated on confidence >= 0.6: CORRECT (grade_assembler.py _apply_centering_cap line ~176)
- Centering excluded from floor/ceiling: CORRECT (floor_components in grade_assembler only use blended dimensions)
- Session TTL 30 min reset on upload: CORRECT (session_manager.py touch() called in update_session())
- File upload 15MB limit: CORRECT (grading.py MAX_UPLOAD_BYTES = 15*1024*1024)
- PSA centering cap applied before half-point: CORRECT (step 5 before step 6 in assemble_grade)
- Vision AI dual-pass with median-of-3 on disagreement > 1.5: CORRECT
- CLAHE is stateless per-call, no cross-request contamination: CONFIRMED

## Architectural Notes

- corners.py analyze_corners_enhanced is called in grading.py but NEVER feeds into grade assembly (dead CPU)
- Front-only grading duplicates front image as back (assess_card(front_img, front_img)) — grade is mathematically neutral but wastes 2 API calls on identical images
- global _clahe object in hybrid_detect.py is shared across concurrent requests — threading risk if multiple simultaneous uploads hit OpenCV methods
- global _detection_stats dict in hybrid_detect.py has no lock — concurrent increments can corrupt counters (minor)
- SessionManager uses threading.Lock from async FastAPI handlers — blocks event loop under contention (low severity for low concurrency)

## March 2026 Targeted Image Pipeline Audit (additional findings)

### CONFIRMED FIXED from previous audit
- Individual floor over-penalization: REMOVED (grade_assembler.py no longer has _apply_individual_floor)
- Conservative prompt bias: "if in doubt, lower" instruction REMOVED from grading_prompt.txt
- Composite weights: corners 37.5%, edges 37.5%, surface 25% — matches MEMORY.md
- Blending ratios: corners 60/40 front-weighted, edges 65/35, surface 70/30 — matches MEMORY.md

### NEW bugs found in this audit

#### CRITICAL-1: interpolate_centering_score returns 1.0 for ratio == table[-1][0]
- centering.py line 68: `if ratio < table[-1][0]: return 1.0` — note strict less-than
- But FRONT_CAP_TABLE[-1] = (0.000, 2): threshold is 0.0, so this branch never fires for valid ratios
- BACK_CAP_TABLE[-1] = (0.000, 5): same — threshold is 0.0 so the below-minimum branch is dead
- The for-loop at line 71-76 will also miss ratio == r_high exactly (condition is r_low <= ratio < r_high)
- If ratio == table[i][0] exactly for an interior entry, it is caught by i-1's (r_low <= ratio < r_high)
  EXCEPT for ratio == table[0][0] which is caught by line 64-65. No actual hole due to floating point rarity,
  but the loop can fall-through to line 78 return 1.0 if floating point lands exactly on a boundary — rare but possible.

#### CRITICAL-2: artwork_box centering uses corrected image dimensions but artwork_box may reference original
- centering.py line 619: `x, y, w, h = artwork_box` where artwork_box = detect_inner_artwork_box(corrected)
- corrected is perspective-warped to 500×700 in hybrid_detect.py
- img_width/img_height captured at line 552 from corrected.shape — consistent, so this is FINE for pure vision_ai path
- But: if vision_ai path fires, perspective_correct_card is called (line 550) on the ORIGINAL raw image, not the already-corrected image from hybrid_detect — the centering module re-corrects the image independently, potentially to different dimensions and orientation

#### CRITICAL-3: detect_card_side back-detection logic: blue_mask.size uses full array size, not pixel count
- combined_grading.py line 37: `blue_pct = cv2.countNonZero(blue_mask) / blue_mask.size * 100`
- blue_mask.size for a 2D uint8 mask is h*w (correct for 2D), so this is actually correct
- BUT: if the image passed to cv2.cvtColor is already BGR (which it is from cv2.imread), this is fine
- Not a bug — marking as VERIFIED CORRECT

#### LOGIC-1: _half_point_grade compares worst centering SCORE to base+1, but centering_score is from cap table (1–10), not the 1–10 composite
- grade_assembler.py line 175: `worst_centering_score >= base + 1`
- centering_score is the cap table interpolated score (from FRONT_CAP_TABLE/BACK_CAP_TABLE)
- base is the floor of the composite (corners/edges/surface)
- These are different scales only by coincidence — both use 1–10 but the semantics differ
- A card scoring composite 7 needs centering score >= 8 to qualify for half-point
- The cap table scores are conservative (BACK at ratio 0.333 → score 10.0), so this gate is loose
- CONSEQUENCE: half-point rarely blocks anything useful, but the comparison is conceptually muddled

#### LOGIC-2: _check_edge_whitening false-positive ratio can call return 0.0 when total_white == 0 but we've already gated on white_pixels >= 10
- corners.py line 196-197: `if white_pixels < 10: return False` (in _is_false_positive)
- But _check_edge_whitening line 233-234 also handles total_white == 0 by returning 0.0
- The gate in _is_false_positive only checks white_pixels before calling _check_edge_whitening
- white_mask passed to _check_edge_whitening is ALREADY bitwise_and with corner_mask
- So white_pixels in _is_false_positive and total_white in _check_edge_whitening can diverge
  if corner_mask area is very small — low risk but logically inconsistent

#### LOGIC-3: detect_border_widths (saturation fallback) initialises left_width = 0, not min_border
- centering.py lines 404, 415, 425, 436: loop breaks on first non-saturated column/row
- If the very first column (x=0) is non-saturated, left_width stays at 0
- Then line 445: `left_width = max(left_width, w * 0.02)` catches this — so the final value is w*0.02
- BUT the "break with left_width = x" where x is the first non-saturated column records x, not x-1
  (the border ends at x-1, not at x) — this is an off-by-one: the detected width is one pixel too wide
- Impact: border is slightly overcounted on all 4 sides, slightly inflating the symmetry ratio and making centering look slightly better than it is. Low severity but systematic.

#### LOGIC-4: _opencv_standard/_opencv_adaptive/_opencv_morphological share a module-level _clahe instance
- hybrid_detect.py line 204: `_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))`
- CLAHE in OpenCV is NOT thread-safe for concurrent apply() calls on the same instance
- Under concurrent uploads, multiple requests calling _clahe.apply(gray) simultaneously can corrupt results
- Should be created per-call or use a lock

#### CONFOUNDING-1: centering.py runs perspective_correct_card() independently from hybrid_detect.py
- hybrid_detect.py warps to a fixed 500×700 output
- centering.py calls perspective_correct_card() (from image_preprocessing) on the SAME file
- If the two perspective corrections disagree on orientation (landscape vs portrait), centering measures
  a different card view than what Vision AI sees — can produce inverted L/R or T/B measurements

#### CONFOUNDING-2: front/back image_path stored in analyze_single_side may point to raw OR corrected image
- combined_grading.py line 79: `"image_path": image_path` — this is the analysis_image_path from grading.py
- grading.py line 78: analysis_image_path = str(corrected_path) if detection succeeded
- So front_analysis["image_path"] is the perspective-corrected image when detection succeeds
- But centering is computed by calculate_centering_ratios(image_path) which re-runs perspective correction on it
- This means centering re-corrects an already-corrected image — double perspective warp, deforming the card

#### CONFOUNDING-3: _detection_stats dict has no lock
- hybrid_detect.py lines 38-44, 380-387: global dict mutated without lock
- Under concurrent requests, increments can be lost (race on dict read-modify-write)
- Does not affect grades, only monitoring statistics

### Verified Correct in this audit
- lookup_centering_cap table exhaustion: table[-1] always has threshold 0.0, so fallback return is unreachable in practice
- cross_axis_unreliable cap to 0.5: CORRECT (centering.py line 748)
- symmetry_corrected cap to 0.6: CORRECT (centering.py line 750), correctly only fires when NOT cross_axis_unreliable
- PSA centering cap gated on confidence >= 0.6: CORRECT (grade_assembler.py line 159)
- Centering excluded from floor/ceiling: CORRECT (_apply_floor_ceiling takes only corners/edges/surface)
- Session TTL reset on every update_session: CORRECT (session_manager.py update_session calls touch())
- 15MB upload limit: CORRECT (grading.py MAX_UPLOAD_BYTES = 15*1024*1024, checked after file.read())
- Vision AI dual-pass / median-of-3: CORRECT
- Half-point grade step placed after centering cap: CORRECT
- Hallucination guard now only fires on placeholder values {1.0, 5.0, 10.0}: CORRECT (was previously too broad)
- BACK_CAP_TABLE is more lenient than FRONT_CAP_TABLE: CORRECT per PSA spec

## Fragile Areas to Monitor

1. Double perspective-warp: centering re-corrects already-corrected images when detection succeeds
2. CLAHE thread-safety under concurrent uploads
3. Artwork box centering — inner frame vs outer border (still present, documented in previous audit)
4. interpolate_centering_score loop fall-through at exact boundary ratios (floating point edge case)
5. detect_border_widths off-by-one: border widths 1px too wide on all 4 sides
