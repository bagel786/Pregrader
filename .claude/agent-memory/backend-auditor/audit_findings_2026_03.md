---
name: March 2026 Comprehensive Backend Audit Findings
description: All audit rounds through March 28 2026. Covers all pipeline stages, all bugs found/fixed, and current open issues. Updated Round-8 (March 28 2026 deep audit of corner/edge/centering/surface/damage pipeline).
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

## Round-8 New Findings (March 28 2026)

### CRITICAL: Stage 3c uses front_enhanced/back_enhanced outside their definition scope (Stage 3e)
- combined_grading.py lines 624-658: Stage 3e references `front_enhanced` and `back_enhanced`
  which were defined inside the Stage 3c try block (lines 519-566). If Stage 3c raises an
  exception, those variables are never assigned; Stage 3e then hits `NameError` on `front_enhanced`.
  The Stage 3e except block catches `Exception` broadly so it silently swallows the NameError and
  logs a warning. Net effect: Stage 3e is silently skipped whenever Stage 3c fails. Since Stage 3c
  is the CLAHE preprocessing stage needed for Stage 3e's input images, Stage 3e degrading gracefully
  is acceptable — but the failure is invisible and the log message ("Crease detection failed") is
  misleading. LOW GRADE IMPACT in practice since Stage 3c rarely fails, but the coupling is fragile.

### MEDIUM: damage_preprocessing.py calls detect_inner_artwork_box expecting dict return but function returns ndarray or None
- damage_preprocessing.py line 57: `art_box.get("success", False)` — but detect_inner_artwork_box
  in centering.py returns either None or a numpy array [x, y, w, h], NOT a dict. The `.get()`
  call on an ndarray raises AttributeError, which is caught by the broad `except Exception` at
  line 67 and silently falls back to fixed margin. Result: the split-region art box detection in
  Stage 3c ALWAYS uses the 15% fixed margin fallback — the art box path is dead code.
  Impact: border vs. interior boundary is imprecise (15% margin vs. actual art box). For most
  standard-sized cards this is acceptable, but for EX-era full-art Pokémon (large art boxes) the
  border region is over-estimated, potentially applying aggressive CLAHE to artwork pixels.

### MEDIUM: Crease consistency escalation can elevate whitening on hairline creases
- combined_grading.py lines 571-581: The consistency check escalates whitening to "minor" when
  crease is "heavy" OR "moderate" AND whitening is "none". The docstring says this is
  "physically correct" — creases always cause stress whitening. But a "hairline" crease
  is explicitly excluded. The check is `crease in ("heavy", "moderate")` — correct as-is.
  However, if Stage 3b or 3c later upgrades the crease from "none" to "hairline" AFTER the
  consistency check, the hairline crease gets no corresponding whitening escalation. Since
  the consistency check runs BEFORE Stage 3e (not after), it may miss crease detections that
  arrive via Stage 3e (OpenCV HoughLinesP). Current pipeline order:
    Stage 3b → Stage 3c → consistency check → Stage 3d → Stage 3e → surface score adjustment
  So Stage 3e crease upgrades (hairline/moderate/heavy) skip the consistency whitening check.
  For moderate/heavy creases from Stage 3e that were missed by 3b/3c, whitening stays "none"
  despite the consistency rule. This is a pipeline ordering bug.

### MEDIUM: Surface score adjustment at lines 662-688 double-counts damage already captured in damage cap
- combined_grading.py lines 662-688: Surface scores are hard-capped at 2.5 (heavy) and 5.0
  (moderate) for display coherence. This is sensible. However the cap values (2.5 heavy, 5.0
  moderate, 6.5 hairline) are applied to BOTH front AND back. A card with a heavy crease on
  the back only will:
  (a) Have its back surface score clamped to 2.5
  (b) Have surface_blended = 0.70 * front_score + 0.30 * 2.5
  (c) Trigger the damage cap at 2.0 (grade_assembler.py) if back confidence >= 0.60
  The floor/ceiling constraint in grade_assembler.py uses the blended surface score, which
  is now also depressed by the back score clamping. There is a mild double-penalty: the
  damage cap enforces the 2.0 hard ceiling AND the depressed blended surface score pulls
  the composite (weighted) downward before that cap is applied. For front heavy crease this
  means the final grade is capped at 2.0 by the cap, but the composite before cap was
  also lower than it would have been (e.g., composite 3.5 instead of 5.0). The cap catches
  it anyway, so no incorrect grade results — but the composite_score in the API response
  underestimates the physical card quality relative to PSA intent. Low accuracy impact.

