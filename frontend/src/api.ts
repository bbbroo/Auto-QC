import type {
  AIReviewResponse,
  AIPreviewResponse,
  AIImportBatch,
  AIStatus,
  AISettingsRequest,
  BatchRollbackPreview,
  BulkFindingResponse,
  ChecklistItem,
  ChecklistItemUpdate,
  ChecklistTemplate,
  ExportRequest,
  ExportResponse,
  Finding,
  FindingEvent,
  FindingUpdate,
  MarkupMemoryPreview,
  MarkupMemoryRebuildResponse,
  MarkupMemorySettings,
  MarkupMemorySettingsUpdate,
  MarkupMemoryStats,
  MergeFindingResponse,
  ManualAIPromptResponse,
  ManualReviewPlan,
  ManualReviewScope,
  PlacementRecalculateResponse,
  ProjectChecklist,
  ProjectPackageExportResponse,
  ProjectPackageImportResponse,
  ProjectPackageImportPreview,
  PromptTemplate,
  Project,
  ReadinessResponse,
  Sheet,
  ValidationProjectCleanupResponse,
  ValidationProjectTagResponse,
} from "./types";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;

export const API_BASE_URL = normalizeBaseUrl(
  configuredBaseUrl ?? (import.meta.env.DEV ? "/api" : "http://127.0.0.1:8000"),
);

class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function endpoint(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function apiOrigin(): string {
  if (!/^https?:\/\//i.test(API_BASE_URL)) {
    return "";
  }

  return new URL(API_BASE_URL).origin;
}

async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(endpoint(path), {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });

  const payload = await parseResponse(response);

  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "detail" in payload
        ? formatApiDetail((payload as { detail: unknown }).detail)
        : `Request failed with ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

function unwrapCollection<T>(payload: unknown, keys: string[]): T[] {
  if (Array.isArray(payload)) {
    return payload as T[];
  }

  if (typeof payload === "object" && payload) {
    for (const key of keys) {
      const value = (payload as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        return value as T[];
      }
    }

    const data = (payload as Record<string, unknown>).data;
    if (Array.isArray(data)) {
      return data as T[];
    }
  }

  return [];
}

function unwrapItem<T>(payload: unknown, key: string): T {
  if (typeof payload === "object" && payload && key in payload) {
    return (payload as Record<string, unknown>)[key] as T;
  }

  return payload as T;
}

export async function listProjects(includeValidation = false): Promise<Project[]> {
  const query = includeValidation ? "?include_validation=true" : "";
  const payload = await request<unknown>(`/projects${query}`);
  return unwrapCollection<Project>(payload, ["projects", "items"]);
}

export async function createProject(name: string, file: File): Promise<Project> {
  const body = new FormData();
  body.append("name", name);
  body.append("file", file);

  const payload = await request<unknown>("/projects", {
    method: "POST",
    body,
  });

  return unwrapItem<Project>(payload, "project");
}

export async function createSampleProject(): Promise<Project> {
  const payload = await request<unknown>("/sample-project", {
    method: "POST",
  });

  return unwrapItem<Project>(payload, "project");
}

export async function getProject(projectId: string): Promise<Project> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}`);
  return unwrapItem<Project>(payload, "project");
}

export async function deleteProject(projectId: string): Promise<void> {
  await request<unknown>(`/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
  });
}

export async function deleteValidationProjects(): Promise<ValidationProjectCleanupResponse> {
  return request<ValidationProjectCleanupResponse>("/maintenance/validation-projects", {
    method: "DELETE",
  });
}

export async function tagGeneratedValidationProjects(dryRun = false): Promise<ValidationProjectTagResponse> {
  const query = dryRun ? "?dry_run=true" : "?dry_run=false";
  return request<ValidationProjectTagResponse>(`/maintenance/validation-projects/tag-generated${query}`, {
    method: "POST",
  });
}

export async function exportProjectPackage(projectId: string): Promise<ProjectPackageExportResponse> {
  return request<ProjectPackageExportResponse>(`/projects/${encodeURIComponent(projectId)}/project-package`, {
    method: "POST",
  });
}

export async function importProjectPackage(file: File): Promise<ProjectPackageImportResponse> {
  const body = new FormData();
  body.append("file", file);
  const payload = await request<unknown>("/project-packages/import", {
    method: "POST",
    body,
  });
  return payload as ProjectPackageImportResponse;
}

export async function previewProjectPackageImport(file: File): Promise<ProjectPackageImportPreview> {
  const body = new FormData();
  body.append("file", file);
  const payload = await request<unknown>("/project-packages/import/preview", {
    method: "POST",
    body,
  });
  return payload as ProjectPackageImportPreview;
}

export async function listSheets(projectId: string): Promise<Sheet[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/sheets`);
  return unwrapCollection<Sheet>(payload, ["sheets", "items"]);
}

