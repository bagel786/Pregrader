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
corners.py analyze_corners IS CALLED in grading.py but its result is NEVER used by grade_assembler.py (dead CPU cost). Only the overall_grade is stored as opencv_corner_grade for Vision AI cross-check.

## Critical Bugs Found (March 2026 — current session)

### CRITICAL-1: detect_border_widths_hsv transposes scan arrays for LR but not TB — wrong axis shape
- centering.py lines 290-305:
  - Left scan: `_border_width_axis(left_strip_hue, left_strip_sat, hue.T, sat.T, val.T, w, ...)`
  - Right scan: same transposed arrays, dim=w
  - Top scan: `_border_width_axis(top_strip_hue, top_strip_sat, hue, sat, val, h, ...)`
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

### CRITICAL-3: Vision AI corner order in ai_corners not validated before perspective warp
- vision_detector.py line 227: `ai_corners = np.array(llm_result["corners"], dtype=np.float32)`
- This is passed directly to `_refine_corners_with_opencv` and then to `apply_perspective_correction`
- `apply_perspective_correction` calls `self._order_points(corners)` which reorders them
- BUT: if Claude returns fewer or more than 4 corner points, the np.array will have wrong shape
  and `_order_points` will crash with an obscure numpy error
- No validation of len(llm_result["corners"]) == 4 before the array operation
- IMPACT: Unhandled exception propagates up through _try_ai_fallback which catches it and returns
  `{"success": False}` — so it fails gracefully but with no specific error message logged about why

### CRITICAL-4: Quality check 'valid' key semantics: can_analyze=False cards are accepted
- quality_checks.py line 150-162: quality="poor" sets `can_analyze=False` but `valid=True`
- grading.py line 61: gate is `if not quality_result.get("valid", True)` — only blocks when valid=False
- But valid is ALWAYS True when image loads successfully; quality="poor" / can_analyze=False is NOT blocked
- A heavily blurred or very dark/overexposed image proceeds to full grading
- IMPACT: Poor-quality images go through Vision AI grading producing unreliable scores with no gate

### CRITICAL-5: _apply_damage_cap "most severe wins" logic has a comparison bug
- grade_assembler.py lines 213-215:
  ```python
  if crease and CREASE_ORDER.get(crease, 0) >= 3:     # heavy
      if cap is None or cap > 3.0:
  ```
- The inner condition `cap > 3.0` means: only update cap if current cap is WORSE (higher number) than 3.0
- This is correct — smaller cap number = worse grade ceiling.
- BUT for the moderate crease path:
  ```python
  elif crease and CREASE_ORDER.get(crease, 0) >= 2:   # moderate
      if cap is None or cap > 5.0:
          cap = 5.0
  ```
- If the front side sets cap=3.0 (heavy crease) and the back side has moderate crease,
  `cap > 5.0` is `3.0 > 5.0` = False, so cap stays at 3.0 — correct (heavy wins).
- If front has moderate (cap=5.0) and back has heavy (cap=3.0):
  - Front loop: cap set to 5.0
  - Back loop hits heavy branch: `cap > 3.0` = `5.0 > 3.0` = True, cap updated to 3.0 — correct.
- NET: Actually correct. VERIFIED CORRECT.

### CRITICAL-6: detect_card_side blue_pct calculation uses wrong size for 2D array (VERIFIED NOT BUG)
- combined_grading.py line 37: `blue_pct = cv2.countNonZero(blue_mask) / blue_mask.size * 100`
- For a 2D binary mask from cv2.inRange, `.size` = h*w (total elements) — correct denominator
- VERIFIED CORRECT (confirmed from prior audit)

## Logic Errors

### LOGIC-1: detect_inner_artwork_box margin check only excludes top-left corner
- centering.py lines 143-145:
  ```python
  margin = 0.05
  if x < img_width * margin and y < img_height * margin:
      continue  # Too close to top-left corner — probably the card itself
  ```
- This exclusion only applies when BOTH x AND y are near zero (top-left corner)
- A large contour at x=0, y=img_height/2 (the left edge of the card itself) would NOT be excluded
- The card boundary contour can sometimes be the largest contour in 15-70% area range for
  cropped images where the card fills most of the frame — this would produce centering measured
  relative to the card edge itself (all zeros/near-zero borders) → ratio = undefined or 1.0

