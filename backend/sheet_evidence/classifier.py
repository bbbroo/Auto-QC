from __future__ import annotations

import re
from typing import Any


DISCIPLINES = {
    "cover",
    "drawing_index",
    "general_notes",
    "bom",
    "equipment_list",
    "p_and_id_symbols",
    "p_and_id",
    "mechanical_plan",
    "mechanical_detail",
    "structural",
    "civil",
    "electrical",
    "instrumentation",
    "architectural",
    "appendix",
    "unknown",
}

DRAWING_NUMBER_RE = re.compile(
    r"\b(?:DRAWING|DWG)\s*(?:NO\.?|NUMBER|#)?\s*[:#-]?\s*([A-Z]{1,5}[- ]?\d{2,5}[A-Z]?)\b",
    re.I,
)
LOOSE_DRAWING_RE = re.compile(r"\b(?:G|GN|P|PID|M|S|C|E|EP|EE|I|IN|PLC|FGS|A|B)[- ]?\d{2,5}[A-Z]?\b", re.I)
SHEET_NUMBER_RE = re.compile(r"\b(?:SHEET|SHT)\s*(?:NO\.?|NUMBER|#)?\s*[:#-]?\s*([A-Z]?\d{1,4}(?:\s+OF\s+\d{1,4})?)\b", re.I)
TITLE_LINE_RE = re.compile(r"\b(?:SHEET\s+)?TITLE\s*[:#-]\s*([^\n\r]{3,140})", re.I)
REVISION_RE = re.compile(r"\b(?:REV|REVISION)\s*[:#-]?\s*([A-Z0-9]{1,4})\b", re.I)


def classify_sheet(
    *,
    text: str,
    drawing_number: str = "",
    sheet_title: str = "",
    page_number: int = 0,
) -> dict[str, Any]:
    combined = f"{drawing_number}\n{sheet_title}\n{text[:5000]}".upper()
    drawing = normalize_drawing_number(drawing_number)
    prefix = re.match(r"([A-Z]+)", drawing.replace("-", ""))
    prefix_text = prefix.group(1) if prefix else ""

    candidates: list[tuple[str, float, str]] = []
    add = candidates.append
    if page_number == 1 and _has_any(combined, "COVER", "TITLE SHEET", "VICINITY MAP"):
        add(("cover", 0.82, "first page/title-sheet text"))
    if _has_any(combined, "DRAWING INDEX", "SHEET INDEX", "DRAWING LIST", "INDEX OF DRAWINGS"):
        add(("drawing_index", 0.9, "drawing index text"))
    if _has_any(combined, "GENERAL NOTES", "CONSTRUCTION NOTES", "GENERAL REQUIREMENTS"):
        add(("general_notes", 0.86, "notes title/text"))
    if _has_any(combined, "BILL OF MATERIAL", "BOM", "MATERIAL LIST"):
        add(("bom", 0.86, "bill of materials text"))
    if _has_any(combined, "EQUIPMENT LIST", "EQUIPMENT SCHEDULE"):
        add(("equipment_list", 0.86, "equipment list text"))
    if _has_any(combined, "P&ID SYMBOL", "P AND ID SYMBOL", "SYMBOLS", "LEGEND") and _has_any(combined, "P&ID", "PIPING"):
        add(("p_and_id_symbols", 0.84, "P&ID symbol/legend text"))
    if _has_any(combined, "P&ID", "PIPING AND INSTRUMENTATION", "PROCESS AND INSTRUMENTATION"):
        add(("p_and_id", 0.82, "P&ID text"))
    if _has_any(combined, "MECHANICAL") and _has_any(combined, "DETAIL", "SECTION"):
        add(("mechanical_detail", 0.8, "mechanical detail text"))
    if _has_any(combined, "MECHANICAL", "PLAN VIEW", "PIPING PLAN", "SKID PLAN"):
        add(("mechanical_plan", 0.76, "mechanical/plan text"))
    if _has_any(combined, "STRUCTURAL", "FOUNDATION", "STEEL", "ANCHOR BOLT"):
        add(("structural", 0.78, "structural text"))
    if _has_any(combined, "CIVIL", "GRADING", "EROSION", "SEDIMENT", "SITE PLAN"):
        add(("civil", 0.78, "civil/grading text"))
    if _has_any(combined, "ELECTRICAL", "ONE-LINE", "ONE LINE", "CONDUIT", "PANEL"):
        add(("electrical", 0.78, "electrical text"))
    if _has_any(combined, "INSTRUMENT", "LOOP", "I/O LIST", "IO LIST", "PLC", "SCADA"):
        add(("instrumentation", 0.78, "instrumentation text"))
    if _has_any(combined, "ARCHITECTURAL", "BUILDING", "FLOOR PLAN"):
        add(("architectural", 0.72, "architectural text"))
    if _has_any(combined, "APPENDIX", "ATTACHMENT", "REFERENCE DRAWING"):
        add(("appendix", 0.65, "appendix/reference text"))

    prefix_map = {
        "G": ("general_notes", 0.45),
        "GN": ("general_notes", 0.55),
        "P": ("p_and_id", 0.55),
        "PID": ("p_and_id", 0.65),
        "M": ("mechanical_plan", 0.55),
        "S": ("structural", 0.55),
        "C": ("civil", 0.55),
        "E": ("electrical", 0.55),
        "EP": ("electrical", 0.6),
        "EE": ("electrical", 0.6),
        "I": ("instrumentation", 0.55),
        "IN": ("instrumentation", 0.6),
        "PLC": ("instrumentation", 0.65),
        "FGS": ("instrumentation", 0.6),
        "A": ("architectural", 0.5),
        "B": ("architectural", 0.45),
    }
    if prefix_text in prefix_map:
        discipline, confidence = prefix_map[prefix_text]
        add((discipline, confidence, f"drawing prefix {prefix_text}"))

    if not candidates and page_number == 1:
        add(("cover", 0.45, "first page fallback"))
    if not candidates:
        return {"discipline": "unknown", "confidence": 0.0, "reasons": []}
    candidates.sort(key=lambda item: item[1], reverse=True)
    best = candidates[0]
    return {"discipline": best[0], "confidence": best[1], "reasons": [item[2] for item in candidates[:3]]}


def extract_identity(text: str, page_number: int) -> dict[str, str]:
    drawing_number = _first_group(DRAWING_NUMBER_RE, text)
    if not drawing_number:
        loose = LOOSE_DRAWING_RE.findall(text or "")
        drawing_number = loose[0] if loose else "UNKNOWN"
    sheet_number = _first_group(SHEET_NUMBER_RE, text) or str(page_number)
    sheet_title = _first_group(TITLE_LINE_RE, text)
    if not sheet_title:
        sheet_title = _title_from_heading(text)
    revision = _first_group(REVISION_RE, text) or "UNKNOWN"
    return {
        "drawing_number": normalize_drawing_number(drawing_number) or "UNKNOWN",
        "sheet_number": sheet_number.strip() or str(page_number),
        "sheet_title": sheet_title.strip()[:160] if sheet_title else "Unknown Sheet",
        "revision": revision.strip() or "UNKNOWN",
    }


def normalize_drawing_number(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").upper())
    match = re.match(r"([A-Z]+)-?(\d+[A-Z]?)$", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return text


def _title_from_heading(text: str) -> str:
    for line in (text or "").splitlines():
        clean = re.sub(r"\s+", " ", line).strip(" -:\t")
        if 4 <= len(clean) <= 100 and re.search(r"[A-Za-z]", clean):
            if not re.fullmatch(r"[\d./ -]+", clean):
                return clean
    return ""


def _first_group(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)

