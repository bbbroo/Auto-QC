from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SheetType(str, Enum):
    COVER = "cover"
    INDEX = "drawing_index"
    PFD = "pfd"
    PID = "p&id"
    LAYOUT = "layout"
    LEGEND = "legend"
    NOTES = "notes"
    DETAIL = "detail"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    LINE_NUMBER = "line_number"
    VALVE_TAG = "valve_tag"
    EQUIPMENT_TAG = "equipment_tag"
    INSTRUMENT_TAG = "instrument_tag"
    NOTE_REFERENCE = "note_reference"
    DRAWING_REFERENCE = "drawing_reference"
    REVISION_CALLOUT = "revision_callout"
    TITLE_BLOCK_FIELD = "title_block_field"
    SYMBOL_OR_KEYWORD = "symbol_or_keyword"


class FindingCategory(str, Enum):
    TAG_CONSISTENCY = "tag consistency"
    LINE_NUMBER_CONSISTENCY = "line number consistency"
    DRAWING_COORDINATION = "drawing coordination"
    MISSING_INFORMATION = "missing information"
    REGULATOR_STATION_DESIGN = "regulator station design"
    SAFETY_OPERABILITY = "safety and operability"
    OVERPRESSURE_PROTECTION = "overpressure protection"
    INSTRUMENTATION = "instrumentation"
    DRAFTING_QUALITY = "drafting quality"
    TITLE_BLOCK_REVISION = "title block and revision"
    BOM_COUNT = "BOM or count issue"
    NOTES_SPECIFICATIONS = "notes and specifications"
    HUMAN_REVIEW_NEEDED = "human review needed"


class Severity(str, Enum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    NOTE = "Note"


class FindingStatus(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class ReviewStatus(str, Enum):
    NEW = "new"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class Evidence(BaseModel):
    observation: str
    sheet_id: str | None = None
    page_number: int | None = None
    text_excerpt: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.75


class ProjectRecord(BaseModel):
    id: str
    name: str
    source_pdf_path: str | None = None
    status: str = ReviewStatus.NEW.value
    summary: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    sheet_count: int = 0
    finding_count: int = 0


class SheetRecord(BaseModel):
    id: str
    project_id: str
    page_number: int
    drawing_number: str = "UNKNOWN"
    sheet_title: str = "Unknown Sheet"
    revision: str = "UNKNOWN"
    sheet_type: str = SheetType.UNKNOWN.value
    extraction_status: str = "pending"
    ocr_status: str = "not_required"
    image_path: str | None = None
    image_url: str | None = None
    text_content: str = ""
    width: float = 0
    height: float = 0
    review_status: str = "new"


class EntityRecord(BaseModel):
    id: str
    project_id: str
    sheet_id: str
    entity_type: str
    text: str
    normalized_text: str
    page_number: int
    bbox: BoundingBox | None = None
    confidence: float = 0.75
    source: str = "pdf_text"


class StationComponent(BaseModel):
    component_type: str
    present: bool
    sheet_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.0


class StationGraph(BaseModel):
    project_id: str
    components: dict[str, StationComponent] = Field(default_factory=dict)
    pfd_sheet_ids: list[str] = Field(default_factory=list)
    pid_sheet_ids: list[str] = Field(default_factory=list)
    line_numbers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class FindingRecord(BaseModel):
    id: str
    project_id: str
    sheet_id: str | None = None
    stable_id: str
    title: str
    category: str
    severity: str
    confidence: float
    page_number: int | None = None
    location: BoundingBox | None = None
    involved_entities: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning_summary: str
    suggested_correction: str
    comment_text: str
    status: str = FindingStatus.NEEDS_REVIEW.value
    source: str = "rules"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class FindingUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    severity: str | None = None
    confidence: float | None = None
    reasoning_summary: str | None = None
    suggested_correction: str | None = None
    comment_text: str | None = None
    status: Literal["accepted", "needs_review", "rejected"] | None = None


class ExportRecord(BaseModel):
    id: str
    project_id: str
    export_dir: str
    marked_pdf_path: str | None = None
    csv_path: str | None = None
    xlsx_path: str | None = None
    json_path: str | None = None
    summary_path: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ExportResponse(BaseModel):
    export: ExportRecord
    files: dict[str, str]


JsonDict = dict[str, Any]