### LOGIC-2: calculate_centering_score uses dampened bands that don't align with cap table
- centering.py lines 488-505: dampened scoring curve uses avg_ratio of lr and tb
- interpolate_centering_score uses worst_ratio (min(lr, tb))
- For a card with lr_ratio=0.95, tb_ratio=0.50:
  - avg_ratio = 0.725 → calculate_centering_score returns ~6.5
  - worst_ratio = 0.50 → interpolate_centering_score returns ~7.0 (from table interpolation)
  - centering_avg_score (6.5) < centering_score/cap_score (7.0)
  - Half-point gate uses avg score (6.5), cap uses worst score (7.0)
  - This is intentional per MEMORY.md, but creates a situation where avg score is LOWER than
    worst-axis score — conceptually inverted for a card that is asymmetrically off-center
- SEVERITY: Low — the two scores use different scales (dampened curve vs. table interpolation)
  and different inputs (avg vs worst). They cannot be compared directly.

### LOGIC-3: detect_border_widths (saturation fallback) off-by-one in pixel width (confirmed from prior audit)
- centering.py lines 411-446: `left_width = x` records the FIRST non-saturated column
- True border ends at x-1, not x; so border widths are 1px too wide on all 4 sides
- `max(left_width, w * 0.02)` applied after means minimum border is enforced
- IMPACT: Systematic 1px overcount on all 4 sides → slightly inflates all border widths equally
  → cancels in ratio computation → minimal practical impact

### LOGIC-4: half-point gate compares centering_avg_score (dampened curve, 1-10) to floor(composite)+1
- grade_assembler.py line 263: `worst_avg_centering >= base + 1`
- centering_avg_score comes from calculate_centering_score() which uses the dampened band formula
- composite is produced by a weighted average of Vision AI scores (corners/edges/surface)
- These are "both 1-10" but the dampened centering curve compresses the top range significantly:
  lr_ratio=0.95, tb_ratio=0.95 → avg=0.95 → centering_score = 9.0 (from band 0.93-0.975)
  A Vision AI edge score of 9.0 means near-perfect edges
- In practice: a card with base=8 needs centering_avg >= 9 for half-point. Centering of 0.95 avg
  gives exactly 9.0, which passes. Cards with avg_ratio < 0.93 get < 9.0 and cannot reach half-point
  at a base of 8. This seems reasonable but the coupling is undocumented.

### LOGIC-5: Front-only grading path uses front image as BOTH sides for Vision AI
- combined_grading.py line 510: `vision_result = assess_card(front_img, front_img)`
- The Vision AI receives the SAME image for front and back
- back_* scores will be identical to front_* scores
- Blending: corners 60/40, edges 65/35, surface 70/30 front-weighted
- Result: `blended = 0.60*front + 0.40*front = front` — mathematically neutral
- BUT: damage cap uses surface_raw["back"] which is the same as front — so if front has heavy crease,
  the cap fires TWICE (once for "front" surface, once for "back" surface which is also front)
  Both fire as >= 3.0 severity → cap set to 3.0 either way (idempotent). Not a bug, but wasted work.
- Centering uses front cap table for both sides (is_front=True for both) → BACK_CAP_TABLE not used
  This makes front-only grading slightly more conservative than dual-side for back centering
- SEVERITY: Low — grades are mathematically correct, just back centering is harshly judged

### LOGIC-6: interpolate_centering_score loop fall-through at exact boundary
- centering.py lines 77-84: `if r_low <= ratio < r_high` — misses `ratio == r_high` for interior entries
- For FRONT_CAP_TABLE: table[0] has r_high=0.818. If ratio=0.818 exactly:
  - Line 70-71: `if ratio >= table[0][0]`: 0.818 >= 0.818 → True → returns 10.0 immediately
  - No fall-through possible for the first entry
- For interior entries (e.g. r_high=0.667): if ratio=0.667 exactly:
  - Table[1] r_high=0.667, r_low=0.538: condition is `0.538 <= 0.667 < 0.667` → False
  - Table[0]: `0.667 <= 0.667 < 0.818` → True (caught by previous entry) → returns interpolated value
  - WAIT: loop goes i=0 first: r_high=0.818, r_low=0.667; `0.667 <= 0.667 < 0.818` → True → caught
