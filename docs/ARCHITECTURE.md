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
8. Pasted manual AI output is first parsed into an import preview. The preview records parser repairs, warnings, candidate/valid/skipped counts, duplicate stable IDs, rejected update reasons, and whether each valid update would create or update a finding.
9. Confirmed AI updates are normalized into `source="ai"` findings, deduplicated, set to `needs_review`, linked to an AI import batch/prompt version when available, and stored in SQLite.
10. The React UI lists, edits, accepts, rejects, defers, escalates, deletes, and exports only AI-sourced findings.
11. Export generation writes accepted or selected AI findings as standard PDF annotations plus a QA register CSV, XLSX, JSON, Markdown, and HTML summary files. Export records placement status for each exported AI finding.

## Backend Modules

- `backend/app/main.py`: FastAPI routes, source PDF endpoint, and safe generated-file serving.
- `backend/app/database.py`: SQLite schema and persistence methods.
- `backend/app/services/pdf_processor.py`: PDF ingestion, rendering, extraction, and project reprocessing.
- `backend/app/services/storage.py`: shared safe path helpers for project source PDFs and public sheet/export assets.
- `backend/app/services/classifier.py`: title block extraction and sheet classification.
- `backend/app/services/extraction.py`: regex-based engineering entity extraction.
- `backend/app/services/ai_review.py`: active AI-only review-item workflow, including provider review, prompt versioning, manual prompt generation, manual JSON preview/import, batch history, and conversion of AI updates into findings.
- `backend/app/services/reasoning/engine.py`: legacy deterministic station graph builder and rule modules. This remains internal/testable code, but it is not the source of user-facing UI findings.
- `backend/app/services/reasoning/normalizer.py`: stable finding IDs, deduplication, and confidence-based status helpers used by internal deterministic tests and compatible finding normalization paths.
- `backend/app/services/exports.py`: marked PDF, placement status calculation, QA register CSV, Excel, JSON, Markdown, and HTML outputs.
- `backend/app/services/ai_service.py`: legacy optional AI hook retained for older internal integration points.

## Frontend

The React UI is intentionally operational: project list and upload controls on the left, sheet image review in the center, and AI review/export controls on the right. It works against the FastAPI API and uses rendered sheet PNGs rather than requiring browser PDF plugins.

The findings panel is intentionally AI-only. Project summaries and finding counts are based on records returned by `/projects/{project_id}/findings`, which filters to `source="ai"`. Edit, bulk edit, delete, and export flows use the same AI-source boundary, so legacy deterministic findings are not exposed as active reviewer comments.

Manual AI import uses two API steps:

- `POST /projects/{project_id}/ai-review/preview`: parses pasted output into a preview and creates an `ai_import_batches` row.
- `POST /projects/{project_id}/ai-review/import` with `preview_id`: imports only valid recoverable preview updates.

The previous direct import shape with `response_text` remains compatible and internally performs preview plus confirm.

Preview/import rejects updates that lack a usable `target_text`, rejects stale or already-imported preview IDs, and records failed preview batches when nothing is importable.

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

Set `AUTOQC_DATA_DIR` or `AUTOQC_DB_PATH` to move local storage.

The browser can fetch rendered sheet images and export outputs through `/data/...`; raw input PDFs and the SQLite database are not exposed through that generic route. Source PDFs are opened through `/projects/{project_id}/source-pdf`, which validates that the stored path resolves inside the project input directory. Processing and export use the same managed-source boundary.
