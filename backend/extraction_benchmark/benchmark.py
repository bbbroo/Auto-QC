from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend.extraction_benchmark.adapters import ADAPTER_CLASSES
from backend.extraction_benchmark.adapters.base import ExtractorAdapter, safe_name
from backend.extraction_benchmark.metrics import compute_metrics
from backend.extraction_benchmark.report import (
    aggregate_summary,
    environment_info,
    timestamp_for_run,
    write_csv,
    write_jsonl,
    write_markdown_report,
)
from backend.extraction_benchmark.sample_pages import PageSample, select_pages


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".local" / "autoqc_extraction_benchmark"
DEFAULT_EXAMPLES_DIR = PROJECT_ROOT / "examples"
DEFAULT_PDF_HINTS = (
    "Nicor STA 147_020223(3).pdf",
    "20250508_Alliant Sheboygan Skid Upgrade_IFC(2).pdf",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run internal AutoQC PDF extraction benchmark.")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick", help="Page sampling mode. Defaults to quick.")
    parser.add_argument("--pdf", action="append", default=[], help="PDF path to benchmark. Can be passed multiple times.")
    parser.add_argument("--extractors", default="", help="Comma-separated extractor names. Defaults to all registered extractors.")
    parser.add_argument("--pages", default="", help="Comma-separated 1-based page numbers. Overrides --mode sampling.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help="Benchmark output root directory.")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum pages per PDF after sampling.")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Timeout for a single extractor/page.")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_benchmark(
    args: argparse.Namespace,
    *,
    adapter_classes: tuple[type[ExtractorAdapter], ...] | list[type[ExtractorAdapter]] = ADAPTER_CLASSES,
) -> dict[str, Any]:
    pdf_paths = resolve_pdf_paths(args.pdf)
    if not pdf_paths:
        raise ValueError(f"No benchmark PDFs found. Checked explicit paths and {DEFAULT_EXAMPLES_DIR}.")

    extractors = instantiate_adapters(args.extractors, adapter_classes)
    explicit_pages = parse_page_list(args.pages)
    run_id = timestamp_for_run()
    run_dir = Path(args.output).expanduser().resolve() / run_id
    debug_dir = run_dir / "debug"
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    metrics_rows: list[dict[str, Any]] = []
    samples_by_pdf: dict[str, list[dict[str, Any]]] = {}

    for pdf_path in pdf_paths:
        samples = select_pages(
            pdf_path,
            mode=args.mode,
            explicit_pages=explicit_pages,
            max_pages=args.max_pages,
        )
        samples_by_pdf[pdf_path.name] = [_sample_to_dict(sample) for sample in samples]
        for adapter in extractors:
            for sample in samples:
                result = adapter.extract_page(
                    pdf_path=pdf_path,
                    page_number=sample.page_number,
                    output_dir=debug_dir,
                    timeout_seconds=max(1, int(args.timeout_seconds)),
                )
                result.setdefault("metadata", {})
                result["metadata"]["sample_reason"] = sample.reason
                result["metadata"]["sample_confidence"] = sample.confidence
                write_debug_outputs(result, debug_dir)
                metrics = compute_metrics(result)
                metrics["sample_reason"] = sample.reason
                metrics["sample_confidence"] = sample.confidence
                results.append(result)
                metrics_rows.append(metrics)

    summary_rows = aggregate_summary(metrics_rows)
    raw_jsonl = run_dir / "raw_normalized_results.jsonl"
    metrics_csv = run_dir / "metrics.csv"
    summary_csv = run_dir / "aggregate_summary.csv"
    report_md = run_dir / "report.md"

    write_jsonl(raw_jsonl, results)
    write_csv(metrics_csv, metrics_rows)
    write_csv(summary_csv, summary_rows)
    run_metadata = {
        "run_id": run_id,
        "run_timestamp": run_id,
        "mode": args.mode,
        "run_dir": str(run_dir),
        "pdfs": [str(path) for path in pdf_paths],
        "extractors": [adapter.tool_name for adapter in extractors],
        "samples": samples_by_pdf,
        "environment": environment_info(),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(run_metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(report_md, run_metadata=run_metadata, metrics_rows=metrics_rows, summary_rows=summary_rows)

    return {
        "run_dir": run_dir,
        "raw_jsonl": raw_jsonl,
        "metrics_csv": metrics_csv,
        "summary_csv": summary_csv,
        "report_md": report_md,
        "metrics": metrics_rows,
        "summary": summary_rows,
        "pdfs": pdf_paths,
        "extractors": [adapter.tool_name for adapter in extractors],
        "samples": samples_by_pdf,
    }


def resolve_pdf_paths(explicit_paths: list[str] | None = None) -> list[Path]:
    if explicit_paths:
        resolved = [Path(path).expanduser().resolve() for path in explicit_paths]
        missing = [str(path) for path in resolved if not path.exists()]
        if missing:
            raise ValueError(f"PDF path(s) not found: {', '.join(missing)}")
        return resolved

    candidates = sorted(DEFAULT_EXAMPLES_DIR.glob("*.pdf"))
    resolved: list[Path] = []
    for hint in DEFAULT_PDF_HINTS:
        match = _closest_pdf_match(hint, candidates)
        if match and match not in resolved:
            resolved.append(match.resolve())
    return resolved


def instantiate_adapters(
    extractor_names: str,
    adapter_classes: tuple[type[ExtractorAdapter], ...] | list[type[ExtractorAdapter]],
) -> list[ExtractorAdapter]:
    registry = {adapter_class.tool_name.lower(): adapter_class for adapter_class in adapter_classes}
    if extractor_names.strip():
        names = [name.strip().lower() for name in extractor_names.split(",") if name.strip()]
    else:
        names = list(registry.keys())
    unknown = [name for name in names if name not in registry]
    if unknown:
        raise ValueError(f"Unknown extractor(s): {', '.join(unknown)}. Available: {', '.join(sorted(registry))}")
    return [registry[name]() for name in names]


def parse_page_list(value: str) -> list[int] | None:
    if not value.strip():
        return None
    pages: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        page = int(raw)
        if page < 1:
            raise ValueError("--pages values must be 1-based positive integers")
        pages.append(page)
    return pages


def write_debug_outputs(result: dict[str, Any], debug_dir: Path) -> None:
    tool = safe_name(str(result.get("tool_name") or "unknown"))
    pdf_name = safe_name(Path(str(result.get("pdf_path") or "document")).stem)
    page_number = int(result.get("page_number") or 0)
    target_dir = debug_dir / tool / pdf_name
    target_dir.mkdir(parents=True, exist_ok=True)

    text = str(result.get("text") or "")
    if text.strip():
        (target_dir / f"page_{page_number:03d}.txt").write_text(text, encoding="utf-8", errors="replace")

    for index, table in enumerate(result.get("tables") or [], start=1):
        content = str(table.get("content") or "")
        if not content.strip():
            continue
        table_format = str(table.get("format") or "txt").lower().replace(".", "")
        extension = "txt" if table_format not in {"csv", "html", "md", "markdown", "json", "tsv"} else table_format
        (target_dir / f"page_{page_number:03d}_table_{index:02d}.{extension}").write_text(
            content,
            encoding="utf-8",
            errors="replace",
        )


def print_terminal_summary(result: dict[str, Any]) -> None:
    print("AutoQC extraction benchmark complete")
    print(f"Output: {result['run_dir']}")
    print("Resolved PDFs:")
    for path in result["pdfs"]:
        print(f"  - {path}")
    print(f"Extractors: {', '.join(result['extractors'])}")
    print("Aggregate:")
    for row in result["summary"]:
        print(
            "  - {tool} | {pdf} | reliability {reliability:.2f} | avg score {score:.2f}".format(
                tool=row.get("tool_name"),
                pdf=row.get("pdf_name"),
                reliability=float(row.get("reliability") or 0),
                score=float(row.get("average_heuristic_score") or 0),
            )
        )
    print(f"Report: {result['report_md']}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        result = run_benchmark(args)
        print_terminal_summary(result)
        return 0
    except Exception as exc:
        print(f"AutoQC extraction benchmark failed: {exc}")
        return 2


def _closest_pdf_match(hint: str, candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    normalized_hint = _normalize_name(hint)
    scored = []
    for candidate in candidates:
        normalized_candidate = _normalize_name(candidate.name)
        sequence_score = SequenceMatcher(None, normalized_hint, normalized_candidate).ratio()
        token_score = _token_overlap(normalized_hint, normalized_candidate)
        scored.append((sequence_score * 0.65 + token_score * 0.35, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    score, match = scored[0]
    return match if score >= 0.45 else None


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in value.replace("(2)", "").replace("(3)", " "))


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {token for token in left.split() if token}
    right_tokens = {token for token in right.split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _sample_to_dict(sample: PageSample) -> dict[str, Any]:
    return {"page_number": sample.page_number, "reason": sample.reason, "confidence": sample.confidence}


if __name__ == "__main__":
    raise SystemExit(main())
