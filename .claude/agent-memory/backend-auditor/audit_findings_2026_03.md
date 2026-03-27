---
name: March 2026 Comprehensive Backend Audit Findings
description: Critical bugs, verified invariants, architecture notes from the March 2026 full audit (updated March 24 Round-5 — production readiness sweep)
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
- FIXED (March 24 Round-5): hybrid_detect.py line 386 now has `_detection_stats["total_time_ms"] += duration_ms`
- All three call sites pass total_ms correctly (lines 94, 121, 140).
- VERIFIED FIXED.

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

## Verified Correct Invariants (March 24 Round-5 — full list)

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
- _record_stat total_time_ms now accumulates: CORRECT (hybrid_detect.py:386)
- Front re-upload clears stale back_analysis/combined_grade: CORRECT (grading.py:130-136)
- Vision AI failure returns status="error": CORRECT (grading.py:271-290)
- combine_front_back_analysis wrapped in asyncio.to_thread: CORRECT (grading.py:266-268)
- grade_range works for half-point grades: CORRECT (combined_grading.py:261-267)
- detect_card_side blue threshold 55% + red>2% check: CORRECT (combined_grading.py:48)
- assess_card raises VisionAssessorError if SYSTEM_PROMPT empty: CORRECT (vision_assessor.py:691-695)
- _normalize_label defaults unknown labels to most severe: CORRECT (vision_assessor.py:447-451)
- Damage synonyms split into _CREASE_SYNONYMS/_WHITENING_SYNONYMS: CORRECT
- confidence["level"] key in grade_assembler output: CORRECT (grade_assembler.py:483)
- startup_check.py called from main.py @on_event("startup"): CORRECT (main.py:146-157)
- Flutter review_screen.dart checks backResult['status']=='error': CORRECT (review_screen.dart:94-96)
- _order_points works for N>4 polygon points (argmin/argmax are correct): VERIFIED CORRECT
- OpenCV success path returns no border_fractions: CORRECT — centering falls through to OpenCV methods, which is the right behavior (acceptable design gap, not a bug)
- _apply_damage_cap WHITENING_ORDER and CREASE_ORDER are local dicts (not module-level vision_assessor lists): CORRECT — grade_assembler.py defines its own dicts at line 200-201, consistent with vision_assessor.py field values

## Warnings (current state)

### WARN-1: quality_checks.py min_resolution is 400px (very lenient)
- STILL PRESENT. quality_checks.py line 107: `min_resolution = 400`.
- Flutter image_validator.dart enforces 800px on the client side. Backend does not re-enforce this.

### WARN-2: COMPOSITE_MODE=False prompt description is wrong
- vision_assessor.py lines 258-268: "corners grid" / "edges composite" text is COMPOSITE_MODE-specific.
- If COMPOSITE_MODE=False is ever enabled, Vision AI receives wrong layout description.
- COMPOSITE_MODE=True is currently hardcoded at line 52. Latent risk only.

### WARN-3: _record_stat total_time_ms
- FIXED March 24 Round-5. RESOLVED.

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

### WARN-7 (NEW): _validate_response does not check .0/.5 increment constraint
- vision_assessor.py _validate_response lines 283-327: only validates score in [1.0, 10.0]
- grading_prompt.txt line 119: instructs "Use only .0 or .5 increments"
- If model returns e.g. 8.3, it passes validation and is used directly
- Impact: averaging two passes of [8.0, 8.3] → 8.15 (not a valid PSA increment)
  displayed_grade uses math.floor → 8.0, so half-point gate handles it correctly
- The dampened values propagate into the composite but the final grade is floored to integer
  before half-point display — no user-facing score corruption from non-.5 values
- RISK: Low. The non-standard increment affects intermediate math but not final displayed grade

