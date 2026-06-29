export type Severity = "Critical" | "Major" | "Minor" | "Note";

export type FindingStatus =
  | "needs_review"
  | "accepted"
  | "rejected"
  | "needs_manual_placement"
  | "needs_engineer_input"
  | "duplicate"
  | "deferred";

export type PlacementStatus =
  | "exact_target_found"
  | "fuzzy_target_found"
  | "page_level_fallback"
  | "manual_placement_needed"
  | string;

export type SheetType =
  | "cover"
  | "drawing_index"
  | "pfd"
  | "p&id"
  | "layout"
  | "legend"
  | "notes"
  | "detail"
  | "unknown"
  | string;

export interface Project {
  id: string;
  name: string;
  status: string;
  source_pdf_path?: string | null;
  source_pdf_url?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  summary?: string | null;
  review_summary?: string | null;
  sheet_count?: number;
  finding_count?: number;
  findings_count?: number;
  finding_status_counts?: Record<string, number>;
  finding_severity_counts?: Record<string, number>;
  finding_category_counts?: Record<string, number>;
  review_coverage?: ReviewCoverageSummary | null;
}

export interface Sheet {
  id: string;
  project_id: string;
  page_number: number;
  drawing_number?: string | null;
  sheet_title?: string | null;
  sheet_title_source?: string | null;
  sheet_title_confidence?: number | null;
  raw_extracted_title?: string | null;
  revision?: string | null;
  sheet_type?: SheetType | null;
  extraction_status?: string | null;
  ocr_status?: string | null;
  image_path?: string | null;
  image_url?: string | null;
  text_content?: string | null;
  width?: number | null;
  height?: number | null;
  rotation?: number | null;
  source_width?: number | null;
  source_height?: number | null;
}

export interface Evidence {
  observation?: string;
  sheet_id?: string | null;
  page_number?: number | null;
  drawing_number?: string | null;
  text_excerpt?: string | null;
  target_text?: string | null;
  markup_text?: string | null;
  required_update?: string | null;
  rationale?: string | null;
  ai_batch_id?: string | null;
  prompt_version?: string | null;
  source?: string;
  confidence?: number;
}

export interface LocationPayload {
  bbox?: number[] | null;
  rect?: number[] | null;
  x0?: number;
  y0?: number;
  x1?: number;
  y1?: number;
  left?: number;
  top?: number;
  width?: number;
  height?: number;
  origin?: "top_left" | "bottom_left" | string;
  [key: string]: unknown;
}

