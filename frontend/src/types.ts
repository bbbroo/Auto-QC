export type Severity = "Critical" | "Major" | "Minor" | "Note";

export type FindingStatus = "accepted" | "needs_review" | "rejected";

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
  created_at?: string | null;
  updated_at?: string | null;
  review_summary?: string | null;
  sheet_count?: number;
  finding_count?: number;
  findings_count?: number;
}

export interface Sheet {
  id: string;
  project_id: string;
  page_number: number;
  drawing_number?: string | null;
  sheet_title?: string | null;
  revision?: string | null;
  sheet_type?: SheetType | null;
  extraction_status?: string | null;
  ocr_status?: string | null;
  image_path?: string | null;
  image_url?: string | null;
  text_content?: string | null;
  width?: number | null;
  height?: number | null;
}

export interface Evidence {
  observation?: string;
  sheet_id?: string | null;
  page_number?: number | null;
  drawing_number?: string | null;
  text_excerpt?: string | null;
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
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FindingUpdate {
  title?: string;
  category?: string;
  severity?: Severity;
  confidence?: number;
  reasoning_summary?: string;
  suggested_correction?: string;
  comment_text?: string;
  status?: FindingStatus;
}

export interface ExportResponse {
  export_id: string;
  marked_pdf: string;
  csv_log: string;
  excel_log?: string | null;
  json_findings: string;
  markdown_summary: string;
  html_summary: string;
}

export interface ExportRequest {
  statuses: FindingStatus[];
}
