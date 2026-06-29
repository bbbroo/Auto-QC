# AutoQC - Natural Gas Drawing Markup Assistant

AutoQC is a local-first review workflow app for natural gas drawing packages. It uploads and processes PDF drawing sets, extracts sheet/page context, generates a copy/paste Chat Prompt for ChatGPT or Copilot Chat, imports AI-generated drawing update JSON, converts those updates into review findings, and exports a marked PDF plus structured review files.

AutoQC is currently designed as an **AI-only review item workflow**. The app does not create its own rule-based QC comments for the user to review. PDF extraction, sheet metadata, page images, and entity extraction are used to support prompting, review organization, and markup export. The review items shown in the app should come from AI-generated updates imported through the manual Chat Prompt workflow or direct AI review workflow.

AutoQC is not a sealed engineering authority. It is a markup and workflow aid. Final issue judgment remains with the responsible reviewer/engineer.

## What Is Included

- FastAPI backend with SQLite persistence
- React TypeScript review UI
- Local PDF upload, storage, rendering, and source PDF access
- PyMuPDF PDF text extraction, page rendering, and annotation export
- Optional OCR fallback when `pytesseract` is available locally
- Sheet classification and title block extraction for project context
- Entity extraction for tags, line numbers, references, notes, and revisions
- AI-only findings workflow
- Manual Chat Prompt bridge for ChatGPT or Copilot Chat without API keys
- Optional OpenAI-compatible API review path when configured
- AI import preview before findings are created
- AI prompt template/version manager and import batch history
- Robust AI response import for common ChatGPT/Copilot JSON issues
- Explicit AI JSON schema/parser mode reporting for common wrapper shapes
- Editable finding review workflow with expanded reviewer statuses
- Duplicate/merge tools that preserve original AI evidence and hide duplicates from normal exports
- Markup placement status for exact, fuzzy, page-level, and manual-placement cases
- Audit events for review actions, reruns, imports, exports, and bulk updates
- Full in-app audit log, compact dashboard, readiness/system check, and first-run help guide
- Guided review workflow with next-step status, recovery cards, and long-operation progress messages
- Project package backup/restore with safe local source/export file copies
- Marked PDF, QA register CSV, XLSX, JSON, HTML, and Markdown summary exports
- Marked PDF export validation by reopening generated PDFs with PyMuPDF
- Synthetic sample PDF and backend regression tests

## Current Product Workflow

```text
Upload PDF drawing package
-> AutoQC extracts sheets/pages and project context
-> Choose a prompt template and click Chat Prompt
-> Attach/upload the actual PDF package to ChatGPT or Copilot Chat
-> Paste the generated prompt into ChatGPT/Copilot
-> ChatGPT/Copilot returns update JSON
-> Paste the update JSON into AutoQC
-> Preview AI Updates
-> Import Valid Updates
-> Review, edit, accept, reject, defer, or escalate findings
-> Check placement status
-> Export marked PDF and QA report
```

The generated Chat Prompt intentionally contains mostly instructions and response schema. It requires the actual PDF package to be attached/uploaded to ChatGPT or Copilot Chat. The prompt should not be treated as the drawing source of truth by itself.

By default, the manual Chat Prompt includes only project metadata and a lightweight sheet index: page number, drawing number, title, revision, and sheet type. It does not include extracted sheet body text, OCR text, entity samples, or existing finding text. If the Advanced Markup Memory feature is explicitly enabled, a bounded historical guidance section may be added; the attached PDF is still the drawing evidence.

## AI-Only Review Behavior

AutoQC currently enforces the following direction:

- Uploading or processing a PDF creates sheets/pages and metadata, but zero app-generated QC findings.
- The findings endpoint returns AI-sourced findings only.
- Project finding counts are based on AI findings only.
- Marked PDF exports include AI findings only.
- Old rule-generated findings are filtered from the active review workflow and cannot be edited, bulk-updated, deleted, counted, or exported through active review routes.
- The app still keeps extraction, page images, source PDF access, and export support.

This means a newly uploaded project may show no findings until AI update JSON is imported.

