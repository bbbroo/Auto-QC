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

Manual prompt integration is gated by:

```powershell
AUTOQC_USE_SHEET_EVIDENCE=true
```

When enabled, prompt generation attempts to build/load supporting sheet evidence. If evidence generation fails, the existing manual prompt still works and records the failure in prompt metadata. The attached PDF remains the source of truth in every generated context.

