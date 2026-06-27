from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import Any

from backend.app.models import EntityType


REGEXES: dict[EntityType, list[re.Pattern[str]]] = {
    EntityType.VALVE_TAG: [
        re.compile(r"\b(?:V|HV|MOV|XV|BV|ESD|SDV|BDV|RV|PSV|PRV)[\s\-]?\d{2,5}[A-Z]?\b", re.I),
    ],
    EntityType.EQUIPMENT_TAG: [
        re.compile(r"\b(?:REG|FLT|FILTER|FIL|SEP|MTR|MON|PCV|FCV)[\s\-]?\d{1,5}[A-Z]?\b", re.I),
    ],
    EntityType.INSTRUMENT_TAG: [
        re.compile(r"\b(?:PI|PG|PT|PIT|PIC|PSH|PSL|PDI|PDG|FI|FT|TI|TT|AIT)[\s\-]?\d{2,5}[A-Z]?\b", re.I),
    ],
    EntityType.LINE_NUMBER: [
        re.compile(r'\b\d{1,2}"?\s*[- ]?[A-Z]{2,6}\s*[- ]?\d{3,6}(?:[- ][A-Z0-9"]+)?\b', re.I),
        re.compile(r"\bLINE\s+[A-Z]{1,6}[- ]?\d{3,6}\b", re.I),
    ],
    EntityType.DRAWING_REFERENCE: [
        re.compile(r"\b(?:PFD|PID|P&ID|M|L|N|D|GA)-?\d{2,5}[A-Z]?\b", re.I),
    ],
    EntityType.NOTE_REFERENCE: [
        re.compile(r"\b(?:NOTE|REF\.?\s*NOTE)\s*\d{1,3}\b", re.I),
    ],
    EntityType.REVISION_CALLOUT: [
        re.compile(r"\b(?:REV|REVISION)\s*[A-Z0-9]\b", re.I),
        re.compile(r"\bDELTA\s*\d+\b", re.I),
    ],
    EntityType.SYMBOL_OR_KEYWORD: [
        re.compile(r"\b(?:BYPASS|VENT|DRAIN|RELIEF|SLAM[- ]SHUT|MONITOR|SENSING\s+LINE|PILOT)\b", re.I),
    ],
}


def normalize_entity_text(entity_type: str, text: str) -> str:
    value = re.sub(r"\s+", "", text.upper().strip())
    value = value.replace("P&ID", "PID")
    if entity_type in {EntityType.VALVE_TAG.value, EntityType.EQUIPMENT_TAG.value, EntityType.INSTRUMENT_TAG.value}:
        match = re.match(r"([A-Z]+)-?(\d+[A-Z]?)", value)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    if entity_type == EntityType.LINE_NUMBER.value:
        return value.replace("LINE", "").strip("-")
    return value


def extract_entities(
    project_id: str,
    sheet_id: str,
    page_number: int,
    text: str,
    blocks: Iterable[tuple[float, float, float, float, str]] | None = None,
    source: str = "pdf_text",
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int | None, int | None]] = set()
    block_list = list(blocks or [])

    for entity_type, patterns in REGEXES.items():
        for pattern in patterns:
            for match in pattern.finditer(text or ""):
                raw = match.group(0).strip()
                normalized = normalize_entity_text(entity_type.value, raw)
                bbox = _find_block_bbox(block_list, raw)
                key = (
                    entity_type.value,
                    normalized,
                    page_number,
                    round(bbox["x0"]) if bbox else None,
                    round(bbox["y0"]) if bbox else match.start(),
                )
                if key in seen:
                    continue
                seen.add(key)
                entities.append(
                    {
                        "id": str(uuid.uuid4()),
                        "project_id": project_id,
                        "sheet_id": sheet_id,
                        "entity_type": entity_type.value,
                        "text": raw,
                        "normalized_text": normalized,
                        "page_number": page_number,
                        "bbox": bbox,
                        "confidence": 0.88 if bbox else 0.72,
                        "source": source,
                    }
                )

    for label, value in _extract_title_fields(text).items():
        if value == "UNKNOWN":
            continue
        entities.append(
            {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "sheet_id": sheet_id,
                "entity_type": EntityType.TITLE_BLOCK_FIELD.value,
                "text": f"{label}: {value}",
                "normalized_text": f"{label.upper()}:{value.upper()}",
                "page_number": page_number,
                "bbox": None,
                "confidence": 0.7,
                "source": source,
            }
        )

    return entities


def _find_block_bbox(blocks: list[tuple[float, float, float, float, str]], needle: str) -> dict[str, float] | None:
    normalized_needle = re.sub(r"\s+", "", needle.lower())
    for x0, y0, x1, y1, block_text in blocks:
        if normalized_needle in re.sub(r"\s+", "", block_text.lower()):
            return {"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}
    return None


def _extract_title_fields(text: str) -> dict[str, str]:
    fields = {
        "drawing_number": "UNKNOWN",
        "revision": "UNKNOWN",
        "sheet_title": "UNKNOWN",
    }
    patterns = {
        "drawing_number": r"(?:drawing|dwg)\s*(?:no\.?|number|#)\s*[:\-]\s*([A-Z0-9&.\-]+)",
        "revision": r"\brev(?:ision)?\s*[:\-]\s*([A-Z0-9]+)\b",
        "sheet_title": r"(?:sheet\s*)?title\s*[:\-]\s*([^\n]+)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text or "", flags=re.I)
        if match:
            fields[field] = match.group(1).strip()[:160]
    return fields