export async function listFindings(projectId: string): Promise<Finding[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/findings`);
  return unwrapCollection<Finding>(payload, ["findings", "items"]);
}

export async function listFindingEvents(projectId: string): Promise<FindingEvent[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/events`);
  return unwrapCollection<FindingEvent>(payload, ["events", "items"]);
}

export async function recalculateFindingPlacement(projectId: string): Promise<PlacementRecalculateResponse> {
  return request<PlacementRecalculateResponse>(`/projects/${encodeURIComponent(projectId)}/findings/recalculate-placement`, {
    method: "POST",
  });
}

export async function getAIStatus(): Promise<AIStatus> {
  const payload = await request<unknown>("/ai/status");
  return unwrapItem<AIStatus>(payload, "status");
}

export async function saveAISettings(settings: AISettingsRequest): Promise<AIStatus> {
  return request<AIStatus>("/ai/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export async function runAIReview(projectId: string): Promise<AIReviewResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review`, {
    method: "POST",
  });
  return unwrapItem<AIReviewResponse>(payload, "result");
}

export async function getManualAIPrompt(
  projectId: string,
  templateId?: string | null,
  reviewDepth?: string | null,
  options: {
    reviewScope?: ManualReviewScope | string | null;
    pageNumber?: number | null;
    pageNumbers?: number[] | null;
    batchSize?: number | null;
  } = {},
): Promise<ManualAIPromptResponse> {
  const params = new URLSearchParams();
  if (templateId) {
    params.set("template_id", templateId);
  }
  if (reviewDepth) {
    params.set("review_depth", reviewDepth);
  }
  if (options.reviewScope) {
    params.set("review_scope", options.reviewScope);
  }
  if (options.pageNumber) {
    params.set("page_number", String(options.pageNumber));
  }
  if (options.pageNumbers?.length) {
    params.set("page_numbers", options.pageNumbers.join(","));
  }
  if (options.batchSize) {
    params.set("batch_size", String(options.batchSize));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review/manual-prompt${query}`);
  return payload as ManualAIPromptResponse;
}

export async function getManualReviewPlan(projectId: string, batchSize?: number | null): Promise<ManualReviewPlan> {
  const params = new URLSearchParams();
  if (batchSize) {
    params.set("batch_size", String(batchSize));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<ManualReviewPlan>(`/projects/${encodeURIComponent(projectId)}/ai-review/manual-review-plan${query}`);
}

export async function listPromptTemplates(): Promise<PromptTemplate[]> {
  const payload = await request<unknown>("/ai-review/prompt-templates");
  return unwrapCollection<PromptTemplate>(payload, ["templates", "items"]);
}

export async function importManualAIResponse(projectId: string, responseText: string): Promise<AIReviewResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review/import`, {
    method: "POST",
    body: JSON.stringify({ response_text: responseText }),
  });
  return unwrapItem<AIReviewResponse>(payload, "result");
}

export async function previewManualAIResponse(
  projectId: string,
  responseText: string,
  promptVersion?: string | null,
  promptId?: string | null,
  sourceType = "manual_chat_prompt",
  auditOfBatchId?: string | null,
  auditRound?: number | null,
  reviewModality?: string | null,
): Promise<AIPreviewResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review/preview`, {
    method: "POST",
    body: JSON.stringify({
      response_text: responseText,
      source_type: sourceType,
      prompt_version: promptVersion ?? undefined,
      prompt_id: promptId ?? undefined,
      audit_of_batch_id: auditOfBatchId ?? undefined,
      audit_round: auditRound ?? undefined,
      review_modality: reviewModality ?? undefined,
    }),
  });
  return payload as AIPreviewResponse;
}

export async function importManualAIPreview(projectId: string, previewId: string): Promise<AIReviewResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review/import`, {
    method: "POST",
    body: JSON.stringify({ preview_id: previewId }),
  });
  return unwrapItem<AIReviewResponse>(payload, "result");
}

