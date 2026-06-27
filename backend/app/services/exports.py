from __future__ import annotations

import csv
import html
import json
import uuid
from pathlib import Path
from typing import Any

import fitz

from backend.app.database import Database
from backend.app.models import ExportRecord, utc_now_iso


class ExportService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = Path(data_dir)

    def export_project(
        self,
        project_id: str,
        accepted_only: bool = True,
        statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        source_pdf = project.get("source_pdf_path")
        if not source_pdf:
            raise ValueError("Project has no source PDF")

        export_statuses = statuses if statuses is not None else (["accepted"] if accepted_only else ["accepted", "needs_review"])
        findings = self.db.list_findings(project_id, statuses=export_statuses)
        sheets = self.db.list_sheets(project_id)
        sheet_by_id = {sheet["id"]: sheet for sheet in sheets}

        export_id = str(uuid.uuid4())
        export_dir = self.data_dir / "projects" / project_id / "exports" / export_id
        export_dir.mkdir(parents=True, exist_ok=True)

        marked_pdf = export_dir / f"{_safe_stem(project['name'])}_marked.pdf"
        csv_path = export_dir / f"{_safe_stem(project['name'])}_qc_log.csv"
        xlsx_path = export_dir / f"{_safe_stem(project['name'])}_qc_log.xlsx"
        json_path = export_dir / f"{_safe_stem(project['name'])}_findings.json"
        summary_path = export_dir / f"{_safe_stem(project['name'])}_review_summary.md"
        html_path = export_dir / f"{_safe_stem(project['name'])}_review_summary.html"

        self._write_marked_pdf(Path(source_pdf), marked_pdf, findings)
        self._write_csv(csv_path, findings, sheet_by_id)
        self._write_xlsx(xlsx_path, findings, sheet_by_id)
        self._write_json(json_path, findings)
        self._write_summary(summary_path, html_path, project, sheets, findings)

        record = ExportRecord(
            id=export_id,
            project_id=project_id,
            export_dir=str(export_dir),
            marked_pdf_path=str(marked_pdf),
            csv_path=str(csv_path),
            xlsx_path=str(xlsx_path) if xlsx_path.exists() else None,
            json_path=str(json_path),
            summary_path=str(summary_path),
            created_at=utc_now_iso(),
        ).model_dump()
        record["html_path"] = str(html_path)
        self.db.insert_export(record)
        return {"export": record, "findings_exported": len(findings)}

    def _write_marked_pdf(self, source_pdf: Path, target_pdf: Path, findings: list[dict[str, Any]]) -> None:
        by_page: dict[int, list[dict[str, Any]]] = {}
        for finding in findings:
            page_number = finding.get("page_number") or 1
            by_page.setdefault(int(page_number), []).append(finding)

        with fitz.open(source_pdf) as doc:
            for page_number, page_findings in by_page.items():
                if page_number < 1 or page_number > len(doc):
                    continue
                page = doc[page_number - 1]
                fallback_index = 0
                for finding in page_findings:
                    color = _severity_color(finding.get("severity"))
                    content = f"{finding.get('stable_id')}: {finding.get('comment_text')}"
                    rect = _location_rect(finding.get("location"))
                    if rect:
                        rect_annot = page.add_rect_annot(rect)
                        rect_annot.set_colors(stroke=color)
                        rect_annot.set_border(width=1.2)
                        rect_annot.set_info(
                            title="Natural Gas Engineering Copilot",
                            subject=finding.get("category", "QC Finding"),
                            content=content,
                        )
                        rect_annot.update()
                        point = fitz.Point(min(rect.x1 + 8, page.rect.width - 24), max(rect.y0, 24))
                    else:
                        point = fitz.Point(page.rect.width - 36, 48 + fallback_index * 32)
                        fallback_index += 1
                    note = page.add_text_annot(point, content)
                    note.set_info(
                        title="Natural Gas Engineering Copilot",
                        subject=finding.get("category", "QC Finding"),
                        content=content,
                    )
                    note.set_colors(stroke=color)
                    note.update()
            doc.save(target_pdf, garbage=4, deflate=True)

    def _write_csv(self, path: Path, findings: list[dict[str, Any]], sheet_by_id: dict[str, dict[str, Any]]) -> None:
        fieldnames = [
            "finding_id",
            "status",
            "severity",
            "category",
            "sheet_number",
            "page_number",
            "drawing_title",
            "comment",
            "evidence",
            "suggested_correction",
            "confidence",
            "source",
            "created_at",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for finding in findings:
                sheet = sheet_by_id.get(finding.get("sheet_id") or "", {})
                writer.writerow(_qc_log_row(finding, sheet))

    def _write_xlsx(self, path: Path, findings: list[dict[str, Any]], sheet_by_id: dict[str, dict[str, Any]]) -> None:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            from openpyxl.utils import get_column_letter
        except Exception:
            return

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "QC Log"
        headers = [
            "finding_id",
            "status",
            "severity",
            "category",
            "sheet_number",
            "page_number",
            "drawing_title",
            "comment",
            "evidence",
            "suggested_correction",
            "confidence",
            "source",
            "created_at",
        ]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="253241")
        for finding in findings:
            row = _qc_log_row(finding, sheet_by_id.get(finding.get("sheet_id") or "", {}))
            sheet.append([row[key] for key in headers])
        widths = [16, 14, 12, 24, 16, 12, 30, 48, 58, 42, 12, 16, 22]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        workbook.save(path)

    def _write_json(self, path: Path, findings: list[dict[str, Any]]) -> None:
        path.write_text(json.dumps(findings, indent=2, ensure_ascii=True), encoding="utf-8")

    def _write_summary(
        self,
        markdown_path: Path,
        html_path: Path,
        project: dict[str, Any],
        sheets: list[dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> None:
        severity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for finding in findings:
            severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1
            category_counts[finding["category"]] = category_counts.get(finding["category"], 0) + 1

        lines = [
            f"# Review Summary: {project['name']}",
            "",
            f"- Project ID: `{project['id']}`",
            f"- Sheets processed: {len(sheets)}",
            f"- Findings exported: {len(findings)}",
            f"- Severity counts: {severity_counts}",
            f"- Category counts: {category_counts}",
            "",
            "## Accepted Findings",
            "",
        ]
        for finding in findings:
            sheet = next((item for item in sheets if item["id"] == finding.get("sheet_id")), {})
            lines.extend(
                [
                    f"### {finding['stable_id']} - {finding['title']}",
                    "",
                    f"- Severity: {finding['severity']}",
                    f"- Category: {finding['category']}",
                    f"- Sheet: {sheet.get('drawing_number', 'UNKNOWN')} page {finding.get('page_number')}",
                    f"- Comment: {finding['comment_text']}",
                    f"- Suggested correction: {finding['suggested_correction']}",
                    f"- Evidence: {' | '.join(item.get('observation', '') for item in finding.get('evidence', []))}",
                    "",
                ]
            )
        markdown = "\n".join(lines)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_lines = [
            "<!doctype html><html><head><meta charset='utf-8'><title>AutoQC Review Summary</title>",
            "<style>body{font-family:Arial,sans-serif;max-width:980px;margin:32px auto;line-height:1.45;color:#1f2933}",
            "h1,h2,h3{margin-top:24px} code{background:#eef2f5;padding:2px 4px;border-radius:3px}</style></head><body>",
        ]
        for line in lines:
            if line.startswith("# "):
                html_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("### "):
                html_lines.append(f"<h3>{html.escape(line[4:])}</h3>")
            elif line.startswith("- "):
                html_lines.append(f"<p>{html.escape(line)}</p>")
            elif line:
                html_lines.append(f"<p>{html.escape(line)}</p>")
        html_lines.append("</body></html>")
        html_path.write_text("\n".join(html_lines), encoding="utf-8")


def _qc_log_row(finding: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": finding.get("stable_id"),
        "status": finding.get("status"),
        "severity": finding.get("severity"),
        "category": finding.get("category"),
        "sheet_number": sheet.get("drawing_number", "UNKNOWN"),
        "page_number": finding.get("page_number"),
        "drawing_title": sheet.get("sheet_title", "Unknown Sheet"),
        "comment": finding.get("comment_text"),
        "evidence": " | ".join(item.get("observation", "") for item in finding.get("evidence", [])),
        "suggested_correction": finding.get("suggested_correction"),
        "confidence": finding.get("confidence"),
        "source": finding.get("source"),
        "created_at": finding.get("created_at"),
    }


def _severity_color(severity: str | None) -> tuple[float, float, float]:
    return {
        "Critical": (0.85, 0.05, 0.05),
        "Major": (1.0, 0.45, 0.05),
        "Minor": (0.95, 0.78, 0.05),
        "Note": (0.1, 0.35, 0.8),
    }.get(severity or "", (0.2, 0.2, 0.2))


def _location_rect(location: Any) -> fitz.Rect | None:
    if not location:
        return None
    if isinstance(location, dict):
        if all(key in location for key in ("x0", "y0", "x1", "y1")):
            return fitz.Rect(location["x0"], location["y0"], location["x1"], location["y1"])
        bbox = location.get("bbox") or location.get("rect")
        if isinstance(bbox, list) and len(bbox) >= 4:
            return fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
    if isinstance(location, list) and len(location) >= 4:
        return fitz.Rect(location[0], location[1], location[2], location[3])
    return None


def _safe_stem(name: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip())
    return value.strip("_") or "autoqc_review"
