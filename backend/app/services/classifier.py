from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models import SheetType


@dataclass(frozen=True)
class TitleCandidate:
    title: str
    source: str
    confidence: float


@dataclass(frozen=True)
class TitleBlock:
    drawing_number: str = "UNKNOWN"
    sheet_title: str = "Unknown Sheet"
    revision: str = "UNKNOWN"
    project_number: str = "UNKNOWN"
    issue_date: str = "UNKNOWN"
    sheet_title_source: str = "fallback"
    sheet_title_confidence: float = 0.0
    raw_extracted_title: str = ""


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


def extract_title_block(text: str, page_number: int, supplemental_candidates: list[TitleCandidate] | None = None) -> TitleBlock:
    """Extract tolerant title block fields from normal PDF/OCR text.

    Supplemental candidates come from PDF metadata-adjacent sources such as bookmarks,
    page labels, and document metadata. They are ranked with visible title-block text but
    must pass the same sanity checks before becoming the display title.
    """

    lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    compact = "\n".join(lines)

    drawing_number = _field(
        compact,
        [
            r"(?:drawing|dwg)\s*(?:no\.?|number|#)\s*[:\-]\s*([A-Z0-9&.\-]+)",
            r"\b(?:DWG|DRAWING)\s+([A-Z]{1,4}-?\d{2,5}[A-Z]?)\b",
            r"\b((?:PFD|PID|P&ID|M|L|N|D|GA|EP)-?\d{2,5}[A-Z]?)\b",
        ],
    )

    raw_title = _field(
        compact,
        [
            r"(?:sheet\s*)?title\s*[:\-]\s*([^\n]+)",
            r"drawing\s*title\s*[:\-]\s*([^\n]+)",
        ],
    )

    candidates: list[TitleCandidate] = list(supplemental_candidates or [])
    raw_extracted_title = "" if raw_title == "UNKNOWN" else raw_title
    if raw_title != "UNKNOWN":
        candidates.append(TitleCandidate(raw_title, "title_block", 0.88))

    inferred_title = _infer_title_from_lines(lines, page_number)
    if inferred_title != "UNKNOWN":
        if not raw_extracted_title:
            raw_extracted_title = inferred_title
        candidates.append(TitleCandidate(inferred_title, "inferred_text", 0.62))

    selected = select_sheet_title(candidates)
    if selected:
        title = normalize_space(selected.title)[:160]
        title_source = selected.source
        title_confidence = selected.confidence
    elif page_number == 1:
        title = "Cover Sheet"
        title_source = "fallback"
        title_confidence = 0.35
    else:
        title = "Unknown Sheet"
        title_source = "fallback"
        title_confidence = 0.0

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
        sheet_title=title,
        revision=revision.upper(),
        project_number=project_number,
        issue_date=issue_date,
        sheet_title_source=title_source,
        sheet_title_confidence=title_confidence,
        raw_extracted_title=raw_extracted_title[:240],
    )


def select_sheet_title(candidates: list[TitleCandidate]) -> TitleCandidate | None:
    sane_candidates = [
        TitleCandidate(normalize_space(candidate.title), candidate.source, candidate.confidence)
        for candidate in candidates
        if is_sane_sheet_title(candidate.title)
    ]
    if not sane_candidates:
        return None
    return max(sane_candidates, key=lambda candidate: (candidate.confidence, _title_specificity(candidate.title)))


def is_sane_sheet_title(value: str | None) -> bool:
    title = normalize_space(value or "")
    if not title:
        return False

    low = title.lower()
    if low in {"unknown", "unknown sheet", "untitled", "n/a", "na", "none"}:
        return False
    if "..." in title or len(title) > 120:
        return False
    if re.fullmatch(r"[A-Z]{1,4}-?\d{2,5}[A-Z]?", title, flags=re.IGNORECASE):
        return False
    if re.search(r"\b(page|sheet)\s+\d+\b", low) and len(title.split()) <= 3:
        return False

    tokens = re.findall(r"[A-Z0-9&/#\-]+", title.upper())
    word_tokens = [token for token in tokens if re.search(r"[A-Z]", token)]
    if len(word_tokens) >= 6:
        unique_ratio = len(set(word_tokens)) / len(word_tokens)
        adjacent_repeats = sum(1 for left, right in zip(word_tokens, word_tokens[1:]) if left == right)
        if unique_ratio < 0.58 or adjacent_repeats >= 2:
            return False

    if _looks_like_index_row(title):
        return False

    return True


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
    title_keywords = [
        "process flow",
        "p&id",
        "piping and instrumentation",
        "layout",
        "general arrangement",
        "general notes",
        "legend",
        "drawing index",
        "sheet index",
        "cover sheet",
    ]
    for line in lines[:24]:
        candidate = normalize_space(line)
        low = candidate.lower()
        if any(token in low for token in title_keywords) and is_sane_sheet_title(candidate):
            return candidate[:160]
    return "UNKNOWN"


def _looks_like_index_row(title: str) -> bool:
    low = title.lower()
    if low in {"drawing index", "sheet index", "drawing list", "cover sheet"}:
        return False

    table_tokens = [
        "bill",
        "civil",
        "fuel",
        "heat",
        "mechanical",
        "electrical",
        "structural",
        "instrument",
        "instrumentation",
        "p&id",
        "pfd",
        "process",
        "layout",
        "detail",
        "index",
    ]
    hits = sum(1 for token in table_tokens if token in low)
    words = re.findall(r"[A-Z0-9&/#\-]+", title.upper())
    repeated_keywords = any(words.count(token.upper()) >= 3 for token in ["BILL", "CIVIL", "P&ID", "PFD", "FUEL"])
    category_heavy = hits >= 4 and len(words) >= 7
    all_caps_table_row = title == title.upper() and hits >= 3 and len(words) >= 6
    return repeated_keywords or category_heavy or all_caps_table_row


def _title_specificity(title: str) -> int:
    words = re.findall(r"[A-Z0-9&/#\-]+", title.upper())
    return len(set(words))
