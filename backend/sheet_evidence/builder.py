from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.extraction_benchmark.sample_pages import select_pages
from backend.sheet_evidence.cache import write_json
from backend.sheet_evidence.classifier import classify_sheet, extract_identity, normalize_drawing_number
from backend.sheet_evidence.extractors import (
    extract_camelot_tables,
    extract_pdfplumber_page,
    extract_pymupdf_page,
    is_extractor_available,
    package_page_count,
    safe_pdf_stem,
)
from backend.sheet_evidence.models import (
    EvidenceBlock,
    EvidenceTable,
    ExtractionStrategy,
    PackageIndexEntry,
    QualityScores,
    SheetEvidencePacket,
    SourceFiles,
    TextEvidence,
)
from backend.sheet_evidence.prompt_context import SOURCE_OF_TRUTH_WARNING, enhanced_prompt_preview, page_prompt_context
from backend.sheet_evidence.references import extract_engineering_tokens, extract_references


DEFAULT_OUTPUT_ROOT = Path(".local") / "autoqc_sheet_evidence"


class SheetEvidenceBuilder:
    def __init__(
        self,
        *,
        recommendation: dict[str, Any] | None = None,
        output_root: Path | None = None,
        render_dpi: int = 120,
    ) -> None:
        self.recommendation = recommendation or {}
        self.output_root = Path(output_root or DEFAULT_OUTPUT_ROOT)
        self.render_dpi = render_dpi

    def build_pdfs(
        self,
        pdf_paths: list[Path],
        *,
        mode: str = "full",
        pages: list[int] | None = None,
        max_pages: int | None = None,
        force: bool = False,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_root.resolve() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        pdf_results = []
        all_validations = []
        all_packets: list[dict[str, Any]] = []
        for pdf_path in pdf_paths:
            result = self.build_pdf(pdf_path, run_dir=run_dir, mode=mode, pages=pages, max_pages=max_pages, force=force)
            pdf_results.append(result)
            all_validations.extend(result.get("validation", []))
            all_packets.extend(result.get("packets", []))
        preview_path = run_dir / "enhanced_prompt_preview.md"
        preview_path.write_text(enhanced_prompt_preview(all_packets), encoding="utf-8")
        summary = {
            "run_dir": str(run_dir),
            "pdf_count": len(pdf_paths),
            "processed_page_count": len(all_packets),
            "recommendation": self.recommendation,
            "validation": all_validations,
            "valid": all(item.get("passed") for item in all_validations),
            "enhanced_prompt_preview": str(preview_path),
            "pdf_results": [
                {
                    "pdf_path": item["pdf_path"],
                    "output_dir": item["output_dir"],
                    "processed_page_count": item["processed_page_count"],
                    "page_count": item["page_count"],
                }
                for item in pdf_results
            ],
        }
        write_json(run_dir / "evidence_build_summary.json", summary)
        return {**summary, "packets": all_packets}

    def build_pdf(
        self,
        pdf_path: Path,
        *,
        run_dir: Path,
        mode: str = "full",
        pages: list[int] | None = None,
        max_pages: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        pdf_path = pdf_path.expanduser().resolve()
        pdf_dir = run_dir / safe_pdf_stem(pdf_path)
        pages_dir = pdf_dir / "pages"
        prompt_dir = pdf_dir / "prompt_context"
        debug_dir = pdf_dir / "debug"
        image_dir = pdf_dir / "rendered_pages"
        for directory in (pages_dir, prompt_dir, debug_dir, image_dir):
            directory.mkdir(parents=True, exist_ok=True)

        page_count = package_page_count(pdf_path)
        selected_pages = _selected_page_numbers(pdf_path, page_count, mode=mode, pages=pages, max_pages=max_pages)
        packets = []
        for page_number in selected_pages:
            packet = self.build_page_packet(pdf_path, page_number, page_count, debug_dir=debug_dir, image_dir=image_dir)
            packet_dict = packet.to_dict()
            packet_path = pages_dir / f"page_{page_number:03d}.json"
            context_path = prompt_dir / f"page_{page_number:03d}.md"
            debug_text_path = debug_dir / f"page_{page_number:03d}.txt"
            debug_text_path.write_text(packet.text.full_text, encoding="utf-8", errors="replace")
            packet_dict["source_files"]["debug_text"] = str(debug_text_path)
            write_json(packet_path, packet_dict)
            context_path.write_text(page_prompt_context(packet_dict) + "\n", encoding="utf-8")
            packets.append(packet_dict)

        package_index = build_package_index(packets)
        _apply_package_index_to_packets(package_index, packets)
        for packet_dict in packets:
            page_number = int(packet_dict["page_number"])
            write_json(pages_dir / f"page_{page_number:03d}.json", packet_dict)
            (prompt_dir / f"page_{page_number:03d}.md").write_text(page_prompt_context(packet_dict) + "\n", encoding="utf-8")

        write_json(pdf_dir / "package_index.json", {"pdf_path": str(pdf_path), "entries": [entry.to_dict() for entry in package_index]})
        summary_md = package_summary_markdown(pdf_path, page_count, selected_pages, packets, package_index)
        (pdf_dir / "package_summary.md").write_text(summary_md, encoding="utf-8")
        validation = validate_pdf_output(pdf_path, page_count, selected_pages, packets, pdf_dir)
        write_json(pdf_dir / "evidence_build_summary.json", {"pdf_path": str(pdf_path), "page_count": page_count, "processed_pages": selected_pages, "validation": validation})
        return {
            "pdf_path": str(pdf_path),
            "output_dir": str(pdf_dir),
            "page_count": page_count,
            "processed_page_count": len(packets),
            "packets": packets,
            "package_index": [entry.to_dict() for entry in package_index],
            "validation": validation,
        }

    def build_page_packet(
        self,
        pdf_path: Path,
        page_number: int,
        page_count: int,
        *,
        debug_dir: Path,
        image_dir: Path,
    ) -> SheetEvidencePacket:
        strategy = self._strategy()
        pymupdf = extract_pymupdf_page(pdf_path, page_number, image_dir=image_dir, dpi=self.render_dpi)
        pdfplumber = extract_pdfplumber_page(pdf_path, page_number) if _uses_pdfplumber(strategy) else {"status": "skipped", "warnings": []}
        table_result = _table_result_for_strategy(strategy, pdf_path, page_number, pdfplumber)
        warnings = [*pymupdf.get("warnings", []), *pdfplumber.get("warnings", []), *table_result.get("warnings", [])]

        text_source = pdfplumber if _prefer_text(pdfplumber, pymupdf, strategy) else pymupdf
        layout_source = pdfplumber if _prefer_layout(pdfplumber, strategy) else pymupdf
        table_source = table_result
        text = str(text_source.get("text") or "")
        blocks = list(layout_source.get("blocks") or [])
        tables = list(table_source.get("tables") or [])
        identity = extract_identity(text or str(pymupdf.get("text") or ""), page_number)
        classification = classify_sheet(
            text=text,
            drawing_number=identity["drawing_number"],
            sheet_title=identity["sheet_title"],
            page_number=page_number,
        )
        title_block_text = _title_block_text(blocks, text, float(pymupdf.get("page_height") or 0), float(pymupdf.get("page_width") or 0))
        revision_block_text = _revision_block_text(text, tables)
        text_evidence = TextEvidence(
            full_text=text,
            important_text=_important_lines(text),
            notes=_note_lines(text),
            title_block_text=title_block_text,
            revision_block_text=revision_block_text,
        )
        classified_blocks = _classify_blocks(blocks, title_block_text, revision_block_text)
        classified_tables = [_normalize_table(table) for table in tables]
        quality = _quality_scores(text, classified_blocks, classified_tables, warnings)
        debug_raw = debug_dir / f"page_{page_number:03d}_raw_extraction.json"
        raw_payload = {
            "pymupdf": _debug_extract_payload(pymupdf),
            "pdfplumber": _debug_extract_payload(pdfplumber),
            "table_result": _debug_extract_payload(table_result),
        }
        debug_raw.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return SheetEvidencePacket(
            pdf_path=str(pdf_path),
            pdf_name=pdf_path.name,
            page_number=page_number,
            page_count=page_count,
            sheet_number=identity["sheet_number"],
            drawing_number=identity["drawing_number"],
            sheet_title=identity["sheet_title"],
            discipline=str(classification["discipline"]),
            page_width=float(pymupdf.get("page_width") or pdfplumber.get("page_width") or 0),
            page_height=float(pymupdf.get("page_height") or pdfplumber.get("page_height") or 0),
            extraction_strategy=strategy,
            quality=quality,
            text=text_evidence,
            layout_blocks=classified_blocks,
            tables=classified_tables,
            references=extract_references(text),
            engineering_tokens=extract_engineering_tokens(text),
            rendered_page_image=pymupdf.get("rendered_page_image"),
            source_files=SourceFiles(raw_extraction=str(debug_raw), debug_text=None),
        )

    def _strategy(self) -> ExtractionStrategy:
        text = _available_or_fallback(str(self.recommendation.get("primary_text_extractor") or "pymupdf"), "pymupdf")
        layout = _available_or_fallback(str(self.recommendation.get("primary_layout_extractor") or text), "pymupdf")
        table = _available_or_fallback(str(self.recommendation.get("primary_table_extractor") or text), "pymupdf")
        rendering = "pymupdf"
        return ExtractionStrategy(text_extractor=text, layout_extractor=layout, table_extractor=table, rendering_tool=rendering)


def build_package_index(packets: list[dict[str, Any]]) -> list[PackageIndexEntry]:
    entries: list[PackageIndexEntry] = []
    seen: set[tuple[str, int]] = set()
    for packet in packets:
        if packet.get("discipline") == "drawing_index":
            for entry in parse_drawing_index(packet.get("text", {}).get("full_text", ""), int(packet.get("page_number") or 0)):
                key = (entry.drawing_number, entry.page_number)
                if key not in seen:
                    seen.add(key)
                    entries.append(entry)
    for packet in packets:
        drawing = normalize_drawing_number(str(packet.get("drawing_number") or ""))
        if not drawing or drawing == "UNKNOWN":
            continue
        key = (drawing, int(packet.get("page_number") or 0))
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            PackageIndexEntry(
                drawing_number=drawing,
                sheet_number=str(packet.get("sheet_number") or packet.get("page_number")),
                title=str(packet.get("sheet_title") or "Unknown Sheet"),
                page_number=int(packet.get("page_number") or 0),
                discipline=str(packet.get("discipline") or "unknown"),
                confidence=0.6,
            )
        )
    return sorted(entries, key=lambda item: (item.page_number, item.drawing_number))


def parse_drawing_index(text: str, index_page_number: int) -> list[PackageIndexEntry]:
    entries: list[PackageIndexEntry] = []
    for line in (text or "").splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if len(clean) < 6:
            continue
        match = re.search(r"\b((?:G|GN|P|PID|M|S|C|E|EP|EE|I|IN|PLC|FGS|A|B)[- ]?\d{2,5}[A-Z]?)\b\s+(.{4,140})", clean, re.I)
        if not match:
            continue
        drawing = normalize_drawing_number(match.group(1))
        title = _clean_index_title(match.group(2))
        if not title:
            continue
        classified = classify_sheet(text=title, drawing_number=drawing, sheet_title=title, page_number=0)
        entries.append(
            PackageIndexEntry(
                drawing_number=drawing,
                sheet_number=drawing,
                title=title,
                page_number=index_page_number,
                discipline=classified["discipline"],
                confidence=0.72,
            )
        )
    return entries[:300]


def validate_pdf_output(pdf_path: Path, page_count: int, selected_pages: list[int], packets: list[dict[str, Any]], pdf_dir: Path) -> list[dict[str, Any]]:
    validations = [
        _check("package summary exists", (pdf_dir / "package_summary.md").is_file()),
        _check("package index exists", (pdf_dir / "package_index.json").is_file()),
        _check("one packet per processed page", len(packets) == len(selected_pages)),
        _check("page numbers are correct", sorted(int(packet.get("page_number") or 0) for packet in packets) == sorted(selected_pages)),
        _check("page count matches PDF", all(int(packet.get("page_count") or 0) == page_count for packet in packets)),
        _check("page dimensions present", all(float(packet.get("page_width") or 0) > 0 and float(packet.get("page_height") or 0) > 0 for packet in packets)),
        _check("no packet claims completeness", not any(_claims_completeness(packet) for packet in packets)),
        _check(
            "prompt contexts include source-of-truth warning",
            all(SOURCE_OF_TRUTH_WARNING in (pdf_dir / "prompt_context" / f"page_{int(packet.get('page_number')):03d}.md").read_text(encoding="utf-8") for packet in packets),
        ),
    ]
    for page in selected_pages:
        validations.append(_check(f"page {page} evidence json exists", (pdf_dir / "pages" / f"page_{page:03d}.json").is_file()))
    return validations


def package_summary_markdown(
    pdf_path: Path,
    page_count: int,
    selected_pages: list[int],
    packets: list[dict[str, Any]],
    package_index: list[PackageIndexEntry],
) -> str:
    lines = [
        f"# Sheet Evidence Summary: {pdf_path.name}",
        "",
        SOURCE_OF_TRUTH_WARNING,
        "",
        f"- PDF path: `{pdf_path}`",
        f"- Page count: {page_count}",
        f"- Processed pages: {', '.join(str(page) for page in selected_pages)}",
        f"- Package index entries: {len(package_index)}",
        "",
        "## Processed Pages",
        "",
    ]
    for packet in packets:
        quality = packet.get("quality") or {}
        lines.append(
            f"- Page {packet.get('page_number')}: `{packet.get('drawing_number')}` {packet.get('sheet_title')} "
            f"({packet.get('discipline')}, score {float(quality.get('overall_score') or 0):.1f})"
        )
    return "\n".join(lines) + "\n"


def _selected_page_numbers(pdf_path: Path, page_count: int, *, mode: str, pages: list[int] | None, max_pages: int | None) -> list[int]:
    if pages:
        selected = [page for page in dict.fromkeys(int(page) for page in pages) if 1 <= page <= page_count]
    elif mode == "quick":
        selected = [sample.page_number for sample in select_pages(pdf_path, mode="quick", max_pages=max_pages)]
    else:
        selected = list(range(1, page_count + 1))
    if max_pages and max_pages > 0:
        selected = selected[:max_pages]
    return selected


def _table_result_for_strategy(strategy: ExtractionStrategy, pdf_path: Path, page_number: int, pdfplumber: dict[str, Any]) -> dict[str, Any]:
    if strategy.table_extractor == "camelot":
        result = extract_camelot_tables(pdf_path, page_number)
        if result.get("status") == "ok" and result.get("tables"):
            return result
        return {"tables": list(pdfplumber.get("tables") or []), "warnings": list(result.get("warnings") or [])}
    if strategy.table_extractor == "pdfplumber":
        return {"tables": list(pdfplumber.get("tables") or []), "warnings": []}
    return {"tables": [], "warnings": ["table extractor fell back to PyMuPDF; table extraction is limited"]}


def _uses_pdfplumber(strategy: ExtractionStrategy) -> bool:
    return "pdfplumber" in {strategy.text_extractor, strategy.layout_extractor, strategy.table_extractor}


def _prefer_text(candidate: dict[str, Any], fallback: dict[str, Any], strategy: ExtractionStrategy) -> bool:
    return strategy.text_extractor == "pdfplumber" and candidate.get("status") == "ok" and len(str(candidate.get("text") or "")) >= max(20, len(str(fallback.get("text") or "")) * 0.8)


def _prefer_layout(candidate: dict[str, Any], strategy: ExtractionStrategy) -> bool:
    return strategy.layout_extractor == "pdfplumber" and candidate.get("status") == "ok" and bool(candidate.get("blocks"))


def _available_or_fallback(name: str, fallback: str) -> str:
    normalized = name.strip().lower()
    if normalized in {"pymupdf", "pdfplumber", "camelot"} and is_extractor_available(normalized):
        return normalized
    return fallback


def _important_lines(text: str) -> list[str]:
    lines = []
    for line in (text or "").splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if len(clean) < 8:
            continue
        if re.search(r"\b(?:SHALL|MUST|REQUIRED|PROVIDE|INSTALL|REMOVE|VERIFY|SEE|DETAIL|SECTION|REV|P&ID|REGULATOR|VALVE|NOTE)\b", clean, re.I):
            lines.append(clean)
    return _dedupe(lines, 24)


def _note_lines(text: str) -> list[str]:
    return _dedupe(
        re.sub(r"\s+", " ", line).strip()
        for line in (text or "").splitlines()
        if re.search(r"\b(?:NOTE|NOTES|KEYNOTE|GENERAL NOTE)\b", line, re.I)
    )[:24]


def _title_block_text(blocks: list[EvidenceBlock], text: str, page_height: float, page_width: float) -> str:
    pieces = []
    for block in blocks:
        bbox = block.bbox or []
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = bbox
        block_text = block.text.strip()
        if not block_text:
            continue
        lower_band = page_height and y0 >= page_height * 0.68
        right_band = page_width and x0 >= page_width * 0.60
        has_title_tokens = re.search(r"\b(?:DRAWING|DWG|SHEET|REV|DATE|SCALE|PROJECT|TITLE|CHECKED|APPROVED)\b", block_text, re.I)
        if has_title_tokens or (lower_band and right_band):
            pieces.append(block_text)
    if pieces:
        return "\n".join(_dedupe(pieces, 30))[:2500]
    fallback = "\n".join(line for line in (text or "").splitlines() if re.search(r"\b(?:DRAWING|DWG|SHEET|REV|DATE|SCALE|PROJECT|TITLE)\b", line, re.I))
    return fallback[:2500]


def _revision_block_text(text: str, tables: list[EvidenceTable]) -> str:
    table_text = "\n".join(table.content for table in tables if table.type == "revision_block")
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in (text or "").splitlines()
        if re.search(r"\b(?:REV|REVISION|DATE|DESCRIPTION|ISSUED|BY|CHK|APPROVED)\b", line, re.I)
    ]
    return "\n".join(_dedupe([table_text, *lines], 30)).strip()[:2500]