export interface Finding {
  id: string;
  project_id: string;
  sheet_id?: string | null;
  stable_id?: string;
  title: string;
  category: string;
  severity: Severity;
  confidence: number;
  page_number?: number | null;
  location?: LocationPayload | number[] | null;
  involved_entities?: string[];
  evidence?: Evidence[];
  reasoning_summary: string;
  suggested_correction: string;
  comment_text: string;
  status: FindingStatus;
  source?: string;
  original_ai_json?: Record<string, unknown> | null;
  ai_batch_id?: string | null;
  prompt_version?: string | null;
  reviewer_note?: string | null;
  placement_status?: PlacementStatus | null;
  placement_details?: Record<string, unknown> | null;
  duplicate_of?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FindingUpdate {
  title?: string;
  category?: string;
  severity?: Severity;
  confidence?: number;
  page_number?: number;
  target_text?: string;
  reasoning_summary?: string;
  rationale?: string;
  suggested_correction?: string;
  required_update?: string;
  comment_text?: string;
  reviewer_note?: string;
  status?: FindingStatus;
  duplicate_of?: string | null;
}

export interface FindingEvent {
  id: string;
  project_id: string;
  finding_id?: string | null;
  stable_id?: string | null;
  action: string;
  changes?: Record<string, unknown>;
  created_at: string;
}

export interface BulkFindingResponse {
  updated: Finding[];
  count: number;
}

export interface AIStatus {
  configured: boolean;
  provider?: string | null;
  model?: string | null;
  base_url?: string | null;
  max_sheets?: number;
  api_key_saved?: boolean;
  api_key_hint?: string | null;
  settings_path?: string | null;
  available_providers?: string[];
}

export interface AISettingsRequest {
  api_key: string;
  model: string;
  provider?: "openai" | "deepseek";
  base_url?: string;
}

export interface AIReviewResponse {
  project: Project;
  direct_review_mode?: "text_context_only" | string;
  direct_review_sheet_limit_applied?: boolean;
  direct_review_sent_sheet_count?: number;
  direct_review_total_sheet_count?: number;
  warnings?: string[];
  ai_findings_created: number;
  ai_updates_imported?: number;
  raw_ai_count: number;
  imported_stable_ids?: string[];
  imported_finding_ids?: string[];
  batch?: AIImportBatch;
  quality_report?: ImportQualityReport;
  findings: Finding[];
}

export interface ManualAIPromptResponse {
  project_id: string;
  prompt_id?: string;
  prompt_version?: string;
  generated_at?: string;
  prompt: string;
  payload_sheet_count: number;
  instructions: string;
  prompt_metadata?: Record<string, unknown>;
  review_plan?: ManualReviewPlan | null;
}

export type ManualReviewScope = "package" | "batch" | "sheet";

export interface ManualReviewBatch {
  id: string;
  label: string;
  page_numbers: number[];
  batch_index: number;
  batch_count: number;
  status: "unreviewed" | "partial" | "reviewed" | string;
  reviewed_pages?: number[];
}

export interface ManualReviewDeepDiveCandidate {
  sheet_id?: string | null;
  page_number: number;
  drawing_number?: string | null;
  sheet_title?: string | null;
  sheet_type?: string | null;
  label: string;
  reasons: string[];
  score: number;
  status: "unreviewed" | "reviewed" | string;
}

export interface ManualReviewPlan {
  project_id: string;
  sheet_count: number;
  batch_size: number;
  batches: ManualReviewBatch[];
  deep_dive_candidates: ManualReviewDeepDiveCandidate[];
  reviewed_pages: number[];
  unreviewed_pages: number[];
  review_coverage?: ReviewCoverageSummary;
  review_coverage_status?: "complete" | "incomplete" | "not_confirmed" | string;
  review_coverage_percent?: number;
}

export interface AIPreviewUpdate {
  index: number;
  valid: boolean;
  will_import: boolean;
  action?: "create_new" | "update_existing" | "duplicate_in_response" | "skipped" | string;
  duplicate_kind?: "exact" | "likely" | "same_page_same_issue" | string;
  duplicate_reason?: string | null;
  related_update_indices?: number[];
  stable_id?: string | null;
  stable_id_match?: boolean;
  existing_finding_id?: string | null;
  page_number?: number | null;
  raw_page?: unknown;
  target_text?: string | null;
  required_update?: string | null;
  rationale?: string | null;
  category?: string | null;
  severity?: Severity | string | null;
  confidence?: number | null;
  issue?: string | null;
  warnings?: string[];
  missing_or_weak_fields?: string[];
  skipped_reason?: string | null;
}

export interface AIPreviewResponse {
  batch_id: string;
  project_id: string;
  source_type?: string;
  prompt_version?: string | null;
  prompt_id?: string | null;
  schema_version?: string | null;
  parser_mode?: string | null;
  response_shape?: string | null;
  review_scope?: ManualReviewScope | string | null;
  review_strategy?: string | null;
  scope_pages?: number[];
  scope_label?: string | null;
  expected_review_pages?: number[];
  reviewed_pages?: Array<{ page_number: number; review_status: string; issue_count: number; notes?: string | null }>;
  reviewed_page_numbers?: number[];
  reviewed_pages_confirmed?: number[];
  missing_review_pages?: number[];
  incomplete_review_pages?: number[];
  not_readable_pages?: number[];
  review_coverage_status?: "complete" | "incomplete" | "not_confirmed" | string;
  review_coverage_percent?: number;
  review_coverage?: ReviewCoverageSummary;
  pages_without_review_confirmation?: number[];
  scoped_review_complete?: boolean;
  total_candidate_updates: number;
  valid_recoverable_updates: number;
  skipped_updates: number;
  duplicate_updates?: number;
  parser_repairs_applied: string[];
  warnings: string[];
  quality_report?: ImportQualityReport;
  updates: AIPreviewUpdate[];
  batch?: AIImportBatch;
}

export interface ImportQualityReport {
  total_updates_parsed: number;
  total_importable_updates: number;
  imported_findings: number;
  skipped_updates: number;
  duplicate_count: number;
  missing_page_number_count: number;
  missing_target_text_count: number;
  exact_placement_count: number;
  fuzzy_placement_count: number;
  page_level_fallback_count: number;
  manual_placement_needed_count: number;
  low_confidence_count: number;
  page_count?: number;
  expected_review_pages?: number[];
  reviewed_pages_confirmed?: number[];
  missing_review_pages?: number[];
  incomplete_review_pages?: number[];
  not_readable_pages?: number[];
  review_coverage_status?: "complete" | "incomplete" | "not_confirmed" | string;
  review_coverage_percent?: number;
  pages_with_returned_updates?: number[];
  pages_with_importable_updates?: number[];
  pages_with_imported_updates?: number[];
  pages_with_updates?: number[];
  pages_reviewed?: number[];
  pages_without_review_confirmation?: number[];
  scoped_review_complete?: boolean;
  pages_without_returned_updates?: number[];
  pages_with_returned_updates_count?: number;
  pages_with_imported_updates_count?: number;
  pages_without_returned_updates_count?: number;
  warnings?: string[];
  errors?: string[];
}

export interface AIImportBatch {
  id: string;
  project_id: string;
  source_type?: string | null;
  prompt_version?: string | null;
  prompt_id?: string | null;
  raw_response_stored?: boolean;
  raw_response_length?: number;
  raw_response_sha256?: string | null;
  parser_warnings?: string[];
  parser_repairs?: string[];
  candidate_count: number;
  valid_count: number;
  skipped_count: number;
  created_count: number;
  updated_count: number;
  duplicate_count: number;
  import_status: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  imported_at?: string | null;
}

export interface PlacementSummary {
  exact_target_found?: number;
  fuzzy_target_found?: number;
  page_level_fallback?: number;
  manual_placement_needed?: number;
  [key: string]: number | undefined;
}

export interface PlacementRecalculateResponse {
  project: Project;
  findings: Finding[];
  summary: PlacementSummary;
  updated_count: number;
  total_findings: number;
}

export interface ExportResponse {
  export_id: string;
  marked_pdf?: string | null;
  csv_log?: string | null;
  qa_report?: string | null;
  excel_log?: string | null;
  json_findings?: string | null;
  markdown_summary?: string | null;
  html_summary?: string | null;
  findings_exported?: number;
  placement_summary?: PlacementSummary;
  validation?: ExportValidationResult;
  export_mode?: "draft" | "final" | string;
  review_coverage?: ReviewCoverageSummary;
  signoff?: ReviewerSignoff | null;
}

export interface ExportRequest {
  export_mode?: "draft" | "final";
  statuses: FindingStatus[];
  reviewer_name?: string;
  final_export_confirmed?: boolean;
  acknowledge_validation_warnings?: boolean;
}

export interface ExportValidationResult {
  status: "passed" | "warning" | "failed" | string;
  checks?: Array<{ name: string; passed: boolean; detail?: string }>;
  warnings?: string[];
  errors?: string[];
  expected_findings?: number;
  annotation_count?: number;
  source_page_count?: number | null;
  marked_page_count?: number | null;
  placement_summary?: PlacementSummary;
}

export interface PromptTemplate {
  id: string;
  name: string;
  version: string;
  description?: string;
  category?: string;
  intended_use?: string;
  review_depth?: string;
  when_to_use?: string;
  when_not_to_use?: string;
  review_priorities?: string[];
}

export interface ChecklistTemplate {
  id: string;
  name: string;
  version: string;
  description?: string;
  item_count?: number;
}

export type ChecklistStatus = "not_started" | "checked" | "issue_found" | "not_applicable" | "needs_human_review";

export interface ChecklistItem {
  id: string;
  project_checklist_id: string;
  project_id: string;
  checklist_id: string;
  checklist_name: string;
  version: string;
  section: string;
  discipline?: string | null;
  sheet_type?: string | null;
  item_text: string;
  applicability: string;
  status: ChecklistStatus;
  mapped_finding_ids: string[];
  reviewer_notes?: string | null;
  source_template_reference?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChecklistItemUpdate {
  status?: ChecklistStatus;
  applicability?: string;
  mapped_finding_ids?: string[];
  reviewer_notes?: string;
}

export interface ChecklistProgress {
  total_items: number;
  completed_items: number;
  issue_items: number;
  linked_items: number;
  percent_complete: number;
  by_status: Record<string, number>;
}

export interface ProjectChecklist {
  id?: string;
  project_id: string;
  checklist_id?: string;
  checklist_name?: string;
  version?: string;
  items: ChecklistItem[];
  progress?: ChecklistProgress | null;
  created_at?: string;
  updated_at?: string;
}

export interface ReadinessCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface ReadinessResponse {
  status: "passed" | "warning" | "failed" | string;
  mode?: string;
  summary?: string;
  actor?: string;
  checks: ReadinessCheck[];
  instructions: Record<string, string>;
}

export interface ProjectPackageExportResponse {
  package_id: string;
  project_id: string;
  path: string;
  filename: string;
  download_url: string;
}

export interface ProjectPackageImportResponse {
  project: Project;
  original_project_id: string;
  restored_project_id: string;
  remapped_ids: boolean;
  preview?: ProjectPackageImportPreview;
}

export interface ProjectPackageImportPreview {
  valid: boolean;
  schema_version?: string | null;
  project_name?: string | null;
  original_project_id?: string | null;
  restored_project_id?: string | null;
  remapped_ids?: boolean;
  sheet_count: number;
  finding_count: number;
  import_batches_count: number;
  export_record_count?: number;
  export_artifact_count: number;
  source_pdf_included: boolean;
  source_pdf_valid: boolean;
  warnings: string[];
  errors: string[];
}

export interface ReviewCoverageSummary {
  expected_review_pages: number[];
  reviewed_pages_confirmed: number[];
  missing_review_pages: number[];
  incomplete_review_pages: number[];
  not_readable_pages: number[];
  review_coverage_status: "complete" | "incomplete" | "not_confirmed" | string;
  review_coverage_percent: number;
}

export interface ReviewerSignoff {
  reviewer_name: string;
  timestamp: string;
  final_export_confirmed: boolean;
}

export interface BatchRollbackPreview {
  batch_id: string;
  import_status?: string;
  findings_to_remove?: number;
  findings_removed?: number;
  reviewed_or_edited_findings: number;
  status_counts: Record<string, number>;
  finding_ids: string[];
  confirmed: boolean;
  project?: Project;
  findings?: Finding[];
}

export interface MergeFindingResponse {
  duplicate: Finding;
  target: Finding;
}

export interface MarkupMemorySettings {
  enabled: boolean;
  include_in_prompts: boolean;
  max_examples_per_prompt: number;
  max_avoid_examples_per_prompt: number;
  include_rejected_examples: boolean;
  include_accepted_examples: boolean;
  include_edited_examples: boolean;
  include_current_project_examples: boolean;
  min_usefulness_score: number;
  advanced_feature_enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export type MarkupMemorySettingsUpdate = Partial<MarkupMemorySettings>;

export interface MarkupMemoryExample {
  id: string;
  source_project_id?: string | null;
  source_finding_id?: string | null;
  source_pdf_name?: string | null;
  page_number?: number | null;
  sheet_id?: string | null;
  drawing_number?: string | null;
  sheet_title?: string | null;
  sheet_type?: string | null;
  category?: string | null;
  severity?: string | null;
  target_text?: string | null;
  required_update?: string | null;
  final_comment_text?: string | null;
  rationale?: string | null;
  reviewer_note?: string | null;
  status_outcome: string;
  source_type?: string;
  usefulness_score?: number;
  similarity_score?: number;
  updated_at?: string;
}

export interface MarkupMemoryStats {
  total_memory_examples: number;
  accepted_examples: number;
  edited_examples: number;
  rejected_examples: number;
  duplicate_examples: number;
  exported_examples: number;
  deferred_examples?: number;
  needs_manual_placement_examples?: number;
  needs_engineer_input_examples?: number;
  examples_by_category: Record<string, number>;
  examples_by_outcome?: Record<string, number>;
}

export interface MarkupMemoryPreview {
  enabled: boolean;
  prompt_section: string;
  disabled_reason?: string | null;
  positive_examples: MarkupMemoryExample[];
  avoid_examples: MarkupMemoryExample[];
  placement_examples?: MarkupMemoryExample[];
  settings?: MarkupMemorySettings;
}

export interface MarkupMemoryRebuildResponse {
  projects_scanned: number;
  memory_examples_upserted: number;
  outcome_counts: Record<string, number>;
  stats: MarkupMemoryStats;
}
