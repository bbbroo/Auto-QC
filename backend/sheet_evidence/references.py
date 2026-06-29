from __future__ import annotations

import re

from backend.sheet_evidence.classifier import normalize_drawing_number
from backend.sheet_evidence.models import EngineeringTokens, ReferenceEvidence


DRAWING_REF_RE = re.compile(r"\b(?:G|GN|P|PID|M|S|C|E|EP|EE|I|IN|PLC|FGS|A|B)[- ]?\d{2,5}[A-Z]?\b", re.I)
SHEET_REF_RE = re.compile(r"\bSEE\s+(?:SHEET|SHT)\s+((?:[A-Z]{1,4}[- ]?)?\d{2,5}[A-Z]?)\b", re.I)
DRAWING_SEE_RE = re.compile(r"\bSEE\s+(?:DRAWING|DWG)\s+([A-Z]{1,4}[- ]?\d{2,5}[A-Z]?)\b", re.I)
DETAIL_RE = re.compile(r"\bDETAIL\s+([A-Z0-9]+)\s*/\s*([A-Z]{1,4}[- ]?\d{2,5}[A-Z]?)\b", re.I)
SECTION_RE = re.compile(r"\bSECTION\s+([A-Z0-9]+)\s*/\s*([A-Z]{1,4}[- ]?\d{2,5}[A-Z]?)\b", re.I)
REFER_TO_RE = re.compile(r"\bREFER\s+TO\s+([A-Z]{1,4}[- ]?\d{2,5}[A-Z]?)\b", re.I)
NOTE_RE = re.compile(r"\b(?:NOTE|NOTES|GENERAL NOTE|KEYNOTE|REF\.?\s*NOTE)\s*#?\s*(\d{1,3})?\b", re.I)

VALVE_RE = re.compile(r"\b(?:V|HV|MOV|XV|BV|ESD|SDV|BDV|RV|PSV|PRV)[-\s]?\d{1,5}[A-Z]?\b", re.I)
INSTRUMENT_RE = re.compile(r"\b(?:FV|PT|PIT|PI|PIC|PSH|PSL|PDI|PDG|TI|TT|TE|FI|FIT|FT|AIT|PLC|SCADA)[-\s]?\d{1,5}[A-Z]?\b", re.I)
EQUIPMENT_RE = re.compile(r"\b(?:REG|FLT|FILTER|FIL|SEP|MTR|MON|PCV|FCV|P|V)[-\s]?\d{1,5}[A-Z]?\b", re.I)
PIPE_SIZE_RE = re.compile(r"\b(?:\d{1,2}\s*(?:\"|INCH|IN\.?|-\s?IN)|NPS\s*\d{1,2}|SCH\s*\d{1,3})\b", re.I)
LINE_NUMBER_RE = re.compile(r'\b(?:LINE\s+)?\d{1,2}"?\s*[- ]?[A-Z]{2,8}\s*[- ]?\d{2,6}(?:[- ][A-Z0-9"]+)?\b', re.I)
SPEC_RE = re.compile(r"\b(?:ASME|API|NFPA|CFR|DOT|ASTM|ANSI|AWWA|IEEE|NEC|NACE)\s*[A-Z0-9./-]*\b", re.I)


def extract_references(text: str) -> ReferenceEvidence:
    drawing_refs = _unique(normalize_drawing_number(item) for item in DRAWING_REF_RE.findall(text or ""))
    sheet_refs = _unique(normalize_drawing_number(item) for item in SHEET_REF_RE.findall(text or ""))
    sheet_refs.extend(item for item in _unique(normalize_drawing_number(item) for item in DRAWING_SEE_RE.findall(text or "")) if item not in sheet_refs)
    detail_refs = _unique(f"DETAIL {detail}/{normalize_drawing_number(sheet)}" for detail, sheet in DETAIL_RE.findall(text or ""))
    section_refs = _unique(f"SECTION {section}/{normalize_drawing_number(sheet)}" for section, sheet in SECTION_RE.findall(text or ""))
    note_refs = _unique(match.group(0).strip().upper() for match in NOTE_RE.finditer(text or ""))
    refer_to = _unique(normalize_drawing_number(item) for item in REFER_TO_RE.findall(text or ""))
    cross = _unique([*sheet_refs, *detail_refs, *section_refs, *refer_to])
    return ReferenceEvidence(
        drawing_references=drawing_refs,
        sheet_references=sheet_refs,
        detail_references=detail_refs,
        section_references=section_refs,
        note_references=note_refs,
        cross_references=cross,
    )


def extract_engineering_tokens(text: str) -> EngineeringTokens:
    return EngineeringTokens(
        equipment_tags=_unique(_normalize_tag(item) for item in EQUIPMENT_RE.findall(text or "")),
        instrument_tags=_unique(_normalize_tag(item) for item in INSTRUMENT_RE.findall(text or "")),
        valve_tags=_unique(_normalize_tag(item) for item in VALVE_RE.findall(text or "")),
        pipe_size_tokens=_unique(item.upper().replace("IN.", "IN") for item in PIPE_SIZE_RE.findall(text or "")),
        line_numbers=_unique(re.sub(r"\s+", "", item.upper()) for item in LINE_NUMBER_RE.findall(text or "")),
        spec_or_code_references=_unique(item.upper() for item in SPEC_RE.findall(text or "")),
    )


def _normalize_tag(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").upper())
    match = re.match(r"([A-Z]+)-?(\d+[A-Z]?)$", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return text


def _unique(values: object) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered

