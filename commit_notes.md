# Commit Notes

## Suggested Commit Message

```text
Add admin evaluation tools and refresh demo materials
```

## Summary

- Improved RAG evaluation hit checks by including retrieved event text, reason, and topic tags.
- Updated default RAG evaluation prompts so all three demo elders have stable, data-grounded hit-rate examples.
- Added responsive UI protection for admin session rows and two-column tool controls.
- Rewrote `demo_script.md` to match the current UI and removed outdated references to deleted test/demo pages.
- Added `poster_screenshot_plan.md` for poster-ready screenshot capture planning.
- Added `xtts_wav_guide.md` with recording format, consent notes, sample scripts, and upload checklist.

## Verification

- `backend/tools/rag_evaluation.py` compiles.
- `frontend/admin.html` inline script parses successfully.
- RAG default examples were verified through the API:
  - `W001`: 3/3 hits
  - `C001`: 3/3 hits
  - `L001`: 3/3 hits
