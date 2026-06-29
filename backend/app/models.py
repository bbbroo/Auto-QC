from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_MANUAL_PLACEMENT = "needs_manual_placement"
    NEEDS_ENGINEER_INPUT = "needs_engineer_input"
    DUPLICATE = "duplicate"
    DEFERRED = "deferred"


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
    project_type: str = "review"
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
    rotation: int = 0
    source_width: float = 0
    source_height: float = 0
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
    original_ai_json: JsonDict | None = None
    ai_batch_id: str | None = None
    prompt_version: str | None = None
    reviewer_note: str | None = None
    placement_status: str | None = None
    placement_details: JsonDict | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class FindingUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    severity: Literal["Critical", "Major", "Minor", "Note"] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    page_number: int | None = Field(default=None, ge=1)
    target_text: str | None = None
    reasoning_summary: str | None = None
    rationale: str | None = None
    suggested_correction: str | None = None
    required_update: str | None = None
    comment_text: str | None = None
    reviewer_note: str | None = None
    duplicate_of: str | None = None
    status: Literal[
        "needs_review",
        "accepted",
        "rejected",
        "needs_manual_placement",
        "needs_engineer_input",
        "duplicate",
        "deferred",
    ] | None = None


class BulkFindingUpdate(BaseModel):
    finding_ids: list[str] = Field(default_factory=list, min_length=1)
    update: FindingUpdate


class ExportRequest(BaseModel):
    export_mode: Literal["draft", "final"] = "draft"
    statuses: list[
        Literal[
            "needs_review",
            "accepted",
            "rejected",
            "needs_manual_placement",
            "needs_engineer_input",
            "duplicate",
            "deferred",
        ]
    ] | None = Field(default=None, min_length=1)
    accepted_only: bool | None = None
    reviewer_name: str | None = None
    final_export_confirmed: bool = False
    acknowledge_validation_warnings: bool = False


MAX_AI_RESPONSE_CHARS = 2_000_000


class ManualAIPreviewRequest(BaseModel):
    response_text: str = Field(min_length=2, max_length=MAX_AI_RESPONSE_CHARS)
    source_type: str = "manual_chat_prompt"
    prompt_version: str | None = None
    prompt_id: str | None = None
    review_modality: str | None = None
    audit_of_batch_id: str | None = None
    audit_round: int | None = Field(default=None, ge=1)


class ManualAIImportRequest(BaseModel):
    response_text: str | None = Field(default=None, max_length=MAX_AI_RESPONSE_CHARS)
    preview_id: str | None = None
    source_type: str = "manual_chat_prompt"
    prompt_version: str | None = None
    prompt_id: str | None = None
    review_modality: str | None = None
    audit_of_batch_id: str | None = None
    audit_round: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def response_or_preview_required(self) -> "ManualAIImportRequest":
        if not (self.preview_id or (self.response_text and self.response_text.strip())):
            raise ValueError("Provide preview_id from Preview AI Updates or response_text to import.")
        return self


class RollbackRequest(BaseModel):
    confirm: bool = False


class MergeFindingRequest(BaseModel):
    target_finding_id: str


class ManualPlacementRequest(BaseModel):
    page_number: int = Field(ge=1)
    rect: list[float] = Field(min_length=4, max_length=4)
    coordinate_space: Literal["image_pixel", "pdf_unrotated", "display_rotated"] = "image_pixel"
    image_width: float | None = Field(default=None, gt=0)
    image_height: float | None = Field(default=None, gt=0)
    display_width: float | None = None
    display_height: float | None = None
    page_rotation: int | None = None
    source_width: float | None = None
    source_height: float | None = None


class ChecklistSelectRequest(BaseModel):
    checklist_id: str


class ChecklistItemUpdate(BaseModel):
    status: Literal["not_started", "checked", "issue_found", "not_applicable", "needs_human_review"] | None = None
    applicability: str | None = None
    mapped_finding_ids: list[str] | None = None
    reviewer_notes: str | None = None


class ProjectPackageImportResponse(BaseModel):
    project: dict[str, Any]
    original_project_id: str
    restored_project_id: str
    remapped_ids: bool


class ExportRecord(BaseModel):
    id: str
    project_id: str
    export_dir: str
    marked_pdf_path: str | None = None
    csv_path: str | None = None
    qa_report_path: str | None = None
    xlsx_path: str | None = None
    json_path: str | None = None
    summary_path: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ExportResponse(BaseModel):
    export: ExportRecord
    files: dict[str, str]


JsonDict = dict[str, Any]


class ManualAIPromptResponse(BaseModel):
    project_id: str
    prompt_id: str
    prompt_version: str
    generated_at: str
    prompt: str
    payload_sheet_count: int
    instructions: str
    prompt_metadata: JsonDict = Field(default_factory=dict)


class AIImportBatchRecord(BaseModel):
    id: str
    project_id: str
    source_type: str = "unknown"
    prompt_version: str | None = None
    prompt_id: str | None = None
    raw_response_text: str | None = None
    parser_warnings: list[str] = Field(default_factory=list)
    parser_repairs: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    valid_count: int = 0
    skipped_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    import_status: str = "previewed"
    preview: JsonDict | None = None
    metadata: JsonDict = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    imported_at: str | None = None
