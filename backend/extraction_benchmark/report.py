from __future__ import annotations

import csv
import json
import platform
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.extraction_benchmark.metrics import SCORE_WEIGHTS


def environment_info() -> dict[str, Any]:
    return {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def write_jsonl(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_summary(metrics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metrics_rows:
        grouped[(str(row.get("tool_name")), str(row.get("pdf_path")))].append(row)

    summary_rows: list[dict[str, Any]] = []
    score_columns = [
        "heuristic_score",
        "text_completeness_score",
        "layout_score",
        "table_title_revision_score",
        "engineering_token_score",
        "noise_score",
        "runtime_reliability_score",
    ]
    for (tool_name, pdf_path), rows in sorted(grouped.items()):
        statuses = Counter(str(row.get("status")) for row in rows)
        ok_rows = [row for row in rows if row.get("status") == "ok"]
        summary = {
            "tool_name": tool_name,
            "pdf_path": pdf_path,
            "pdf_name": rows[0].get("pdf_name") if rows else "",
            "pages_tested": len(rows),
            "ok_count": statuses.get("ok", 0),
            "skipped_count": statuses.get("skipped", 0),
            "failed_count": statuses.get("failed", 0),
            "reliability": round(statuses.get("ok", 0) / len(rows), 4) if rows else 0.0,
            "average_runtime_seconds": _mean(row.get("runtime_seconds") for row in rows),
            "errors": _join_unique(row.get("error") for row in rows if row.get("error")),
        }
        for column in score_columns:
            summary[f"average_{column}"] = _mean(row.get(column) for row in ok_rows)
        summary_rows.append(summary)
    return summary_rows


def write_markdown_report(
    path: Path,
    *,
    run_metadata: dict[str, Any],
    metrics_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AutoQC Extraction Benchmark Report",
        "",
        f"- Run timestamp: {run_metadata.get('run_timestamp')}",
        f"- Mode: {run_metadata.get('mode')}",
        f"- Output directory: `{run_metadata.get('run_dir')}`",
        "",
        "## Environment",
        "",
    ]
    for key, value in (run_metadata.get("environment") or {}).items():
        lines.append(f"- {key}: `{value}`")

    lines.extend(["", "## Tested PDFs", ""])
    for pdf in run_metadata.get("pdfs", []):
        lines.append(f"- `{pdf}`")

    lines.extend(["", "## Tested Extractors", ""])
    for extractor in run_metadata.get("extractors", []):
        lines.append(f"- `{extractor}`")

    lines.extend(["", "## Page Sampling", ""])
    for pdf_name, samples in (run_metadata.get("samples") or {}).items():
        rendered = ", ".join(f"{item['page_number']} ({item['reason']})" for item in samples)
        lines.append(f"- `{pdf_name}`: {rendered}")

    lines.extend(["", "## Aggregate Summary", ""])
    lines.extend(_summary_table(summary_rows))

    lines.extend(["", "## Skipped Extractors And Reasons", ""])
    skipped = _status_reasons(metrics_rows, "skipped")
    lines.extend(skipped or ["- None"])

    lines.extend(["", "## Best Extractor By Sample Type", ""])
    lines.extend(_best_by_sample_reason(metrics_rows) or ["- No successful extractor/page rows were produced."])

    lines.extend(["", "## Best Extractor By Metric Category", ""])
    for category in SCORE_WEIGHTS:
        best = _best_tool_for_metric(metrics_rows, category)
        if best:
            tool, score = best
            lines.append(f"- `{category}`: `{tool}` ({score:.2f})")
        else:
            lines.append(f"- `{category}`: no successful rows")

    lines.extend(["", "## Worst Failure Modes", ""])
    failures = _status_reasons(metrics_rows, "failed")
    lines.extend(failures or ["- No failed extractor rows."])

    lines.extend(["", "## Recommendation", ""])
    lines.extend(_recommendations(summary_rows, metrics_rows))
    lines.extend(
        [
            "",
            "## Scoring Note",
            "",
            "The 0-100 score is an internal heuristic for AutoQC evidence usefulness. It is not an absolute OCR-quality benchmark.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summary_table(summary_rows: list[dict[str, Any]]) -> list[str]:
    if not summary_rows:
        return ["No summary rows produced."]
    lines = [
        "| Extractor | PDF | Pages | OK | Skipped | Failed | Reliability | Avg Score | Avg Runtime |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            "| {tool} | {pdf} | {pages} | {ok} | {skipped} | {failed} | {reliability:.2f} | {score:.2f} | {runtime:.2f} |".format(
                tool=row.get("tool_name"),
                pdf=row.get("pdf_name"),
                pages=row.get("pages_tested"),
                ok=row.get("ok_count"),
                skipped=row.get("skipped_count"),
                failed=row.get("failed_count"),
                reliability=float(row.get("reliability") or 0),
                score=float(row.get("average_heuristic_score") or 0),
                runtime=float(row.get("average_runtime_seconds") or 0),
            )
        )
    return lines


def _best_by_sample_reason(metrics_rows: list[dict[str, Any]]) -> list[str]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in metrics_rows:
        if row.get("status") != "ok":
            continue
        reason = str(row.get("sample_reason") or "unknown")
        tool = str(row.get("tool_name"))
        grouped[(reason, tool)].append(float(row.get("heuristic_score") or 0))
    by_reason: dict[str, tuple[str, float]] = {}
    for (reason, tool), scores in grouped.items():
        average = statistics.mean(scores)
        current = by_reason.get(reason)
        if current is None or average > current[1]:
            by_reason[reason] = (tool, average)
    return [f"- `{reason}`: `{tool}` ({score:.2f})" for reason, (tool, score) in sorted(by_reason.items())]


def _best_tool_for_metric(metrics_rows: list[dict[str, Any]], metric: str) -> tuple[str, float] | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in metrics_rows:
        if row.get("status") == "ok":
            grouped[str(row.get("tool_name"))].append(float(row.get(metric) or 0))
    if not grouped:
        return None
    return max(((tool, statistics.mean(values)) for tool, values in grouped.items()), key=lambda item: item[1])


def _status_reasons(metrics_rows: list[dict[str, Any]], status: str) -> list[str]:
    counts = Counter(
        (str(row.get("tool_name")), str(row.get("error") or "unknown reason"))
        for row in metrics_rows
        if row.get("status") == status
    )
    return [f"- `{tool}`: {reason} ({count} rows)" for (tool, reason), count in counts.most_common()]


def _recommendations(summary_rows: list[dict[str, Any]], metrics_rows: list[dict[str, Any]]) -> list[str]:
    if not summary_rows:
        return ["No benchmark rows were produced. Confirm the PDF paths and rerun the command."]
    successful = [row for row in summary_rows if float(row.get("reliability") or 0) > 0]
    if not successful:
        return ["All extractors skipped or failed. Install the baseline optional dependencies first, then rerun quick mode."]
    best = max(successful, key=lambda row: float(row.get("average_heuristic_score") or 0))
    recommendations = [
        f"- Current best overall signal is `{best.get('tool_name')}` on `{best.get('pdf_name')}` with average score {float(best.get('average_heuristic_score') or 0):.2f}.",
    ]
    tested_tools = {str(row.get("tool_name")) for row in metrics_rows}
    ok_tools = {str(row.get("tool_name")) for row in metrics_rows if row.get("status") == "ok"}
    if "pdfplumber" in tested_tools and "pdfplumber" not in ok_tools:
        recommendations.append("- Install `pdfplumber` next to compare word-level coordinates and table extraction against the PyMuPDF baseline.")
    if "camelot" in tested_tools and "camelot" not in ok_tools:
        recommendations.append("- Add Camelot only if drawing index, BOM, or revision table extraction becomes the next focus.")
    recommendations.append("- Keep this benchmark isolated until at least two extractors show repeatable gains on title blocks, drawing references, or table-heavy sheets.")
    return recommendations


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "tool_name",
        "tool_version",
        "pdf_name",
        "pdf_path",
        "page_number",
        "sample_reason",
        "sample_confidence",
        "status",
        "error",
        "heuristic_score",
    ]
    keys = set().union(*(row.keys() for row in rows)) if rows else set()
    return [key for key in preferred if key in keys] + sorted(key for key in keys if key not in preferred)


def _mean(values: object) -> float:
    parsed: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    return round(statistics.mean(parsed), 4) if parsed else 0.0


def _join_unique(values: object) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.append(text)
    return " | ".join(seen)


def timestamp_for_run() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