### LOW: grade_range logic compares psa_label string against _GRADE_BRACKETS but psa_label may not appear in brackets
- combined_grading.py lines 271-279: `grade_range` loop searches for `label == psa_label`. If
  psa_label is "8.5" or any half-point grade, the _GRADE_BRACKETS list at lines 264-269 does
  include half-point grades (8.5, 7.5, etc.) — so this is actually handled. Verified correct.

### LOW: assess_damage_from_full_images uses role=user with the damage prompt in the message content
- vision_assessor.py lines 820-847: The damage prompt is injected as the first text block in
  the `content` array within the user message (not as a system prompt). This means the model
  receives the prompt as user text, not as a system instruction. This is less reliable than a
  proper system prompt — models treat system prompts with higher authority than user text.
  The main grading assessor (assess_card) correctly uses SYSTEM_PROMPT. The damage assessor
  does not. Risk: model is more likely to deviate from format instructions or add preamble.
  Partially mitigated by the JSON extraction heuristic (find first `{`, last `}`), but the
  hallucination guard from _validate_response is NOT called on damage assessment output.

### LOW: Hallucination guard stdev < 0.2 threshold may incorrectly reject genuinely uniform gem-mint cards
- vision_assessor.py lines 356-362: The Guard 3 (low-variance) fires when stdev of 8 corner
  scores < 0.2. A PSA 10 card with all 8 corners at 9.5 produces stdev = 0.0 — rejected as
  hallucination. A card with 7 corners at 9.5 and 1 at 9.0 produces stdev ≈ 0.18 — also rejected.
  This guard was added to catch uniform hallucination (all 9.0s) but it over-fires on genuinely
  excellent cards. Impact: excellent cards requiring 3 passes (2 fail hallucination guard → retry
  → third pass median). With MAX_JSON_RETRIES=2, after 3 attempts the guard raises VisionAssessorError,
  which returns a grading error to the user. A truly exceptional card could FAIL grading entirely.

### LOW: _most_severe logic in vision_assessor.py will map None labels to order[-1] when both are None
- vision_assessor.py lines 490-498: `_most_severe(None, None, order)` calls `_normalize_label(None)`
  which returns None (line 469). Then `ia = order.index(None) if None in order else -1` → -1 for both.
  Returns `order[max(-1, -1)]` = `order[-1]` = most severe label. BUG: `_most_severe(None, None)`
  should return None (no damage), but returns the most severe category.
  Impact: if BOTH passes have no crease_depth field, merged result gets crease_depth="heavy".
  However, `.get("crease_depth")` on a dict without the key returns None only if the key is absent.
  The grading_prompt.txt REQUIRES crease_depth field and instructs model to default "none" if unsure.
  In practice this means crease_depth will typically be "none" string not None. But the
  damage_assessment_prompt output is NOT validated — it can legally omit crease_depth (it's described
  as an optional JSON field). If the damage assessor returns a side dict without crease_depth,
  `_most_severe(None, None)` triggers this bug. Fortunately damage assessor output is not passed
  through `_average_passes` or `_median_of_three` — it's merged directly in combined_grading.py
  via individual `.get()` calls. The `_most_severe` bug only affects the dual/triple pass merge of
  main grading assessor output, where crease_depth is required. Risk is low but non-zero.

## Previously Found Bugs (all rounds before Round-8)

### FIXED (from first audit)
- quality gate now checks `can_analyze` (grading.py:61)
- Vision AI corner count validated (vision_detector.py:228-235)
- Artwork box margin filter uses OR across all 4 edges (centering.py:141-145)
- Privacy policy TTL matches code (both 30 min)
- `asyncio.Lock` in SessionManager (session_manager.py:63)