- For ALL interior entries: ratio==r_high is always caught by the i-1 entry's r_low==ratio check
- ONLY exception: ratio == table[-1][0] = 0.000: `if ratio < table[-1][0]: return 1.0` with strict < means
  ratio=0.0 falls through the loop (0.0 < 0.0 = False, loop finds no match) → returns 1.0 at line 84
- Exact behavior for ratio=0.0: loop finds no match (0.000 < threshold for all but table[-1], and
  for i=-2: r_low=0.000, r_high=0.111: `0.000 <= 0.000 < 0.111` → True → interpolated score at 0.0
  between cap_low=2 and cap_high=3: t = (0.0-0.0)/(0.111-0.000) = 0 → returns 2.0 + 0*(3-2) = 2.0
- NET: ratio=0.0 correctly returns 2.0, NOT 1.0. The line 84 fallback is unreachable for valid tables.
- VERIFIED CORRECT from prior audit notes.

## Confounding Variables

### CONFOUND-1: get_card_corners partial zero-fill when corner lands exactly on centroid axis
- image_preprocessing.py lines 237-243: quadrant-based sorting
- If a corner point has x == center[0] OR y == center[1], it matches NO quadrant
- That slot in sorted_points remains [0,0]
- The global zero check (`if np.all(sorted_points == 0)`) only catches if ALL are zero
- Result: one or more corners at [0,0] → getPerspectiveTransform gets degenerate input
- CONCURRENCY IMPACT: Each call uses local variables — no state leakage between requests

### CONFOUND-2: Double perspective-warp path (confirmed in prior audit)
- hybrid_detect.py warps to 500x700 and saves as front_corrected.jpg
- grading.py sets `already_corrected=True` when detection succeeds
- centering.py line 612: `if already_corrected: corrected = image` — skips re-warp. CORRECT.
- BUT: when vision_border_fractions are provided AND already_corrected=True:
  - The vision_ai path (lines 552-601) uses `image.shape` which IS the corrected image shape
  - Centering is computed on pixel dimensions of the corrected 500x700 image — consistent
- This path is ACTUALLY CORRECT when both `vision_border_fractions` and `already_corrected` are set

### CONFOUND-3: _detection_stats dict has no lock (confirmed prior audit, low severity)
- hybrid_detect.py lines 38-44: global dict mutated without lock
- Concurrent requests can lose increment operations — monitoring only, not grades

### CONFOUND-4: CLAHE instances are created per-call in hybrid_detect.py (FIXED vs prior audit)
- Prior audit found a shared _clahe module-level object — that has been REMOVED
- hybrid_detect.py lines 205, 214, 225, 238: each OpenCV function creates `clahe = cv2.createCLAHE(...)`
  locally → no thread-safety issue. VERIFIED CORRECT.

### CONFOUND-5: analyze_single_side passes `detection_data` but the key is passed without back-side data for combined path
- combined_grading.py line 501: `back_analysis = analyze_single_side(back_path, "back", debug_output_dir)`
  (in grade_card_session — the grade_card_session function is NOT the path called from upload-back)
- The upload-back router calls `analyze_single_side` directly with detection_data — CORRECT
- grade_card_session does NOT pass detection_data for back — uses default None → falls through
  to OpenCV-only centering for back when called via grade_card_session
- IMPACT: grade_card_session is not called from any router (routers call analyze_single_side +
  combine_front_back_analysis separately) — grade_card_session appears to be dead code

### CONFOUND-6: session_manager uses threading.Lock() called from async FastAPI handlers
- session_manager.py line 64: `self._lock = threading.Lock()`
- FastAPI runs on uvicorn with asyncio; concurrent awaits do NOT run in parallel unless
  they await coroutines — but file I/O in session handlers (cv2.imwrite, file.write) blocks event loop
- The _lock acquisition inside update_session/get_session/etc is a synchronous blocking call
  inside async functions — this blocks the event loop under contention
- SEVERITY: Low for low concurrency (typical mobile app with few simultaneous users)
  but becomes a bottleneck if load increases

## Verified Correct Invariants (current session)

- Centering cap gated on confidence >= 0.6: CORRECT (grade_assembler.py line 242)
- Centering excluded from floor/ceiling: CORRECT (_apply_floor_ceiling takes only corners/edges/surface)
- Session TTL 30 min reset on every update_session: CORRECT (session_manager.py update_session calls touch())
- 15MB upload limit: CORRECT (grading.py MAX_UPLOAD_BYTES = 15*1024*1024, enforced after file.read())
- PSA centering cap applied before half-point: CORRECT (step 4 before step 5 in assemble_grade)
- Damage cap applied before centering cap: CORRECT (step 3.5 before step 4)
- Vision AI dual-pass / median-of-3: CORRECT (vision_assessor.py lines 641-649)
- BACK_CAP_TABLE is more lenient than FRONT_CAP_TABLE: CORRECT
- Hallucination guard only fires on placeholder values {1.0, 5.0, 10.0}: CORRECT
- cross_axis_unreliable cap to 0.5: CORRECT (centering.py line 769)
- symmetry_corrected cap to 0.6: CORRECT (centering.py line 771), correctly only fires when NOT cross_axis_unreliable
- CLAHE per-call (not shared): CORRECT — hybrid_detect.py creates clahe locally in each method
- _apply_damage_cap "most severe wins" logic: CORRECT
- Composite weights (corners 37.5% + edges 37.5% + surface 25% = 100%): CORRECT
- Blending: corners 60/40, edges 65/35, surface 70/30 (fixed front-weighted): CORRECT
- Floor/ceiling: worst = min(corners, edges, surface), floor=worst-0.5, ceiling=worst+1.0: CORRECT
- detect_border_widths_hsv axis handling (transposed vs non-transposed): CORRECT
- _apply_damage_cap crease severity comparison direction: CORRECT
- CORS origins: ["https://pregrader-production.up.railway.app", "http://localhost:8000", "http://localhost:3000"]: CORRECT
- Session cleanup loop runs every 2 minutes via asyncio task: CORRECT (main.py line 158)
- File saved before size check would have been a bug but file.read() + len(content) check comes BEFORE write: CORRECT

## Warnings

### WARN-1: quality_checks.py min_resolution is 400px (very lenient) but MEMORY.md says 800px minimum
- quality_checks.py line 107: `min_resolution = 400`
- MEMORY.md states: "Image validator: aspect ratio 0.67–0.76, min 800px (hard block)"
- If there's a separate image_validator.py it would block at 800px; quality_checks allows 400px
- Check if both validators are in the chain or if they serve different purposes

### WARN-2: privacy policy says "15 minutes" but session TTL is 30 minutes
- main.py privacy policy HTML (line 103): "stored temporarily for up to 15 minutes"
- session_manager.py line 19: `timedelta(minutes=30)`
- The public-facing privacy policy misrepresents the actual retention period by 2x

### WARN-3: upload-front endpoint filename sanitization is missing
- grading.py line 47: `front_path = session_dir / f"front_{Path(file.filename).name}"`
- `Path(file.filename).name` strips path separators but does not sanitize characters
- A filename like `../../../../etc/passwd` is sanitized by `.name` to `passwd`
- BUT a filename like `front_; rm -rf /.jpg` → file is named `front_; rm -rf /.jpg`
- File is written with `open()` not shell — so command injection is NOT possible
- But filenames with special characters could cause issues in downstream tools
- SEVERITY: Low — Python's file operations are safe, no shell execution of filenames

### WARN-4: check_image_quality returns `valid=True` even for poor-quality images
- quality_checks.py: `valid` is always True when the image loads (line 99 returns valid=False only on load fail)
- grading.py line 61 gates only on `valid=False` — poor-quality images (blur<50, dark, overexposed) pass through
- A separately documented image_validator.py may handle this, but within the visible pipeline, blurry/dark images are not blocked

### WARN-5: grade_card_session function in combined_grading.py is dead code
- combined_grading.py lines 487-558: grade_card_session() is defined but never imported by any router
- Routers call analyze_single_side + combine_front_back_analysis directly
- This function does NOT pass detection_data to back analyze_single_side (no border_fractions, no already_corrected)
- If ever called, centering for back images would always fall back to OpenCV methods

### WARN-6: VisionAIDetector re-reads image from disk for perspective correction
- vision_detector.py line 322: `img = cv2.imread(image_path)` inside apply_perspective_correction
- The image was already read to encode it as base64 (line 65) — reads same file twice from disk
- No semantic bug but wastes I/O

### WARN-7: _ai_semaphore created at module import time with asyncio.Semaphore()
- hybrid_detect.py line 35: `_ai_semaphore = asyncio.Semaphore(DetectionConfig.MAX_CONCURRENT_AI)`
- asyncio.Semaphore must be used within the same event loop where it was created
- Since uvicorn creates one event loop for the app lifetime and the semaphore is created at import
  (before uvicorn starts its loop), this could cause "attached to a different loop" errors
  in some asyncio/uvicorn versions. In Python 3.10+ this is less strict.
- SEVERITY: Low but worth monitoring on Python version upgrades

## Algorithm Documentation (March 2026 — confirmed from code)

### Composite weights (live)
corners 37.5% + edges 37.5% + surface 25% = 100%. Centering excluded.

### Blending weights (live, fixed front-weighted)
corners 60/40, edges 65/35, surface 70/30. NOT adaptive worse/better.

### PSA centering cap tables
FRONT: 55/45→10, 60/40→9, 65/35→8, 70/30→7, 75/25→6, 80/20→5, 85/15→4, 90/10→3, worse→2.
BACK: 75/25→10, 90/10→9, ~92/8→8, ~95/5→7, ~97.5/2.5→6, worse→5.
Effective cap = min(front_cap, back_cap). Front is almost always binding.

### Floor/ceiling (live)
worst_dim = min(corners_blended, edges_blended, surface_blended)
floor: composite cannot go more than 0.5 below worst_dim.
ceiling: composite cannot exceed worst_dim by more than 1.0.
Centering NOT included in worst_dim computation.

### Damage cap (live)
heavy crease → cap 3.0; moderate crease OR extensive whitening → cap 5.0
Gate: surface_confidence >= 0.60 per side; "most severe wins" across front/back.

### Half-point display rule
Requires fractional(composite) >= 0.3 AND min(front_avg_centering_score, back_avg_centering_score) >= floor(composite) + 1.
centering_avg_score = calculate_centering_score() using average lr/tb ratio (dampened curve).

### Two centering score functions (important distinction)
calculate_centering_score(): avg of lr_ratio and tb_ratio. Stored as centering_avg_score. Used for half-point gate.
interpolate_centering_score(): worst of lr_ratio and tb_ratio (via _centering_cap_and_score). Stored as centering_score. Used for cap enforcement.

### Centering confidence ceilings by method (live)
vision_ai: 0.90 (always triggers cap and half-point if threshold met)
artwork_box: 0.90
hsv_border: 0.75 (triggers cap; cross_axis still possible to cap it to 0.50)
gradient_detection: 0.50 (below cap gate threshold of 0.60 — never triggers centering cap)
fallback/saturation: 0.40 (below cap gate — never triggers centering cap)
symmetry_corrected: caps to 0.60 (just at threshold — may or may not trigger cap)
cross_axis_unreliable: caps to 0.50 (below threshold — never triggers cap)

### Session lifecycle
create (POST /api/grading/start) → upload-front → upload-back → result
Front-only grading possible via grade_card_session (dead code) or if client skips back upload
and calls /result directly (returns status: front_uploaded, not complete)

### CORS origins (main.py)
["https://pregrader-production.up.railway.app", "http://localhost:8000", "http://localhost:3000"]
Port 3000 = undocumented web-dev convenience.

## Fragile Areas to Monitor

1. get_card_corners partial zero-fill: points exactly on centroid axis leave slots as [0,0]
2. quality_check valid/can_analyze semantics: poor-quality images not blocked
3. Privacy policy says 15 min, code is 30 min — legal/compliance discrepancy
4. grade_card_session dead code: if ever activated, back centering loses border_fractions
5. asyncio.Semaphore created at import time: potential event loop mismatch on Python upgrades
6. Front-only grading: front image used as back image, back centering uses FRONT cap table
