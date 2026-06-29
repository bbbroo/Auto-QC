from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any


SCORE_WEIGHTS: dict[str, float] = {
    "text_completeness_score": 0.25,
    "layout_score": 0.20,
    "table_title_revision_score": 0.20,
    "engineering_token_score": 0.15,
    "noise_score": 0.10,
    "runtime_reliability_score": 0.10,
}

DRAWING_REFERENCE_RE = re.compile(r"\b(?:[A-Z]{1,4}[- ]?\d{2,5}[A-Z]?|EP\d{2,5}|PFD[- ]?\d+|PID[- ]?\d+|P&ID[- ]?\d+)\b", re.I)
NOTE_REFERENCE_RE = re.compile(r"\b(?:NOTE|NOTES|SEE\s+SHEET|DETAIL|SECTION|REV|REVISION|BY|DATE)\b", re.I)
DRAWING_NUMBER_RE = re.compile(r"\b(?:DRAWING|DWG)\s*(?:NO\.?|NUMBER|#)?\s*[:#-]?\s*([A-Z]{1,5}[- ]?\d{2,5}[A-Z]?)\b", re.I)
SHEET_NUMBER_RE = re.compile(r"\b(?:SHEET|SHT)\s*(?:NO\.?|NUMBER|#)?\s*(?:[:#-]?\s*)?(?:\d+\s+OF\s+\d+|[A-Z]?\d{1,4})\b", re.I)
REVISION_BLOCK_RE = re.compile(r"\b(?:REV|REVISION)\b.{0,80}\b(?:DATE|BY|DESCRIPTION|CHK|APP|APPROVED)\b", re.I | re.S)
EQUIPMENT_TAG_RE = re.compile(
    r"\b(?:FV|PSV|PRV|PT|PIT|PI|PIC|PSH|PSL|TI|TT|TE|FI|FIT|FT|XV|HV|MOV|BV|V|P|PCV|FCV|REG|FLT|FILTER|MTR|SEP)[-\s]?\d{1,5}[A-Z]?\b",
    re.I,
)
PIPE_SIZE_RE = re.compile(r"\b(?:\d{1,2}\s*(?:\"|INCH|IN\.?|-\s?IN)|NPS\s*\d{1,2}|SCH\s*\d{1,3})\b", re.I)
PID_TERMS_RE = re.compile(
    r"\b(?:P\s*&\s*ID|PIPING\s+AND\s+INSTRUMENTATION|VALVE|REGULATOR|FILTER|METER|RELIEF|BYPASS|VENT|DRAIN|SENSING\s+LINE|SLAM[-\s]?SHUT|MONITOR)\b",
    re.I,
)


