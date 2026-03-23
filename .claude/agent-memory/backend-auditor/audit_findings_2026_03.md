---
name: March 2026 Comprehensive Backend Audit Findings
description: Critical bugs, verified invariants, architecture notes from the March 2026 full audit (updated March 22 with new findings)
type: project
---

## Architecture (confirmed current state)

The LIVE grading pipeline is:
1. grading.py (upload handlers) -> hybrid_detect.py (card detection/correction)
2. combined_grading.py (analyze_single_side for centering, then combine_front_back_analysis)
3. vision_assessor.py (assess_card -> Vision AI API for all scores)
4. grade_assembler.py (assemble_grade -> pure logic)

scoring.py GradingEngine is DEAD CODE — not imported by any live pipeline file.
corners.py analyze_corners IS CALLED in grading.py but its result is NEVER used by grade_assembler.py (dead CPU cost). Only the overall_grade is stored as opencv_corner_grade for Vision AI cross-check.

## Critical Bugs Found (March 2026 — current session)

### CRITICAL-1: detect_border_widths_hsv transposes scan arrays for LR but not TB — wrong axis shape
- centering.py lines 290-305:
  - Left scan: `_border_width_axis(left_strip_hue, left_strip_sat, hue.T, sat.T, val.T, w, ...)`
  - Right scan: same transposed arrays, dim=w
  - Top scan: `_border_width_axis(top_strip_hue, top_strip_sat, hue, sat, val, h, reverse=False)`
  - Bottom scan: same, dim=h
- For Left/Right, `hue.T` is transposed: shape (w, h) indexed by column-index, which is correct
  for horizontal axis iteration (column-by-column). BUT:
- The `scan_range` iterates indices 0..dim//3 where dim=w. That's correct for left/right.
- Then `scan_hue[idx]` on hue.T gives `hue.T[idx]` = row idx of the TRANSPOSED array = COLUMN idx of original
  This IS correct for scanning columns left-to-right. VERDICT: Logic is correct.
- BUT for the strip sampling: `left_strip_hue = hue[:, :SAMPLE_STRIP].flatten()` — this samples
  the first 3 columns of the full image height — also correct.
- NET: Not actually a bug after full trace. Marking as VERIFIED CORRECT.

### CRITICAL-1 (new): _border_width_axis scan for RIGHT border has reversed direction semantics
- centering.py line 259: `scan_range = range(dim - 1 - SAMPLE_STRIP, max(dim - dim // 3, dim - 120), -1)`
- With dim=w, this scans from right toward center (column w-1 to ~w-120 or ~2w/3), going negative (reverse=True)
- `width = (dim - 1 - idx)` when reverse=True: if idx=w-50, width = 49. That's the right border width. Correct.
- NET: Not a bug. VERIFIED CORRECT.

### CRITICAL-1 (actual): detect_border_widths_hsv: Top/Bottom scan passes `hue` (not hue.T) but indexes by [idx]
- centering.py line 300: `top = _border_width_axis(top_strip_hue, top_strip_sat, hue, sat, val, h, reverse=False)`
- Inside `_border_width_axis`, `scan_hue[idx]` for a NON-transposed array gives ROW idx — that's a horizontal
  slice. For top/bottom scanning (row by row), this is CORRECT: `hue[row_idx]` = that entire row.
- NET: Also correct. The function is parameterized correctly for both axes.

### CRITICAL-2 (actual): get_card_corners zero-initialized fallback is silently wrong
- image_preprocessing.py lines 234-253: `sorted_points = np.zeros((4, 2), dtype=np.float32)`
- Points not hitting any quadrant (cards rotated exactly on axis, or points on the center line) leave
  sorted_points[i] at [0, 0] — i.e. one or more corners mapped to the top-left pixel
- The fallback `if np.all(sorted_points == 0)` only fires if ALL 4 are zero, not if only some are
- A card with one corner exactly on the center vertical/horizontal line leaves one entry as [0,0]
  and the fallback never fires → perspective warp warps to a degenerate quadrilateral
- IMPACT: Rare but produces a corrupted corrected image when a card corner lies exactly on the
  centroid's x or y coordinate. The `_check_warp_quality` gate may or may not catch it.
- STATUS (March 22 re-audit): STILL PRESENT. image_preprocessing.py lines 226-232 use sum/diff approach
  which is NOT zero-based — this is actually a different implementation. The sum/diff approach assigns
  TL=argmin(sum), BR=argmax(sum), TR=argmin(diff), BL=argmax(diff). This ALWAYS assigns all 4 positions
  (argmin/argmax always return valid indices). No zero-fill issue. REVISED: VERIFIED CORRECT.

