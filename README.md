# Natural Gas Engineering Copilot

A local-first engineering QC copilot for natural gas regulator station PDF drawing packages. It ingests PDFs, renders sheets, extracts text and tags, runs evidence-backed regulator station review rules, lets a reviewer edit/accept/reject findings, and exports a Bluebeam-compatible marked-up PDF plus CSV, Excel, JSON, and review summaries.

## What Is Included

- FastAPI backend with SQLite persistence
- React TypeScript review UI
- PyMuPDF PDF text extraction, rendering, and annotation export
- Optional OCR fallback when `pytesseract` is available locally
- Sheet classification and title block extraction
- Entity extraction for tags, line numbers, references, notes, and revisions
- Regulator station reasoning engine with structured evidence
- PFD/P&ID coordination checks
- Operability, OPP, instrumentation, drafting, and revision checks
- Editable finding review workflow
- Marked PDF, CSV, XLSX, JSON, and Markdown summary exports
- Synthetic sample PDF and scenario tests

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install --prefix frontend
```

Start both servers:

```powershell
.\scripts\dev.ps1
```

Or run them in separate terminals:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`.

## Try the Sample

In the UI, click `Open Sample`. The backend generates a synthetic regulator station drawing set, processes it, runs the review, and opens the findings.

CLI sample workflow:

```powershell
python scripts/make_sample_pdf.py
python scripts/run_sample_review.py
```

## Run Tests

```powershell
pytest
```

The tests cover sheet classification, entity extraction, reasoning scenarios, PDF ingestion, PDF annotation export, and finding deduplication.

## Exports

From the UI, choose which finding statuses to export and click the download button in the Export panel. Generated files are under:

```text
data/projects/<project-id>/exports/<export-id>/
```

The marked PDF uses standard PDF annotations, so it opens in Bluebeam and common PDF viewers without Bluebeam-specific APIs.

## AI Configuration

The app works without AI keys. Deterministic rules are the default and are fully testable.

The backend includes a conservative AI service abstraction for future structured enrichment:

```powershell
$env:AUTOQC_AI_PROVIDER = "openai"
$env:AUTOQC_AI_MODEL = "your-model"
$env:AUTOQC_AI_API_KEY = "your-key"
```

AI output must be converted to structured evidence-backed findings before it can enter the review database.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Rule Engine](docs/RULES.md)
- [Sample Scenarios](docs/SAMPLE_SCENARIOS.md)

## Notes

This is a serious foundation, not a sealed engineering authority. It is designed to accelerate first-pass drawing QC and keep final issue control with the reviewer.