def compute_metrics(result: dict[str, Any]) -> dict[str, Any]:
    text = str(result.get("text") or "")
    blocks = list(result.get("blocks") or [])
    tables = list(result.get("tables") or [])
    metadata = dict(result.get("metadata") or {})
    combined_table_text = "\n".join(str(table.get("content") or "") for table in tables)
    combined_text = f"{text}\n{combined_table_text}".strip()

    character_count = len(text)
    words = re.findall(r"\b[\w&./#\"-]+\b", text)
    non_ws = len(re.findall(r"\S", text))
    line_count = len([line for line in text.splitlines() if line.strip()])
    alpha_chars = [ch for ch in text if ch.isalpha()]
    uppercase_ratio = (sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars)) if alpha_chars else 0.0
    block_count = len(blocks)
    blocks_with_bbox = sum(1 for block in blocks if block.get("bbox"))
    tables_with_bbox = sum(1 for table in tables if table.get("bbox"))
    table_cells = sum(_table_cell_count(table) for table in tables)
    output_size_bytes = len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8", errors="replace"))

    metrics = {
        "tool_name": result.get("tool_name"),
        "tool_version": result.get("tool_version"),
        "pdf_path": result.get("pdf_path"),
        "pdf_name": _pdf_name(result.get("pdf_path")),
        "page_number": int(result.get("page_number") or 0),
        "status": result.get("status"),
        "error": result.get("error"),
        "runtime_seconds": float(result.get("runtime_seconds") or 0.0),
        "character_count": character_count,
        "word_count": len(words),
        "non_whitespace_character_count": non_ws,
        "line_count": line_count,
        "extraction_empty": non_ws == 0,
        "suspicious_garble_score": suspicious_garble_score(text),
        "duplicate_text_ratio": duplicate_text_ratio(text),
        "uppercase_ratio": uppercase_ratio,
        "numeric_token_count": len(re.findall(r"\b\d+(?:[./-]\d+)*\b", text)),
        "drawing_reference_token_count": len(DRAWING_REFERENCE_RE.findall(combined_text)),
        "note_reference_count": len(NOTE_REFERENCE_RE.findall(combined_text)),
        "block_count": block_count,
        "blocks_with_bbox_count": blocks_with_bbox,
        "percent_blocks_with_bbox": (blocks_with_bbox / block_count) if block_count else 0.0,
        "page_width": _first_number(metadata.get("page_width"), metadata.get("width")),
        "page_height": _first_number(metadata.get("page_height"), metadata.get("height")),
        "has_coordinate_data": bool(blocks_with_bbox or tables_with_bbox),
        "table_count": len(tables),
        "total_table_cells": table_cells,
        "likely_drawing_index_detected": _likely_drawing_index(combined_text),
        "likely_bom_detected": _likely_bom(combined_text),
        "likely_revision_table_detected": _likely_revision_table(combined_text),
        "title_block_text_detected": _title_block_detected(combined_text),
        "drawing_number_detected": bool(DRAWING_NUMBER_RE.search(combined_text)),
        "sheet_number_detected": bool(SHEET_NUMBER_RE.search(combined_text)),
        "revision_block_detected": bool(REVISION_BLOCK_RE.search(combined_text)) or _likely_revision_table(combined_text),
        "p_and_id_terms_detected": len(PID_TERMS_RE.findall(combined_text)),
        "equipment_tag_count": len(EQUIPMENT_TAG_RE.findall(combined_text)),
        "pipe_size_token_count": len(PIPE_SIZE_RE.findall(combined_text)),
        "output_size_bytes": output_size_bytes,
    }
    metrics.update(score_metrics(metrics))
    return metrics


def score_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    if metrics.get("status") != "ok":
        scores = {key: 0.0 for key in SCORE_WEIGHTS}
        scores["heuristic_score"] = 0.0
        return scores

    text_completeness = _clamp(
        30.0 * (not metrics["extraction_empty"])
        + 35.0 * _saturate(metrics["non_whitespace_character_count"], 2500)
        + 20.0 * _saturate(metrics["word_count"], 350)
        + 15.0 * _saturate(metrics["line_count"], 90)
    )
    layout = _clamp(
        30.0 * bool(metrics["has_coordinate_data"])
        + 35.0 * float(metrics["percent_blocks_with_bbox"])
        + 20.0 * _saturate(metrics["block_count"], 80)
        + 15.0 * bool(metrics["page_width"] and metrics["page_height"])
    )
    table_title_revision = _clamp(
        20.0 * _saturate(metrics["table_count"], 2)
        + 20.0 * _saturate(metrics["total_table_cells"], 100)
        + 20.0 * bool(metrics["title_block_text_detected"])
        + 15.0 * bool(metrics["drawing_number_detected"])
        + 10.0 * bool(metrics["sheet_number_detected"])
        + 15.0 * bool(metrics["revision_block_detected"])
    )
    engineering = _clamp(
        25.0 * _saturate(metrics["drawing_reference_token_count"], 25)
        + 20.0 * _saturate(metrics["note_reference_count"], 35)
        + 20.0 * _saturate(metrics["p_and_id_terms_detected"], 25)
        + 25.0 * _saturate(metrics["equipment_tag_count"], 40)
        + 10.0 * _saturate(metrics["pipe_size_token_count"], 20)
    )
    noise = _clamp(100.0 - 60.0 * metrics["suspicious_garble_score"] - 40.0 * metrics["duplicate_text_ratio"])
    runtime_reliability = _clamp(70.0 + 30.0 * (1.0 - _saturate(metrics["runtime_seconds"], 120.0)))

    scores = {
        "text_completeness_score": text_completeness,
        "layout_score": layout,
        "table_title_revision_score": table_title_revision,
        "engineering_token_score": engineering,
        "noise_score": noise,
        "runtime_reliability_score": runtime_reliability,
    }
    scores["heuristic_score"] = round(sum(scores[key] * weight for key, weight in SCORE_WEIGHTS.items()), 2)
    return {key: round(value, 2) for key, value in scores.items()}