AutoQC also tracks review coverage separately from findings. A page with imported updates does not count as reviewed unless the AI response includes that page in `reviewed_pages` with `review_status: "complete"`. Pages with no updates can be recorded as reviewed clean only through the same `reviewed_pages` confirmation.

## Quick Start

### Option 1: Windows launcher

From the repo root, run:

```powershell
.\Run AutoQC.bat
```

The launcher creates/uses the Python virtual environment, installs backend requirements, installs frontend dependencies if needed, starts the backend and frontend, and opens the app in the browser.

### Option 2: Manual setup

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

Open:

```text
http://127.0.0.1:5173
```

### Company-use readiness check

Run the local doctor before a company/demo use session:

```powershell
python scripts/doctor.py
```

For a deeper local check that also runs backend tests and frontend build checks:

```powershell
python scripts/doctor.py --full
```

The doctor is a pre-start check: it expects the default backend/frontend ports to be free before launch. The in-app System Check uses `/readiness` for running-app health and does not warn just because ports 8000/5173 are already occupied by AutoQC.

## Reviewer efficiency

The Review panel includes a `What should I do next?` guide that walks through upload, prompt generation, external PDF-attached AI review, JSON preview/import, reviewer disposition, placement cleanup, draft export, and final export. The `Recovery Center` shows the most important active blocker or recovery action, such as incomplete preview coverage, failed import batches, missing source PDF, manual-placement blockers, or final export readiness failures.

Long-running or high-risk actions such as upload/extraction, prompt generation, preview, import, placement recalculation, package restore, Direct AI Review, and export show step-by-step progress messages. These messages are status indicators only; the underlying gates still come from backend validation, coverage metadata, placement status, and export validation.

The findings panel includes a review queue, placement-quality filters, and keyboard shortcuts for faster review:

- `A`: accept selected finding
- `X`: reject selected finding
- `R`: return selected finding to needs review
- `J` / `K`: next / previous finding
- `N`: next unreviewed finding
- `[` / `]`: previous / next sheet

Auto-advance can be toggled in the findings panel. When enabled, accepting or rejecting a finding selects the next needs-review finding.

## Manual Chat Prompt Workflow

1. Upload a drawing package PDF.
2. Let AutoQC extract sheets and page context.
3. Choose a prompt template and click `Chat Prompt`.
4. Copy the generated prompt.
5. Open ChatGPT or Copilot Chat.
6. Attach/upload the same drawing package PDF to the chat.
7. Paste the prompt.
8. Ask ChatGPT/Copilot to return only the JSON response.
9. Copy the returned JSON.
10. Paste it into `Paste AI update JSON` in AutoQC.
11. Click `Preview AI Updates`.
12. Review parsed updates, warnings, repairs, duplicates, and create/update actions.
13. Click `Import Valid Updates`.
14. Review, edit, accept, reject, mark duplicate, merge, defer, or escalate the imported AI findings.
15. Check placement status after export.
16. Export the marked PDF and QA report.

The app shows a success message such as:

```text
Imported 16 AI updates.
```

After import, AutoQC selects an imported AI finding and shows it in the review workflow.

## AI Import Preview

Pasted ChatGPT/Copilot output is previewed before it becomes findings. The preview reports:

- expected review pages, confirmed reviewed pages, missing pages, incomplete pages, not-readable pages, coverage status, and coverage percent
- total candidate updates found
- valid recoverable updates
- skipped updates
- schema version and parser mode
- parser repairs applied
- warnings and missing/weak fields
- exact duplicates, likely duplicates, same-page/similar-target updates, and same-page/same-title updates
- whether each update will create a new finding or update an existing stable-ID match
- normalized page number, target text, required update, rationale, category, severity, and confidence

If zero updates are importable, AutoQC can still preview the response. Import is blocked unless review coverage is complete, or it records a clean-page confirmation when the AI reviewed every expected page and found no updates.
Updates with missing or blank `target_text` are rejected during preview with a user-facing reason. AutoQC only imports updates that cite usable drawing text anchors, so it does not create confusing page-only findings from vague AI output.

## Required AI Response Schema