### FIXED (second audit, March 23 2026)
- `_record_stat` now accumulates `total_time_ms` (hybrid_detect.py:383)
- Centering dampened-curve discontinuity at avg_ratio=0.93 eliminated (centering.py:493, divisor 0.05→0.03)
- `COMPOSITE_MODE=False` prompt now conditional (vision_assessor.py:258-275)
- Front re-upload clears stale back_analysis/combined_grade (grading.py:129-135)
- Front/back swap detection now warns user (combined_grading.py:432-437)

### FIXED (third audit, March 24 2026)
- Vision AI failure now returns status="error" not "complete" (grading.py:271-290)
- combine_front_back_analysis wrapped in asyncio.to_thread (grading.py:266-268)
- grade_range works for half-point grades (_GRADE_BRACKETS expanded, combined_grading.py:261-267)
- Centering display shows worse side, exposes both as front_centering/back_centering (combined_grading.py:507-514)
- Dead import _centering_cap_and_score removed (combined_grading.py:15)
- detect_card_side blue threshold 40%→55% + red Pokeball check (combined_grading.py:29-52)
- assess_card raises VisionAssessorError if SYSTEM_PROMPT empty (vision_assessor.py:677-681)
- Unknown damage labels default to most severe via _normalize_label (vision_assessor.py:423-454)
- Damage synonyms split into _CREASE_SYNONYMS/_WHITENING_SYNONYMS (vision_assessor.py:411-427)
- API response includes is_estimate, disclaimer, estimated_grade fields (combined_grading.py:237-245)
- Startup checks for API key + prompt file + calibration warning (main.py:146-157, startup_check.py)
- Flutter checks backResult['status']=='error' from upload-back (review_screen.dart:90-96)
- Confidence chip shows High/Medium/Low (grade_assembler.py:483)
- Dead _SYNONYM_TABLES variable removed (vision_assessor.py)

### FIXED (rounds 4-7, March 24-28 2026)
- Hallucination guard enhanced: 3 checks (all-identical, 7+-identical, low-variance stdev<0.2)
- isinstance guard for surface_raw dict entries (grade_assembler.py:211)
- Stage 3e OpenCV crease detector activated
- Stage 3d texture thresholds raised (THRESH_MINOR=40, THRESH_MODERATE=100, THRESH_EXTENSIVE=150)
- Stage 3c front-only preprocessing (back uses original image to preserve crease signal)
- Surface score adjustment block added (heavy→2.5, moderate→5.0, hairline→6.5 ceilings)
- Vision AI corner hallucination improved prompt (⚠️ CRITICAL warning in grading_prompt.txt)
- Japanese card rejection removed (was incorrectly blocking WOTC era cards)

## Verified Correct Invariants (as of Round-8)

- Blending ratios: corners 60/40, edges 65/35, surface 70/30 front-weighted (grade_assembler.py)
- Composite weights: 37.5% corners + 37.5% edges + 25% surface (grade_assembler.py:156)
- Centering EXCLUDED from composite — operates as hard PSA cap only
- Floor/ceiling: worst-0.5 floor, worst+1.0 ceiling — centering excluded (grade_assembler.py:159-180)
- Damage cap: heavy crease → 2.0, moderate crease OR extensive whitening → 5.0 (grade_assembler.py)
- Damage cap gated at surface_confidence >= 0.60 (grade_assembler.py:212)
- PSA centering cap gated at centering_confidence >= 0.60 (grade_assembler.py:251)
- Half-point uses AVERAGE-axis centering (not worst-axis) to avoid double-penalization (grade_assembler.py:268)
- Session TTL resets on every upload (touch() called in update_session) (session_manager.py:99)
- Front re-upload clears back_analysis and combined_grade (grading.py:134-136)
- asyncio.Lock protects session dict mutations (session_manager.py:63)
- combine_front_back_analysis runs in asyncio.to_thread (grading.py:266)
- Vision AI dual-pass with third pass tiebreaker on >1.5 disagreement (vision_assessor.py:744)
- "Most severe wins" merge for crease_depth and whitening_coverage across all passes
- Stage 3d confidence fixed at 0.55 (below 0.60 cap gate → never triggers grade cap)
- Stage 3e confidence 0.65 for moderate/heavy (above 0.60 → does trigger grade cap)
- CORS restricted to production Railway URL + localhost only (main.py:50-54)
- 15MB upload limit enforced server-side (grading.py:44, 192)

