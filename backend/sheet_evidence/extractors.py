from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path
from typing import Any

from backend.extraction_benchmark.adapters.base import safe_name
from backend.sheet_evidence.models import EvidenceBlock, EvidenceTable, RenderedPageImage


def package_page_count(pdf_path: Path) -> int:
    import fitz

    with fitz.open(pdf_path) as doc:
        return int(doc.page_count)


def extract_pymupdf_page(
    pdf_path: Path,
    page_number: int,
    *,
    image_dir: Path | None = None,
    dpi: int = 120,
) -> dict[str, Any]:
    import fitz

    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_number - 1)
        text = page.get_text("text", sort=True) or ""
        blocks = []
        for index, block in enumerate(page.get_text("blocks", sort=True) or []):
            if len(block) < 5:
                continue
            block_text = str(block[4] or "").strip()
            if not block_text:
                continue
            blocks.append(
                EvidenceBlock(
                    type="text",
                    text=block_text,
                    bbox=[float(block[0]), float(block[1]), float(block[2]), float(block[3])],
                    source="pymupdf",
                    confidence=None,
                )
            )
        rendered = RenderedPageImage()
        if image_dir is not None:
            image_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / f"page_{page_number:03d}.png"
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(image_path)
            rendered = RenderedPageImage(path=str(image_path), width=int(pix.width), height=int(pix.height), dpi=dpi)
        return {
            "status": "ok",
            "text": text,
            "blocks": blocks,
            "tables": [],
            "page_width": float(page.rect.width),
            "page_height": float(page.rect.height),
            "page_count": int(doc.page_count),
            "rendered_page_image": rendered,
            "warnings": [],
        }


def extract_pdfplumber_page(pdf_path: Path, page_number: int) -> dict[str, Any]:
    if importlib.util.find_spec("pdfplumber") is None:
        return {"status": "skipped", "text": "", "blocks": [], "tables": [], "warnings": ["pdfplumber is not installed"]}
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[page_number - 1]
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            words = _extract_words(page)
            blocks = _words_to_blocks(words)
            tables = _extract_tables(page)
            return {
                "status": "ok",
                "text": text,
                "blocks": blocks,
                "tables": tables,
                "page_width": float(page.width),
                "page_height": float(page.height),
                "warnings": [],
            }
    except Exception as exc:
        return {"status": "failed", "text": "", "blocks": [], "tables": [], "warnings": [f"pdfplumber failed: {exc}"]}


def extract_camelot_tables(pdf_path: Path, page_number: int) -> dict[str, Any]:
    if importlib.util.find_spec("camelot") is None:
        return {"status": "skipped", "tables": [], "warnings": ["camelot is not installed"]}
    try:
        import camelot

        tables = camelot.read_pdf(str(pdf_path), pages=str(page_number), flavor="stream")
        evidence_tables: list[EvidenceTable] = []
        for table in tables:
            dataframe = table.df
            evidence_tables.append(
                EvidenceTable(
                    type="generic",
                    content=dataframe.to_csv(index=False, header=False),
                    format="csv",
                    bbox=list(getattr(table, "_bbox", None) or []) or None,
                    source="camelot",
                )
            )
        return {"status": "ok", "tables": evidence_tables, "warnings": []}
    except Exception as exc:
        return {"status": "failed", "tables": [], "warnings": [f"camelot failed: {exc}"]}


def is_extractor_available(name: str) -> bool:
    aliases = {"pymupdf": "fitz", "pdfplumber": "pdfplumber", "camelot": "camelot"}
    return importlib.util.find_spec(aliases.get(name, name)) is not None


def safe_pdf_stem(pdf_path: Path) -> str:
    return safe_name(pdf_path.stem)


def _extract_words(page: Any) -> list[dict[str, Any]]:
    try:
        return page.extract_words(extra_attrs=["fontname", "size"]) or []
    except Exception:
        return page.extract_words() or []


def _words_to_blocks(words: list[dict[str, Any]]) -> list[EvidenceBlock]:
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (round(float(item.get("top", item.get("y0", 0))) / 3) * 3, float(item.get("x0", 0)))):
        if not str(word.get("text") or "").strip():
            continue
        y0 = float(word.get("top", word.get("y0", 0)))
        for row in rows:
            row_y0 = float(row[0].get("top", row[0].get("y0", 0)))
            if abs(row_y0 - y0) <= 3:
                row.append(word)
                break
        else:
            rows.append([word])

    blocks: list[EvidenceBlock] = []
    for row in rows:
        row.sort(key=lambda item: float(item.get("x0", 0)))
        text = " ".join(str(item.get("text") or "") for item in row).strip()
        if not text:
            continue
        blocks.append(
            EvidenceBlock(
                type="text",
                text=text,
                bbox=[
                    min(float(item.get("x0", 0)) for item in row),
                    min(float(item.get("top", item.get("y0", 0))) for item in row),
                    max(float(item.get("x1", 0)) for item in row),
                    max(float(item.get("bottom", item.get("y1", 0))) for item in row),
                ],
                source="pdfplumber",
                confidence=None,
            )
        )
    return blocks


def _extract_tables(page: Any) -> list[EvidenceTable]:
    tables: list[EvidenceTable] = []
    try:
        found_tables = page.find_tables() or []
    except Exception:
        found_tables = []
    for table in found_tables:
        try:
            rows = table.extract() or []
        except Exception:
            rows = []
        tables.append(_table_from_rows(rows, getattr(table, "bbox", None), "pdfplumber"))
    if tables:
        return tables
    try:
        extracted = page.extract_tables() or []
    except Exception:
        extracted = []
    return [_table_from_rows(rows or [], None, "pdfplumber") for rows in extracted]


def _table_from_rows(rows: list[list[Any]], bbox: Any, source: str) -> EvidenceTable:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return EvidenceTable(type=_classify_table(output.getvalue()), content=output.getvalue(), format="csv", bbox=list(bbox) if bbox else None, source=source)


def _classify_table(content: str) -> str:
    upper = content.upper()
    if "DRAWING" in upper and "TITLE" in upper:
        return "drawing_index"
    if "BILL OF MATERIAL" in upper or "BOM" in upper or "QTY" in upper:
        return "bom"
    if "EQUIPMENT" in upper:
        return "equipment_list"
    if "REV" in upper and "DATE" in upper:
        return "revision_block"
    if "CABLE" in upper:
        return "cable_list"
    if "CONDUIT" in upper:
        return "conduit_list"
    return "generic"

