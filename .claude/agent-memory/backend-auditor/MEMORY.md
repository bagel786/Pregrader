# Backend Auditor Memory Index

## Memory Files

- [audit_findings_2026_03.md](audit_findings_2026_03.md) — March 2026 comprehensive audit (9 rounds): Prior Round-8 issues re-verified; damage prompt IS correctly sent as system prompt (prior concern was wrong); Stage 3c art box path IS live (prior concern was wrong); grading_prompt.txt IMAGE LAYOUT stale (still describes 6-image composite layout, COMPOSITE_MODE=False uses 20 images); Stage 3e consistency whitening ordering bug still open; _most_severe(None,None) still open; production-ready verdict maintained Round-9

## Documentation

- GRADING_MODEL.md at repo root — Complete technical reference for the grading pipeline (written March 28 2026). Covers: full pipeline architecture, every scoring formula with line numbers, Vision AI integration details, damage detection stages 3/3b/3c/3d/3e, centering detection chain, all constants and thresholds, session management, API endpoints, and known limitations. Authoritative source of truth for algorithm design decisions.