## Round-10 New Findings (March 29 2026 — focused surface damage audit)

### CRITICAL: Stage 3b silently swallows non-VisionAssessorError exceptions
- combined_grading.py line 509: `except VisionAssessorError as exc`. The `assess_damage_from_full_images`
  call at line 481 can raise `httpx.HTTPError`, `json.JSONDecodeError`, or plain `Exception` for
  unexpected issues. Only `VisionAssessorError` is caught here. Any other exception propagates
  upward, aborts `combine_front_back_analysis`, and crashes the entire grading response. The main
  `assess_card` function (Stage 3) wraps its call with `except VisionAssessorError` too (line 469).
  If any network quirk or unexpected library error surfaces from Stage 3b as a plain Exception,
  the user gets a 500 error instead of a degraded-but-present grade. Severity: MEDIUM-HIGH.
  (Stage 3c is wrapped in bare `except Exception` so it is fully protected; Stage 3b is not.)

### LOGIC ERROR: Stage 3e confidence fixup is conditional on crease severity but Stage 3c always floors to 0.65 regardless
- combined_grading.py lines 560-563 (Stage 3c): When Stage 3c upgrades crease at ANY severity
  (hairline, moderate, or heavy), confidence is always floored to 0.65. This means Stage 3c
  hairline upgrades trigger the damage cap gate (0.60), but there is no cap for hairline crease.
  That is benign — hairline crease has no cap, so confidence doesn't matter for cap enforcement.
  However Stage 3e (lines 656-660) correctly does NOT floor confidence for hairline upgrades,
  only for moderate/heavy. Stage 3c is MORE aggressive than Stage 3e on confidence flooring.
  The disparity means: a hairline crease detected by Stage 3c gets confidence=0.65 (overcautious
  but harmless), while Stage 3e hairline gets the natural confidence from vision assessor. Minor
  inconsistency, no grade impact.

### LOGIC ERROR: Damage cap reads surface_confidences from vision_result BEFORE Stage 3c/3d/3e confidence updates
- grade_assembler.py line 414: `_apply_damage_cap(composite, inputs.surface_raw, inputs.surface_confidences)`
  The `surface_confidences` passed to the assembler are extracted at combined_grading.py line 204-207
  AFTER all stages are complete. Specifically, `_vision_to_assembly_input` reads
  `s[side].get("confidence", 1.0)` (line 205-206) where `s = vision["surface"]`. At this point
  `vision_result["surface"]` has already been mutated by Stages 3c and 3e which floor confidence
  to 0.65. So the confidence used for cap gating IS the post-mutation value — this is correct.
  Close this concern — no bug.

### MEDIUM: `_most_severe(None, None, order)` returns None correctly — but `_normalize_label` "unknown label" path diverges
- vision_assessor.py line 471-492: `_normalize_label(None, order)` returns `None` at line 474.
  So `_most_severe(None, None, order)` → both normalize to None → both are `not in order` →
  `ia = -1, ib = -1` → `ia < 0 and ib < 0` → returns `None`. The function is CORRECT for the
  None/None case. However, if a SINGLE pass returns an unknown string label (e.g. "crinkled")
  and the other returns None, `_normalize_label("crinkled", order)` returns `order[-1]="heavy"`.
  Then `ia = 3, ib = -1` → `max(3, -1)=3` → returns "heavy". The most-severe-wins merge of
  an unknown label from one pass vs. absent label from the other pass silently produces the worst
  possible severity. The prior concern about `_most_severe(None,None)` was a MISREAD of the code.
  The actual issue is: a single bad label from one Vision AI pass contaminates the merge.
  Risk: low but real — unknown AI label on one pass → heavy crease in merged result → cap at 2.0.

