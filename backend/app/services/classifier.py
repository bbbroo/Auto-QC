from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models import SheetType


@dataclass(frozen=True)
class TitleBlock:
    drawing_number: str = "UNKNOWN"
    sheet_title: str = "Unknown Sheet"
    revision: str = "UNKNOWN"
    project_number: str = "UNKNOWN"
    issue_date: str = "UNKNOWN"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def classify_sheet(text: str, page_number: int, drawing_number: str = "", title: str = "") -> str:
    haystack = f"{drawing_number}\n{title}\n{text}".lower()
    scores: dict[SheetType, int] = {kind: 0 for kind in SheetType}

    keyword_scores = {
        SheetType.PID: [
            "p&id",
            "piping and instrumentation",
            "piping & instrumentation",
            "process and instrumentation",
            "instrumentation diagram",
        ],
        SheetType.PFD: ["process flow diagram", " pfd ", "flow diagram", "process flow"],
        SheetType.LAYOUT: ["layout", "general arrangement", "plot plan", "plan view", "station layout"],
        SheetType.LEGEND: ["legend", "symbols", "abbreviations"],
        SheetType.NOTES: ["general notes", "notes", "specification", "design basis"],
        SheetType.DETAIL: ["detail", "typical", "section", "installation detail"],
        SheetType.INDEX: ["drawing index", "sheet index", "drawing list"],
        SheetType.COVER: ["cover sheet", "title sheet", "cover"],
    }
    for sheet_type, keywords in keyword_scores.items():
        for keyword in keywords:
            if keyword in haystack:
                scores[sheet_type] += 4 if len(keyword.strip()) > 4 else 2

    number = drawing_number.upper()
    if re.search(r"\b(PID|P&ID|PI)-?\d+", number):
        scores[SheetType.PID] += 5
    if re.search(r"\b(PFD|PF)-?\d+", number):
        scores[SheetType.PFD] += 5
    if re.search(r"\b(GA|L|LAY)-?\d+", number):
        scores[SheetType.LAYOUT] += 3
    if re.search(r"\b(N|GN)-?\d+", number):
        scores[SheetType.NOTES] += 2

    if page_number == 1 and max(scores.values()) < 4:
        scores[SheetType.COVER] += 1

    best = max(scores, key=lambda item: scores[item])
    return best.value if scores[best] > 0 else SheetType.UNKNOWN.value


def extract_title_block(text: str, page_number: int) -> TitleBlock:
    """Extract tolerant title block fields from normal PDF/OCR text."""

    lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    compact = "\n".join(lines)

    drawing_number = _field(
        compact,
        [
            r"(?:drawing|dwg)\s*(?:no\.?|number|#)\s*[:\-]\s*([A-Z0-9&.\-]+)",
            r"\b(?:DWG|DRAWING)\s+([A-Z]{1,4}-?\d{2,5}[A-Z]?)\b",
            r"\b((?:PFD|PID|P&ID|M|L|N|D|GA)-?\d{2,5}[A-Z]?)\b",
        ],
    )

    title = _field(
        compact,
        [
            r"(?:sheet\s*)?title\s*[:\-]\s*([^\n]+)",
            r"drawing\s*title\s*[:\-]\s*([^\n]+)",
        ],
    )
    if title == "UNKNOWN":
        title = _infer_title_from_lines(lines, page_number)

    revision = _field(
        compact,
        [
            r"\brev(?:ision)?\s*[:\-]\s*([A-Z0-9]+)\b",
            r"\brevision\s+([A-Z0-9]+)\b",
        ],
    )
    project_number = _field(compact, [r"project\s*(?:no\.?|number|#)\s*[:\-]\s*([A-Z0-9.\-]+)"])
    issue_date = _field(compact, [r"(?:issue|issued|date)\s*(?:date)?\s*[:\-]\s*([0-9]{1,4}[/-][0-9]{1,2}[/-][0-9]{1,4})"])

    return TitleBlock(
        drawing_number=drawing_number.upper(),
        sheet_title=title[:160],
        revision=revision.upper(),
        project_number=project_number,
        issue_date=issue_date,
    )


def _field(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = normalize_space(match.group(1))
            value = re.split(r"\s{2,}|\s+\|\s+", value)[0].strip(" ;,")
            if value:
                return value
    return "UNKNOWN"


def _infer_title_from_lines(lines: list[str], page_number: int) -> str:
    for line in lines[:18]:
        low = line.lower()
        if any(token in low for token in ["process flow", "p&id", "layout", "general notes", "legend", "drawing index"]):
            return line[:160]
    return "Cover Sheet" if page_number == 1 else "Unknown Sheet"