ChatGPT or Copilot should return a JSON object with an `updates` array:

```json
{
  "schema_version": "autoqc-ai-updates-v1",
  "reviewed_pages": [
    { "page_number": 1, "review_status": "complete", "issue_count": 1 }
  ],
  "updates": [
    {
      "issue": "Spill response plan appears misspelled as pill response plan.",
      "severity": "Major",
      "category": "safety and operability",
      "page_number": 4,
      "target_text": "APPROVED PILL RESPONSE PLAN",
      "required_update": "Revise to APPROVED SPILL RESPONSE PLAN unless PILL is an intentional defined project term.",
      "rationale": "The note appears to address spill controls, and the current wording changes the meaning of the requirement.",
      "confidence": 0.94
    }
  ]
}
```

Supported severity values:

```text
Critical, Major, Minor, Note
```

Common category values include:

```text
drafting quality
drawing coordination
title block and revision
notes and specifications
instrumentation
overpressure protection
safety and operability
regulator station design
missing information
human review needed
```

`target_text` must be exact text from the PDF. AutoQC uses it as the searchable markup anchor when creating PDF annotations.

## AI Import Robustness

The importer accepts strict JSON and also tries to recover common ChatGPT/Copilot formatting issues:

- markdown code fences
- extra prose before or after JSON
- smart quotes
- trailing commas
- `page`, `page_no`, `pdf_page`, `pageNumber`, and similar page aliases
- page strings such as `Page 4`
- unescaped inch marks such as `12" Inlet Valve`
- unescaped quoted correction text such as `Revise "CONTINTUED" to "CONTINUED"`
- multiple malformed update objects in one `updates` array

If no updates are importable, the app returns a visible error instead of silently doing nothing. Very large pasted responses are rejected before parsing.

## How AI Updates Become Markups

Each imported update becomes an AutoQC finding with:

- `source = "ai"`
- page number
- severity
- category
- confidence
- rationale/reasoning summary
- suggested correction / required update
- evidence based on `target_text`
- generated markup-ready comment text
- original AI response fields preserved for audit/debugging
- AI import batch ID and prompt version when available

ChatGPT/Copilot provides the update needed. AutoQC turns that update into the final finding/comment structure used by the UI and export pipeline.

Imported AI findings default to `needs_review`. A reviewer should accept, reject, edit, defer, mark duplicate, request engineer input, or mark manual placement before issuing a marked PDF.

Reviewer-editable fields include final PDF comment, required update, rationale, category, severity, page number, target text/evidence, status, confidence, and reviewer note. The original AI payload is retained separately so reviewers can audit what the AI originally returned.

When exact coordinates are unavailable, the marked PDF exporter searches the page for the finding's `target_text`. If found, it places the annotation near that text. If the text cannot be found, the exporter should not crash; the finding remains available for review/manual placement handling.

Placement statuses:

- `exact_target_found`: target/location was found and annotated directly.
- `fuzzy_target_found`: a reasonable shortened/normalized target match was found.
- `page_level_fallback`: target text was not found, so AutoQC added a page-level note.
- `manual_placement`: the reviewer placed a rectangle on the drawing image; that saved location drives future display/export.
- `manual_placement_needed`: no valid target/page placement was available; manual placement is required.

The UI labels these as `Placed`, `Fuzzy placed`, `Page note`, `Manually placed`, and `Needs manual placement`.

## Prompt Versioning and Import History

Generated Chat Prompts include a prompt template, prompt version such as `autoqc-chat-prompt-v4-exhaustive-manual`, prompt ID, generated timestamp, and metadata confirming that the manual prompt includes only sheet metadata rather than full extracted sheet text.

Built-in production prompt templates now default to Exhaustive Manual-Style Review behavior. The default/deep/comprehensive templates instruct ChatGPT/Copilot to review every visible sheet with the same baseline method: extracted page-text review plus rendered sheet-image inspection. They explicitly forbid triage, sampling, skimming, high-risk-only review, and partial findings when the full package cannot be completed.

