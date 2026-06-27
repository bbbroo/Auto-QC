import type { Finding, FindingStatus, LocationPayload, Severity, Sheet } from "./types";

export const SEVERITIES: Severity[] = ["Critical", "Major", "Minor", "Note"];

export const STATUSES: FindingStatus[] = ["needs_review", "accepted", "rejected"];

export const CATEGORIES = [
  "tag consistency",
  "line number consistency",
  "drawing coordination",
  "missing information",
  "regulator station design",
  "safety and operability",
  "overpressure protection",
  "instrumentation",
  "drafting quality",
  "title block and revision",
  "BOM or count issue",
  "notes and specifications",
  "human review needed",
];

export function formatDate(value?: string | null): string {
  if (!value) {
    return "Unknown";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatStatus(value?: string | null): string {
  if (!value) {
    return "Unknown";
  }

  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function sheetLabel(sheet?: Sheet | null): string {
  if (!sheet) {
    return "No sheet";
  }

  const number = sheet.drawing_number?.trim();
  const title = sheet.sheet_title?.trim();
  if (number && title) {
    return `${number} - ${title}`;
  }

  return number || title || `Page ${sheet.page_number}`;
}

export function severityClass(severity: Severity | string): string {
  return severity.toLowerCase().replace(/\s+/g, "-");
}

export function statusClass(status: FindingStatus | string): string {
  return status.toLowerCase().replace(/_/g, "-");
}

export function confidenceLabel(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "n/a";
  }

  return `${Math.round(value * 100)}%`;
}

export function countFindingsByStatus(findings: Finding[], status: FindingStatus): number {
  return findings.filter((finding) => finding.status === status).length;
}

export function getFindingSheet(finding: Finding, sheets: Sheet[]): Sheet | undefined {
  return (
    sheets.find((sheet) => finding.sheet_id && sheet.id === finding.sheet_id) ??
    sheets.find((sheet) => finding.page_number && sheet.page_number === finding.page_number)
  );
}

export function extractBbox(location: Finding["location"]): number[] | null {
  if (!location) {
    return null;
  }

  if (Array.isArray(location)) {
    return normalizeBbox(location);
  }

  const payload = location as LocationPayload;
  if (Array.isArray(payload.bbox)) {
    return normalizeBbox(payload.bbox);
  }

  if (Array.isArray(payload.rect)) {
    return normalizeBbox(payload.rect);
  }

  if (
    typeof payload.x0 === "number" &&
    typeof payload.y0 === "number" &&
    typeof payload.x1 === "number" &&
    typeof payload.y1 === "number"
  ) {
    return normalizeBbox([payload.x0, payload.y0, payload.x1, payload.y1]);
  }

  if (
    typeof payload.left === "number" &&
    typeof payload.top === "number" &&
    typeof payload.width === "number" &&
    typeof payload.height === "number"
  ) {
    return normalizeBbox([
      payload.left,
      payload.top,
      payload.left + payload.width,
      payload.top + payload.height,
    ]);
  }

  return null;
}

function normalizeBbox(value: number[]): number[] | null {
  if (value.length < 4 || value.some((coordinate) => !Number.isFinite(coordinate))) {
    return null;
  }

  const [x0, y0, x1, y1] = value;
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
}