export async function listAIImportBatches(projectId: string): Promise<AIImportBatch[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/ai-review/import-batches`);
  return unwrapCollection<AIImportBatch>(payload, ["batches", "items"]);
}

export async function previewImportBatchRollback(projectId: string, batchId: string): Promise<BatchRollbackPreview> {
  return request<BatchRollbackPreview>(
    `/projects/${encodeURIComponent(projectId)}/ai-review/import-batches/${encodeURIComponent(batchId)}/rollback-preview`,
    { method: "POST" },
  );
}

export async function rollbackImportBatch(projectId: string, batchId: string): Promise<BatchRollbackPreview> {
  return request<BatchRollbackPreview>(
    `/projects/${encodeURIComponent(projectId)}/ai-review/import-batches/${encodeURIComponent(batchId)}/rollback`,
    { method: "POST", body: JSON.stringify({ confirm: true }) },
  );
}

export async function rollbackLatestBulkStatus(projectId: string, confirm = false): Promise<unknown> {
  return request<unknown>(`/projects/${encodeURIComponent(projectId)}/findings/bulk/rollback-latest-status`, {
    method: "POST",
    body: JSON.stringify({ confirm }),
  });
}

export async function updateFinding(
  findingId: string,
  update: FindingUpdate,
): Promise<Finding> {
  const payload = await request<unknown>(`/findings/${encodeURIComponent(findingId)}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  });

  return unwrapItem<Finding>(payload, "finding");
}

export async function bulkUpdateFindings(
  findingIds: string[],
  update: FindingUpdate,
): Promise<BulkFindingResponse> {
  const payload = await request<unknown>("/findings/bulk", {
    method: "PATCH",
    body: JSON.stringify({ finding_ids: findingIds, update }),
  });

  return unwrapItem<BulkFindingResponse>(payload, "result");
}

export async function deleteFinding(findingId: string): Promise<void> {
  await request<unknown>(`/findings/${encodeURIComponent(findingId)}`, {
    method: "DELETE",
  });
}

export async function mergeFindingInto(findingId: string, targetFindingId: string): Promise<MergeFindingResponse> {
  return request<MergeFindingResponse>(`/findings/${encodeURIComponent(findingId)}/merge`, {
    method: "POST",
    body: JSON.stringify({ target_finding_id: targetFindingId }),
  });
}

export async function saveManualPlacement(
  findingId: string,
  pageNumber: number,
  rect: number[],
  imageWidth: number,
  imageHeight: number,
): Promise<Finding> {
  const payload = await request<unknown>(`/findings/${encodeURIComponent(findingId)}/manual-placement`, {
    method: "POST",
    body: JSON.stringify({
      page_number: pageNumber,
      rect,
      coordinate_space: "image_pixel",
      image_width: imageWidth,
      image_height: imageHeight,
    }),
  });
  return unwrapItem<Finding>(payload, "finding");
}

export async function listChecklistTemplates(): Promise<ChecklistTemplate[]> {
  const payload = await request<unknown>("/checklists/templates");
  return unwrapCollection<ChecklistTemplate>(payload, ["templates", "items"]);
}

export async function getProjectChecklist(projectId: string): Promise<ProjectChecklist> {
  return request<ProjectChecklist>(`/projects/${encodeURIComponent(projectId)}/checklist`);
}

export async function selectProjectChecklist(projectId: string, checklistId: string): Promise<ProjectChecklist> {
  return request<ProjectChecklist>(`/projects/${encodeURIComponent(projectId)}/checklist/select`, {
    method: "POST",
    body: JSON.stringify({ checklist_id: checklistId }),
  });
}

export async function updateProjectChecklistItem(
  projectId: string,
  itemId: string,
  update: ChecklistItemUpdate,
): Promise<ChecklistItem> {
  return request<ChecklistItem>(
    `/projects/${encodeURIComponent(projectId)}/checklist/items/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(update),
    },
  );
}

export async function getMarkupMemorySettings(): Promise<MarkupMemorySettings> {
  return request<MarkupMemorySettings>("/markup-memory/settings");
}

export async function updateMarkupMemorySettings(settings: MarkupMemorySettingsUpdate): Promise<MarkupMemorySettings> {
  return request<MarkupMemorySettings>("/markup-memory/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export async function getMarkupMemoryStats(): Promise<MarkupMemoryStats> {
  return request<MarkupMemoryStats>("/markup-memory/stats");
}

export async function rebuildMarkupMemory(): Promise<MarkupMemoryRebuildResponse> {
  return request<MarkupMemoryRebuildResponse>("/markup-memory/rebuild", {
    method: "POST",
  });
}

export async function clearMarkupMemory(): Promise<{ deleted: number; stats: MarkupMemoryStats }> {
  return request<{ deleted: number; stats: MarkupMemoryStats }>("/markup-memory", {
    method: "DELETE",
  });
}

export async function previewMarkupMemoryContext(projectId: string): Promise<MarkupMemoryPreview> {
  return request<MarkupMemoryPreview>(`/projects/${encodeURIComponent(projectId)}/markup-memory/preview`);
}

export async function exportProject(
  projectId: string,
  requestBody: ExportRequest,
): Promise<ExportResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/exports`, {
    method: "POST",
    body: JSON.stringify(requestBody),
  });

  return normalizeExportResponse(payload);
}