The app still exposes intentionally lighter focused or smoke-test templates, but they are labeled as non-production shortcuts so they are not confused with the exhaustive manual prompt. Templates are stored locally in `data/prompt_templates.json`; built-in template IDs are refreshed from the canonical definitions so stale local v1/v2/v3 template text does not override the current exhaustive behavior.

Generated prompts include the hard no-triage rule, the incomplete-review rule, the required `autoqc-ai-updates-v1` JSON schema, and an AI response self-check section. If ChatGPT/Copilot cannot complete the full sheet-by-sheet review, the prompt tells it to return the incomplete-review JSON error instead of partial findings. The attached PDF remains the drawing source of truth; sheet index, parser output, OCR status, and UNKNOWN metadata are navigation only and must not become drawing updates.

Each AI import preview/import creates an import batch record with source type, prompt/template version, AI tool/provider/model provenance when known, exact raw pasted response stored server-side, parser mode/schema version, parser warnings/repairs, candidate/valid/skipped counts, created/updated/duplicate counts, coverage summary, and import status. Normal UI/API batch lists expose only a raw-response stored flag, character count, and SHA-256 hash, not the full pasted response. The Import Quality Report shows parsed/importable/imported/skipped counts, duplicate count, missing page/target counts, exact/fuzzy/page-level/manual-placement counts, low-confidence count, and warnings/errors. The UI shows recent AI import batches for the selected project and can remove findings created by a selected imported batch after confirmation.

The findings panel includes a Finding Quality/Placement dashboard for exact placed, fuzzy placed, page-level, manual placement needed, low confidence, accepted, needs review, and duplicate/merged groups. These groups organize imported AI findings; they do not create findings.

## Checklist Tracker

AutoQC includes a checklist coverage tracker for client/package review organization, starting with an Xcel Engineering Package QC Checklist-style template. Checklist items track coverage and can link to existing AI findings. They do not create drawing findings, do not infer issues, and do not replace the attached PDF or reviewer judgment.

Checklist item statuses are:

- Not started
- Checked
- Issue found
- Not applicable
- Needs human review

The checklist UI lets reviewers select a project checklist, filter sections such as All Sheets, Cover Sheet, Index, General Notes, Regulator Characteristics, PFD, P&ID, Civil/Structural, Civil Site, Demo, Mechanical Plan, Piping Sections/Details, Isometric, Heat Number/MTR, Weld/NDE, Bolt Torque, BOM, and Environmental, update statuses, add reviewer notes, link existing findings, and see completion progress. Checklist completion is included in export summaries when a checklist is selected.

## Backup, Restore, and Rollback

Use `Export Project Package` in the Projects panel to create a portable AutoQC zip archive. The package includes project metadata, sheet metadata, imported AI findings and reviewer edits/statuses, AI prompt/import history, audit events, export records, safe local source PDF copy when available, rendered sheet images, and generated export files. Package `project.json` strips local absolute file paths for source PDFs, sheet images, and export artifacts; restore rebuilds local paths from the package file manifest.

Use `Import Project Package` to restore a package. AutoQC runs a dry-run validation first: zip readability, schema and required JSON, safe paths, allowed file extensions, uncompressed size/file-count limits, source PDF readability, image readability, payload shape, and checksums when present. If restore fails after file copying starts, AutoQC removes the newly-created project directory and partial project row where practical. AutoQC does not overwrite an existing project by default; if the original project ID already exists, the restore is remapped to new IDs consistently. Older packages with missing optional collections are accepted with compatibility warnings; unsupported schema versions fail with a clear message.

Use `Remove imported batch` in AI Import History to roll back findings created by a specific AI import batch. The confirmation states how many findings will be removed and how many reviewed/edited findings are affected. Updated pre-existing findings and unrelated findings are not deleted.

## Optional Direct AI API Configuration

The primary workflow works without API keys by using ChatGPT or Copilot Chat manually.

An optional OpenAI-compatible API path can be configured with:

```powershell
$env:AUTOQC_AI_PROVIDER = "openai"
$env:AUTOQC_AI_MODEL = "your-model"
$env:AUTOQC_AI_API_KEY = "your-key"
$env:AUTOQC_AI_BASE_URL = "https://api.openai.com/v1/chat/completions"
```

