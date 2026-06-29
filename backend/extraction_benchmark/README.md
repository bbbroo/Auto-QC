# AutoQC Extraction Benchmark

Internal backend-only experiment for comparing PDF/document extraction approaches on natural gas drawing packages.

This module does not replace the production extraction pipeline, does not modify projects/uploads/findings, and does not expose UI controls. It only reads PDFs and writes benchmark artifacts.

## Quick Start

From the repository root:

```powershell
python -m backend.extraction_benchmark.benchmark --mode quick
```

Full package run:

```powershell
python -m backend.extraction_benchmark.benchmark --mode full
```

Useful narrower runs:

```powershell
python -m backend.extraction_benchmark.benchmark --mode quick --extractors pymupdf,pdfplumber --max-pages 10
python -m backend.extraction_benchmark.benchmark --pdf "examples\Nicor STA 147_020223.pdf" --pages 1,2,5 --extractors pymupdf
python -m backend.extraction_benchmark.benchmark --mode full --timeout-seconds 180 --output .local\autoqc_extraction_benchmark
```

By default, output is written to:

```text
.local/autoqc_extraction_benchmark/<run_timestamp>/
```

Generated files:

- `raw_normalized_results.jsonl`: one normalized extractor/PDF/page result per line.
- `metrics.csv`: one metrics row per extractor/PDF/page.
- `aggregate_summary.csv`: one summary row per extractor/PDF.
- `report.md`: human-readable internal report.
- `debug/`: extracted text, tables, thumbnails, and extractor output files when available.

## Default Test PDFs

The benchmark looks in `examples/` for the closest matches to:

- `Nicor STA 147_020223(3).pdf`
- `20250508_Alliant Sheboygan Skid Upgrade_IFC(2).pdf`

The current repo examples resolve to:

- `examples/Nicor STA 147_020223.pdf`
- `examples/20250508_Alliant Sheboygan Skid Upgrade_IFC.pdf`

## Extractors

Implemented baseline adapters:

- `pymupdf`: text, text blocks with coordinates, image metadata, page dimensions, and debug thumbnails.
- `pdfplumber`: text, word-derived line blocks, object counts, and best-effort tables.
- `camelot`: table extraction only, using stream mode.

Optional experimental adapters:

- `mineru`
- `docling`
- `marker`
- `paddleocr`
- `surya`

Optional adapters are skipped when the package or command is unavailable. If installed but incompatible, they fail only their own extractor/page rows and the benchmark continues.

## Optional Dependencies

PyMuPDF is already part of the app requirements. To try the lightweight optional baselines:

```powershell
pip install -r requirements-extraction-benchmark.txt
```

The heavy tools are intentionally not required by AutoQC. Install them only in a local experiment environment and rerun with `--extractors` to keep runs focused.

## Scoring

The score is an internal heuristic from 0 to 100, weighted for AutoQC usefulness:

- 25% text completeness and non-empty extraction
- 20% coordinate/layout usefulness
- 20% table/title-block/revision-block detection
- 15% engineering drawing token detection
- 10% low garble/duplicate noise
- 10% runtime and reliability

Edit `SCORE_WEIGHTS` in `metrics.py` to tune the model.

## Boundary

This benchmark must not:

- Modify production review findings.
- Modify user uploads.
- Create PDF markups.
- Change the UI.
- Replace existing extraction code.
- Require API keys.
- Send documents to external services.
- Commit generated benchmark result files.

