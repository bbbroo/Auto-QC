from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from backend.extraction_benchmark.adapters.base import OptionalDependencyAdapter, NormalizedResult


class PDFPlumberAdapter(OptionalDependencyAdapter):
    tool_name = "pdfplumber"
    package_names = ("pdfplumber",)
    module_names = ("pdfplumber",)

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                raise ValueError(f"page {page_number} is outside PDF page range 1-{len(pdf.pages)}")
            page = pdf.pages[page_number - 1]
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            words = _extract_words(page)
            blocks = _words_to_line_blocks(words)
            tables = _extract_tables(page)
            return {
                "text": text,
                "blocks": blocks,
                "tables": tables,
                "metadata": {
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "word_count": len(words),
                    "char_count": len(getattr(page, "chars", []) or []),
                    "line_object_count": len(getattr(page, "lines", []) or []),
                    "rect_object_count": len(getattr(page, "rects", []) or []),
                    "curve_object_count": len(getattr(page, "curves", []) or []),
                    "page_count": len(pdf.pages),
                },
            }


def _extract_words(page: Any) -> list[dict[str, Any]]:
    try:
        return page.extract_words(extra_attrs=["fontname", "size"]) or []
    except Exception:
        try:
            return page.extract_words() or []
        except Exception:
            return []


def _words_to_line_blocks(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (round(float(item.get("top", item.get("y0", 0))) / 3) * 3, float(item.get("x0", 0)))):
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        y0 = float(word.get("top", word.get("y0", 0)))
        for row in rows:
            row_y0 = float(row[0].get("top", row[0].get("y0", 0)))
            if abs(row_y0 - y0) <= 3:
                row.append(word)
                break
        else:
            rows.append([word])

    blocks: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        row.sort(key=lambda item: float(item.get("x0", 0)))
        text = " ".join(str(item.get("text") or "") for item in row).strip()
        if not text:
            continue
        x0 = min(float(item.get("x0", 0)) for item in row)
        y0 = min(float(item.get("top", item.get("y0", 0))) for item in row)
        x1 = max(float(item.get("x1", 0)) for item in row)
        y1 = max(float(item.get("bottom", item.get("y1", 0))) for item in row)
        blocks.append(
            {
                "type": "text",
                "text": text,
                "bbox": [x0, y0, x1, y1],
                "confidence": None,
                "metadata": {"row_index": row_index, "word_count": len(row)},
            }
        )
    return blocks


def _extract_tables(page: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    try:
        found_tables = page.find_tables() or []
    except Exception:
        found_tables = []

    for table_index, table in enumerate(found_tables):
        try:
            rows = table.extract() or []
        except Exception:
            rows = []
        tables.append(_table_result(rows, getattr(table, "bbox", None), table_index))

    if tables:
        return tables

    try:
        extracted_tables = page.extract_tables() or []
    except Exception:
        extracted_tables = []
    return [_table_result(rows or [], None, index) for index, rows in enumerate(extracted_tables)]


def _table_result(rows: list[list[Any]], bbox: Any, table_index: int) -> dict[str, Any]:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    column_count = max((len(row) for row in rows), default=0)
    return {
        "format": "csv",
        "content": output.getvalue(),
        "bbox": list(bbox) if bbox else None,
        "row_count": len(rows),
        "column_count": column_count,
        "metadata": {"table_index": table_index},
    }

