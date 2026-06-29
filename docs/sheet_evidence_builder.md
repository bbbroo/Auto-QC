# AutoQC Sheet Evidence Builder

The Sheet Evidence Builder is an internal backend workflow that converts benchmark-informed local PDF extraction into page-level evidence packets for AutoQC prompt context.

It currently uses the latest extraction benchmark to select a practical strategy. In the latest analyzed run, pdfplumber provided the strongest text, layout, table/title-block, and engineering-token signal, while PyMuPDF remains the rendering and markup compatibility baseline.

The workflow is:

```text
PDF package
-> page rendering and extraction
-> benchmark-informed extractor selection
-> structured sheet evidence packets
-> compact prompt context
-> existing JSON import and PDF markup workflow
```

This is intentionally not user-facing yet. It does not add benchmark UI, expose raw benchmark results, replace production extraction, require cloud services, require API keys, or send PDF content outside the local machine.

Run the end-to-end internal command:

```powershell
python -m backend.sheet_evidence.autopilot --pdf-dir examples --use-latest-benchmark --mode quick
```

Use `--full` to process every page, or `--no-benchmark-required` to use the PyMuPDF fallback if no benchmark exists.

## Full Example Validation

The deferred full-package validation over both example PDFs was completed on 2026-06-29:

```powershell
python -m backend.sheet_evidence.autopilot --pdf-dir examples --use-latest-benchmark --full --generate-enhanced-prompts --pages-per-batch 10 --run-id full_examples_hardening
```

Recorded result:

- Evidence output: `.local/autoqc_sheet_evidence/full_examples_hardening`
- Benchmark run analyzed: `.local/autoqc_extraction_benchmark/20260628_200852`
- Strategy: pdfplumber for text/layout/table evidence, PyMuPDF for rendering and markup compatibility
- Packet coverage: 220/220 pages
- `20250508_Alliant Sheboygan Skid Upgrade_IFC.pdf`: 123/123 pages
- `Nicor STA 147_020223.pdf`: 97/97 pages
- Failed pages: none
- Enhanced prompt batches: 22, with 10 pages per batch
- Validation status: passed
- Fallback behavior: PyMuPDF fallback strategy remained available from the benchmark recommendation, but no page failures were recorded in this run

Enhanced prompt batches now require the same app importer contract as normal Chat Prompts: `schema_version: "autoqc-ai-updates-v1"`, complete `reviewed_pages` entries for every scoped page, and updates with `page_number`, `target_text`, `issue`, `severity`, `category`, `required_update`, `rationale`, and numeric `confidence`.

Manual prompt integration is gated by:

```powershell
AUTOQC_USE_SHEET_EVIDENCE=true
```

When enabled, prompt generation attempts to build/load supporting sheet evidence. If evidence generation fails, the existing manual prompt still works and records the failure in prompt metadata. The attached PDF remains the source of truth in every generated context.

The app integration is still conservative: it is disabled by default, uses the fast PyMuPDF-only extraction strategy during prompt generation, and caps evidence context with `AUTOQC_SHEET_EVIDENCE_PROMPT_MAX_PAGES` for responsiveness. If the cap omits scoped pages, prompt metadata records a warning; the reviewer must still attach and review the full PDF scope.