### WARN-8 (NEW): No rate limiting on any endpoint
- backend/main.py, backend/api/routers/*: No rate limiting middleware
- POST /api/grading/start could be called in a tight loop to exhaust memory
- RISK: Medium in production (denial-of-service via session flooding)
- Sessions are bounded by 30-min TTL and cleanup loop, but 2-min cleanup interval means
  up to 2 minutes of unchecked flood is possible

### WARN-9 (NEW): server.log file accumulates on disk without rotation
- main.py line 19: `logging.FileHandler('server.log')` — no rotation configured
- In production (Railway), this file will grow unboundedly and eventually cause disk pressure
- RISK: Low short-term (Railway ephemeral container resets on redeploy), medium long-term

## Algorithm Documentation (March 24 Round-5 — confirmed from code)

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
5. grade_card_session dead code: if ever activated, back centering loses border_fractions
6. Vision AI non-.5-increment scores pass validation — benign in final grade display but affects intermediate composites
7. No rate limiting — session flood possible
8. server.log file grows without rotation

---

## March 24 2026 Round-3 Final Audit

### Round-2 Fixes — Verification Status

#### LOGIC-NEW-1 VERIFIED: _CREASE_SYNONYMS / _WHITENING_SYNONYMS split is correctly implemented
- vision_assessor.py lines 411-427: Two separate dicts, distinct entries per context.
- _normalize_label (line 433) dispatches via `order is _CREASE_ORDER` / `order is _WHITENING_ORDER`
  identity check — works correctly because the module-level list objects are unique singletons.
- All callers pass `_CREASE_ORDER` or `_WHITENING_ORDER` directly, never a copy.
- Identity check is safe. VERIFIED CORRECT.
- DEAD CODE NOTE: `_SYNONYM_TABLES = {}` (line 430) is declared but never populated or used.
  Comment says "Map order list identity to the right synonym table" — the actual dispatch uses `is`
  identity check instead of this dict. Should be removed to avoid confusion. LOW risk (code smell only).

#### CONFOUND-NEW-1 VERIFIED: main.py @app.on_event("startup") run_startup_checks() is present
- main.py lines 146-157: @app.on_event("startup") run_startup_checks() calls check_api_key(),
  check_grading_prompt(), and logs calibration warning. All three execute at server start.
- Prior gap (standalone startup_check.py not called by Procfile) is NOW FIXED.
- VERIFIED CORRECT.

#### CONFOUND-NEW-2 VERIFIED: Flutter review_screen.dart checks backResult['status'] == 'error'
- lib/screens/review_screen.dart lines 90-96: uploadBackImage return captured into backResult,
  status == 'error' check fires before getGradingResult call.
- Backend returns {"status": "error", "error": <str>, ...} on HTTP 200 for Vision AI failure.
  Flutter reads backResult['error'] ?? backResult['message']. Key 'error' is present. Match confirmed.
- VERIFIED CORRECT.

### New Bug Found in Round-3 Audit

#### NEW-BUG-4 (LOGIC ERROR — UI DISPLAY): confidence chip always shows "Unknown"
- lib/screens/result_screen.dart line 29: reads `confidenceData['level']` → always null.
- Backend grade_assembler.py line 481-484 returns `confidence: {"overall": <float>, "low_confidence_flags": [...]}`.
  There is no "level" key. The "level" key was present in the old scoring.py GradingEngine output (dead code).
- result_screen.dart line 29: `confidenceLevel = confidenceData['level']?.toString() ?? "Unknown"` → always "Unknown".
- _buildConfidenceChip (line 423-440): only colors "Medium" and "Low" specially; "Unknown" falls
  through to green (default). User always sees "Confidence: Unknown" in green — misleading.
- IMPACT: Purely UI display issue. Grades are unaffected. Users see stale "level" key that no longer exists.
- FIX: Either (a) add a `"level"` field to the confidence dict in grade_assembler.py based on `overall_conf`
  thresholds, or (b) change result_screen.dart to read `confidenceData['overall']` and format it as a percentage.

### Remaining Pre-Existing Issues (Unchanged)
- Flutter Dio receiveTimeout 60s < Vision AI worst-case 90s (api_client.dart:30) — pre-existing WARN
- grade_card_session dead code in combined_grading.py — never called
- update_session synchronous race (very low risk for mobile workflow)
- COMPOSITE_MODE=False prompt text latent bug (vision_assessor.py)
- quality_checks min_resolution 400px vs client 800px

---

## March 24 2026 Re-Audit (10 Fixes Applied)

### Fixes Verified CORRECT

#### CRITICAL-1 VERIFIED: grading.py now checks combined_grade.get("grade", {}).get("error")
- backend/api/routers/grading.py lines 271-290: error dict check fires before setting status='complete'.
- All three error paths in combine_front_back_analysis (missing path, imread fail, VisionAssessorError) produce combined['grade']['error']. All are caught. VERIFIED CORRECT.
- Note: Flutter client (review_screen.dart) DISCARDS the upload-back 200 response — it proceeds to GET /result regardless. GET /result returns status='error' → result_screen gets empty grading dict → null finalScore → _buildErrorScreen. User sees generic error, not the specific Vision AI message. Backend is correct; Flutter UX gap.

#### CRITICAL-2 VERIFIED: asyncio.to_thread wrapping combine_front_back_analysis
- backend/api/routers/grading.py lines 266-268: `await asyncio.to_thread(combine_front_back_analysis, ...)`
- combine_front_back_analysis is fully synchronous; httpx.Client calls inside assess_card() are safe in thread. VERIFIED CORRECT.
- Note: up to 90 seconds possible (3 Vision AI passes × 30s timeout each) in the thread. This was always the case — the fix prevents event loop blocking but doesn't reduce latency.

#### LOGIC-1 VERIFIED: _GRADE_BRACKETS now includes half-point entries
- backend/api/combined_grading.py lines 261-267: all half-point grades (8.5, 7.5, 6.5, etc.) present.
- grade_range logic for PSA '8.5': finds index 2, upper=(9.0, '9'), composite >= 8.7 → '8.5-9'. CORRECT.
- Grade range for PSA '10' still stays '10' (i=0 → no upper bracket). CORRECT.
- Grade range for PSA '1' can show '1-1.5' when composite >= 1.2. CORRECT.

#### LOGIC-2 VERIFIED: combined["centering"] shows worse cap side
- backend/api/combined_grading.py lines 507-514: if back_cap < front_cap → back_centering, else front_centering.
- Both sides exposed as front_centering/back_centering for detail screen. CORRECT.
- Minor display note: UI may show a centering_cap that's not actually applied when confidence < 0.6. This is informational, not a grade error.

#### LOGIC-3 VERIFIED: Dead import _centering_cap_and_score removed from combined_grading.py
- No occurrence of _centering_cap_and_score in combined_grading.py. VERIFIED CLEAN.

#### LOGIC-4 VERIFIED: detect_card_side threshold raised 40%→55%, red_pct > 2% added
- backend/api/combined_grading.py lines 38-52: new thresholds in place.
- detect_card_side used ONLY for swap warning (combined_grading.py line 96, 453). No grade impact.
- Double-front upload: swap warning won't fire (neither card detects as 'back'). Low risk.

#### CONFOUND-1 VERIFIED: assess_card() raises VisionAssessorError if SYSTEM_PROMPT empty
- backend/grading/vision_assessor.py lines 677-681: guard in place. VERIFIED CORRECT.

#### CONFOUND-2 VERIFIED: _most_severe/_most_severe_of_three use _normalize_label
- backend/grading/vision_assessor.py lines 440-455: normalization applied before index lookup.
- None inputs handled correctly (return None, not crash). VERIFIED CORRECT.
- Known issue: 'small' synonym maps to 'minor' which is NOT in CREASE_ORDER → falls through to 'heavy'. Extremely low risk (prompt constrains to canonical labels; 'small' would only appear via hallucination).

#### ETHICAL-1 VERIFIED: is_estimate, disclaimer, estimated_grade fields in grade response
- backend/api/combined_grading.py lines 237-244: all three fields present in grade_out.
- psa_estimate kept as backward-compat alias. VERIFIED CORRECT.
- Flutter client does not read these fields directly — it has its own DisclaimerScreen. Backend role fulfilled.

#### ETHICAL-2/WARN-6 VERIFIED: startup_check.py has API key + prompt checks + calibration disclaimer
- backend/startup_check.py lines 60-83, 111-116: checks and disclaimer in place.
- GAP: startup_check.py is NOT called from main.py or the Procfile. It is a standalone CLI tool only. The disclaimer and checks are only visible when startup_check.py is run manually. Runtime protection (API key, SYSTEM_PROMPT) is correctly placed in assess_card(). The startup_check.py disclaimer is developer-facing only.

### New Bugs Found in March 24 Re-Audit

#### NEW-BUG-1 (WARNING): startup_check.py not invoked by server startup
- backend/startup_check.py is standalone (`if __name__ == "__main__"` guard).
- Procfile: `uvicorn main:app ...` — never calls startup_check.py.
- The calibration disclaimer log line (lines 111-116) is never printed during normal server operation.
- The API key and prompt checks run at grading time inside assess_card() (correct), not at startup.
- Impact: operators deploying without manually running startup_check.py won't see the disclaimer in production logs.
- Fix: add `from startup_check import check_api_key, check_grading_prompt` call in main.py startup event, or add a logger.warning in the FastAPI startup event.

#### NEW-BUG-2 (WARNING): Flutter client discards upload-back 200 response
- lib/screens/review_screen.dart lines 90-93: uploadBackImage return value is not assigned/checked.
- api_client.dart line 104: returns response.data on HTTP 200.
- When Vision AI fails: backend returns HTTP 200 with status='error' — Flutter proceeds to GET /result.
- GET /result returns status='error' dict → empty grading → null finalScore → generic error screen.
- User sees "Could not read grading result" rather than the actual Vision AI failure message.
- Fix: review_screen should check result['status'] == 'error' after uploadBackImage and show result['error'] directly. Or backend could return HTTP 422 on Vision AI failure to trigger the client error path.

#### NEW-BUG-3 (OBSERVATION): _DAMAGE_SYNONYMS shared dict has whitening-context entries applied to crease context
- backend/grading/vision_assessor.py lines 411-420: 'small'→'minor' and 'large'→'extensive' are whitening-context synonyms.
- If applied to CREASE_ORDER: 'small' maps to 'minor', not in CREASE_ORDER → defaults to 'heavy' cap (3.0).
- 'large' maps to 'extensive', not in CREASE_ORDER → defaults to 'heavy' cap (3.0).
- Both cases are overly aggressive (a 'small' crease should cap at 5.0 at most, not 3.0).
- Real-world risk: LOW (prompt constrains to canonical labels). But the intent behind _normalize_label's "unknown → most severe" policy would silently over-penalize if hallucination occurs.
- Fix: Split into two synonym dicts (_CREASE_SYNONYMS, _WHITENING_SYNONYMS) or guard 'small'/'large' to whitening context only.

---

## March 24 2026 Round-4 Final Verification Audit

### Round-3 Fixes — Verification Status

#### R3-FIX-1 VERIFIED: confidence["level"] key added to grade_assembler.py
- backend/grading/grade_assembler.py line 483: `"level": "High" if overall_conf >= 0.75 else "Medium" if overall_conf >= 0.55 else "Low"`
- Flutter result_screen.dart line 29: reads `confidenceData['level']?.toString() ?? "Unknown"` — key is now present, fallback never reached.
- _buildConfidenceChip: "High" falls through to default (green), "Medium"/"Low" colored specially. Correct.
- VERIFIED CORRECT. NEW-BUG-4 (UI confidence chip always "Unknown") is RESOLVED.

#### R3-FIX-2 VERIFIED: _SYNONYM_TABLES dead variable removed from vision_assessor.py
- Grep for `_SYNONYM_TABLES` in backend/grading/vision_assessor.py returns no matches. Completely removed.
- Dispatch logic using `if order is _CREASE_ORDER` / `elif order is _WHITENING_ORDER` identity check intact at lines 437-441.
- VERIFIED CORRECT.

### No New Bugs Introduced by Round-3 Changes
- The `"level"` addition is a read-only inline computation; cannot affect scoring, caps, or confidence gates.
- The `_SYNONYM_TABLES` removal has zero callers; no regressions.

---

## March 24 2026 Round-5 Production Readiness Sweep

### New Verified Fixes
- _record_stat total_time_ms accumulation: FIXED (hybrid_detect.py:386)
- All three call sites pass duration_ms: CONFIRMED (lines 94, 121, 140)

### New Warnings Found (Round-5)

#### WARN-7: _validate_response does not enforce .0/.5 increment constraint
- vision_assessor.py _validate_response: only checks range [1.0, 10.0], not half-point increment
- Non-.5 values pass validation and affect intermediate composites
- Final displayed grade is integer-floored before half-point display → no user-visible grade error
- RISK: Low

#### WARN-8: No rate limiting on any API endpoint
- Any caller can flood POST /api/grading/start to create unbounded sessions
- 2-minute cleanup loop is the only protection
- RISK: Medium for production

#### WARN-9: server.log has no rotation
- main.py FileHandler writes to server.log without RotatingFileHandler
- In long-running production deployment, file grows unboundedly
- RISK: Low on Railway (ephemeral), medium on persistent deployments

### Final Production Readiness Status
SYSTEM IS READY FOR PUBLICATION with the following accepted risks:
- 3 new low-severity warnings (WARN-7/8/9) documented above
- All grade-correctness invariants verified correct
- All previously flagged critical bugs resolved
- Remaining warnings are monitoring/ops concerns, not accuracy concerns

Total bugs fixed across all 5 audit rounds: 16
Remaining accepted issues: 7 (all warnings, none affect grade correctness)

---

## March 26 2026 Round-6 Audit

### Focus: grade_assembler.py, vision_assessor.py, grading_prompt.txt (recent git changes)

### No New Critical Bugs Found

All previously documented critical bugs remain fixed. The grading algorithm, session management, blending logic, centering caps, damage caps, and half-point gate are all correctly implemented.

### LOGIC-6 (NEW): _apply_damage_cap docstring and inline comment say cap=3.0 but code is 2.0

- grade_assembler.py line 191: docstring says `heavy crease → cap at 3.0`
- grade_assembler.py line 391: inline comment says `a heavy crease (cap=3)`
- grade_assembler.py line 215: actual code is `cap = 2.0`
- MEMORY.md confirms intentional calibration: "heavy crease now 2.0 (was 3.0) — calibrated against TAG report"
- IMPACT: Documentation-only error. Code is correct. Docstring must be updated.
- STATUS: NOT YET FIXED

### WARN-NEW-1 (NEW): Hallucination guard only catches three placeholder values

- vision_assessor.py line 326: `if len(set(corner_scores)) == 1 and corner_scores[0] in (1.0, 5.0, 10.0):`
- All-identical non-placeholder values (e.g. all 9.0) pass the guard silently
- Recommended fix: remove the `in (1.0, 5.0, 10.0)` condition — any 8-identical-corner response is suspicious
- RISK: Low (rare hallucination pattern)

### WARN-NEW-2 (NEW): _apply_damage_cap does not guard against surface_raw[side] being non-dict

- grade_assembler.py line 206: `data = surface_raw.get(side, {})` then `data.get("crease_depth")`
- If surface_raw[side] is somehow None/non-dict (malformed Vision AI response passing _validate_response), AttributeError
- _validate_response validates score key existence but not that the entire surface dict is well-typed
- RISK: Very low — prompt constrains output format

### Verified Correct (Round-6 additions)

- Composite weights 37.5/37.5/25: CORRECT
- Blending 60/40, 65/35, 70/30 (front-weighted): CORRECT
- Floor/ceiling bounds-guarded, centering excluded: CORRECT
- Damage cap at 2.0 (heavy crease): CORRECT (code), docstring stale
- Damage cap at 5.0 (moderate crease, extensive whitening): CORRECT
- Centering cap gated on confidence >= 0.6: CORRECT
- Pipeline order: CORRECT
- Half-point gate uses avg-axis centering: CORRECT
- grade_range logic for all PSA labels including half-points: CORRECT
- _normalize_label None passthrough: CORRECT
- Dual-pass / median-of-3 "most severe wins": CORRECT
- startup_check.py now invoked via main.py @app.on_event("startup"): CORRECT
- confidence["level"] key present in grade_assembler output: CORRECT
- _SYNONYM_TABLES dead variable removed: CONFIRMED ABSENT
- COMPOSITE_MODE=True layout description correct: CORRECT for current hardcoded mode

### Updated Status

Total bugs fixed: 16 (no new fixes this round)
Remaining documentation error: 1 (LOGIC-6 — docstring says cap=3.0, code is 2.0)
Remaining warnings: 9 total (WARN-2 through WARN-NEW-2)
Production readiness: MAINTAINED — no grade-correctness issues found

---

## March 27 2026 Round-7 Audit — Damage Detection & Capping Focus

### Scope
Focused audit of the full damage detection pipeline:
vision_assessor.py → grade_assembler._apply_damage_cap → combined_grading._vision_to_assembly_input

### New Finding: Hallucination Guard Improved (WARN-NEW-1 resolved)
- vision_assessor.py line 326: The `in (1.0, 5.0, 10.0)` placeholder restriction flagged in Round-6 is NOW GONE.
- Current code: `if len(set(corner_scores)) == 1:` — fires on ANY all-identical response, not just placeholders.
- WARN-NEW-1 is RESOLVED. This was the right fix.

### New Finding: LOGIC-6 docstring staleness (STILL NOT FIXED)
- grade_assembler.py lines 190-192 docstring still says "heavy crease → cap at 3.0"
- Actual code: line 217 `cap = 2.0` ← correct per TAG calibration
- Comment at assemble_grade line 394: "a heavy crease (cap=3)" ← also stale
- STILL NOT FIXED. Both docstring and inline comment need updating to say 2.0.

### New Finding: WARN-NEW-2 partial guard added
- grade_assembler.py line 207: `if not isinstance(data, dict): continue` — guard is now in place
- WARN-NEW-2 is RESOLVED. The isinstance guard correctly skips non-dict sides.

### Real-World Trace: Heavy Crease Card
Scenario: card with a visible heavy crease, bright lighting, sharp photo.

**Step 1 — Vision AI (vision_assessor.py)**
- Surface crops sent as front_surface / back_surface full images.
- Prompt grading_prompt.txt instructs: "A wrinkle or fold that distorts the card surface must be classified as 'heavy'".
- Prompt also: "A surface score of 5.0 or above requires crease_depth 'hairline' or 'none'."
- For a heavy crease, Vision AI is expected to return: crease_depth="heavy", surface score ≤ 4.0.
- Confidence would typically be high (0.8–1.0) for visually obvious damage.

**Step 2 — Dual-pass / median-of-3 (vision_assessor.py _average_passes)**
- "Most severe wins" merge: if pass1 says "heavy" and pass2 says "moderate", result is "heavy".
- This is correct — cannot vote away real damage.

**Step 3 — surface_raw propagation (combined_grading.py line 217)**
- `surface_raw=vision["surface"]` — the raw surface dict (including crease_depth, confidence) is passed to AssemblyInput.
- surface_confidences is keyed by "front"/"back" from vision["surface"]["front"]["confidence"] etc.

**Step 4 — _apply_damage_cap (grade_assembler.py)**
- Gate: surface_confidences.get("front", 0.0) >= 0.60 — with visible obvious damage, Vision AI confidence will be high.
- CREASE_ORDER["heavy"] = 3 → >= 3 triggers heavy cap.
- cap = 2.0; reason = "heavy crease on front surface".
- Composite is overridden to 2.0 (if it was higher). This is correct.

**Failure Mode #1: Vision AI says "moderate" not "heavy"**
- If Vision AI downgrades a heavy crease to "moderate": cap is 5.0 not 2.0.
- The composite score from Vision AI will likely already be ≤ 4.0 for such a card (surface score 3-4),
  floor/ceiling would keep it in the 3-5 range anyway.
- Practical impact: a card that deserves cap=2.0 gets cap=5.0. If composite is already ≤ 5.0 from Vision AI scoring,
  the cap never fires and the grade is correct by coincidence (Vision AI score carries it).
  If composite is pushed up by good corners/edges, cap=5.0 vs cap=2.0 matters — up to 3 PSA points difference.
- RISK: Moderate. Vision AI prompt has strong guidance ("wrinkle or fold = heavy") but inconsistency between
  the SURFACE SCORING CRITERIA (surface score 3-4 implies heavy crease) and crease_depth label is possible.

**Failure Mode #2: surface_confidence < 0.60 gates the cap off**
- If Vision AI returns confidence=0.5 for the surface (blur, bad lighting), cap is skipped.
- Composite score from Vision AI would also have low confidence, but the score itself still feeds the composite.
- A heavily creased card could score 5-6 if corners/edges are perfect, and the cap won't fire.
- RISK: Low-Medium. Quality checks gate on can_analyze; very poor images are rejected at upload.
  Marginally-acceptable images (can_analyze=True, confidence < 0.60) could slip through.
  The quality check only guards the extreme end.

**Failure Mode #3: crease_depth field omitted / null**
- Prompt line 128: "crease_depth and whitening_coverage are optional fields. Omit them entirely or set to null if you cannot assess them reliably."
- If Vision AI returns `crease_depth: null` or omits the field: data.get("crease_depth") → None.
- `if crease and ...` → None is falsy → cap skipped.
- This is intentional design (can't penalize what can't be seen). But if Vision AI omits it because of
  poor image quality or uncertainty (not because there's no crease), a real crease escapes the cap.
- The surface score would still be lowered by Vision AI's general assessment — but the hard cap won't enforce 2.0.
- RISK: Low-Medium. The same uncertainty that causes null crease_depth will also lower the Vision AI surface score.
  The only gap is when Vision AI surface score is inconsistent with its own crease label.

**Failure Mode #4: Inconsistency between surface score and crease_depth label**
- Prompt says: "A surface score of 5.0 or above requires crease_depth 'hairline' or 'none'."
- If Vision AI returns surface_score=5.5, crease_depth="heavy" — this contradicts the prompt.
- _validate_response does NOT check this constraint (only validates score range and identical-corners guard).
- Result: cap=2.0 fires (correctly), overriding the inconsistent surface score.
- VERDICT: The damage cap acts as a safety net even against Vision AI self-contradictions. CORRECT.

**Failure Mode #5: moderate crease whitening_coverage="extensive" conflict**
- A card can have moderate crease AND extensive whitening simultaneously.
- grade_assembler.py loops through both: if crease="moderate" → cap=5.0; if whitening="extensive" → cap=5.0.
- Both set cap to 5.0; no conflict. The heavier crease check uses `if cap is None or cap > 2.0` semantics,
  so if heavy crease fires first → cap=2.0; subsequent whitening check `cap > 5.0` is False → stays at 2.0.
- VERDICT: Most-severe-wins logic is correct for all combinations. VERIFIED.

### Summary Assessment (Round-7)
The damage detection pipeline is SOUND for typical cases. Key strengths:
1. "Most severe wins" dual-pass merge prevents voting away real damage.
2. isinstance guard protects against malformed surface_raw.
3. Damage cap fires before centering cap — correct ordering.
4. Heavy crease cap at 2.0 is calibrated and correctly implemented.

Two legitimate under-penalization scenarios exist (not code bugs, but system limitations):
A. Vision AI downgrading "heavy" → "moderate" crease: cap fires at 5.0 instead of 2.0.
   Mitigated by: (a) strong prompt guidance, (b) Vision AI surface score itself being low.
B. surface_confidence < 0.60 gates off a legitimate damage cap.
   Mitigated by: upstream quality check rejecting very poor images.

No new code bugs found in Round-7.

### Documents Updated
- LOGIC-6 (cap=2.0 docstring staleness): STILL OPEN, no fix applied.
- WARN-NEW-1 (hallucination guard): RESOLVED in code — `in (...)` restriction removed.
- WARN-NEW-2 (isinstance guard): RESOLVED in code — guard added at line 207.