### MEDIUM: texture.py Sobel gradient score is NOT unit-consistent with its thresholds
- texture.py lines 74-111: `gray_f32 = gray.astype(np.float32) / 255.0` — so pixel values are 0.0-1.0.
  Sobel on [0,1] range produces gradients in [0,1] scale. The local_std is also in [0,1] scale.
  The 80th-percentile combined score is then in [0, ~0.5] range for real cards.
  THRESH_MINOR=40.0 — this threshold makes sense only if the score were in [0,255] scale.
  In [0,1] scale a 40.0 threshold would NEVER be exceeded, so every card returns "none".
  However: `cv2.Sobel(gray_f32, cv2.CV_32F, 1, 0, ksize=3)` with ksize=3 on [0,1] image
  produces outputs in approximately [-1, 1] range (Sobel output is not bounded to input range).
  Empirical calibration comment says "Score range observed: clean=5-15, minor_whitening=40-80".
  These empirical scores imply the actual score range is [0, 150+], which would require
  the gradient magnitude values to be in [0, ~8] before the 80th percentile step. This is
  plausible for coarse-kernel Sobel on float32: cv2.Sobel with ksize=7 on [0,1] can produce
  values up to ~8 in the interior, and the sqrt(grad_x^2 + grad_y^2) can reach higher still.
  Combined with the local std (0.0-0.5 range) weighted 50/50, the observed score range seems
  consistent. The thresholds appear empirically calibrated and function correctly.
  HOWEVER: the scores are highly resolution-dependent (a small 400px card has larger Sobel
  gradients per pixel than a 2000px card of same damage). If a phone captures a large image,
  the effective per-pixel gradient is smaller and the card under-reports. Severity: LOW.

### CONFIRMED: Stage 3d does NOT update confidence — by design, but has an undocumented corollary
- combined_grading.py lines 609-615: Stage 3d upgrades whitening_coverage in vision_result but
  NEVER updates the surface confidence. The damage cap in grade_assembler reads the confidence
  from surface_confidences (which was floored by Stage 3c if applicable). If Stage 3c didn't
  run or didn't upgrade anything, the confidence comes from the Vision AI pass average. If that
  confidence is >= 0.60 AND Stage 3d upgrades whitening to "extensive", the cap WILL fire at 5.0
  from grade_assembler. The comment claiming Stage 3d "affects label display only" is incorrect
  for this case. However this only triggers the cap if the original Vision AI confidence was
  already >= 0.60 — which it typically is (Vision AI returns high confidence scores).
  Impact: when Stage 3d is the sole source of "extensive" whitening, the damage cap (5.0) fires
  based on OpenCV texture data alone (confidence 0.55 was the OpenCV signal, but the confidence
  used by the cap gate is the Vision AI confidence from the underlying score). The design comment
  is misleading. Severity: MEDIUM. Grade impact: Stage 3d can silently trigger cap at 5.0.

### CONFIRMED OPEN: Consistency whitening check runs AFTER Stage 3e but COMMENT says "after ALL stages"
- combined_grading.py line 682: Comment reads "Runs after ALL stages (3c/3d/3e)". The code
  ordering at lines 681-693 places the consistency check AFTER Stage 3e (line 629-679). This
  WAS the open bug from Round-8 (ordering wrong), but re-reading: the comment is now CORRECT —
  the consistency check is at lines 681-693, which is AFTER Stage 3e at lines 629-679. The
  Round-8 finding that it ran before Stage 3e was based on an OLD version of the code. In the
  CURRENT code the ordering is correct: 3c → 3d → 3e → consistency check → score adjustment.
  CLOSE the Stage 3e consistency ordering bug. This is now correctly implemented.

### NEW LOGIC ERROR: Surface score adjustment uses `_WH_ORDER` but this variable is out of scope
- combined_grading.py line 609: `_WH_ORDER` is defined at line 517 inside the
  `combine_front_back_analysis` function scope. Lines 609 (Stage 3d) and 644 (Stage 3e) both
  reference `_WH_ORDER` — these are inside the same function scope, so the reference is valid.
  Close — no scope issue.

