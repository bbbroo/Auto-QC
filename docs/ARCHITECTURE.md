# Architecture

AutoQC is a local-first FastAPI, SQLite, and React application.

## Pipeline

1. A PDF is saved into `data/projects/<project-id>/input`.
2. PyMuPDF opens the PDF, extracts embedded text and text blocks, and renders each page to PNG.
3. When extracted text is weak, the backend tries optional `pytesseract` OCR and records the OCR status.
4. The classifier uses title block fields, drawing numbers, and drawing keywords to classify cover, index, PFD, P&ID, layout, legend, notes, detail, and unknown sheets.
5. Entity extraction finds line numbers, valves, equipment, instruments, drawing references, note references, revision callouts, and title block fields.
6. Upload/review processing stops after extraction, classification, entity capture, and sheet rendering. It does not create deterministic rule findings for the active UI.
7. The active review-item workflow is AI-only. The primary no-key workflow generates a manual prompt, requires the reviewer to attach the PDF package in ChatGPT or Copilot Chat, and imports the returned JSON updates. The configured direct AI endpoint remains optional.
8. Pasted manual AI output is first parsed into an import preview. The exact raw response is preserved on the server-side import batch, while normal UI/API lists expose only stored/length/hash trace fields. The preview records parser repairs, warnings, candidate/valid/skipped counts, duplicate stable IDs, rejected update reasons, review coverage status, review modality, and whether each valid update would create or update a finding.
9. Import is blocked unless every expected page for the review scope is present in `reviewed_pages` with `review_status: "complete"`. Clean pages are recorded from imported `reviewed_pages`; pages with updates do not count as reviewed by themselves.
10. Confirmed AI updates are normalized into `source="ai"` findings, deduplicated, set to `needs_review`, linked to an AI import batch/prompt version when available, and stored in SQLite. Second-pass missed-issue audit imports are linked to their prior batch with `audit_of_batch_id`, `audit_round`, and `audit_yield_count`. If a late import write fails after findings begin changing, AutoQC attempts to restore the prior AI findings and marks the import batch failed for retry/audit.
11. The React UI lists, edits, accepts, rejects, defers, escalates, deletes, and exports only AI-sourced findings.
12. Export generation writes accepted or selected AI findings as standard PDF annotations plus a QA register CSV, XLSX, JSON, Markdown, and HTML summary files. Draft export remains flexible and uses draft-labeled filenames/summaries; final export requires accepted-only findings, complete review coverage, signoff, and validation readiness.

## Backend Modules

- `backend/app/main.py`: FastAPI routes, source PDF endpoint, and safe generated-file serving.
- `backend/app/database.py`: SQLite schema and persistence methods.
- `backend/app/services/pdf_processor.py`: PDF ingestion, rendering, extraction, and project reprocessing.
- `backend/app/services/storage.py`: shared safe path helpers for project source PDFs and public sheet/export assets.
- `backend/app/services/classifier.py`: title block extraction and sheet classification.
- `backend/app/services/extraction.py`: regex-based engineering entity extraction.
- `backend/app/services/ai_review.py`: active AI-only review-item workflow, including provider review, prompt versioning, manual prompt generation, manual JSON preview/import, batch history, and conversion of AI updates into findings.
- `backend/app/services/review_coverage.py`: expected/confirmed page coverage summaries for preview, import, dashboard, and final export gates.
- `backend/app/services/reasoning/engine.py`: legacy deterministic station graph builder and rule modules. This remains internal/testable code, but it is not the source of user-facing UI findings.
- `backend/app/services/reasoning/normalizer.py`: stable finding IDs, deduplication, and confidence-based status helpers used by internal deterministic tests and compatible finding normalization paths.
- `backend/app/services/exports.py`: marked PDF, placement status calculation, QA register CSV, Excel, JSON, Markdown, and HTML outputs.
- `backend/app/services/project_packages.py`: project package export, checksum manifest generation, dry-run import validation, safe file restore, and ID remapping.
- `backend/app/services/ai_service.py`: legacy optional AI hook retained for older internal integration points.

## Frontend

The React UI is intentionally operational: project list and upload controls on the left, sheet image review in the center, and AI review/export controls on the right. It works against the FastAPI API and uses rendered sheet PNGs rather than requiring browser PDF plugins.

The findings panel is intentionally AI-only. Project summaries and finding counts are based on records returned by `/projects/{project_id}/findings`, which filters to `source="ai"`. Edit, bulk edit, delete, and export flows use the same AI-source boundary, so legacy deterministic findings are not exposed as active reviewer comments.

Manual AI import uses two API steps:

- `POST /projects/{project_id}/ai-review/preview`: parses pasted output into a preview and creates an `ai_import_batches` row.
- `POST /projects/{project_id}/ai-review/import` with `preview_id`: imports only valid recoverable preview updates.

The previous direct import shape with `response_text` remains compatible and internally performs preview plus confirm.

Preview/import rejects updates that lack a usable `target_text`, rejects stale or already-imported preview IDs, and blocks import when coverage is incomplete. Preview still shows partial or incomplete responses so reviewers can see missing pages before asking the AI to retry.

The optional configured direct AI endpoint is labeled experimental/text-context-only unless upgraded to true PDF/image review. It stores `direct_review_mode: text_context_only` and `review_modality: text_context_only`, uses the same coverage and quality gates, and cannot treat a capped text-only response as full-package complete. When `AUTOQC_AI_MAX_SHEETS` limits the sent sheets, Direct AI imports are scoped to the sent pages so dashboard/final export coverage remains incomplete until the missing pages are confirmed through imported AI review.

## Package Restore Safety

Project package export writes a manifest with file references and checksums where practical. The package payload strips local absolute source/image/export paths and sanitizes audit-event change details in `project.json`; restore copies package files into the new project directory and rebuilds local paths from the manifest. The import preview validates zip structure, schema, JSON shape, safe paths, allowed file extensions, upload/uncompressed size and file-count limits, source PDF readability, sheet image readability, and checksum mismatches before DB/file restore begins. If confirmed restore fails after file copying starts, AutoQC removes newly-created restore files and project rows where practical.

Public project, export, package, and audit-event API responses redact local filesystem paths and provide controlled source/download URLs instead. Internal DB records retain managed paths where needed for file serving and cleanup.

## Storage

By default, all generated artifacts live under `data/`:

- `data/autoqc.sqlite`
- `data/projects/<project-id>/input/source.pdf`
- `data/projects/<project-id>/sheets/page_###.png`
- `data/projects/<project-id>/exports/<export-id>/marked_review.pdf`
- `data/projects/<project-id>/exports/<export-id>/qc_log.csv` (QA register)
- `data/projects/<project-id>/exports/<export-id>/qc_log.xlsx`
- `data/projects/<project-id>/exports/<export-id>/findings.json`
- `data/projects/<project-id>/exports/<export-id>/review_summary.md`
- `data/validation_reports/*.json` and `*.md` from smoke, stress, and real-PDF validation scripts

Set `AUTOQC_DATA_DIR` or `AUTOQC_DB_PATH` to move local storage.

The browser can fetch rendered sheet images and export outputs through `/data/...`; raw input PDFs and the SQLite database are not exposed through that generic route. Source PDFs are opened through `/projects/{project_id}/source-pdf`, which validates that the stored path resolves inside the project input directory. Processing and export use the same managed-source boundary.

Project package import is two-phase in the UI: dry-run preview validates the zip, schema, paths, file count/size, allowed extensions, source PDF, images, JSON payload shape, and checksums when present; confirmed import then restores the validated payload.