def _classify_blocks(blocks: list[EvidenceBlock], title_block_text: str, revision_block_text: str) -> list[EvidenceBlock]:
    output = []
    title_set = set(title_block_text.splitlines())
    revision_set = set(revision_block_text.splitlines())
    for block in blocks:
        block_type = "text"
        if block.text in title_set:
            block_type = "title_block"
        elif block.text in revision_set or re.search(r"\b(?:REV|REVISION)\b", block.text, re.I):
            block_type = "revision_block"
        elif re.search(r"\b(?:NOTE|NOTES|GENERAL NOTE)\b", block.text, re.I):
            block_type = "notes"
        output.append(EvidenceBlock(type=block_type, text=block.text, bbox=block.bbox, source=block.source, confidence=block.confidence))
    return output


def _normalize_table(table: Any) -> EvidenceTable:
    if isinstance(table, EvidenceTable):
        return table
    return EvidenceTable(
        type=str(getattr(table, "type", None) or "generic"),
        content=str(getattr(table, "content", None) or ""),
        format=str(getattr(table, "format", None) or "text"),
        bbox=getattr(table, "bbox", None),
        source=str(getattr(table, "source", None) or "unknown"),
    )


def _quality_scores(text: str, blocks: list[EvidenceBlock], tables: list[EvidenceTable], warnings: list[str]) -> QualityScores:
    text_score = min(100.0, 20.0 + len(text) / 30.0) if text.strip() else 0.0
    with_bbox = sum(1 for block in blocks if block.bbox)
    layout_score = min(100.0, 30.0 + (with_bbox / len(blocks)) * 50.0 + min(len(blocks), 40) * 0.5) if blocks else 0.0
    table_score = min(100.0, 20.0 + len(tables) * 25.0 + sum(min(len(table.content), 1200) for table in tables) / 80.0) if tables else 0.0
    overall = round(text_score * 0.45 + layout_score * 0.35 + table_score * 0.20, 2)
    quality_warnings = list(dict.fromkeys(warnings))
    if text_score < 35:
        quality_warnings.append("text extraction weak; rely on visual PDF page")
    if layout_score < 35:
        quality_warnings.append("coordinate/layout extraction weak")
    if not tables:
        quality_warnings.append("no tables extracted")
    return QualityScores(round(text_score, 2), round(layout_score, 2), round(table_score, 2), overall, quality_warnings)


