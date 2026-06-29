# AutoQC Sheet Evidence Builder

Internal backend-only upgrade that turns benchmark-informed PDF extraction into compact evidence packets and prompt context.

The builder does not replace the production PDF processor, does not modify review findings, does not create markups, and does not expose benchmark results or controls in the UI.

## End-to-End Autopilot

From the repository root:

```powershell
python -m backend.sheet_evidence.autopilot --pdf-dir examples --use-latest-benchmark --mode quick
```

Full page evidence run:

```powershell
python -m backend.sheet_evidence.autopilot --pdf-dir examples --use-latest-benchmark --full
```

Fallback without a benchmark:

```powershell
python -m backend.sheet_evidence.autopilot --pdf-dir examples --no-benchmark-required --mode quick
```

## What It Produces

Each run writes to:

```text
.local/autoqc_sheet_evidence/<timestamp>/
```

For each PDF:

- `package_index.json`
- `pages/page_001.json`
- `prompt_context/page_001.md`
- `package_summary.md`
- `evidence_build_summary.json`

At the run root:

- `evidence_build_summary.json`
- `enhanced_prompt_preview.md`

## Recommendation Selection

The autopilot analyzes the latest `.local/autoqc_extraction_benchmark/<run>/` directory when available and writes:

```text
.local/autoqc_extraction_benchmark/<run>/recommendation.json
```

The recommendation chooses practical local extractors by benchmark reliability and metric category:

- primary text extractor
- primary coordinate/layout extractor
- primary table/title-block extractor
- rendering and markup tool
- fallback strategy

If a recommended optional extractor is missing or fails, the builder falls back to PyMuPDF for the affected page.

## Prompt Integration

The existing manual Chat Prompt flow remains unchanged by default.

Set this internal environment variable to include Sheet Evidence context when manual prompts are generated:

```powershell
$env:AUTOQC_USE_SHEET_EVIDENCE = "true"
```

The prompt context always warns that the attached PDF is the source of truth and the evidence is supporting navigation only.

