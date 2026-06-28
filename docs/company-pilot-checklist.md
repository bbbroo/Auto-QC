# AutoQC Company Pilot Checklist

Use this checklist before and during a company pilot. AutoQC is a local workflow aid for natural gas drawing QC tracking; final engineering judgment remains with the responsible reviewer.

## Local Setup

- Confirm Python 3.11+ and Node.js LTS are installed.
- From repo root, run `python -m venv .venv`, activate it, and run `pip install -r requirements.txt`.
- Run `npm install --prefix frontend`.
- Start with `.\Run AutoQC.bat` or `.\scripts\dev.ps1`.

## Doctor Check

- Run `python scripts/doctor.py`.
- For deeper validation, run `python scripts/doctor.py --full`.
- Resolve failed checks for Python/backend health, database writability, data directory writability, source/export directories, and default port conflicts.
- In the app, open `System Check` and confirm the same readiness items are visible to a coworker.

## Sample Project Workflow

- Click `Sample Package`.
- Confirm sheets render and navigation works.
- Generate a Chat Prompt using the default prompt template.
- Import known-good AI JSON or use `python scripts/smoke_ai_workflow.py`.
- Review, accept, reject, edit, and export at least one finding.

## Real PDF Upload Workflow

- Upload a real company drawing package PDF.
- Confirm extracted sheet count and sheet titles/drawing numbers are plausible.
- Open the source PDF from AutoQC and confirm it is the same package used for review.

## ChatGPT/Copilot Manual Bridge

- Choose the appropriate prompt template.
- Generate `Chat Prompt`.
- Attach/upload the same PDF package in ChatGPT or Copilot Chat.
- Paste the prompt and request JSON only.
- Do not use the prompt alone as drawing evidence.

## Import JSON Checks

- Paste or import the returned JSON.
- Confirm schema version/parser mode appears in preview.
- Confirm valid/skipped counts make sense.
- Review exact and likely duplicate warnings.
- Confirm bad items without `page_number` or usable `target_text` are rejected.
- Import only after preview is acceptable.

## Finding Review Checks

- Select each imported AI finding.
- Confirm target text, final PDF comment, required update, rationale, category, severity, status, and reviewer note.
- Accept only findings the responsible reviewer agrees with.
- Reject or defer uncertain/non-actionable findings.
- Use `Mark as duplicate`, `Merge`, or `Hide duplicate from export` instead of deleting evidence.

## Placement Recalculation Checks

- Check placement chips: exact, fuzzy, page-level, manual.
- Click `Recalculate Location` after edits to target text/page number.
- Manually review any page-level or manual-placement findings before issuing a PDF.

## Marked PDF Export Checks

- Select export statuses intentionally.
- Confirm empty/no-op exports are blocked.
- Export the review package.
- Confirm Export validation shows Passed or acceptable Warning.
- Open generated CSV/XLSX/JSON/HTML/Markdown outputs if needed.

## Bluebeam/Adobe Open Check

- Open the marked PDF in Bluebeam and Adobe Acrobat/Reader.
- Confirm page count matches the source PDF.
- Confirm annotations/comments are visible and associated with expected pages.
- Spot-check exact/fuzzy/page-level placement against the source drawing.

## Backup / Export Project Package Check

- Click `Export Project Package`.
- Save the generated `.zip`.
- Import the package into a clean or existing AutoQC workspace.
- Confirm IDs are remapped when the original project already exists.
- Confirm sheets, imported AI findings, statuses/edits, import history, audit log, exports, source PDF copy, and generated reports are restored.

## Known Limitations

- AutoQC does not create internal rule-based QC findings for active review.
- AI findings depend on the quality of the ChatGPT/Copilot response and the attached PDF.
- The app cannot prove engineering correctness.
- Manual placement may still be needed for missing/fuzzy target text.
- Live direct-AI API behavior is optional and separate from the manual bridge.

## Data / Privacy Notes

- AutoQC stores project data locally under `data/`.
- Uploaded source PDFs are served only through the project source-PDF endpoint.
- Generic `/data` serving is limited to generated sheet images and export files.
- Manual ChatGPT/Copilot use sends the attached PDF to the selected external chat service; follow company data rules before uploading confidential drawings.
- Project package zips may contain source PDFs and export artifacts; handle them as company drawing records.
