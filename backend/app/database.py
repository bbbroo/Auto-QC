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
                    sheet_title_source TEXT,
                    sheet_title_confidence REAL,
                    raw_extracted_title TEXT,
                    extraction_status TEXT,
                    ocr_status TEXT,
                    image_path TEXT,
                    text_content TEXT,
                    width REAL,
                    height REAL,
                    rotation INTEGER DEFAULT 0,
                    source_width REAL,
                    source_height REAL,
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
                    original_ai_json TEXT,
                    ai_batch_id TEXT,
                    prompt_version TEXT,
                    reviewer_note TEXT,
                    placement_status TEXT,
                    placement_details_json TEXT,
                    duplicate_of TEXT,
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
                    qa_report_path TEXT,
                    xlsx_path TEXT,
                    json_path TEXT,
                    summary_path TEXT,
                    html_path TEXT,
                    status_filter_json TEXT,
                    validation_json TEXT,
                    finding_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finding_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    finding_id TEXT,
                    stable_id TEXT,
                    action TEXT NOT NULL,
                    changes_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_prompt_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    prompt_version TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    sheet_index_json TEXT,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS ai_import_batches (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_type TEXT,
                    prompt_version TEXT,
                    prompt_id TEXT,
                    raw_response_text TEXT,
                    parser_warnings_json TEXT,
                    parser_repairs_json TEXT,
                    candidate_count INTEGER DEFAULT 0,
                    valid_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    created_count INTEGER DEFAULT 0,
                    updated_count INTEGER DEFAULT 0,
                    duplicate_count INTEGER DEFAULT 0,
                    import_status TEXT NOT NULL,
                    preview_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    imported_at TEXT
                );

                CREATE TABLE IF NOT EXISTS markup_memory_examples (
                    id TEXT PRIMARY KEY,
                    source_project_id TEXT,
                    source_finding_id TEXT NOT NULL,
                    source_pdf_name TEXT,
                    page_number INTEGER,
                    sheet_id TEXT,
                    drawing_number TEXT,
                    sheet_title TEXT,
                    sheet_type TEXT,
                    category TEXT,
                    severity TEXT,
                    target_text TEXT,
                    required_update TEXT,
                    final_comment_text TEXT,
                    rationale TEXT,
                    reviewer_note TEXT,
                    status_outcome TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    normalized_search_text TEXT,
                    tags_json TEXT,
                    original_ai_json TEXT,
                    usefulness_score REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_finding_id, status_outcome)
                );

                CREATE TABLE IF NOT EXISTS markup_memory_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    include_in_prompts INTEGER NOT NULL DEFAULT 0,
                    max_examples_per_prompt INTEGER NOT NULL DEFAULT 8,
                    max_avoid_examples_per_prompt INTEGER NOT NULL DEFAULT 5,
                    include_rejected_examples INTEGER NOT NULL DEFAULT 1,
                    include_accepted_examples INTEGER NOT NULL DEFAULT 1,
                    include_edited_examples INTEGER NOT NULL DEFAULT 1,
                    include_current_project_examples INTEGER NOT NULL DEFAULT 0,
                    min_usefulness_score REAL NOT NULL DEFAULT 0,
                    advanced_feature_enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_checklists (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    checklist_id TEXT NOT NULL,
                    checklist_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_checklist_items (
                    id TEXT PRIMARY KEY,
                    project_checklist_id TEXT NOT NULL REFERENCES project_checklists(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    checklist_id TEXT NOT NULL,
                    checklist_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    section TEXT NOT NULL,
                    discipline TEXT,
                    sheet_type TEXT,
                    item_text TEXT NOT NULL,
                    applicability TEXT NOT NULL DEFAULT 'applicable',
                    status TEXT NOT NULL DEFAULT 'not_started',
                    mapped_finding_ids_json TEXT,
                    reviewer_notes TEXT,
                    source_template_reference TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "exports", "html_path", "TEXT")
            self._ensure_column(conn, "exports", "qa_report_path", "TEXT")
            self._ensure_column(conn, "exports", "status_filter_json", "TEXT")
            self._ensure_column(conn, "exports", "validation_json", "TEXT")
            self._ensure_column(conn, "exports", "finding_count", "INTEGER DEFAULT 0")
            for column, column_type in {
                "rotation": "INTEGER DEFAULT 0",
                "source_width": "REAL",
                "source_height": "REAL",
                "sheet_title_source": "TEXT",
                "sheet_title_confidence": "REAL",
                "raw_extracted_title": "TEXT",
            }.items():
                self._ensure_column(conn, "sheets", column, column_type)
            for column, column_type in {
                "original_ai_json": "TEXT",
                "ai_batch_id": "TEXT",
                "prompt_version": "TEXT",
                "reviewer_note": "TEXT",
                "placement_status": "TEXT",
                "placement_details_json": "TEXT",
                "duplicate_of": "TEXT",
            }.items():
                self._ensure_column(conn, "findings", column, column_type)
            self._ensure_column(conn, "ai_import_batches", "metadata_json", "TEXT")
            self._ensure_column(conn, "markup_memory_examples", "original_ai_json", "TEXT")
            self._ensure_column(conn, "markup_memory_settings", "max_avoid_examples_per_prompt", "INTEGER NOT NULL DEFAULT 5")
            self._ensure_column(conn, "markup_memory_settings", "include_current_project_examples", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_markup_memory_settings(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_markup_memory_examples_project
                ON markup_memory_examples(source_project_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_markup_memory_examples_outcome
                ON markup_memory_examples(status_outcome, usefulness_score)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_project_checklists_project
                ON project_checklists(project_id, updated_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_project_checklist_items_project
                ON project_checklist_items(project_id, section, status)
                """
            )

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _ensure_markup_memory_settings(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT id FROM markup_memory_settings WHERE id = 1").fetchone()
        if row is not None:
            return
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO markup_memory_settings (
                id, enabled, include_in_prompts, max_examples_per_prompt,
                max_avoid_examples_per_prompt, include_rejected_examples,
                include_accepted_examples, include_edited_examples,
                include_current_project_examples, min_usefulness_score,
                advanced_feature_enabled, created_at, updated_at
            )
            VALUES (1, 0, 0, 8, 5, 1, 1, 1, 0, 0, 0, ?, ?)
            """,
            (now, now),
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
                       (SELECT COUNT(*) FROM findings WHERE project_id = p.id AND source = 'ai') AS finding_count
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
                       (SELECT COUNT(*) FROM findings WHERE project_id = p.id AND source = 'ai') AS finding_count
                FROM projects p
                ORDER BY p.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_project(self, project_id: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            if cursor.rowcount == 0:
                raise KeyError(project_id)

    def clear_project_analysis(self, project_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM sheets WHERE project_id = ?", (project_id,))

    def insert_sheet(self, sheet: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sheets (
                    id, project_id, page_number, drawing_number, sheet_title, revision, sheet_type,
                    sheet_title_source, sheet_title_confidence, raw_extracted_title,
                    extraction_status, ocr_status, image_path, text_content, width, height,
                    rotation, source_width, source_height, review_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sheet["id"],
                    sheet["project_id"],
                    sheet["page_number"],
                    sheet.get("drawing_number"),
                    sheet.get("sheet_title"),
                    sheet.get("revision"),
                    sheet.get("sheet_type"),
                    sheet.get("sheet_title_source"),
                    float(sheet.get("sheet_title_" + "confidence") or 0.0),
                    sheet.get("raw" + "_extracted" + "_title"),
                    sheet.get("extraction_status"),
                    sheet.get("ocr_status"),
                    sheet.get("image_path"),
                    sheet.get("text_content"),
                    sheet.get("width"),
                    sheet.get("height"),
                    sheet.get("rotation", 0),
                    sheet.get("source_width"),
                    sheet.get("source_height"),
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

    def replace_findings(
        self,
        project_id: str,
        findings: Iterable[dict[str, Any]],
        sources: list[str] | None = None,
    ) -> None:
        rows = _merge_duplicate_stable_findings([finding for finding in findings if not _is_legacy_spam_finding(finding)])
        now = utc_now_iso()
        with self.connect() as conn:
            params: list[Any] = [project_id]
            source_clause = ""
            if sources:
                source_clause = f" AND source IN ({','.join('?' for _ in sources)})"
                params.extend(sources)
            previous_rows = conn.execute(
                f"SELECT * FROM findings WHERE project_id = ?{source_clause}",
                params,
            ).fetchall()
            previous_by_stable = {row["stable_id"]: self._finding_from_row(row) for row in previous_rows}
            incoming_stable_ids = {finding["stable_id"] for finding in rows}
            retired = [row for row in previous_rows if row["stable_id"] not in incoming_stable_ids]

            conn.execute(f"DELETE FROM findings WHERE project_id = ?{source_clause}", params)
            insert_rows = []
            for finding in rows:
                previous = previous_by_stable.get(finding["stable_id"])
                merged = dict(finding)
                if previous:
                    merged.update(_preserved_review_fields(previous))
                    merged["id"] = previous["id"]
                    merged["created_at"] = previous.get("created_at", merged.get("created_at", now))
                    merged["updated_at"] = now
                    self._insert_finding_event(
                        conn,
                        project_id=project_id,
                        finding_id=merged["id"],
                        stable_id=merged["stable_id"],
                        action="rerun_preserved_review",
                        changes={"preserved_status": previous.get("status")},
                        created_at=now,
                    )
                insert_rows.append(
                    (
                        merged["id"],
                        project_id,
                        merged.get("sheet_id"),
                        merged["stable_id"],
                        merged["title"],
                        merged["category"],
                        merged["severity"],
                        merged["confidence"],
                        merged.get("page_number"),
                        _json(merged.get("location")) if merged.get("location") else None,
                        _json(merged.get("involved_entities", [])),
                        _json(merged.get("evidence", [])),
                        merged.get("reasoning_summary", ""),
                        merged.get("suggested_correction", ""),
                        merged.get("comment_text", ""),
                        merged.get("status", "needs_review"),
                        merged.get("source", "rules"),
                        _json(merged.get("original_ai_json")) if merged.get("original_ai_json") is not None else None,
                        merged.get("ai_batch_id"),
                        merged.get("prompt_version"),
                        merged.get("reviewer_note"),
                        merged.get("placement_status"),
                        _json(merged.get("placement_details")) if merged.get("placement_details") is not None else None,
                        merged.get("duplicate_of"),
                        merged.get("created_at", now),
                        merged.get("updated_at", now),
                    )
                )
            conn.executemany(
                """
                INSERT INTO findings (
                    id, project_id, sheet_id, stable_id, title, category, severity, confidence,
                    page_number, location_json, involved_entities_json, evidence_json,
                    reasoning_summary, suggested_correction, comment_text, status, source,
                    original_ai_json, ai_batch_id, prompt_version, reviewer_note,
                    placement_status, placement_details_json, duplicate_of,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
            for row in retired:
                self._insert_finding_event(
                    conn,
                    project_id=project_id,
                    finding_id=row["id"],
                    stable_id=row["stable_id"],
                    action="rerun_retired_finding",
                    changes={"title": row["title"], "status": row["status"]},
                    created_at=now,
                )

    def list_findings(
        self,
        project_id: str,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [project_id]
        where = "project_id = ?"
        if statuses:
            where += f" AND status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        if sources:
            where += f" AND source IN ({','.join('?' for _ in sources)})"
            params.extend(sources)
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
        return [finding for finding in (self._finding_from_row(row) for row in rows) if not _is_legacy_spam_finding(finding)]

    def get_finding(self, finding_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        if row is None:
            raise KeyError(finding_id)
        return self._finding_from_row(row)

    def update_finding(self, finding_id: str, fields: dict[str, Any], action: str = "manual_update") -> dict[str, Any]:
        allowed = {
            "title",
            "category",
            "severity",
            "confidence",
            "page_number",
            "reasoning_summary",
            "suggested_correction",
            "comment_text",
            "status",
            "reviewer_note",
            "duplicate_of",
        }
        updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
        with self.connect() as conn:
            before_row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
            if before_row is None:
                raise KeyError(finding_id)
            before = self._finding_from_row(before_row)
            if fields.get("rationale") is not None:
                updates["reasoning_summary"] = fields["rationale"]
            if fields.get("required_update") is not None:
                updates["suggested_correction"] = fields["required_update"]
            if fields.get("target_text") is not None:
                updates["evidence_json"] = _json(_updated_target_evidence(before.get("evidence") or [], fields.get("target_text")))
            if "page_number" in updates:
                updates["sheet_id"] = self._sheet_id_for_page(conn, before["project_id"], updates["page_number"])
            if updates:
                updates["updated_at"] = utc_now_iso()
                assignments = ", ".join(f"{key} = ?" for key in updates)
                values = list(updates.values()) + [finding_id]
                conn.execute(f"UPDATE findings SET {assignments} WHERE id = ?", values)
                changed = {
                    key: {"from": before.get(key), "to": value}
                    for key, value in updates.items()
                    if key != "updated_at" and before.get(key) != value
                }
                if changed:
                    event_action = action
                    if action == "manual_update":
                        event_action = "status_change" if set(changed) == {"status"} else "finding_edit"
                    self._insert_finding_event(
                        conn,
                        project_id=before["project_id"],
                        finding_id=finding_id,
                        stable_id=before.get("stable_id"),
                        action=event_action,
                        changes=changed,
                        created_at=updates["updated_at"],
                    )
        return self.get_finding(finding_id)

    def update_finding_placement(self, finding_id: str, placement_status: str, placement_details: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE findings
                SET placement_status = ?, placement_details_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (placement_status, _json(placement_details), now, finding_id),
            )

    def update_finding_manual_placement(
        self,
        finding_id: str,
        page_number: int,
        location: dict[str, Any],
        placement_details: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as conn:
            before_row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
            if before_row is None:
                raise KeyError(finding_id)
            before = self._finding_from_row(before_row)
            sheet_id = self._sheet_id_for_page(conn, before["project_id"], page_number)
            conn.execute(
                """
                UPDATE findings
                SET page_number = ?, sheet_id = ?, location_json = ?, placement_status = ?,
                    placement_details_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    page_number,
                    sheet_id,
                    _json(location),
                    "manual_placement",
                    _json(placement_details),
                    now,
                    finding_id,
                ),
            )
            self._insert_finding_event(
                conn,
                project_id=before["project_id"],
                finding_id=finding_id,
                stable_id=before.get("stable_id"),
                action="manual_placement_saved",
                changes={
                    "page_number": {"from": before.get("page_number"), "to": page_number},
                    "location": location,
                    "placement_status": "manual_placement",
                },
                created_at=now,
            )
        return self.get_finding(finding_id)

    def bulk_update_findings(self, finding_ids: list[str], fields: dict[str, Any]) -> list[dict[str, Any]]:
        return [self.update_finding(finding_id, fields, action="bulk_update") for finding_id in finding_ids]

    def delete_finding(self, finding_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
            if row is None:
                raise KeyError(finding_id)
            finding = self._finding_from_row(row)
            self._insert_finding_event(
                conn,
                project_id=finding["project_id"],
                finding_id=finding_id,
                stable_id=finding.get("stable_id"),
                action="delete",
                changes={"title": finding.get("title"), "status": finding.get("status")},
                created_at=utc_now_iso(),
            )
            conn.execute("DELETE FROM findings WHERE id = ?", (finding_id,))

    def insert_export(self, export: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO exports (
                    id, project_id, export_dir, marked_pdf_path, csv_path, xlsx_path,
                    json_path, summary_path, html_path, qa_report_path,
                    status_filter_json, validation_json, finding_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    export.get("html_path"),
                    export.get("qa_report_path"),
                    _json(export.get("status_filter") or []),
                    _json(export.get("validation")) if export.get("validation") is not None else None,
                    int(export.get("finding_count") or 0),
                    export["created_at"],
                ),
            )
            self._insert_finding_event(
                conn,
                project_id=export["project_id"],
                finding_id=None,
                stable_id=None,
                action="export_created",
                changes={
                    "export_id": export["id"],
                    "export_dir": export["export_dir"],
                    "status_filter": export.get("status_filter") or [],
                    "finding_count": int(export.get("finding_count") or 0),
                    "validation_status": (export.get("validation") or {}).get("status"),
                },
                created_at=export["created_at"],
            )

    def list_exports(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM exports
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["status_filter"] = _loads(item.pop("status_filter_json", None), [])
            item["validation"] = _loads(item.pop("validation_json", None), None)
            out.append(item)
        return out

    def insert_project_event(
        self,
        project_id: str,
        action: str,
        changes: dict[str, Any] | None = None,
        finding_id: str | None = None,
        stable_id: str | None = None,
    ) -> None:
        with self.connect() as conn:
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=finding_id,
                stable_id=stable_id,
                action=action,
                changes=changes or {},
                created_at=utc_now_iso(),
            )

    def list_finding_events(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM finding_events
                WHERE project_id = ?
                ORDER BY created_at DESC, action ASC
                """,
                (project_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["changes"] = _loads(item.pop("changes_json", None), {})
            out.append(item)
        return out

    def rollback_import_batch(self, project_id: str, batch_id: str, *, confirm: bool = False) -> dict[str, Any]:
        batch = self.get_ai_import_batch(batch_id, project_id=project_id)
        preview = batch.get("preview") or {}
        created_stable_ids = {
            item.get("stable_id")
            for item in preview.get("updates", [])
            if isinstance(item, dict) and item.get("will_import") and item.get("action") == "create_new" and item.get("stable_id")
        }
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM findings
                WHERE project_id = ? AND source = 'ai' AND ai_batch_id = ?
                {f"AND stable_id IN ({','.join('?' for _ in created_stable_ids)})" if created_stable_ids else "AND 1 = 0"}
                """,
                [project_id, batch_id, *sorted(created_stable_ids)],
            ).fetchall()
            findings = [self._finding_from_row(row) for row in rows]
            status_counts: dict[str, int] = {}
            affected_reviewed = 0
            for finding in findings:
                status = str(finding.get("status") or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                if status != "needs_review" or finding.get("reviewer_note"):
                    affected_reviewed += 1
            if not confirm:
                return {
                    "batch_id": batch_id,
                    "import_status": batch.get("import_status"),
                    "findings_to_remove": len(findings),
                    "reviewed_or_edited_findings": affected_reviewed,
                    "status_counts": status_counts,
                    "finding_ids": [finding["id"] for finding in findings],
                    "will_delete_unrelated_findings": False,
                    "confirmed": False,
                }
            now = utc_now_iso()
            for finding in findings:
                self._insert_finding_event(
                    conn,
                    project_id=project_id,
                    finding_id=finding["id"],
                    stable_id=finding.get("stable_id"),
                    action="ai_import_batch_rollback_removed_finding",
                    changes={
                        "batch_id": batch_id,
                        "title": finding.get("title"),
                        "status": finding.get("status"),
                    },
                    created_at=now,
                )
            if findings:
                conn.execute(
                    f"DELETE FROM findings WHERE id IN ({','.join('?' for _ in findings)})",
                    [finding["id"] for finding in findings],
                )
            conn.execute(
                """
                UPDATE ai_import_batches
                SET import_status = ?, metadata_json = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    "rolled_back",
                    _json({**(batch.get("metadata") or {}), "rollback": {"removed_count": len(findings), "rolled_back_at": now}}),
                    batch_id,
                    project_id,
                ),
            )
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=None,
                stable_id=None,
                action="ai_import_batch_rolled_back",
                changes={
                    "batch_id": batch_id,
                    "removed_count": len(findings),
                    "reviewed_or_edited_findings": affected_reviewed,
                    "status_counts": status_counts,
                },
                created_at=now,
            )
        return {
            "batch_id": batch_id,
            "import_status": "rolled_back",
            "findings_removed": len(findings),
            "reviewed_or_edited_findings": affected_reviewed,
            "status_counts": status_counts,
            "finding_ids": [finding["id"] for finding in findings],
            "confirmed": True,
        }

    def rollback_latest_bulk_status_update(self, project_id: str, *, confirm: bool = False) -> dict[str, Any]:
        events = [
            event
            for event in self.list_finding_events(project_id)
            if event.get("action") == "bulk_update"
            and isinstance(event.get("changes"), dict)
            and isinstance(event["changes"].get("status"), dict)
        ]
        if not events:
            return {"rolled_back": False, "count": 0, "message": "No bulk status update was found."}
        latest_at = events[0]["created_at"]
        batch_events = [event for event in events if event["created_at"] == latest_at]
        preview_rows = []
        for event in batch_events:
            change = event["changes"]["status"]
            preview_rows.append(
                {
                    "finding_id": event.get("finding_id"),
                    "stable_id": event.get("stable_id"),
                    "from": change.get("from"),
                    "to": change.get("to"),
                }
            )
        if not confirm:
            return {"rolled_back": False, "count": len(preview_rows), "updates": preview_rows, "created_at": latest_at}

        updated = []
        for row in preview_rows:
            if row.get("finding_id") and row.get("from"):
                updated.append(self.update_finding(row["finding_id"], {"status": row["from"]}, action="bulk_status_rollback"))
        self.insert_project_event(
            project_id,
            "bulk_status_rollback",
            {"count": len(updated), "source_created_at": latest_at},
        )
        return {"rolled_back": True, "count": len(updated), "updates": preview_rows, "findings": updated}

    def merge_finding_into(self, duplicate_finding_id: str, target_finding_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            duplicate_row = conn.execute("SELECT * FROM findings WHERE id = ?", (duplicate_finding_id,)).fetchone()
            target_row = conn.execute("SELECT * FROM findings WHERE id = ?", (target_finding_id,)).fetchone()
            if duplicate_row is None or target_row is None:
                raise KeyError(duplicate_finding_id if duplicate_row is None else target_finding_id)
            duplicate = self._finding_from_row(duplicate_row)
            target = self._finding_from_row(target_row)
            if duplicate.get("project_id") != target.get("project_id") or duplicate.get("source") != "ai" or target.get("source") != "ai":
                raise ValueError("Findings must be AI findings in the same project.")
            now = utc_now_iso()
            merged_evidence = _dedupe_json_items(
                (target.get("evidence") or [])
                + [
                    {
                        "observation": f"Merged duplicate finding: {duplicate.get('title')}",
                        "source_finding_id": duplicate.get("id"),
                        "source_stable_id": duplicate.get("stable_id"),
                        "target_text": _first_evidence_text(duplicate),
                        "required_update": duplicate.get("suggested_correction"),
                        "rationale": duplicate.get("reasoning_summary"),
                    }
                ]
                + (duplicate.get("evidence") or [])
            )
            conn.execute(
                """
                UPDATE findings
                SET evidence_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json(merged_evidence), now, target_finding_id),
            )
            duplicate_note = _join_unique_text(
                duplicate.get("reviewer_note"),
                f"Marked duplicate and merged into {target.get('stable_id') or target_finding_id}.",
            )
            conn.execute(
                """
                UPDATE findings
                SET status = 'duplicate', duplicate_of = ?, reviewer_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_finding_id, duplicate_note, now, duplicate_finding_id),
            )
            self._insert_finding_event(
                conn,
                project_id=target["project_id"],
                finding_id=duplicate_finding_id,
                stable_id=duplicate.get("stable_id"),
                action="finding_marked_duplicate",
                changes={"duplicate_of": target_finding_id, "target_stable_id": target.get("stable_id")},
                created_at=now,
            )
            self._insert_finding_event(
                conn,
                project_id=target["project_id"],
                finding_id=target_finding_id,
                stable_id=target.get("stable_id"),
                action="finding_merged_duplicate_evidence",
                changes={"merged_finding_id": duplicate_finding_id, "merged_stable_id": duplicate.get("stable_id")},
                created_at=now,
            )
        return {"duplicate": self.get_finding(duplicate_finding_id), "target": self.get_finding(target_finding_id)}

    def insert_ai_prompt_run(
        self,
        project_id: str,
        prompt_version: str,
        sheet_index: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_id = str(uuid.uuid4())
        generated_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_prompt_runs (id, project_id, prompt_version, generated_at, sheet_index_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prompt_id, project_id, prompt_version, generated_at, _json(sheet_index), _json(metadata)),
            )
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=None,
                stable_id=None,
                action="manual_ai_prompt_generated",
                changes={"prompt_id": prompt_id, "prompt_version": prompt_version, **metadata},
                created_at=generated_at,
            )
        return {
            "id": prompt_id,
            "project_id": project_id,
            "prompt_version": prompt_version,
            "generated_at": generated_at,
            "sheet_index": sheet_index,
            "metadata": metadata,
        }

    def get_ai_prompt_run(self, prompt_id: str, project_id: str | None = None) -> dict[str, Any]:
        params: list[Any] = [prompt_id]
        where = "id = ?"
        if project_id:
            where += " AND project_id = ?"
            params.append(project_id)
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM ai_prompt_runs WHERE {where}", params).fetchone()
        if row is None:
            raise KeyError(prompt_id)
        item = dict(row)
        item["sheet_index"] = _loads(item.pop("sheet_index_json", None), [])
        item["metadata"] = _loads(item.pop("metadata_json", None), {})
        return item

    def create_ai_import_batch(self, project_id: str, batch: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": batch.get("id") or str(uuid.uuid4()),
            "project_id": project_id,
            "source_type": batch.get("source_type") or "unknown",
            "prompt_version": batch.get("prompt_version"),
            "prompt_id": batch.get("prompt_id"),
            "raw_response_text": batch.get("raw_response_text"),
            "parser_warnings": batch.get("parser_warnings") or [],
            "parser_repairs": batch.get("parser_repairs") or [],
            "candidate_count": int(batch.get("candidate_count") or 0),
            "valid_count": int(batch.get("valid_count") or 0),
            "skipped_count": int(batch.get("skipped_count") or 0),
            "created_count": int(batch.get("created_count") or 0),
            "updated_count": int(batch.get("updated_count") or 0),
            "duplicate_count": int(batch.get("duplicate_count") or 0),
            "import_status": batch.get("import_status") or "previewed",
            "preview": batch.get("preview"),
            "metadata": batch.get("metadata") or {},
            "created_at": batch.get("created_at") or utc_now_iso(),
            "imported_at": batch.get("imported_at"),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_import_batches (
                    id, project_id, source_type, prompt_version, prompt_id, raw_response_text,
                    parser_warnings_json, parser_repairs_json, candidate_count, valid_count,
                    skipped_count, created_count, updated_count, duplicate_count, import_status,
                    preview_json, metadata_json, created_at, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["project_id"],
                    record["source_type"],
                    record["prompt_version"],
                    record["prompt_id"],
                    record["raw_response_text"],
                    _json(record["parser_warnings"]),
                    _json(record["parser_repairs"]),
                    record["candidate_count"],
                    record["valid_count"],
                    record["skipped_count"],
                    record["created_count"],
                    record["updated_count"],
                    record["duplicate_count"],
                    record["import_status"],
                    _json(record["preview"]) if record.get("preview") is not None else None,
                    _json(record["metadata"]),
                    record["created_at"],
                    record["imported_at"],
                ),
            )
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=None,
                stable_id=None,
                action=f"ai_import_{record['import_status']}",
                changes={
                    "batch_id": record["id"],
                    "candidate_count": record["candidate_count"],
                    "valid_count": record["valid_count"],
                    "skipped_count": record["skipped_count"],
                },
                created_at=record["created_at"],
            )
        return record

    def update_ai_import_batch(self, batch_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "parser_warnings",
            "parser_repairs",
            "candidate_count",
            "valid_count",
            "skipped_count",
            "created_count",
            "updated_count",
            "duplicate_count",
            "import_status",
            "preview",
            "metadata",
            "imported_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_ai_import_batch(batch_id)
        db_updates: dict[str, Any] = {}
        for key, value in updates.items():
            if key == "parser_warnings":
                db_updates["parser_warnings_json"] = _json(value or [])
            elif key == "parser_repairs":
                db_updates["parser_repairs_json"] = _json(value or [])
            elif key == "preview":
                db_updates["preview_json"] = _json(value) if value is not None else None
            elif key == "metadata":
                db_updates["metadata_json"] = _json(value or {})
            else:
                db_updates[key] = value
        assignments = ", ".join(f"{key} = ?" for key in db_updates)
        with self.connect() as conn:
            before = conn.execute("SELECT * FROM ai_import_batches WHERE id = ?", (batch_id,)).fetchone()
            if before is None:
                raise KeyError(batch_id)
            conn.execute(f"UPDATE ai_import_batches SET {assignments} WHERE id = ?", list(db_updates.values()) + [batch_id])
            row = conn.execute("SELECT * FROM ai_import_batches WHERE id = ?", (batch_id,)).fetchone()
            assert row is not None
            record = self._ai_import_batch_from_row(row)
            self._insert_finding_event(
                conn,
                project_id=record["project_id"],
                finding_id=None,
                stable_id=None,
                action=f"ai_import_{record['import_status']}",
                changes={
                    "batch_id": batch_id,
                    "created_count": record.get("created_count", 0),
                    "updated_count": record.get("updated_count", 0),
                    "duplicate_count": record.get("duplicate_count", 0),
                },
                created_at=utc_now_iso(),
            )
        return record

    def get_ai_import_batch(self, batch_id: str, project_id: str | None = None) -> dict[str, Any]:
        params: list[Any] = [batch_id]
        where = "id = ?"
        if project_id:
            where += " AND project_id = ?"
            params.append(project_id)
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM ai_import_batches WHERE {where}", params).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return self._ai_import_batch_from_row(row)

    def list_ai_import_batches(self, project_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_import_batches
                WHERE project_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        return [self._ai_import_batch_from_row(row) for row in rows]

    def get_markup_memory_settings(self) -> dict[str, Any]:
        with self.connect() as conn:
            self._ensure_markup_memory_settings(conn)
            row = conn.execute("SELECT * FROM markup_memory_settings WHERE id = 1").fetchone()
        assert row is not None
        return self._markup_memory_settings_from_row(row)

    def update_markup_memory_settings(self, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "enabled",
            "include_in_prompts",
            "max_examples_per_prompt",
            "max_avoid_examples_per_prompt",
            "include_rejected_examples",
            "include_accepted_examples",
            "include_edited_examples",
            "include_current_project_examples",
            "min_usefulness_score",
            "advanced_feature_enabled",
        }
        updates: dict[str, Any] = {}
        bool_fields = {
            "enabled",
            "include_in_prompts",
            "include_rejected_examples",
            "include_accepted_examples",
            "include_edited_examples",
            "include_current_project_examples",
            "advanced_feature_enabled",
        }
        int_fields = {"max_examples_per_prompt", "max_avoid_examples_per_prompt"}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in bool_fields:
                updates[key] = 1 if bool(value) else 0
            elif key in int_fields:
                updates[key] = max(1, min(25, int(value)))
            elif key == "min_usefulness_score":
                updates[key] = max(0.0, min(5.0, float(value)))
        if not updates:
            return self.get_markup_memory_settings()
        updates["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as conn:
            self._ensure_markup_memory_settings(conn)
            conn.execute(f"UPDATE markup_memory_settings SET {assignments} WHERE id = 1", list(updates.values()))
        return self.get_markup_memory_settings()

    def upsert_markup_memory_example(self, example: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        record = {
            "id": example.get("id") or str(uuid.uuid4()),
            "source_project_id": example.get("source_project_id"),
            "source_finding_id": example["source_finding_id"],
            "source_pdf_name": example.get("source_pdf_name"),
            "page_number": example.get("page_number"),
            "sheet_id": example.get("sheet_id"),
            "drawing_number": example.get("drawing_number"),
            "sheet_title": example.get("sheet_title"),
            "sheet_type": example.get("sheet_type"),
            "category": example.get("category"),
            "severity": example.get("severity"),
            "target_text": example.get("target_text"),
            "required_update": example.get("required_update"),
            "final_comment_text": example.get("final_comment_text"),
            "rationale": example.get("rationale"),
            "reviewer_note": example.get("reviewer_note"),
            "status_outcome": example["status_outcome"],
            "source_type": example.get("source_type") or "manual_edit",
            "normalized_search_text": example.get("normalized_search_text"),
            "tags": example.get("tags") or {},
            "original_ai_json": example.get("original_ai_json"),
            "usefulness_score": float(example.get("usefulness_score") or 0),
            "created_at": example.get("created_at") or now,
            "updated_at": example.get("updated_at") or now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO markup_memory_examples (
                    id, source_project_id, source_finding_id, source_pdf_name,
                    page_number, sheet_id, drawing_number, sheet_title, sheet_type,
                    category, severity, target_text, required_update, final_comment_text,
                    rationale, reviewer_note, status_outcome, source_type,
                    normalized_search_text, tags_json, original_ai_json, usefulness_score,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_finding_id, status_outcome) DO UPDATE SET
                    source_project_id = excluded.source_project_id,
                    source_pdf_name = excluded.source_pdf_name,
                    page_number = excluded.page_number,
                    sheet_id = excluded.sheet_id,
                    drawing_number = excluded.drawing_number,
                    sheet_title = excluded.sheet_title,
                    sheet_type = excluded.sheet_type,
                    category = excluded.category,
                    severity = excluded.severity,
                    target_text = excluded.target_text,
                    required_update = excluded.required_update,
                    final_comment_text = excluded.final_comment_text,
                    rationale = excluded.rationale,
                    reviewer_note = excluded.reviewer_note,
                    source_type = excluded.source_type,
                    normalized_search_text = excluded.normalized_search_text,
                    tags_json = excluded.tags_json,
                    original_ai_json = excluded.original_ai_json,
                    usefulness_score = excluded.usefulness_score,
                    updated_at = excluded.updated_at
                """,
                (
                    record["id"],
                    record["source_project_id"],
                    record["source_finding_id"],
                    record["source_pdf_name"],
                    record["page_number"],
                    record["sheet_id"],
                    record["drawing_number"],
                    record["sheet_title"],
                    record["sheet_type"],
                    record["category"],
                    record["severity"],
                    record["target_text"],
                    record["required_update"],
                    record["final_comment_text"],
                    record["rationale"],
                    record["reviewer_note"],
                    record["status_outcome"],
                    record["source_type"],
                    record["normalized_search_text"],
                    _json(record["tags"]),
                    _json(record["original_ai_json"]) if record.get("original_ai_json") is not None else None,
                    record["usefulness_score"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM markup_memory_examples
                WHERE source_finding_id = ? AND status_outcome = ?
                """,
                (record["source_finding_id"], record["status_outcome"]),
            ).fetchone()
        assert row is not None
        return self._markup_memory_example_from_row(row)

    def list_markup_memory_examples(
        self,
        *,
        min_usefulness_score: float | None = None,
        status_outcomes: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "1 = 1"
        if min_usefulness_score is not None:
            where += " AND usefulness_score >= ?"
            params.append(float(min_usefulness_score))
        if status_outcomes:
            where += f" AND status_outcome IN ({','.join('?' for _ in status_outcomes)})"
            params.extend(status_outcomes)
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            params.append(max(1, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM markup_memory_examples
                WHERE {where}
                ORDER BY usefulness_score DESC, updated_at DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [self._markup_memory_example_from_row(row) for row in rows]

    def markup_memory_stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM markup_memory_examples").fetchone()["count"]
            by_outcome = {
                row["status_outcome"]: row["count"]
                for row in conn.execute(
                    """
                    SELECT status_outcome, COUNT(*) AS count
                    FROM markup_memory_examples
                    GROUP BY status_outcome
                    """
                ).fetchall()
            }
            by_category = {
                row["category"] or "unknown": row["count"]
                for row in conn.execute(
                    """
                    SELECT COALESCE(category, 'unknown') AS category, COUNT(*) AS count
                    FROM markup_memory_examples
                    GROUP BY COALESCE(category, 'unknown')
                    ORDER BY count DESC, category ASC
                    """
                ).fetchall()
            }
        return {
            "total_memory_examples": int(total or 0),
            "accepted_examples": int(by_outcome.get("accepted", 0)),
            "edited_examples": int(by_outcome.get("edited", 0)),
            "rejected_examples": int(by_outcome.get("rejected", 0)),
            "duplicate_examples": int(by_outcome.get("duplicate", 0)),
            "exported_examples": int(by_outcome.get("exported", 0)),
            "deferred_examples": int(by_outcome.get("deferred", 0)),
            "needs_manual_placement_examples": int(by_outcome.get("needs_manual_placement", 0)),
            "needs_engineer_input_examples": int(by_outcome.get("needs_engineer_input", 0)),
            "examples_by_category": by_category,
            "examples_by_outcome": by_outcome,
        }

    def clear_markup_memory(self) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM markup_memory_examples")
        return int(cursor.rowcount or 0)

    def select_project_checklist(self, project_id: str, template: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        checklist_id = str(template["id"])
        checklist_record_id = str(uuid.uuid4())
        items = template.get("items") if isinstance(template.get("items"), list) else []
        with self.connect() as conn:
            self.get_project(project_id)
            conn.execute("DELETE FROM project_checklist_items WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM project_checklists WHERE project_id = ?", (project_id,))
            conn.execute(
                """
                INSERT INTO project_checklists (
                    id, project_id, checklist_id, checklist_name, version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checklist_record_id,
                    project_id,
                    checklist_id,
                    str(template.get("name") or checklist_id),
                    str(template.get("version") or "v1"),
                    now,
                    now,
                ),
            )
            rows = []
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                rows.append(
                    (
                        str(uuid.uuid4()),
                        checklist_record_id,
                        project_id,
                        checklist_id,
                        str(template.get("name") or checklist_id),
                        str(template.get("version") or "v1"),
                        str(item.get("section") or "General"),
                        item.get("discipline"),
                        item.get("sheet_type"),
                        str(item.get("item_text") or item.get("text") or f"Checklist item {index}"),
                        str(item.get("applicability") or "applicable"),
                        "not_started",
                        _json([]),
                        "",
                        item.get("source_template_reference") or template.get("source_template_reference"),
                        now,
                        now,
                    )
                )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO project_checklist_items (
                        id, project_checklist_id, project_id, checklist_id, checklist_name, version,
                        section, discipline, sheet_type, item_text, applicability, status,
                        mapped_finding_ids_json, reviewer_notes, source_template_reference,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=None,
                stable_id=None,
                action="checklist_selected",
                changes={"checklist_id": checklist_id, "item_count": len(rows)},
                created_at=now,
            )
        return self.get_project_checklist(project_id)

    def get_project_checklist(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            checklist_row = conn.execute(
                """
                SELECT * FROM project_checklists
                WHERE project_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if checklist_row is None:
                return None
            rows = conn.execute(
                """
                SELECT * FROM project_checklist_items
                WHERE project_checklist_id = ?
                ORDER BY section ASC, id ASC
                """,
                (checklist_row["id"],),
            ).fetchall()
        checklist = self._project_checklist_from_row(checklist_row)
        checklist["items"] = [self._project_checklist_item_from_row(row) for row in rows]
        checklist["progress"] = checklist_progress_from_items(checklist["items"])
        return checklist

    def update_project_checklist_item(self, project_id: str, item_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"status", "applicability", "reviewer_notes", "mapped_finding_ids"}
        updates = {key: fields[key] for key in allowed if key in fields}
        if "mapped_finding_ids" in updates:
            updates["mapped_finding_ids_json"] = _json(updates.pop("mapped_finding_ids") or [])
        if not updates:
            checklist = self.get_project_checklist(project_id)
            if checklist is None:
                raise KeyError(item_id)
            for item in checklist["items"]:
                if item["id"] == item_id:
                    return item
            raise KeyError(item_id)

        updates["updated_at"] = utc_now_iso()
        with self.connect() as conn:
            before_row = conn.execute(
                "SELECT * FROM project_checklist_items WHERE id = ? AND project_id = ?",
                (item_id, project_id),
            ).fetchone()
            if before_row is None:
                raise KeyError(item_id)
            before = self._project_checklist_item_from_row(before_row)
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE project_checklist_items SET {assignments} WHERE id = ? AND project_id = ?",
                list(updates.values()) + [item_id, project_id],
            )
            conn.execute(
                "UPDATE project_checklists SET updated_at = ? WHERE id = ?",
                (updates["updated_at"], before["project_checklist_id"]),
            )
            self._insert_finding_event(
                conn,
                project_id=project_id,
                finding_id=None,
                stable_id=None,
                action="checklist_item_updated",
                changes={
                    key: {"from": before.get(key), "to": fields.get(key)}
                    for key in ["status", "applicability", "reviewer_notes", "mapped_finding_ids"]
                    if key in fields and before.get(key) != fields.get(key)
                },
                created_at=updates["updated_at"],
            )
        checklist = self.get_project_checklist(project_id)
        if checklist is None:
            raise KeyError(item_id)
        for item in checklist["items"]:
            if item["id"] == item_id:
                return item
        raise KeyError(item_id)

    def project_checklist_progress(self, project_id: str) -> dict[str, Any] | None:
        checklist = self.get_project_checklist(project_id)
        if checklist is None:
            return None
        return checklist.get("progress")

    def _insert_finding_event(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        finding_id: str | None,
        stable_id: str | None,
        action: str,
        changes: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO finding_events (id, project_id, finding_id, stable_id, action, changes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), project_id, finding_id, stable_id, action, _json(changes), created_at),
        )

    def _finding_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["location"] = _loads(item.pop("location_json", None), None)
        item["involved_entities"] = _loads(item.pop("involved_entities_json", None), [])
        item["evidence"] = _loads(item.pop("evidence_json", None), [])
        item["original_ai_json"] = _loads(item.pop("original_ai_json", None), None)
        item["placement_details"] = _loads(item.pop("placement_details_json", None), None)
        return item

    def _ai_import_batch_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["parser_warnings"] = _loads(item.pop("parser_warnings_json", None), [])
        item["parser_repairs"] = _loads(item.pop("parser_repairs_json", None), [])
        item["preview"] = _loads(item.pop("preview_json", None), None)
        item["metadata"] = _loads(item.pop("metadata_json", None), {})
        return item

    def _markup_memory_example_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = _loads(item.pop("tags_json", None), {})
        item["original_ai_json"] = _loads(item.pop("original_ai_json", None), None)
        return item

    def _markup_memory_settings_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in [
            "enabled",
            "include_in_prompts",
            "include_rejected_examples",
            "include_accepted_examples",
            "include_edited_examples",
            "include_current_project_examples",
            "advanced_feature_enabled",
        ]:
            item[key] = bool(item.get(key))
        item["max_examples_per_prompt"] = int(item.get("max_examples_per_prompt") or 8)
        item["max_avoid_examples_per_prompt"] = int(item.get("max_avoid_examples_per_prompt") or 5)
        item["min_usefulness_score"] = float(item.get("min_usefulness_score") or 0)
        return item

    def _project_checklist_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def _project_checklist_item_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["mapped_finding_ids"] = _loads(item.pop("mapped_finding_ids_json", None), [])
        return item

    def _sheet_id_for_page(self, conn: sqlite3.Connection, project_id: str, page_number: Any) -> str | None:
        try:
            page = int(page_number)
        except (TypeError, ValueError):
            return None
        row = conn.execute(
            "SELECT id FROM sheets WHERE project_id = ? AND page_number = ?",
            (project_id, page),
        ).fetchone()
        return row["id"] if row else None


def _preserved_review_fields(previous: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": previous.get("status"),
        "reviewer_note": previous.get("reviewer_note"),
    }


def _updated_target_evidence(evidence: list[Any], target_text: Any) -> list[dict[str, Any]]:
    target = " ".join(str(target_text or "").split())
    items = [dict(item) for item in evidence if isinstance(item, dict)]
    if not items:
        items = [{"observation": "Reviewer-provided target text for markup placement."}]
    first = items[0]
    first["target_text"] = target
    first["markup_text"] = target
    first["text_excerpt"] = target
    return items


def _first_evidence_text(finding: dict[str, Any]) -> str:
    for item in finding.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        for key in ["target_text", "markup_text", "text_excerpt", "observation"]:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
    return ""


def _is_legacy_spam_finding(finding: dict[str, Any]) -> bool:
    spam_comments = {
        "Complete title block. Drawing number was not identified.",
        "Visually review this sheet. Text extraction/OCR appears weak, so automated QC coverage may be incomplete.",
        "Verify title block revision. Extraction found title-block context but did not identify the revision.",
    }
    spam_titles = {
        "Drawing number not identified",
        "Sheet extraction quality requires visual review",
        "Revision missing or not identified in title block region",
    }
    return str(finding.get("comment_text") or "").strip() in spam_comments or str(finding.get("title") or "").strip() in spam_titles


def _merge_duplicate_stable_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for finding in findings:
        stable_id = finding.get("stable_id")
        if not stable_id:
            continue
        existing = merged.get(stable_id)
        if not existing:
            merged[stable_id] = dict(finding)
            continue
        existing["confidence"] = max(float(existing.get("confidence") or 0), float(finding.get("confidence") or 0))
        if _finding_severity_rank(finding.get("severity")) < _finding_severity_rank(existing.get("severity")):
            existing["severity"] = finding.get("severity")
        existing["evidence"] = _dedupe_json_items((existing.get("evidence") or []) + (finding.get("evidence") or []))
        existing["involved_entities"] = sorted(set((existing.get("involved_entities") or []) + (finding.get("involved_entities") or [])))
        existing["location"] = existing.get("location") or finding.get("location")
        existing["reasoning_summary"] = _join_unique_text(existing.get("reasoning_summary"), finding.get("reasoning_summary"))
        existing["suggested_correction"] = _join_unique_text(existing.get("suggested_correction"), finding.get("suggested_correction"))
        existing["comment_text"] = _join_unique_text(existing.get("comment_text"), finding.get("comment_text"))
    return list(merged.values())


def _finding_severity_rank(severity: Any) -> int:
    return {"Critical": 0, "Major": 1, "Minor": 2, "Note": 3}.get(str(severity or ""), 4)


def _dedupe_json_items(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = _json(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _join_unique_text(first: Any, second: Any) -> str:
    left = str(first or "").strip()
    right = str(second or "").strip()
    if not left:
        return right
    if not right or right == left or right in left:
        return left
    if left in right:
        return right
    return f"{left} | {right}"


def checklist_progress_from_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    by_status: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "not_started")
        by_status[status] = by_status.get(status, 0) + 1
    completed = sum(by_status.get(status, 0) for status in ["checked", "issue_found", "not_applicable"])
    linked_count = sum(1 for item in items if item.get("mapped_finding_ids"))
    return {
        "total_items": total,
        "completed_items": completed,
        "issue_items": int(by_status.get("issue_found", 0)),
        "linked_items": linked_count,
        "percent_complete": round((completed / total) * 100, 1) if total else 0.0,
        "by_status": by_status,
    }