def _apply_package_index_to_packets(index: list[PackageIndexEntry], packets: list[dict[str, Any]]) -> None:
    by_drawing = {entry.drawing_number: entry for entry in index if entry.confidence >= 0.7}
    for packet in packets:
        drawing = normalize_drawing_number(str(packet.get("drawing_number") or ""))
        entry = by_drawing.get(drawing)
        if not entry:
            continue
        if packet.get("sheet_title") in {"Unknown Sheet", "", None}:
            packet["sheet_title"] = entry.title
        if packet.get("discipline") == "unknown":
            packet["discipline"] = entry.discipline


def _clean_index_title(value: str) -> str:
    title = re.sub(r"\b(?:REV|SHEET|DATE)\b.*$", "", value, flags=re.I).strip(" -:\t")
    return title[:160]


def _debug_extract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "text_length": len(str(payload.get("text") or "")),
        "block_count": len(payload.get("blocks") or []),
        "table_count": len(payload.get("tables") or []),
        "warnings": payload.get("warnings") or [],
    }


def _dedupe(values: object, limit: int | None = None) -> list[str]:
    seen = set()
    output = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if limit and len(output) >= limit:
            break
    return output


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _claims_completeness(packet: dict[str, Any]) -> bool:
    serialized = json.dumps(packet, ensure_ascii=False).lower()
    forbidden = ["complete extraction", "authoritative extraction", "extracted text is complete", "fully extracted"]
    return any(item in serialized for item in forbidden)

