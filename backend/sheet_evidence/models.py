from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExtractionStrategy:
    text_extractor: str
    layout_extractor: str
    table_extractor: str
    rendering_tool: str


@dataclass
class QualityScores:
    text_score: float = 0.0
    layout_score: float = 0.0
    table_score: float = 0.0
    overall_score: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class TextEvidence:
    full_text: str = ""
    important_text: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    title_block_text: str = ""
    revision_block_text: str = ""


@dataclass
class EvidenceBlock:
    type: str
    text: str = ""
    bbox: list[float] | None = None
    source: str = "unknown"
    confidence: float | None = None


@dataclass
class EvidenceTable:
    type: str
    content: str
    format: str = "text"
    bbox: list[float] | None = None
    source: str = "unknown"


@dataclass
class ReferenceEvidence:
    drawing_references: list[str] = field(default_factory=list)
    sheet_references: list[str] = field(default_factory=list)
    detail_references: list[str] = field(default_factory=list)
    section_references: list[str] = field(default_factory=list)
    note_references: list[str] = field(default_factory=list)
    cross_references: list[str] = field(default_factory=list)


@dataclass
class EngineeringTokens:
    equipment_tags: list[str] = field(default_factory=list)
    instrument_tags: list[str] = field(default_factory=list)
    valve_tags: list[str] = field(default_factory=list)
    pipe_size_tokens: list[str] = field(default_factory=list)
    line_numbers: list[str] = field(default_factory=list)
    spec_or_code_references: list[str] = field(default_factory=list)


@dataclass
class RenderedPageImage:
    path: str | None = None
    width: int | None = None
    height: int | None = None
    dpi: int | None = None


@dataclass
class SourceFiles:
    raw_extraction: str | None = None
    debug_text: str | None = None


@dataclass
class SheetEvidencePacket:
    pdf_path: str
    pdf_name: str
    page_number: int
    page_count: int
    sheet_number: str
    drawing_number: str
    sheet_title: str
    discipline: str
    page_width: float
    page_height: float
    extraction_strategy: ExtractionStrategy
    quality: QualityScores
    text: TextEvidence
    layout_blocks: list[EvidenceBlock] = field(default_factory=list)
    tables: list[EvidenceTable] = field(default_factory=list)
    references: ReferenceEvidence = field(default_factory=ReferenceEvidence)
    engineering_tokens: EngineeringTokens = field(default_factory=EngineeringTokens)
    rendered_page_image: RenderedPageImage = field(default_factory=RenderedPageImage)
    source_files: SourceFiles = field(default_factory=SourceFiles)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackageIndexEntry:
    drawing_number: str
    sheet_number: str
    title: str
    page_number: int
    discipline: str = "unknown"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