### CRITICAL-3: Vision AI corner order in ai_corners not validated before perspective warp
- vision_detector.py line 227: `ai_corners = np.array(corners, dtype=np.float32)`
- FIXED: vision_detector.py lines 228-235 now validate `len(corners) != 4` before the array operation
  and return {"final_corners": None, "confidence": 0.0, ...}. VERIFIED FIXED.

### CRITICAL-4: Quality check 'valid' key semantics: can_analyze=False cards are accepted
- quality_checks.py line 150-162: quality="poor" sets `can_analyze=False` but `valid=True`
- grading.py line 61: FIXED — now checks `can_analyze` directly: `if not quality_result.get("can_analyze", True)`
- VERIFIED FIXED: grading.py lines 61-70 block on `can_analyze=False`.

### NEW-CRITICAL-1: _record_stat never accumulates total_time_ms
- hybrid_detect.py lines 383-391: `_record_stat(method)` only increments totals/buckets
- `_detection_stats["total_time_ms"]` is never updated — stays at 0 forever
- `get_detection_stats()` line 175: `_detection_stats["total_time_ms"] / total` → always returns 0.0 / N
- This is a monitoring-only bug; grades are unaffected. But admin stats are misleading.

### NEW-CRITICAL-2: _apply_opencv_corner_cross_check mutates vision dict in-place before assembly
- combined_grading.py lines 349-386: `_apply_opencv_corner_cross_check` receives the `vision_result` dict
  and modifies `vision["corners"][k]["confidence"]` in-place
- combined_grading.py line 210: `surface_raw=vision["surface"]` — passes the SAME dict reference to AssemblyInput
- This is fine because surface_raw is read-only in grade_assembler.py
- BUT: `_assemble_result_to_compat` at line 317 also reads from `vision["corners"]` post-mutation
  → the confidence values in the API response are already reduced by the cross-check penalty
- VERDICT: This is intentional behavior (the API should reflect reduced confidence). VERIFIED CORRECT.

### NEW-CRITICAL-3: artwork_box detection assigns confidence 0.90 but can produce inverted measurements
- centering.py lines 635-650: artwork_box method uses `x`, `y`, `w`, `h` from bounding rect
- left = x, right = img_width - (x + w), top = y, bottom = img_height - (y + h)
- If the bounding rect is slightly larger than the inner artwork area (e.g., includes a nearby label
  contour), `x + w > img_width` could yield `right < 0`
- BUT: centering.py lines 643-650 validate lr_ratio and tb_ratio < 0.3 as "unreliable"
  → negative right would give min(left, neg) / max(left, neg) which is 0 or negative / positive,
  always < 0 → fallback triggers
- VERDICT: The validation guard catches this case. VERIFIED CORRECT via fallback logic.

### CRITICAL-5 (prior): _apply_damage_cap "most severe wins" logic
- PREVIOUSLY ASSESSED AS CORRECT. Re-verified March 22. CONFIRMED CORRECT.

## New Logic Errors Found (March 22, 2026)

### NEW-LOGIC-1: artwork_box margin filter now correctly excludes ALL four edges
- centering.py lines 141-145 (UPDATED vs prior audit):
  ```python
  if (x < img_width * margin or y < img_height * margin or
          x + w > img_width * (1 - margin) or y + h > img_height * (1 - margin)):
      continue
  ```
- PRIOR AUDIT flagged this as only excluding top-left corner (AND condition)
- NOW FIXED: uses OR across all 4 edges → contours touching ANY edge are excluded
- VERIFIED FIXED.

### NEW-LOGIC-2: Vision AI grading_prompt.txt says "crease_depth and whitening_coverage are optional"
  but grade_assembler.py _apply_damage_cap does `data.get("crease_depth")` — None for missing fields
- grading_prompt.txt line 128: "Omit them entirely or set to null if you cannot assess them reliably"
- grade_assembler.py lines 210-225: `crease = data.get("crease_depth")` → None if omitted/null
- `if crease and CREASE_ORDER.get(crease, 0) >= 3` — None is falsy → skipped silently
- VERDICT: This is intentional and correct. Omitted crease → no damage cap. No bug.

### NEW-LOGIC-3: Grade range display uses composite_score but composite_score is POST-centering-cap
- combined_grading.py lines 247-260: `_assemble_result_to_compat` computes grade_range from `composite`
- `composite` at this point is `assembler_result["composite_score"]` which is the CAPPED composite
  (centering cap already applied by grade_assembler.py step 4)