### NEW MEDIUM: Stage 3b crease upgrade is NOT symmetric with whitening upgrade logic
- combined_grading.py lines 490-507: Stage 3b crease logic: "heavy" → unconditional override;
  "moderate" → upgrades only if current < moderate. But Stage 3b whitening logic: "extensive" →
  unconditional override; "moderate" → upgrades only if current in ["none", "minor"]. The crease
  "heavy" case ignores the current crease level and unconditionally overwrites, even if Vision AI
  dual-pass already detected "heavy" (benign). But if Vision AI detected "heavy" crease and
  damage assessor returns "moderate", the Stage 3b logic does NOT downgrade — the `elif damage_crease in ["moderate"]`
  branch only fires when damage_crease IS "moderate", and the inner check `current_rank < moderate_rank`
  correctly prevents a downgrade. So heavy→moderate downgrade is correctly blocked. No bug.

### NEW WARNING: detect_surface_creases always converts BGR to grayscale internally — double grayscale conversion for Stage 3e
- creases.py line 103: `gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)`. Stage 3e at line 639
  passes `front_enhanced` (or `back_enhanced`) which was already converted to BGR-gray by
  `damage_preprocessing.py` (single-channel gray stored as 3-channel BGR via cvtColor
  GRAY2BGR at line 141). So `detect_surface_creases` receives a grayscale image packed as BGR
  (all 3 channels equal), then converts it to grayscale again. The result is identical — a true
  grayscale image — but with an unnecessary second conversion. No accuracy impact.

### NEW WARNING: HoughLinesP MIN_LINE_FRACTION=0.15 anchored against card_diagonal, but Stage 3e receives preprocessed image that may differ in size from original
- creases.py lines 94, 126: `card_diagonal = math.sqrt(h**2 + w**2)` then
  `min_line_length = int(card_diagonal * min_line_frac)`. The image passed to Stage 3e is
  `front_enhanced` from `enhance_for_damage_detection()`, which returns an image of the SAME
  dimensions as the input (same h, w). So the card diagonal is accurate. No bug.

## Round-9 New Findings (March 29 2026)

### VERIFIED FIXED: Hallucination guard stdev<0.2 removed from code
- vision_assessor.py lines 362-364: Guard 3 (stdev<0.2) explicitly commented out as "removed".
  Only Guards 1 (all-8-identical) and 2 (7+-identical) remain. Gem-mint cards are no longer rejected.
  The prior concern in Round-8 no longer applies.

### VERIFIED FIXED: isinstance guard for surface_raw dict entries present
- grade_assembler.py line 221: `if not isinstance(data, dict): continue` — present and correct.

### NEW MEDIUM: Stage 3d whitening upgrade does NOT floor the confidence after upgrade
- combined_grading.py lines 609-615: When Stage 3d (OpenCV texture) upgrades whitening_coverage,
  it does NOT update the surface confidence. The damage cap in grade_assembler.py requires
  surface_confidence >= 0.60 to fire. The comment (lines 597-598) says "confidence deliberately
  0.55 → below 0.60 damage-cap gate, so this stage affects label display only." That design is
  intentional for Stage 3d. HOWEVER: when Stage 3d upgrades whitening to "extensive", the
  damage cap (cap=5.0) will NOT fire because the surface confidence from Vision AI may remain
  above 0.60 but the whitening level was already at "none"/"minor" (below cap threshold). So the
  comment is only partially correct: Stage 3d cannot TRIGGER a new cap, but it can BOOST an
  already-extensive label if Stage 3b/3c detected extensive already. Net effect is benign:
  Stage 3d's upgrade elevates the label for display/warning purposes without triggering a grade
  cap independently. This matches the documented design. Mark as LOW (not MEDIUM) — verified intentional.

### CONFIRMED OPEN: Stage 3e crease upgrades skip the consistency whitening check
- combined_grading.py: Consistency check (lines 684-693) runs BETWEEN Stage 3c (lines 521-593)
  and Stage 3d (lines 600-627). Stage 3e (lines 634-679) runs AFTER the consistency check.
  A Stage 3e upgrade of crease from "none" → "hairline" or "none" → "moderate" (capped) will NOT
  trigger the consistency whitening escalation. A card with a moderate crease detected only by
  Stage 3e will show crease="moderate" + whitening="none" in the API response, violating the
  stated physical invariant. The consistency check should be moved to AFTER Stage 3e.