def suspicious_garble_score(text: str) -> float:
    if not text:
        return 1.0
    total = len(text)
    replacement = text.count("\ufffd")
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    weird = sum(1 for ch in text if not (ch.isalnum() or ch.isspace() or ch in ".,:;-/\\()[]{}#&@+*=%'\"<>_|!?$"))
    token_count = len(re.findall(r"\S+", text))
    symbol_heavy_tokens = len(re.findall(r"(?=\S{4,})(?:\S*[^A-Za-z0-9\s]){3,}\S*", text))
    score = (replacement * 8 + control * 4 + weird * 1.5) / max(total, 1)
    if token_count:
        score += min(0.4, symbol_heavy_tokens / token_count)
    return round(_clamp(score, 0.0, 1.0), 4)


def duplicate_text_ratio(text: str) -> float:
    lines = [re.sub(r"\s+", " ", line).strip().lower() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return 0.0
    counts = Counter(lines)
    duplicate_lines = sum(count - 1 for count in counts.values() if count > 1)
    return round(duplicate_lines / len(lines), 4)


def _table_cell_count(table: dict[str, Any]) -> int:
    row_count = table.get("row_count")
    column_count = table.get("column_count")
    if row_count is not None and column_count is not None:
        try:
            return int(row_count) * int(column_count)
        except (TypeError, ValueError):
            return 0
    content = str(table.get("content") or "")
    if not content:
        return 0
    return sum(max(1, len(re.split(r",|\t|\|", line))) for line in content.splitlines() if line.strip())


def _likely_drawing_index(text: str) -> bool:
    return bool(re.search(r"\b(?:drawing|sheet)\s+index\b", text, re.I)) or len(DRAWING_REFERENCE_RE.findall(text)) >= 12


def _likely_bom(text: str) -> bool:
    return bool(re.search(r"\b(?:bill\s+of\s+materials?|BOM|equipment\s+list|item\s+qty|quantity\s+description)\b", text, re.I))


def _likely_revision_table(text: str) -> bool:
    return bool(re.search(r"\bREV(?:ISION)?\b.{0,120}\b(?:DATE|DESCRIPTION|BY|CHK|APP(?:ROVED)?)\b", text, re.I | re.S))


def _title_block_detected(text: str) -> bool:
    tokens = ("DRAWING", "DWG", "SHEET", "REV", "REVISION", "DATE", "BY", "CHECKED", "APPROVED", "SCALE", "TITLE", "PROJECT")
    upper = text.upper()
    return sum(1 for token in tokens if token in upper) >= 4


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return None


def _saturate(value: Any, target: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if target <= 0:
        return 0.0
    return _clamp(numeric / target, 0.0, 1.0)


def _clamp(value: Any, lower: float = 0.0, upper: float = 100.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return lower
    return max(lower, min(upper, numeric))


def _pdf_name(pdf_path: Any) -> str:
    if not pdf_path:
        return ""
    return str(pdf_path).replace("\\", "/").rsplit("/", 1)[-1]