- For a card with composite=8.7 but centering cap=7, `composite_score` = 7.0
- grade_range logic: finds PSA label "7", looks at bracket index 3 (7.0 threshold)
  checks if composite (7.0) >= 9.0 - 0.3 = 8.7 → False → grade_range = "7"
- This means a card capped by centering at 7 never shows a range, even if it would naturally be 9 range
- IMPACT: Grade range display correctly reflects the actual result after all caps.
  The centering cap dominates; showing a higher range would be misleading. CORRECT BY DESIGN.

### NEW-LOGIC-4: Half-point gate uses min(front_avg, back_avg) which is correct
- grade_assembler.py lines 259-264: `worst_avg_centering = min(front_avg_centering_score, back_avg_centering_score)`
- This correctly uses the WORST of the two sides for half-point
- BUT: `front_avg_centering_score` falls back to `front_centering_score` (worst-axis) if avg not provided
  (CenteringResult.__post_init__ at line 97-100)
- combined_grading.py line 135: `front_avg = float(front_centering.get("centering_avg_score", front_score))`
  where `front_score` is the worst-axis score
- If centering detection fails and returns the fallback dict (lines 111-116), `centering_avg_score` key is absent
  → fallback to worst-axis score → half-point gate uses worst-axis instead of avg
- IMPACT: On detection failure, half-point gate is slightly more conservative (uses worst-axis).
  Error fallback dict intentionally returns conservative defaults. Not a correctness bug.

### NEW-LOGIC-5: COMPOSITE_MODE=True prompt text in _build_message_content is COMPOSITE-specific
- vision_assessor.py lines 258-268: Text says "Images are in order: front corners grid, back corners grid,
  front edges composite, back edges composite, full front surface, full back surface."
- This matches COMPOSITE_MODE=True (6 images). But if COMPOSITE_MODE=False (18 images), the prompt text
  is WRONG — it still says "corners grid" and "edges composite" when individual crops are sent
- vision_assessor.py line 52: `COMPOSITE_MODE = True` — currently hardcoded True, so this is a latent bug
  only triggered if someone sets COMPOSITE_MODE=False
- IMPACT: Low while COMPOSITE_MODE=True. Flagged as latent risk if mode is toggled.

## Logic Errors (prior audit — re-verified March 22)

### LOGIC-1: detect_inner_artwork_box margin filter only excludes top-left corner
- FIXED — see NEW-LOGIC-1 above. VERIFIED CORRECT.

### LOGIC-2: calculate_centering_score uses dampened bands that don't align with cap table
- STILL PRESENT. centering.py lines 488-505 (dampened curve) vs interpolate_centering_score (table).
- These are intentionally different functions for different purposes. Not a bug.

### LOGIC-3: detect_border_widths (saturation fallback) off-by-one in pixel width
- STILL PRESENT: centering.py lines 411-416 record `left_width = x` when border ends at x-1
- 1px systematic overcount on all 4 sides, cancels in ratio, minimal practical impact

### LOGIC-5: Front-only grading path uses front image as BOTH sides for Vision AI
- combined_grading.py line 435: `vision_result = assess_card(front_img, back_img)`
  where both paths must be provided
- No grade_card_session dead-code path available in live routers
- The live router always requires back upload before combining
- Front-only grading is not possible via the live API (grading.py result endpoint returns
  status "front_uploaded" not "complete" if back is missing)
- Status: Not exploitable via live API. ACCEPTABLE.

## Confounding Variables (re-verified March 22)

### CONFOUND-1: get_card_corners partial zero-fill
- RE-ASSESSED: image_preprocessing.py uses sum/diff approach (lines 227-232) — no zero-fill.
  All 4 positions always assigned. VERIFIED CORRECT. Prior finding was incorrect.

### CONFOUND-2: Double perspective-warp path
- VERIFIED CORRECT: already_corrected flag prevents double warp.

### CONFOUND-3: _detection_stats dict has no asyncio lock
- hybrid_detect.py lines 46, 383-391: `_stats_lock = threading.Lock()` IS used in `_record_stat()`
- threading.Lock around a sync counter dict is appropriate — the dict mutation is synchronous.
- VERDICT: Lock exists and is used. VERIFIED CORRECT.

### CONFOUND-4: CLAHE instances are created per-call (confirmed fixed)
- VERIFIED CORRECT.