### NEW MEDIUM: grading_prompt.txt IMAGE LAYOUT description is stale (still describes COMPOSITE_MODE=True layout)
- grading_prompt.txt lines 57-67: The "IMAGE LAYOUT" section still says:
  "You will receive 6 images: 1. Front corners grid (2×2)... 2. Back corners grid (2×2)..."
  This is the COMPOSITE_MODE=True layout (6 images). COMPOSITE_MODE is now False — the model
  receives 18 individual crops plus 2 surface images = 20 images. The system prompt layout
  description is wrong for the actual image order the model receives.
  The code in _build_message_content (vision_assessor.py lines 267-289) correctly sends the
  `layout_desc` as part of the user message (not the system prompt) which is accurate. However
  the SYSTEM PROMPT itself still has the old 6-image layout description. The model may be
  confused by conflicting layout instructions (system says 6 images, user message says 18 crops).
  This could degrade corner identification accuracy. Severity: MEDIUM.

### CONFIRMED OPEN: assess_damage_from_full_images sends damage prompt as user text not system prompt
- vision_assessor.py lines 929-938: `payload["system"] = damage_prompt` — wait, re-reading:
  Line 932: `"system": damage_prompt` IS set correctly as the system key. This was WRONG in
  the prior audit note. The prompt IS sent as a system prompt. Re-check: lines 928-939 show
  `payload = {"model": MODEL, "max_tokens": 1024, "system": damage_prompt, "messages": [...]}`
  The prior Round-8 concern was incorrect — this is implemented correctly. CLOSE THIS ISSUE.

### NEW LOW: Centering confidence for artwork_box and vision_ai methods both return 0.90, but artwork_box
  is OpenCV geometry (slightly less reliable than Vision AI border_fractions). Functionally both
  are above the 0.60 cap gate — both correctly trigger the PSA centering cap. No grade impact, but
  may be worth distinguishing in future for confidence display.

### CONFIRMED OPEN: Stage 3c art box path dead (damage_preprocessing.py always uses 15% margin)
- damage_preprocessing.py lines 55-73: `art_box = detect_inner_artwork_box(img)` returns either
  None or a tuple (x, y, w, h). At line 57, code correctly does:
  `bx, by, bw_box, bh_box = art_box` (tuple unpacking). Re-reading the code: this IS correct
  Python tuple unpacking. The earlier finding about `.get()` on ndarray was WRONG. The
  detect_inner_artwork_box returns `(x, y, w, h)` tuple, and damage_preprocessing.py correctly
  unpacks it via `bx, by, bw_box, bh_box = art_box`. This path IS live. CLOSE THIS ISSUE.

## Known Remaining Issues (all rounds, updated Round-9)

- No rate limiting on API
- Debug images accumulate on disk (cleanup config exists but not implemented)
- No calibration study against professional PSA/BGS grades yet
- GradeResult model in grade_result.dart still has misleading 10.0 defaults (model unused in practice)
- HSV border detection needs real-world regression testing across card types
- Moderate crease cap (5.0) still heuristic — no TAG data yet for moderate crease as primary defect
- Floor/ceiling spread (worst+1.0 ceiling) likely too generous for single-corner defects
- full-art cards may fail Vision AI border_fractions sanity check (centering.py:560-607)
- OpenCV corner scores computed but unused by grade_assembler (wasted CPU)
- Multi-pass Vision AI reinforces systematic bias (fundamental limitation)
- Flutter receiveTimeout (60s) shorter than Vision AI worst case (~90s)
- quality_checks.py min_resolution 400px vs Flutter 600px enforcement gap
- `refused` grading_status: Flutter checks for it (result_screen.dart:55-56) but backend never sends it — dead client code
- `final_score` in API response = assembler's `composite_score` (continuous), NOT `final_grade` (PSA integer)
- LOGIC-6 (cap=2.0 docstring): grade_assembler _apply_damage_cap docstring stub doesn't state the cap value; comment in assemble_grade says "heavy crease / extensive whitening" correctly. No stale docstring found in current code — CLOSE.
- Stage 3e crease upgrades miss consistency whitening escalation (pipeline ordering issue) — OPEN
- grading_prompt.txt IMAGE LAYOUT section describes 6-image composite layout but COMPOSITE_MODE=False sends 18+2 crops — OPEN (NEW)
- _most_severe(None, None) returns most severe label instead of None (edge case, low risk) — OPEN
