from __future__ import annotations

# ---------------------------------------------------------------------------
# Status: Full example-package validation complete as of 2026-06-29.
#
# The Sheet Evidence Builder hardening appears implemented and passed
# targeted/full test suites plus a full two-PDF autopilot run.
#
# Completed validation command:
#
#   python -m backend.sheet_evidence.autopilot \
#       --pdf-dir examples \
#       --use-latest-benchmark \
#       --full \
#       --generate-enhanced-prompts \
#       --pages-per-batch 10 \
#       --run-id full_examples_hardening
#
# Validation result:
# - Alliant Sheboygan: 123/123 pages processed
# - Nicor STA 147: 97/97 pages processed
# - Total: 220 evidence JSON files
# - Enhanced prompt batches: 22
# - No missing page prompt contexts
# - Failed pages: none
# - Validation passes
# - compileall, targeted tests, and full pytest pass
# ---------------------------------------------------------------------------

import argparse
from pathlib import Path
from typing import Any

from backend.sheet_evidence.builder import DEFAULT_OUTPUT_ROOT, SheetEvidenceBuilder
from backend.sheet_evidence.cache import write_json
from backend.sheet_evidence.prompt_context import DEFAULT_BATCH_SIZE, DEFAULT_MAX_PROMPT_CHARS, generate_enhanced_prompt_batches
from backend.sheet_evidence.recommendation import DEFAULT_BENCHMARK_ROOT, analyze_benchmark_run, find_latest_benchmark_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark-informed AutoQC Sheet Evidence Builder autopilot.")
    parser.add_argument("--pdf-dir", default="examples", help="Directory of PDFs to process when --pdf is not supplied.")
    parser.add_argument("--pdf", action="append", default=[], help="Specific PDF path to process. Can be passed multiple times.")
    parser.add_argument("--use-latest-benchmark", action="store_true", default=True, help="Analyze latest extraction benchmark run before building evidence.")
    parser.add_argument("--no-benchmark-required", action="store_true", help="Use PyMuPDF fallback recommendation if no benchmark exists.")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick", help="Evidence page mode. Defaults to quick for fast internal iteration.")
    parser.add_argument("--full", action="store_true", help="Process all pages.")
    parser.add_argument("--pages", default="", help="Optional comma-separated page list/ranges, e.g. 1,3,5-8. Applied to each selected PDF.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_ROOT), help="Evidence output root directory.")
    parser.add_argument("--run-id", default=None, help="Optional stable run id for resumable processing into an existing output folder.")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum pages per PDF to process.")
    parser.add_argument("--force", action="store_true", help="Reserved for cache invalidation; current builder writes/reuses the selected run directory by run id.")
    parser.add_argument("--generate-enhanced-prompts", action="store_true", help="Generate page-batched enhanced prompt markdown files under enhanced_prompts/.")
    parser.add_argument("--pages-per-batch", type=int, default=DEFAULT_BATCH_SIZE, help="Pages per enhanced prompt batch. Defaults to 10 for large packages.")
    parser.add_argument("--max-prompt-chars", type=int, default=DEFAULT_MAX_PROMPT_CHARS, help="Maximum characters per enhanced prompt batch before trimming support evidence.")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_autopilot(args: argparse.Namespace) -> dict[str, Any]:
    mode = "full" if args.full else args.mode
    benchmark_run = find_latest_benchmark_run(DEFAULT_BENCHMARK_ROOT) if args.use_latest_benchmark else None
    recommendation = analyze_benchmark_run(benchmark_run, allow_fallback=bool(args.no_benchmark_required or benchmark_run))
    pdf_paths = resolve_pdf_paths(args.pdf, Path(args.pdf_dir))
    if not pdf_paths:
        raise ValueError(f"No PDFs found. Checked --pdf values and {Path(args.pdf_dir).resolve()}.")
    pages = parse_page_ranges(args.pages)
    builder = SheetEvidenceBuilder(recommendation=recommendation, output_root=Path(args.output))
    evidence = builder.build_pdfs(
        pdf_paths,
        mode=mode,
        pages=pages,
        max_pages=args.max_pages,
        force=args.force,
        run_id=args.run_id,
    )
    enhanced_prompt_batches = None
    if args.generate_enhanced_prompts:
        enhanced_prompt_batches = generate_enhanced_prompt_batches(
            evidence.get("packets") or [],
            Path(evidence["run_dir"]) / "enhanced_prompts",
            pages_per_batch=args.pages_per_batch,
            max_prompt_chars=args.max_prompt_chars,
        )
        evidence["enhanced_prompt_batches"] = enhanced_prompt_batches
        summary_path = Path(evidence["run_dir"]) / "evidence_build_summary.json"
        write_json(summary_path, {key: value for key, value in evidence.items() if key != "packets"})
    final_summary = {
        "benchmark_run": str(benchmark_run) if benchmark_run else None,
        "recommendation": recommendation,
        "pdfs": [str(path) for path in pdf_paths],
        "mode": mode,
        "pages": pages,
        "max_pages": args.max_pages,
        "pages_per_batch": args.pages_per_batch,
        "max_prompt_chars": args.max_prompt_chars,
        "generate_enhanced_prompts": bool(args.generate_enhanced_prompts),
        "evidence_run_dir": evidence["run_dir"],
        "processed_page_count": evidence["processed_page_count"],
        "valid": evidence["valid"],
        "enhanced_prompt_preview": evidence["enhanced_prompt_preview"],
        "enhanced_prompt_batches": enhanced_prompt_batches,
        "pdf_results": evidence.get("pdf_results") or [],
        "validation_failures": [item for item in evidence["validation"] if not item.get("passed")],
    }
    return final_summary


def resolve_pdf_paths(explicit_paths: list[str], pdf_dir: Path) -> list[Path]:
    if explicit_paths:
        resolved = [Path(path).expanduser().resolve() for path in explicit_paths]
        missing = [str(path) for path in resolved if not path.is_file()]
        if missing:
            raise ValueError(f"PDF path(s) not found: {', '.join(missing)}")
        return resolved
    if not pdf_dir.exists():
        return []
    return sorted(path.resolve() for path in pdf_dir.glob("*.pdf"))


def parse_page_ranges(raw: str | None) -> list[int] | None:
    if not raw or not raw.strip():
        return None
    pages: list[int] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "-" in item:
            start_raw, end_raw = item.split("-", 1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
            if start <= 0 or end <= 0:
                raise ValueError("Page ranges must be positive integers.")
            low, high = sorted((start, end))
            pages.extend(range(low, high + 1))
        else:
            page = int(item)
            if page <= 0:
                raise ValueError("Page numbers must be positive integers.")
            pages.append(page)
    return list(dict.fromkeys(pages))


def print_summary(summary: dict[str, Any]) -> None:
    recommendation = summary.get("recommendation") or {}
    print("AutoQC Sheet Evidence autopilot complete")
    print(f"Benchmark run analyzed: {summary.get('benchmark_run') or 'fallback/no benchmark'}")
    print(f"Recommended strategy: {recommendation.get('recommended_strategy')}")
    print(f"Evidence output: {summary.get('evidence_run_dir')}")
    print(f"Processed pages: {summary.get('processed_page_count')}")
    for pdf_result in summary.get("pdf_results") or []:
        print(
            "  - "
            f"{Path(str(pdf_result.get('pdf_path'))).name}: "
            f"{pdf_result.get('processed_page_count')}/{pdf_result.get('page_count')} pages"
        )
    print(f"Enhanced prompt preview: {summary.get('enhanced_prompt_preview')}")
    batches = summary.get("enhanced_prompt_batches") or {}
    if batches:
        print(f"Enhanced prompt batches: {batches.get('batch_count')} at {batches.get('output_dir')}")
        print(f"Batch index: {batches.get('batch_index')}")
    print(f"Validation: {'passed' if summary.get('valid') else 'failed'}")
    failures = summary.get("validation_failures") or []
    for failure in failures[:10]:
        print(f"  - {failure.get('name')}: {failure.get('detail')}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = run_autopilot(args)
        print_summary(summary)
        return 0 if summary.get("valid") else 1
    except Exception as exc:
        print(f"AutoQC Sheet Evidence autopilot failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
