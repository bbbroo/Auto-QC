from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PageSample:
    page_number: int
    reason: str
    confidence: float


QUICK_PAGE_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("drawing_index", (r"\bdrawing\s+index\b", r"\bsheet\s+index\b", r"\bdrawing\s+list\b")),
    ("general_notes", (r"\bgeneral\s+notes?\b", r"\bconstruction\s+notes?\b")),
    ("bom_or_equipment_list", (r"\bbill\s+of\s+materials?\b", r"\bBOM\b", r"\bequipment\s+list\b")),
    ("pid_symbols_legend", (r"\bP\s*&\s*ID\s+symbols?\b", r"\bsymbols?\b", r"\blegend\b")),
    ("proposed_pid", (r"\bproposed\b.*\bP\s*&?\s*ID\b", r"\bpiping\s+and\s+instrumentation\b", r"\bP\s*&\s*ID\b")),
    ("mechanical_plan", (r"\bmechanical\b.*\bplan\b", r"\bplan\s+view\b")),
    ("mechanical_detail", (r"\bmechanical\b.*\bdetail\b", r"\bdetail\s+(?:sheet|view|section)\b")),
    ("structural", (r"\bstructural\b", r"\bfoundation\b", r"\bsteel\b")),
    ("civil_grading_erosion", (r"\bcivil\b", r"\bgrading\b", r"\berosion\b", r"\bsediment\b")),
    ("electrical", (r"\belectrical\b", r"\bone[-\s]?line\b", r"\bpanel\b", r"\bconduit\b")),
    ("instrument_list_or_loop", (r"\binstrument\s+list\b", r"\bloop\s+drawing\b", r"\bI/O\s+list\b")),
)


def select_pages(
    pdf_path: Path,
    *,
    mode: str = "quick",
    explicit_pages: list[int] | None = None,
    max_pages: int | None = None,
) -> list[PageSample]:
    page_count = get_page_count(pdf_path)
    if page_count < 1:
        return []

    if explicit_pages:
        samples = [
            PageSample(page, "explicit", 1.0)
            for page in _dedupe(page for page in explicit_pages if 1 <= page <= page_count)
        ]
        return _limit(samples, max_pages)

    if mode == "full":
        return _limit([PageSample(page, "full", 1.0) for page in range(1, page_count + 1)], max_pages)

    return _limit(_quick_samples(pdf_path, page_count), max_pages)


def get_page_count(pdf_path: Path) -> int:
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _quick_samples(pdf_path: Path, page_count: int) -> list[PageSample]:
    page_texts = _extract_page_texts(pdf_path)
    selected: dict[int, PageSample] = {1: PageSample(1, "cover_or_first_sheet", 0.8)}

    for reason, patterns in QUICK_PAGE_TARGETS:
        match = _first_matching_page(page_texts, patterns, selected.keys())
        if match:
            page_number, confidence = match
            selected.setdefault(page_number, PageSample(page_number, reason, confidence))

    selected.setdefault(page_count, PageSample(page_count, "near_end_title_block_heavy_sheet", 0.55))

    minimum = min(page_count, 8)
    if len(selected) < minimum:
        for page_number in _spread_pages(page_count, minimum):
            selected.setdefault(page_number, PageSample(page_number, "spread_fallback", 0.35))
            if len(selected) >= minimum:
                break

    return [selected[page] for page in sorted(selected)]


def _extract_page_texts(pdf_path: Path) -> dict[int, str]:
    texts: dict[int, str] = {}
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            for index, page in enumerate(doc, start=1):
                try:
                    texts[index] = (page.get_text("text", sort=True) or "")[:8000]
                except Exception:
                    texts[index] = ""
    except Exception:
        return texts
    return texts


def _first_matching_page(
    page_texts: dict[int, str],
    patterns: tuple[str, ...],
    already_selected: object,
) -> tuple[int, float] | None:
    selected = set(already_selected)
    for page_number, text in page_texts.items():
        if page_number in selected:
            continue
        normalized = text or ""
        if not normalized.strip():
            continue
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.I | re.S):
                return page_number, 0.75
    return None


def _spread_pages(page_count: int, count: int) -> list[int]:
    if count <= 1:
        return [1]
    if page_count <= count:
        return list(range(1, page_count + 1))
    values = {1, page_count}
    for index in range(count):
        page = 1 + round(index * (page_count - 1) / (count - 1))
        values.add(max(1, min(page_count, page)))
    return sorted(values)


def _dedupe(values: object) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        page = int(value)
        if page in seen:
            continue
        seen.add(page)
        ordered.append(page)
    return ordered


def _limit(samples: list[PageSample], max_pages: int | None) -> list[PageSample]:
    if max_pages is None or max_pages < 1:
        return samples
    return samples[:max_pages]

