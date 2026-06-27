from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

from .models import utc_now_iso


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=lambda item: item.model_dump() if hasattr(item, "model_dump") else item)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_pdf_path TEXT,
                    status TEXT NOT NULL,
                    summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sheets (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    drawing_number TEXT,
                    sheet_title TEXT,
                    revision TEXT,
                    sheet_type TEXT,
                    extraction_status TEXT,
                    ocr_status TEXT,
                    image_path TEXT,
                    text_content TEXT,
                    width REAL,
                    height REAL,
                    review_status TEXT,
                    UNIQUE(project_id, page_number)
                );

                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    sheet_id TEXT NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
                    entity_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    bbox_json TEXT,
                    confidence REAL,
                    source TEXT
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    sheet_id TEXT REFERENCES sheets(id) ON DELETE SET NULL,
                    stable_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    page_number INTEGER,
                    location_json TEXT,
                    involved_entities_json TEXT,
                    evidence_json TEXT,
                    reasoning_summary TEXT,
                    suggested_correction TEXT,
                    comment_text TEXT,
                    status TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, stable_id)
                );

                CREATE TABLE IF NOT EXISTS review_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    summary TEXT
                );

                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    export_dir TEXT NOT NULL,
                    marked_pdf_path TEXT,
                    csv_path TEXT,
                    xlsx_path TEXT,
                    json_path TEXT,
                    summary_path TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_project(self, name: str, source_pdf_path: str | None = None) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, source_pdf_path, status, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, name, source_pdf_path, "new", None, now, now),
            )
        return self.get_project(project_id)

    def update_project(self, project_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [project_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE projects SET {assignments} WHERE id = ?", values)

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM sheets WHERE project_id = p.id) AS sheet_count,
                       (SELECT COUNT(*) FROM findings WHERE project_id = p.id) AS finding_count
                FROM projects p
                WHERE p.id = ?
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM sheets WHERE project_id = p.id) AS sheet_count,
                       (SELECT COUNT(*) FROM findings WHERE project_id = p.id) AS finding_count
                FROM projects p
                ORDER BY p.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_project_analysis(self, project_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM findings WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM sheets WHERE project_id = ?", (project_id,))

    def insert_sheet(self, sheet: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sheets (
                    id, project_id, page_number, drawing_number, sheet_title, revision, sheet_type,
                    extraction_status, ocr_status, image_path, text_content, width, height, review_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sheet["id"],
                    sheet["project_id"],
                    sheet["page_number"],
                    sheet.get("drawing_number"),
                    sheet.get("sheet_title"),
                    sheet.get("revision"),
                    sheet.get("sheet_type"),
                    sheet.get("extraction_status"),
                    sheet.get("ocr_status"),
                    sheet.get("image_path"),
                    sheet.get("text_content"),
                    sheet.get("width"),
                    sheet.get("height"),
                    sheet.get("review_status", "new"),
                ),
            )

    def list_sheets(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sheets WHERE project_id = ? ORDER BY page_number ASC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_entities(self, entities: Iterable[dict[str, Any]]) -> None:
        rows = list(entities)
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO entities (
                    id, project_id, sheet_id, entity_type, text, normalized_text,
                    page_number, bbox_json, confidence, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entity["id"],
                        entity["project_id"],
                        entity["sheet_id"],
                        entity["entity_type"],
                        entity["text"],
                        entity["normalized_text"],
                        entity["page_number"],
                        _json(entity.get("bbox")) if entity.get("bbox") else None,
                        entity.get("confidence", 0.75),
                        entity.get("source", "pdf_text"),
                    )
                    for entity in rows
                ],
            )

    def list_entities(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE project_id = ? ORDER BY page_number ASC, entity_type ASC",
                (project_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["bbox"] = _loads(item.pop("bbox_json", None), None)
            out.append(item)
        return out

    def replace_findings(self, project_id: str, findings: Iterable[dict[str, Any]]) -> None:
        rows = list(findings)
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute("DELETE FROM findings WHERE project_id = ?", (project_id,))
            conn.executemany(
                """
                INSERT INTO findings (
                    id, project_id, sheet_id, stable_id, title, category, severity, confidence,
                    page_number, location_json, involved_entities_json, evidence_json,
                    reasoning_summary, suggested_correction, comment_text, status, source,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        finding["id"],
                        project_id,
                        finding.get("sheet_id"),
                        finding["stable_id"],
                        finding["title"],
                        finding["category"],
                        finding["severity"],
                        finding["confidence"],
                        finding.get("page_number"),
                        _json(finding.get("location")) if finding.get("location") else None,
                        _json(finding.get("involved_entities", [])),
                        _json(finding.get("evidence", [])),
                        finding.get("reasoning_summary", ""),
                        finding.get("suggested_correction", ""),
                        finding.get("comment_text", ""),
                        finding.get("status", "needs_review"),
                        finding.get("source", "rules"),
                        finding.get("created_at", now),
                        finding.get("updated_at", now),
                    )
                    for finding in rows
                ],
            )

    def list_findings(self, project_id: str, statuses: list[str] | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [project_id]
        where = "project_id = ?"
        if statuses:
            where += f" AND status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM findings
                WHERE {where}
                ORDER BY
                    CASE severity
                        WHEN 'Critical' THEN 0
                        WHEN 'Major' THEN 1
                        WHEN 'Minor' THEN 2
                        ELSE 3
                    END,
                    page_number ASC,
                    title ASC
                """,
                params,
            ).fetchall()
        return [self._finding_from_row(row) for row in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        if row is None:
            raise KeyError(finding_id)
        return self._finding_from_row(row)

    def update_finding(self, finding_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "category",
            "severity",
            "confidence",
            "reasoning_summary",
            "suggested_correction",
            "comment_text",
            "status",
        }
        updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
        if updates:
            updates["updated_at"] = utc_now_iso()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            values = list(updates.values()) + [finding_id]
            with self.connect() as conn:
                conn.execute(f"UPDATE findings SET {assignments} WHERE id = ?", values)
        return self.get_finding(finding_id)

    def delete_finding(self, finding_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM findings WHERE id = ?", (finding_id,))

    def insert_export(self, export: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO exports (
                    id, project_id, export_dir, marked_pdf_path, csv_path, xlsx_path,
                    json_path, summary_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    export["id"],
                    export["project_id"],
                    export["export_dir"],
                    export.get("marked_pdf_path"),
                    export.get("csv_path"),
                    export.get("xlsx_path"),
                    export.get("json_path"),
                    export.get("summary_path"),
                    export["created_at"],
                ),
            )

    def _finding_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["location"] = _loads(item.pop("location_json", None), None)
        item["involved_entities"] = _loads(item.pop("involved_entities_json", None), [])
        item["evidence"] = _loads(item.pop("evidence_json", None), [])
        return item