This path is optional and experimental. Direct AI Review currently sends extracted text/context only, is labeled `direct_review_mode: text_context_only`, and is not equivalent to the manual Chat Prompt workflow where the actual PDF is attached to ChatGPT/Copilot. It uses the same preview/import coverage and quality gates. If `AUTOQC_AI_MAX_SHEETS` caps the submitted sheets, the result is treated as a partial batch over the sent pages and cannot complete whole-package coverage by itself.

The optional direct API path is separate from the manual Chat Prompt workflow and may send extracted sheet text to the configured AI endpoint. The manual Chat Prompt workflow intentionally requires the uploaded PDF and does not dump sheet body text into the prompt.

## Advanced Feature: Markup Memory

Markup Memory is an experimental power-user feature under `Advanced Features`, available from the Help dialog rather than the primary workflow rail. When enabled, AutoQC stores local examples from reviewed findings so future Chat Prompts can include bounded reviewer guidance.

What it can learn from:

- accepted findings
- edited final wording
- rejected false positives
- duplicate/merged findings
- deferred or engineer-input outcomes
- manual-placement outcomes
- exported markups

What it does:

- improves future Chat Prompt context with examples to emulate and examples to avoid
- preserves reviewer wording preferences and common false-positive patterns
- helps remind ChatGPT/Copilot what past reviewers accepted, rejected, or corrected
- lets advanced users preview exactly what memory text would be injected into the next prompt

What it does not do:

- it does not train or fine-tune a model
- it does not create automatic findings by itself
- it does not prove that a past issue exists in the current package
- it does not replace attaching the actual drawing PDF to ChatGPT/Copilot
- it does not send past examples anywhere by itself

Memory is local: Markup Memory is stored in AutoQC's local SQLite database. Past examples only appear in generated prompts when Advanced Features, Markup Memory, and prompt inclusion are explicitly enabled. Current-project examples are excluded by default so regenerating a prompt for the same drawing package does not over-bias the AI with already-reviewed findings.

Markup Memory is off by default. To use it, open Help, choose `Advanced Features`, enable Advanced Features, enable Markup Memory, and enable inclusion in generated prompts. The generated prompt explicitly states that past examples are guidance only and that the attached PDF remains the source of truth.

## Try the Sample

In the UI, click `Sample Package`. The backend generates a synthetic regulator station drawing package and processes it for sheets/page context.

Because the app is now AI-only for review findings, opening or processing the sample does not create user-facing rule-based findings. Use `Chat Prompt`, attach the sample PDF to ChatGPT/Copilot, preview the returned update JSON, import valid updates, and then export the marked PDF.

CLI sample helpers:

```powershell
python scripts/make_sample_pdf.py
python scripts/run_sample_review.py
python scripts/smoke_ai_workflow.py
python scripts/stress_large_package.py
```

Some legacy sample scripts may still mention review rules. Treat the active UI workflow as AI-only.
`scripts/run_sample_review.py` processes the sample package shell only; it skips export until AI updates have been imported. `scripts/smoke_ai_workflow.py` runs a complete local smoke path with synthetic AI JSON import and marked PDF export.

## Exports

The Export panel has two modes:

- `Draft`: lets reviewers include selected statuses such as `needs_review`, `deferred`, `needs_engineer_input`, and placement warnings. Draft outputs are intended for working review packages and use draft-labeled filenames/summaries.
- `Final`: accepted findings only, complete review coverage required, manual-placement blockers rejected, generated PDF validation must pass or warnings must be explicitly acknowledged, and reviewer signoff metadata is required.

Generated files are under:

```text
data/projects/<project-id>/exports/<export-id>/
```

Typical export outputs include:

- marked PDF
- QA register CSV
- XLSX findings list
- JSON findings data
- HTML review packet
- Markdown summary

Final exports include export validation details, review coverage summary, and reviewer signoff summary in the response and summary files. Final exports do not support a coverage override in the pilot workflow; missing coverage must be resolved by importing valid `reviewed_pages` confirmations.

