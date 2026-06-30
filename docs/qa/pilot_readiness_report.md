# AutoQC Pilot Readiness Report

Date: 2026-06-30

## Status

Pilot readiness status: implementation and verification complete, with one environment caveat: the pre-start doctor fails while the local dev backend/frontend are already running on default ports 8000 and 5173. Running app health passes and does not report that as a false warning.

AutoQC remains an AI-imported-update workflow. The app extracts PDF sheets/pages/context, generates manual Chat Prompts, previews returned AI JSON, imports only gated AI updates/clean-page confirmations, supports reviewer edits/status decisions/manual placement, and exports draft or final deliverables.

## Implemented In This Pass

- Strict review coverage preview/import fields: expected pages, confirmed pages, missing pages, incomplete pages, not-readable pages, coverage status, and percent.
- Import blocks incomplete coverage by default; clean pages are recorded only from imported `reviewed_pages`.
- Manual review plan/dashboard use imported coverage only, not previewed batches or pages with updates.
- Direct AI Review is labeled experimental/text-context-only and uses the same coverage/quality gates.
- Capped Direct AI Review is treated as partial sent-page coverage, not whole-package completion.
- Draft/final export modes with accepted-only final export, complete coverage gate, signoff, manual-placement blocking, validation acknowledgement, and audit events.
- Project package import dry-run validation plus checksum manifest on export.
- Project package export strips local absolute file paths from package JSON and rebuilds paths from the file manifest on restore.
- Public project/export/package/event API responses and in-app audit summaries redact local filesystem paths while preserving download URLs and filenames.
- Project package checksum mismatches now block preview/import instead of passing as warnings.
- PDF and project-package upload routes enforce size limits while streaming, before processing or restore validation.
- Raw AI responses are preserved server-side on import batches; normal UI/API batch summaries expose only stored/length/hash trace fields.
- Older projects with missing coverage metadata still open and can draft-export; final export fails gracefully until coverage is confirmed.
- Primary workflow tabs support arrow-key, Home, and End navigation.
- Review panel includes a next-step workflow guide, recovery cards for active blockers, and step-by-step progress messages for high-risk actions.
- Final export readiness includes a reviewer-facing `Why blocked?` explanation so incomplete coverage, nonfinal status, manual placement, or signoff gaps are visible before export.
- Primary workflow navigation is simplified to Projects, Review, Findings, and Export, with Advanced hosting system check, AI import history, audit log, sample project, and backup/restore tools.
- The drawing viewer includes direct `Jump to sheet` navigation without restoring a separate sheet tab or legacy tracker surface.
- Retired tracker routes and user-facing prompt/export wording are not part of the active product surface.
- `/readiness` now reports running-app health; `scripts/doctor.py` remains the pre-start port/dependency doctor.
- Real-PDF regression harness: `scripts/regression_real_pdfs.py`.
- Smoke, stress, and real-PDF validation scripts write local JSON/Markdown reports under `data/validation_reports/`.
- Failed AI import attempts after partial finding mutation restore prior AI findings and mark the import batch failed where possible.
- Product-boundary docs updated for AI-only user-facing findings.

## Verification Commands

| Command | Result | Notes |
|---|---:|---|
| `pytest` | Pass | 110 passed in 16.72s. |
| `cd frontend && npm run typecheck` | Pass | TypeScript passed. |
| `cd frontend && npm run build` | Pass | TypeScript and Vite production build passed. |
| `cd frontend && npm test` | Pass | 6 Playwright tests passed in 13.2s. |
| `cd frontend && npm run test:e2e` | Pass | 6 Playwright tests passed in 13.5s. |
| `python scripts/doctor.py` | Expected fail while app is running | Pre-start checks passed except ports 8000 and 5173, occupied by the local dev uvicorn/Vite app. |
| `python scripts/doctor.py --full` | Expected fail while app is running | Backend pytest, frontend typecheck, and frontend build passed; final status failed only for occupied pre-start ports. |
| `python scripts/smoke_ai_workflow.py` | Pass | Imported 2 updates, exported 2 findings, and wrote `data/validation_reports/autoqc_smoke_ai_workflow.md`. |
| `python scripts/stress_large_package.py` | Pass | 24 sheets, 24 findings imported/exported, validation passed in 2.3s, and wrote `data/validation_reports/autoqc_large_package_stress.md`. |
| `python scripts/regression_real_pdfs.py` | Pass | Ran against `20250508_Alliant Sheboygan Skid Upgrade_IFC.pdf`: 123 pages, draft validation passed, final validation passed, 69.0s, and wrote `data/validation_reports/autoqc_real_pdf_regression.md`. |
| Simplified-core stale label scan | Pass | No matches in frontend/docs/static smoke contracts for removed UI labels or old tab/button names. |
| `GET /readiness` on running dev backend | Pass | Returned `mode: running_app_health` and `status: passed` while ports 8000/5173 were occupied by the app. |
| `git diff --check` | Pass | No whitespace errors; Git reported LF/CRLF working-copy warnings only. |

## Known Limitations

- Direct AI Review is text-context-only and experimental; manual Chat Prompt with attached PDF is the pilot review path. If sheet sending is capped, Direct AI only counts the sent pages as reviewed.
- AutoQC does not prove engineering correctness of imported AI findings. A responsible reviewer must accept/edit/reject/escalate items.
- Deterministic ReasoningEngine code remains for internal tests and legacy sample scenarios, but active UI/API findings are AI-sourced only.
- Final export blocks incomplete coverage rather than offering a reviewer override.
- Project package zip files are project records and may include raw AI response history for audit/restore. Treat them as controlled project artifacts.
- Validation reports are local generated artifacts under `data/validation_reports/`; they summarize workflow mechanics and should not be treated as engineering approval records.
- Real-PDF regression verifies mechanics only, not subjective engineering conclusions.

## Manual Pilot Guide

- Start with `python scripts/doctor.py`; resolve dependency and port issues before launch.
- Upload a real PDF package and confirm sheet/page extraction and source PDF access.
- Generate a Chat Prompt, attach the actual PDF in ChatGPT/Copilot, and require `reviewed_pages`.
- Preview AI JSON and verify coverage status is complete before import.
- Review imported findings, edit final comments, resolve duplicates, and save manual placements where needed.
- Confirm dashboard review coverage is complete.
- Create a draft export for internal review if non-final statuses remain.
- Create a final export only after accepted-only status, complete coverage, no manual placement blockers, validation readiness, and reviewer signoff.
- Open the marked PDF and QA register in the intended review tools.
