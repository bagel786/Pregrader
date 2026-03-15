---
name: First Full Cleanup Audit — March 2026
description: Results of the 2026-03-15 comprehensive audit: what was deleted, kept, and patterns of dead code accumulation in this repo
type: project
---

## Audit Date
2026-03-15

## What Was Deleted

### Test Files (user explicitly requested all test deletion)
- `backend/tests/` — entire directory (test_scoring.py + __init__.py + __pycache__)
- `backend/grading/calibration/test_known_grades.py` — pytest test in calibration subdir
- `backend/grading/calibration/__init__.py` — existed only to support above test
- `backend/test_analysis.py` — root-level one-off test script
- `backend/test_before_deploy.py` — root-level pre-deploy script (imported deleted `enhanced_corners`)
- `backend/test_consistency.py` — root-level consistency test
- `backend/test_serialization.py` — root-level serialization test
- `backend/verify_hybrid.py` — unittest-based hybrid verification script
- `test/widget_test.dart` — Flutter widget test
- `test/assets/test_card.jpg` — test fixture image

### Deprecated Modules
- `backend/analysis/deprecated/corners.py` — self-labelled DEPRECATED, zero production imports
- `backend/analysis/deprecated/edges.py` — same
- `backend/analysis/deprecated/surface.py` — same
- `backend/analysis/utils.py` — `order_points` + `find_card_contour`; only imported by deprecated modules above; active code uses `analysis.vision.image_preprocessing` for the same functions

### Orphaned Debug Utilities
- `backend/analysis/vision/debug.py` — zero production imports
- `backend/analysis/vision/debugger.py` — only imported by test_before_deploy.py (deleted)

### Stale Data / Planning Docs
- `REFACTOR_PLAN.md` — planning doc referencing already-deleted files (enhanced_corners.py, enhanced_detection.py)
- `grading_model_prd.md` — PRD document in root, no code value
- `backend/portfolio.db` — SQLite database with zero code references anywhere
- `backend/server.log` — runtime log file (gitignored, regenerated on startup)

### Stale Label Fixed
- `backend/main.py` health check: `"enhanced_corners": True` → `"corner_detection": True`

## What Was Kept (and Why)

- `backend/startup_check.py` — referenced in `backend/Dockerfile` line 27; must stay
- `backend/analysis/vision/image_preprocessing.py` — actively imported by `analysis/centering.py`
- `backend/analysis/vision/quality_checks.py` — imported by `api/routers/grading.py`
- `backend/grading/calibration/__init__.py` was deleted (test file gone, nothing else in dir)
- `backend/grading/calibration/` directory kept because `grading/grade_assembler.py` and `grading/vision_assessor.py` are actively used

## Patterns of Dead Code Accumulation Observed

1. **Root-level test scripts** — `test_*.py` files placed directly in `backend/` instead of `backend/tests/`. Easy to miss in audits.
2. **`deprecated/` subdirectory** — files self-labelled DEPRECATED but never actually removed; had real import chains still working
3. **Planning docs in repo root** — REFACTOR_PLAN.md, grading_model_prd.md accumulate as "drop this file into Claude" artifacts
4. **Orphaned databases** — `portfolio.db` had no code reference; appeared to be a leftover from an experimental feature
5. **Debug visualization modules** — `debug.py` and `debugger.py` written for development, never removed when production path matured

## Active Architecture (post-cleanup)

Production import chain:
- `main.py` → `api/routers/{sessions,grading,admin}.py`
- `grading.py` router → `api/combined_grading.py`, `api/hybrid_detect.py`, `analysis/corners.py`, `analysis/vision/quality_checks.py`, `utils/serialization.py`
- `combined_grading.py` → `grading/vision_assessor.py`, `grading/grade_assembler.py`, `analysis/scoring.py`, `analysis/centering.py`
- `centering.py` → `analysis/vision/image_preprocessing.py`
- `hybrid_detect.py` → `services/ai/vision_detector.py`
- `admin.py` router → `api/hybrid_detect.py` (get_detection_stats)

## Notes for Next Audit
- `backend/grading/calibration/` directory now only contains `__init__.py` — consider removing the empty dir if nothing gets added
- `GradeResult` model in `lib/screens/grade_result.dart` does NOT exist (was a false lead in project notes — no such file found)
- `analysis/utils.py` had `order_points` + `find_card_contour` that duplicate what's in `image_preprocessing.py` — correctly deleted since deprecated modules were deleted
