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

## Known Remaining Issues (all rounds)

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
- LOGIC-6 (cap=2.0 docstring): grade_assembler docstring says "cap 3.0" for heavy crease but code uses 2.0 (calibrated correct, docstring stale)
- Stage 3c art box path dead (damage_preprocessing.py always uses 15% margin due to return type mismatch)
- Stage 3e crease upgrades miss consistency whitening escalation (pipeline ordering issue)
- Hallucination guard stdev<0.2 may reject genuine gem-mint cards
- _most_severe(None, None) returns most severe label instead of None (edge case, low risk)
- assess_damage_from_full_images sends prompt as user text not system prompt