function normalizeExportResponse(payload: unknown): ExportResponse {
  if (typeof payload !== "object" || !payload) {
    return { export_id: "unknown" };
  }

  const root = payload as Record<string, unknown>;
  const exportRecord = typeof root.export === "object" && root.export
    ? (root.export as Record<string, unknown>)
    : root;
  const files = typeof root.files === "object" && root.files
    ? (root.files as Record<string, unknown>)
    : root;

  return {
    export_id: String(exportRecord.id ?? root.export_id ?? "unknown"),
    marked_pdf: stringOrNull(files.marked_pdf ?? exportRecord.marked_pdf_path),
    csv_log: stringOrNull(files.csv ?? files.csv_log ?? exportRecord.csv_path),
    qa_report: stringOrNull(files.qa_report ?? exportRecord.qa_report_path ?? files.csv ?? exportRecord.csv_path),
    excel_log: stringOrNull(files.xlsx ?? files.excel_log ?? exportRecord.xlsx_path),
    json_findings: stringOrNull(files.json ?? files.json_findings ?? exportRecord.json_path),
    markdown_summary: stringOrNull(files.summary ?? files.markdown_summary ?? exportRecord.summary_path),
    html_summary: stringOrNull(files.html ?? files.html_summary ?? exportRecord.html_path),
    findings_exported: typeof root.findings_exported === "number" ? root.findings_exported : undefined,
    placement_summary: typeof root.placement_summary === "object" && root.placement_summary
      ? root.placement_summary as ExportResponse["placement_summary"]
      : undefined,
    validation: typeof root.validation === "object" && root.validation
      ? root.validation as ExportResponse["validation"]
      : undefined,
    export_mode: typeof root.export_mode === "string" ? root.export_mode : stringOrNull(exportRecord.export_mode) ?? undefined,
    review_coverage: typeof root.review_coverage === "object" && root.review_coverage
      ? root.review_coverage as ExportResponse["review_coverage"]
      : undefined,
    signoff: typeof root.signoff === "object" && root.signoff ? root.signoff as ExportResponse["signoff"] : null,
  };
}

export async function getReadiness(): Promise<ReadinessResponse> {
  return request<ReadinessResponse>("/readiness");
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item && "msg" in item) {
          const location = Array.isArray((item as { loc?: unknown }).loc)
            ? ` (${(item as { loc: unknown[] }).loc.join(".")})`
            : "";
          return `${String((item as { msg: unknown }).msg)}${location}`;
        }
        return formatApiDetail(item);
      })
      .filter(Boolean)
      .join("; ");
  }

  if (typeof detail === "object" && detail) {
    try {
      return JSON.stringify(detail);
    } catch {
      return "Request failed with an unreadable error response";
    }
  }

  return String(detail ?? "Request failed");
}

export function resolveAssetUrl(value?: string | null): string | undefined {
  if (!value) {
    return undefined;
  }

  if (/^(https?:|data:|blob:)/i.test(value)) {
    return value;
  }

  if (/^[a-z]:\\/i.test(value) || value.includes("\\")) {
    return undefined;
  }

  const normalizedPath = value.startsWith("/") ? value : `/${value}`;
  const origin = apiOrigin();
  if (origin) {
    return `${origin}${normalizedPath}`;
  }
  if (API_BASE_URL.startsWith("/") && !normalizedPath.startsWith("/data/") && !normalizedPath.startsWith(`${API_BASE_URL}/`)) {
    return `${API_BASE_URL}${normalizedPath}`;
  }
  return normalizedPath;
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return withRecoveryHint(error.message);
  }

  return "Unexpected request failure";
}

function withRecoveryHint(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("reviewed_pages")) {
    return `${message} Ask the AI tool to return reviewed_pages for every scoped page, including pages with no updates.`;
  }
  if (normalized.includes("target_text")) {
    return `${message} Each AI update must cite exact visible drawing text so AutoQC can place the markup credibly.`;
  }
  if (normalized.includes("final export") && normalized.includes("coverage")) {
    return `${message} Import complete reviewed_pages coverage before attempting a final package.`;
  }
  if (normalized.includes("manual placement")) {
    return `${message} Open the finding, use Place on drawing, or keep the package in draft mode.`;
  }
  if (normalized.includes("valid json") || normalized.includes("could not be repaired") || normalized.includes("json")) {
    return `${message} Paste only the AI response JSON object, not the prompt or explanatory chat text.`;
  }
  if (normalized.includes("source pdf") || normalized.includes("project source pdf")) {
    return `${message} Reopen the project package or re-upload the original PDF from managed project storage.`;
  }
  return message;
}
