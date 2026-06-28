# AutoQC QA Continuation Notes

## What was completed in this pass

- Release Candidate/company pilot readiness additions:
  - Project package export/import with safe local source PDF, sheet image, export artifact, metadata, import batch, audit event, and export record roundtrip.
  - AI import batch rollback that removes only findings created by a selected imported batch and records audit history.
  - Stronger audit visibility in the app with `Local reviewer` activity rows.
  - Marked PDF export validation by reopening generated PDFs with PyMuPDF.
  - AI import schema/parser mode reporting and stronger exact/likely duplicate preview.
  - Duplicate/merge tools that preserve original AI evidence and hide duplicates via review status.
  - Prompt template manager with default, regulator station, drawing coordination, title block/revision, and smoke-test templates stored locally.
  - In-app System Check, first-run help, compact management dashboard, and large/wide stress harness.
- Confirmed the RC pass started from a clean `git status --porcelain -uall`; previous stabilization notes about an older dirty workspace remain historical context only.
- Created the canonical final tracker at `docs/qa/final_stabilization_tracker.md`.
- Resolved the npm-script verification mismatch found after the stabilization pass. Root cause: in the Windows/MSYS Pro12 shell, npm had no usable script shell configured, so npm failed before spawning package scripts with `TypeError [ERR_INVALID_ARG_TYPE]: The "file" argument must be of type string. Received undefined`. Direct `npx tsc --noEmit` worked because it bypassed npm script spawning.
- Added `frontend/.npmrc` with an explicit Windows `script-shell=C:\Windows\System32\cmd.exe` so npm scripts run reliably in this workspace.
- Re-ran and fixed frontend toolchain coverage:
  - `npm run typecheck` passes.
  - `npm run build` passes and generates `frontend/dist`.
  - `npm test` is configured and runs Playwright.
  - `npm run test:e2e` passes with the same Playwright suite.
- Added Playwright E2E coverage under `frontend/e2e` with isolated backend/frontend ports and isolated `data/e2e` storage.
- Hardened AI import behavior:
  - missing or blank `target_text` is rejected during preview with visible reasons.
  - structured non-string evidence is not silently stringified into target text.
  - stale/already-imported preview IDs cannot be replayed.
  - oversized pasted AI responses are rejected by request validation.
- Hardened PDF/storage/export behavior:
  - uploaded bytes must open as a valid PDF, even when `auto_review=false`.
  - project processing/export/source PDF serving require the source PDF to live under the project input directory.
  - generic `/data/...` serving is restricted to generated sheet images and export files.
  - raw input PDFs and the SQLite database are not served through `/data`.
  - empty exports are rejected with a clear error.
- Updated scripts so `scripts/smoke_ai_workflow.py` uses managed project input storage and `scripts/run_sample_review.py` no longer tries to export a zero-finding sample shell.
- Updated README, architecture/rules/sample docs, UI/UX audit, final tracker, and feature status with current behavior.
- Added finding placement recalculation for existing imported AI findings. The recalculation pass searches source PDF target text, updates `placement_details`, preserves reviewer status/notes, and returns exact/fuzzy/page-level/manual placement counts.
- Added viewer and export placement diagnostics so users can see whether a selected finding/export is exact, fuzzy, page-level, or needs manual placement.
- Added review efficiency improvements: queue progress, auto-advance, placement filters, keyboard shortcuts, and a local readiness script.

## Tests passed

- `pytest`: 47 passed.
- `cd frontend; npx tsc --noEmit`: passed.
- `cd frontend; npm run typecheck`: passed.
- `cd frontend; npm run build`: passed; Vite generated `frontend/dist`.
- `cd frontend; npm test`: 5 Playwright tests passed.
- `cd frontend; npm run test:e2e`: 5 Playwright tests passed.
- `python scripts/doctor.py`: ran; failed only because ports 8000/5173 were already occupied by local AutoQC-looking Python/Node listeners.
- `python scripts/doctor.py --full`: ran; backend pytest, frontend typecheck, and frontend build passed; final status failed only because ports 8000/5173 were occupied.
- `python scripts/smoke_ai_workflow.py`: passed.
- `python scripts/stress_large_package.py`: passed; 24 wide sheets, 24 findings imported/exported, validation passed.

## Remaining known issues / constraints

- Direct live AI-provider behavior was not exercised; the local no-key manual Chat Prompt workflow is covered.
- The tab UI is keyboard reachable with visible focus, but full arrow-key tablist behavior remains a future accessibility enhancement.
- The E2E suite covers the primary local workflow and smoke states, not every optional convenience path such as drag/drop file import or project deletion through the browser.
- Bluebeam/Adobe validation still requires manual opening of a real exported company package.
- A real company drawing package should still be used for final pilot signoff; the automated stress fixture is synthetic.

## Final workflow status

The preserved AutoQC workflow is verified:

```text
PDF/sample -> Chat Prompt -> AI JSON preview/import -> findings review -> marked PDF export
```

No internal rule-based QC findings were added to the active user-facing workflow.