### NEW-CONFOUND-1: update_session is called without async lock
- session_manager.py line 93: `update_session` is a SYNCHRONOUS method that modifies shared state
- No lock is acquired: concurrent requests for the same session (e.g., double-tap upload-back)
  can race to update `session.status` and `session.front_analysis` without synchronization
- IMPACT: Two concurrent upload-back requests on same session would each call
  `combine_front_back_analysis(session.front_analysis, back_analysis)` independently, potentially
  with different back images. Both would overwrite `session.combined_grade` in sequence.
  Last write wins; no crash, but redundant Vision AI API calls and incorrect combined grade possible.
- MITIGATION: SessionManager._lock exists for create/delete/cleanup. update_session and get_session
  are intentionally lockless (per comment: "only reads in-memory dict, no I/O").
  The race window is narrow and requires concurrent uploads from same session, which is unlikely
  in a real mobile app workflow.
- SEVERITY: Low for typical use. Medium if API exposed to automation.

### NEW-CONFOUND-2: image_path stored in front_analysis points to corrected image, not original
- grading.py lines 76-86: `analysis_image_path` is set to `str(corrected_path)` when detection succeeds
- `front_analysis["image_path"]` = `str(corrected_path)` = `"...front_corrected.jpg"`
- combined_grading.py line 409: `front_path = front_analysis.get("image_path")` loads corrected image
- THEN: `front_img = cv2.imread(front_path)` — reads the already-warped 500x700 image
- Vision AI then receives the CORRECTED card image (500x700), not the raw photo. This is CORRECT
  and intentional — the corrected image is the grading input. VERIFIED CORRECT BY DESIGN.

### NEW-CONFOUND-3: centering.py vision_ai path uses image.shape of the file at image_path
- centering.py lines 561-565: when vision_border_fractions provided, converts fractions to pixels
  using `image.shape` from `cv2.imread(image_path)`
- image_path IS the corrected 500x700 image (analysis_image_path from grading.py)
- `frac_l * img_width_v` where img_width_v=500 → left = frac_l * 500 pixels on a 500px-wide card
- Centering ratio = left / right in pixels → ratio is scale-invariant. CORRECT.

## Verified Correct Invariants (March 22 re-audit — full list)

- Centering cap gated on confidence >= 0.6: CORRECT (grade_assembler.py line 242)
- Centering excluded from floor/ceiling: CORRECT (_apply_floor_ceiling takes only corners/edges/surface)
- Session TTL 30 min reset on every update_session: CORRECT (session_manager.py update_session calls touch())
- 15MB upload limit: CORRECT (grading.py MAX_UPLOAD_BYTES = 15*1024*1024)
- PSA centering cap applied before half-point: CORRECT (step 4 before step 5 in assemble_grade)
- Damage cap applied before centering cap: CORRECT (step 3.5 before step 4)
- Vision AI dual-pass / median-of-3: CORRECT (vision_assessor.py lines 641-649)
- BACK_CAP_TABLE is more lenient than FRONT_CAP_TABLE: CORRECT
- Hallucination guard only fires on placeholder values {1.0, 5.0, 10.0}: CORRECT
- cross_axis_unreliable cap to 0.5: CORRECT (centering.py line 769)
- symmetry_corrected cap to 0.6: CORRECT (centering.py line 771)
- CLAHE per-call (not shared): CORRECT
- _apply_damage_cap "most severe wins" logic: CORRECT
- Composite weights (corners 37.5% + edges 37.5% + surface 25% = 100%): CORRECT
- Blending: corners 60/40, edges 65/35, surface 70/30 (fixed front-weighted): CORRECT
- Floor/ceiling: worst = min(corners, edges, surface), bounds-guarded: CORRECT
- detect_border_widths_hsv axis handling: CORRECT
- CORS origins correct: CORRECT
- Session cleanup loop every 2 minutes: CORRECT (main.py line 158)
- can_analyze quality gate: CORRECT (grading.py lines 61-70)
- Vision AI corner count validated before array op: CORRECT (vision_detector.py lines 228-235)
- artwork_box margin filter now uses OR across all 4 edges: CORRECT (centering.py lines 141-145)
- get_card_corners uses sum/diff approach (no zero-fill): CORRECT (image_preprocessing.py lines 227-232)
- asyncio.Lock used in session_manager (not threading.Lock): CORRECT
- SessionManager._lock (asyncio.Lock) used for create/delete/cleanup: CORRECT
- update_session synchronous by design (no lock needed for mobile single-user workflow): ACCEPTABLE
- Privacy policy now says "30 minutes" — matches session_manager TTL: CORRECT (main.py line 103)

