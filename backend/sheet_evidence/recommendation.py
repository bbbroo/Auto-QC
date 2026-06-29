from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_BENCHMARK_ROOT = Path(".local") / "autoqc_extraction_benchmark"


def find_latest_benchmark_run(root: Path = DEFAULT_BENCHMARK_ROOT) -> Path | None:
    if not root.exists():
        return None
    runs = [path for path in root.iterdir() if path.is_dir()]
    if not runs:
        return None
    return sorted(runs, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def analyze_benchmark_run(run_dir: Path | None, *, allow_fallback: bool = True) -> dict[str, Any]:
    if run_dir is None or not run_dir.exists():
        if not allow_fallback:
            raise FileNotFoundError("No benchmark run directory was found.")
        return fallback_recommendation("No benchmark run was found; using stable PyMuPDF fallback.")

    summary_rows = _read_csv(run_dir / "aggregate_summary.csv")
    metrics_rows = _read_csv(run_dir / "metrics.csv")
    report_text = _read_text(run_dir / "report.md")
    raw_sample = _read_jsonl_sample(run_dir / "raw_normalized_results.jsonl", limit=40)
    if not summary_rows and not metrics_rows:
        if not allow_fallback:
            raise FileNotFoundError(f"No benchmark summary or metrics files found in {run_dir}.")
        recommendation = fallback_recommendation(f"Benchmark files were missing in {run_dir}; using stable PyMuPDF fallback.")
        recommendation["benchmark_run"] = str(run_dir)
        return recommendation

    tested = sorted({str(row.get("tool_name") or "") for row in [*summary_rows, *metrics_rows] if row.get("tool_name")})
    status_counts = Counter((row.get("tool_name"), row.get("status")) for row in metrics_rows)
    skipped = _status_reasons(metrics_rows, "skipped")
    failed = _status_reasons(metrics_rows, "failed")
    successful_tools = {
        str(tool)
        for (tool, status), count in status_counts.items()
        if tool and status == "ok" and count > 0
    }

    text_tool = _best_summary_tool(summary_rows, "average_text_completeness_score", successful_tools) or _best_metric_tool(metrics_rows, "text_completeness_score")
    layout_tool = _best_summary_tool(summary_rows, "average_layout_score", successful_tools) or _best_metric_tool(metrics_rows, "layout_score")
    table_tool = _best_summary_tool(summary_rows, "average_table_title_revision_score", successful_tools) or _best_metric_tool(metrics_rows, "table_title_revision_score")
    overall_tool = _best_summary_tool(summary_rows, "average_heuristic_score", successful_tools) or text_tool or "pymupdf"

    rendering_tool = "pymupdf" if "pymupdf" in tested or "pymupdf" in successful_tools else overall_tool
    markup_tool = "pymupdf"
    confidence = _recommendation_confidence(summary_rows, successful_tools)
    reasons = _reason_lines(summary_rows, metrics_rows, report_text, text_tool, layout_tool, table_tool)
    implementation_notes = [
        "Use benchmark output as strategy input only; do not run benchmarks during normal prompt generation.",
        "Use PyMuPDF for page rendering, dimensions, and PDF markup compatibility.",
        "Use optional extractors only when installed; fall back per page without failing prompt generation.",
    ]
    if table_tool == "camelot":
        implementation_notes.append("Camelot should remain optional and table-only because it does not provide full page text.")
    if "pdfplumber" in {text_tool, layout_tool, table_tool}:
        implementation_notes.append("pdfplumber is recommended where installed because this run showed stronger text/layout/table evidence metrics.")

    strategy = (
        f"Use {text_tool or 'pymupdf'} for primary text evidence, {layout_tool or 'pymupdf'} for coordinate-aware layout, "
        f"{table_tool or 'pymupdf'} for tables/title-block support, and PyMuPDF for rendering/markup."
    )
    recommendation = {
        "benchmark_run": str(run_dir),
        "recommended_strategy": strategy,
        "primary_text_extractor": text_tool or "pymupdf",
        "primary_layout_extractor": layout_tool or "pymupdf",
        "primary_table_extractor": table_tool or "pymupdf",
        "pdf_rendering_tool": rendering_tool or "pymupdf",
        "markup_tool": markup_tool,
        "fallback_strategy": "If the recommended extractor is missing or fails on a page, use PyMuPDF text, layout, dimensions, and rendered image for that page.",
        "confidence": confidence,
        "reasons": reasons,
        "extractors_tested": tested,
        "extractors_skipped": skipped,
        "extractors_failed": failed,
        "implementation_notes": implementation_notes,
        "raw_jsonl_sample_count": len(raw_sample),
    }
    write_recommendation(run_dir, recommendation)
    return recommendation


def write_recommendation(run_dir: Path, recommendation: dict[str, Any]) -> Path:
    path = run_dir / "recommendation.json"
    path.write_text(json.dumps(recommendation, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def fallback_recommendation(reason: str) -> dict[str, Any]:
    return {
        "benchmark_run": None,
        "recommended_strategy": "Use PyMuPDF as the stable local fallback for text, layout, rendering, and markup.",
        "primary_text_extractor": "pymupdf",
        "primary_layout_extractor": "pymupdf",
        "primary_table_extractor": "pymupdf",
        "pdf_rendering_tool": "pymupdf",
        "markup_tool": "pymupdf",
        "fallback_strategy": "Continue using PyMuPDF page extraction when optional extractors are unavailable.",
        "confidence": 0.45,
        "reasons": [reason],
        "extractors_tested": [],
        "extractors_skipped": [],
        "extractors_failed": [],
        "implementation_notes": ["Fallback recommendation created without a benchmark report."],
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.is_file():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except Exception:
        return ""


def _read_jsonl_sample(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not path.is_file():
            return rows
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if len(rows) >= limit:
                    break
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return rows
    return rows


def _best_summary_tool(rows: list[dict[str, Any]], column: str, successful_tools: set[str]) -> str | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        tool = str(row.get("tool_name") or "")
        if successful_tools and tool not in successful_tools:
            continue
        reliability = _float(row.get("reliability"))
        if reliability < 0.8:
            continue
        grouped[tool].append(_float(row.get(column)))
    if not grouped:
        return None
    return max(((tool, sum(values) / len(values)) for tool, values in grouped.items()), key=lambda item: item[1])[0]


def _best_metric_tool(rows: list[dict[str, Any]], column: str) -> str | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.get("status") != "ok":
            continue
        grouped[str(row.get("tool_name") or "")].append(_float(row.get(column)))
    if not grouped:
        return None
    return max(((tool, sum(values) / len(values)) for tool, values in grouped.items()), key=lambda item: item[1])[0]


def _recommendation_confidence(rows: list[dict[str, Any]], successful_tools: set[str]) -> float:
    if not rows or not successful_tools:
        return 0.45
    reliability_values = [_float(row.get("reliability")) for row in rows if str(row.get("tool_name") or "") in successful_tools]
    avg_reliability = sum(reliability_values) / len(reliability_values) if reliability_values else 0.0
    scores = sorted([_float(row.get("average_heuristic_score")) for row in rows if _float(row.get("reliability")) >= 0.8], reverse=True)
    margin = (scores[0] - scores[1]) / 100.0 if len(scores) >= 2 else 0.05
    return round(max(0.45, min(0.95, 0.55 + 0.25 * avg_reliability + min(0.15, margin))), 2)


def _reason_lines(
    summary_rows: list[dict[str, Any]],
    metrics_rows: list[dict[str, Any]],
    report_text: str,
    text_tool: str | None,
    layout_tool: str | None,
    table_tool: str | None,
) -> list[str]:
    reasons: list[str] = []
    if text_tool:
        reasons.append(f"{text_tool} had the strongest benchmark text-completeness signal.")
    if layout_tool:
        reasons.append(f"{layout_tool} had the strongest coordinate/layout signal.")
    if table_tool:
        reasons.append(f"{table_tool} had the strongest table/title-block/revision-block signal.")
    reliable = sorted({str(row.get("tool_name")) for row in summary_rows if _float(row.get("reliability")) >= 0.8})
    if reliable:
        reasons.append(f"Reliable extractors in this run: {', '.join(reliable)}.")
    skipped = _status_reasons(metrics_rows, "skipped")
    if skipped:
        reasons.append("Skipped extractors were excluded from the production recommendation.")
    if "No failed extractor rows" in report_text:
        reasons.append("The benchmark report recorded no failed extractor rows.")
    return reasons


def _status_reasons(rows: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    counts = Counter(
        (str(row.get("tool_name") or "unknown"), str(row.get("error") or "unknown reason"))
        for row in rows
        if row.get("status") == status
    )
    return [{"tool_name": tool, "reason": reason, "count": count} for (tool, reason), count in counts.most_common()]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

