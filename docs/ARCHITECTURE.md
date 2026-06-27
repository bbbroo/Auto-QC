# Architecture

Natural Gas Engineering Copilot is a local-first FastAPI, SQLite, and React application.

## Pipeline

1. A PDF is saved into `data/projects/<project-id>/input`.
2. PyMuPDF opens the PDF, extracts embedded text and text blocks, and renders each page to PNG.
3. When extracted text is weak, the backend tries optional `pytesseract` OCR and records the OCR status.
4. The classifier uses title block fields, drawing numbers, and drawing keywords to classify cover, index, PFD, P&ID, layout, legend, notes, detail, and unknown sheets.
5. Entity extraction finds line numbers, valves, equipment, instruments, drawing references, note references, revision callouts, and title block fields.
6. The reasoning engine builds a station graph from detected components and runs focused rule modules.
7. Candidate findings are normalized, deduplicated, assigned severity/confidence/status, and stored in SQLite.
8. The React UI lets the reviewer edit, accept, reject, delete, and export findings.
9. Export generation writes standard PDF annotations plus CSV, XLSX, JSON, and Markdown summary files.

## Backend Modules

- `backend/app/main.py`: FastAPI routes and static file serving.
- `backend/app/database.py`: SQLite schema and persistence methods.
- `backend/app/services/pdf_processor.py`: PDF ingestion, rendering, extraction, review orchestration.
- `backend/app/services/classifier.py`: title block extraction and sheet classification.
- `backend/app/services/extraction.py`: regex-based engineering entity extraction.
- `backend/app/services/reasoning/engine.py`: station graph builder and rule modules.
- `backend/app/services/reasoning/normalizer.py`: stable finding IDs, deduplication, confidence-based status.
- `backend/app/services/exports.py`: marked PDF, CSV, Excel, JSON, Markdown, and HTML outputs.
- `backend/app/services/ai_service.py`: conservative AI provider abstraction for future evidence-backed enrichment.

## Frontend

The React UI is intentionally operational: project list and upload controls on the left, sheet image review in the center, and finding review/export controls on the right. It works against the FastAPI API and uses rendered sheet PNGs rather than requiring browser PDF plugins.

## Storage

By default, all generated artifacts live under `data/`:

- `data/autoqc.sqlite`
- `data/projects/<project-id>/input/source.pdf`
- `data/projects/<project-id>/sheets/page_###.png`
- `data/projects/<project-id>/exports/<export-id>/marked_review.pdf`
- `data/projects/<project-id>/exports/<export-id>/qc_log.csv`
- `data/projects/<project-id>/exports/<export-id>/qc_log.xlsx`
- `data/projects/<project-id>/exports/<export-id>/findings.json`
- `data/projects/<project-id>/exports/<export-id>/review_summary.md`

Set `AUTOQC_DATA_DIR` or `AUTOQC_DB_PATH` to move local storage.