## Warnings (current state)

### WARN-1: quality_checks.py min_resolution is 400px (very lenient)
- STILL PRESENT. quality_checks.py line 107: `min_resolution = 400`.
- Flutter image_validator.dart enforces 800px on the client side. Backend does not re-enforce this.

### WARN-2: COMPOSITE_MODE=False prompt description is wrong
- vision_assessor.py lines 258-268: "corners grid" / "edges composite" text is COMPOSITE_MODE-specific.
- If COMPOSITE_MODE=False is ever enabled, Vision AI receives wrong layout description.
- COMPOSITE_MODE=True is currently hardcoded at line 52. Latent risk only.

### WARN-3: _record_stat never updates total_time_ms
- hybrid_detect.py: `_detection_stats["total_time_ms"]` stays at 0. Admin endpoint shows 0ms avg.
- Monitoring only. Grades unaffected.

### WARN-4: grade_card_session function in combined_grading.py is dead code
- combined_grading.py: function defined but never called from any live router.
- Live routers call analyze_single_side + combine_front_back_analysis directly.

### WARN-5: _ai_semaphore created at module import time
- hybrid_detect.py line 36: `_ai_semaphore = asyncio.Semaphore(DetectionConfig.MAX_CONCURRENT_AI)`
- Must be in same event loop. Python 3.10+ is more lenient. Low risk in practice.

### WARN-6: Full-art cards may fail Vision AI border_fractions sanity check
- centering.py lines 557-560: `all(0.01 <= f <= 0.30 for f in (frac_l, frac_r, frac_t, frac_b))`
- Genuine borderless/full-art cards have near-zero fractions → may fall through to OpenCV
- OpenCV methods likely also struggle with borderless cards; degraded centering detection

## Algorithm Documentation (March 22 — confirmed from code)

### Composite weights (live)
corners 37.5% + edges 37.5% + surface 25% = 100%. Centering excluded.

### Blending weights (live, fixed front-weighted)
corners 60/40, edges 65/35, surface 70/30. NOT adaptive worse/better.
Corner blending: each side = 50% avg + 50% worst (single bad corner penalized).

### PSA centering cap tables
FRONT: 55/45→10, 60/40→9, 65/35→8, 70/30→7, 75/25→6, 80/20→5, 85/15→4, 90/10→3, worse→2.
BACK: 75/25→10, 90/10→9, ~92/8→8, ~95/5→7, ~97.5/2.5→6, worse→5.
Effective cap = min(front_cap, back_cap). Front is almost always binding.

### Floor/ceiling (live)
worst_dim = min(corners_blended, edges_blended, surface_blended)
floor: composite cannot go more than 0.5 below worst_dim.
ceiling: composite cannot exceed worst_dim by more than 1.0.
Both floor and ceiling clamped to [1.0, 10.0].
Centering NOT included in worst_dim computation.

### Damage cap (live)
heavy crease → cap 3.0; moderate crease OR extensive whitening → cap 5.0
Gate: surface_confidence >= 0.60 per side; "most severe wins" across front/back.

### Half-point display rule
Requires fractional(composite) >= 0.3 AND min(AVERAGE-axis front, AVERAGE-axis back) >= floor(composite) + 1.
centering_avg_score = calculate_centering_score() using average lr/tb ratio (dampened curve).
Fallback to worst-axis if centering detection fails.

### Centering confidence ceilings by method (live)
vision_ai: 0.90
artwork_box: 0.90
hsv_border: 0.75 (triggers cap; cross_axis can reduce to 0.50)
gradient_detection: 0.50 (below 0.60 gate — never triggers cap)
fallback/saturation: 0.40 (below gate)
symmetry_corrected: caps to 0.60 (just at threshold)
cross_axis_unreliable: caps to 0.50 (below gate)

### Session lifecycle
create (POST /api/grading/start) → upload-front → upload-back → result
Front-only grading not supported via live API (result returns status: front_uploaded).

## Fragile Areas to Monitor

1. COMPOSITE_MODE=False path: prompt text wrong, would confuse Vision AI layout
2. Full-art/borderless cards: vision_border_fractions sanity check may reject valid near-zero fractions
3. update_session race (very low risk for typical mobile workflow)
4. quality_checks min_resolution 400px vs client-side 800px gate
5. _record_stat total_time_ms never updated (monitoring only)
6. grade_card_session dead code: if ever activated, back centering loses border_fractions