The marked PDF uses standard PDF text annotations, so it opens in Bluebeam and common PDF viewers without Bluebeam-specific APIs. AutoQC does not claim to create proprietary Bluebeam Cloud+ markups. Exact Bluebeam Cloud+ output should only be added if AutoQC integrates a verified Bluebeam-compatible/proprietary markup writer rather than approximating Cloud+ with separate cloud, line, and text-box annotations.

Exports include AI-sourced findings only.
Empty exports are blocked. Select at least one status that has imported AI findings before generating a package.
After a marked PDF is generated, AutoQC reopens it with PyMuPDF and reports validation status in the Export panel:

- `Passed`: file exists, page count matches, and annotations are present for the selected findings.
- `Warning`: export completed but placement/manual-review warnings remain.
- `Failed`: generated PDF could not be reopened or critical validation failed.

The QA register includes finding ID, page number, drawing number/sheet identifier, category, severity, reviewer status, AI source/batch/prompt version, target text/evidence, required update, rationale, final exported comment, placement status, target-found flag, exported flag, manual-placement flag, reviewer note, confidence, and timestamps.

Browser-accessible generated files are limited to rendered sheet images and export outputs under each project. Uploaded source PDFs are served through the project source PDF endpoint rather than the generic `/data` path.

## Run Tests

```powershell
pytest
cd frontend
npm run typecheck
npm run build
npm test
```

The backend tests cover:

- PDF ingestion and sheet extraction
- AI-only processing behavior
- manual Chat Prompt generation
- AI update import
- AI import preview and confirm/import workflow
- AI import batch history and prompt metadata
- malformed ChatGPT/Copilot JSON recovery
- multiple imported AI updates
- page aliases and page strings
- finding deduplication and review-status preservation
- editable AI finding fields
- AI-only finding filtering
- invalid ID and safe file-serving behavior
- AI preview rejection for missing target text and stale preview imports
- import quality report counting
- strict review coverage gates and clean-page confirmation
- direct AI text-only labeling and coverage blocking
- draft/final export readiness gates and signoff metadata
- project package import dry-run validation
- running-app readiness without false port warnings
- legacy project/package compatibility defaults
- raw AI response preservation with public API redaction
- manual placement persistence
- checklist tracker selection, progress, and existing-finding links
- export safety for bad/missing annotation rectangles
- empty export prevention
- marked PDF export behavior, placement statuses, and QA report output

The frontend test script runs Playwright against isolated local ports and data storage. It does not require external API keys.

Additional local workflow scripts:

```powershell
python scripts/smoke_ai_workflow.py
python scripts/stress_large_package.py
python scripts/regression_real_pdfs.py
```

Each validation script writes a JSON and Markdown report under `data/validation_reports/` with tested checks, pass/fail status, workflow metrics, and generated artifact references. These reports are local generated artifacts and are not intended to be committed.

`regression_real_pdfs.py` uses PDFs under `examples/` when present and checks workflow mechanics only: upload/extraction, images, source PDF endpoint, prompt scope, coverage gates, representative AI JSON import, placement recalculation, draft export, final export readiness/signoff behavior, and PDF reopen validation. It does not assert engineering finding conclusions.

## Current Engineering Review Limits

AutoQC helps create, organize, review, and export drawing comments. It does not prove the engineering correctness of AI-generated findings.

Human review is still required for:

- final technical validity of every AI finding
- natural gas code/company-standard interpretation
- safety and operability judgment
- overpressure protection decisions
- instrumentation and SCADA coordination
- construction feasibility
- whether a suspected typo or discrepancy is intentional
- whether a finding should be accepted, edited, rejected, or escalated

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Rule Engine](docs/RULES.md)
- [Sample Scenarios](docs/SAMPLE_SCENARIOS.md)

Some docs may still describe the earlier deterministic rule engine. The current product direction is AI-only for user-facing review findings.

## Notes

AutoQC is a serious workflow foundation for natural gas drawing package review. Its current value is in PDF handling, prompt generation, AI update import, review tracking, and marked PDF export. It should be used as a reviewer-controlled markup assistant, not as an autonomous engineering authority.
