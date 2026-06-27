import type {
  ExportRequest,
  ExportResponse,
  Finding,
  FindingUpdate,
  Project,
  Sheet,
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
        ? String((payload as { detail: unknown }).detail)
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

export async function listProjects(): Promise<Project[]> {
  const payload = await request<unknown>("/projects");
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

export async function listSheets(projectId: string): Promise<Sheet[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/sheets`);
  return unwrapCollection<Sheet>(payload, ["sheets", "items"]);
}

export async function listFindings(projectId: string): Promise<Finding[]> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/findings`);
  return unwrapCollection<Finding>(payload, ["findings", "items"]);
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

export async function deleteFinding(findingId: string): Promise<void> {
  await request<unknown>(`/findings/${encodeURIComponent(findingId)}`, {
    method: "DELETE",
  });
}

export async function exportProject(
  projectId: string,
  requestBody: ExportRequest,
): Promise<ExportResponse> {
  const payload = await request<unknown>(`/projects/${encodeURIComponent(projectId)}/exports`, {
    method: "POST",
    body: JSON.stringify(requestBody),
  });

  return unwrapItem<ExportResponse>(payload, "export");
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
  return origin ? `${origin}${normalizedPath}` : normalizedPath;
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Unexpected request failure";
}
