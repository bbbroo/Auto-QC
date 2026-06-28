from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from backend.app.database import Database
from backend.app.models import utc_now_iso
from backend.app.services.storage import require_project_source_pdf_path, safe_public_data_asset_path


PACKAGE_SCHEMA_VERSION = "autoqc-project-package-v1"


class ProjectPackageService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = Path(data_dir).resolve()

    def export_project_package(self, project_id: str, include_source_pdf: bool = True) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        package_id = str(uuid.uuid4())
        package_dir = self.data_dir / "projects" / project_id / "packages" / package_id
        package_dir.mkdir(parents=True, exist_ok=True)
        package_path = package_dir / f"{safe_stem(project['name'])}_autoqc_package.zip"

        with TemporaryDirectory() as temp_name:
            staging = Path(temp_name)
            files_dir = staging / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            data = self._project_payload(project_id)
            file_manifest: dict[str, Any] = {"source_pdf": None, "sheet_images": {}, "exports": {}}

            if include_source_pdf:
                try:
                    source_pdf = require_project_source_pdf_path(self.data_dir, project_id, project.get("source_pdf_path"))
                except Exception:
                    source_pdf = None
                if source_pdf and source_pdf.exists():
                    target = files_dir / "source_pdf" / source_pdf.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_pdf, target)
                    file_manifest["source_pdf"] = target.relative_to(staging).as_posix()
                    data["project"]["source_pdf_reference"] = source_pdf.name

            for sheet in data["sheets"]:
                image_path = sheet.get("image_path")
                copied = self._copy_safe_data_file(image_path, files_dir / "sheet_images")
                if copied:
                    file_manifest["sheet_images"][sheet["id"]] = copied.relative_to(staging).as_posix()

            for export in data["exports"]:
                export_files: dict[str, str] = {}
                for key in ["marked_pdf_path", "csv_path", "qa_report_path", "xlsx_path", "json_path", "summary_path", "html_path"]:
                    copied = self._copy_safe_data_file(export.get(key), files_dir / "exports" / export["id"])
                    if copied:
                        export_files[key] = copied.relative_to(staging).as_posix()
                if export_files:
                    file_manifest["exports"][export["id"]] = export_files

            manifest = {
                "schema_version": PACKAGE_SCHEMA_VERSION,
                "package_id": package_id,
                "created_at": utc_now_iso(),
                "project_id": project_id,
                "project_name": project.get("name"),
                "file_manifest": file_manifest,
                "counts": {
                    "sheets": len(data["sheets"]),
                    "findings": len(data["findings"]),
                    "import_batches": len(data["ai_import_batches"]),
                    "audit_events": len(data["finding_events"]),
                    "exports": len(data["exports"]),
                },
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
            (staging / "project.json").write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in staging.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(staging).as_posix())

        self.db.insert_project_event(
            project_id,
            "project_package_exported",
            {"package_id": package_id, "package_path": str(package_path), "include_source_pdf": include_source_pdf},
        )
        return {
            "package_id": package_id,
            "project_id": project_id,
            "path": str(package_path),
            "filename": package_path.name,
            "download_url": f"/projects/{project_id}/project-package/{package_id}/download",
        }

    def package_path(self, project_id: str, package_id: str) -> Path | None:
        package_dir = (self.data_dir / "projects" / project_id / "packages" / package_id).resolve()
        try:
            package_dir.relative_to(self.data_dir)
        except ValueError:
            return None
        if not package_dir.exists():
            return None
        matches = list(package_dir.glob("*.zip"))
        return matches[0] if matches else None

    def import_project_package(self, package_file: Path, *, confirm_overwrite: bool = False) -> dict[str, Any]:
        with TemporaryDirectory() as temp_name:
            staging = Path(temp_name)
            try:
                with zipfile.ZipFile(package_file) as archive:
                    _safe_extract_zip(archive, staging)
            except zipfile.BadZipFile as exc:
                raise ValueError("Uploaded AutoQC project package is not a readable zip archive.") from exc

            manifest_path = staging / "manifest.json"
            project_path = staging / "project.json"
            if not manifest_path.exists() or not project_path.exists():
                raise ValueError("Package is missing manifest.json or project.json.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data = json.loads(project_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
                raise ValueError("Unsupported AutoQC project package schema version.")
            original_project_id = str(data.get("project", {}).get("id") or manifest.get("project_id") or "")
            if not original_project_id:
                raise ValueError("Package does not contain a project ID.")

            collision = self._project_exists(original_project_id)
            if collision and not confirm_overwrite:
                id_map = self._build_id_map(data, remap=True)
            else:
                id_map = self._build_id_map(data, remap=False)
            restored_project_id = id_map["projects"].get(original_project_id, original_project_id)
            project_dir = self.data_dir / "projects" / restored_project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            restored = self._remap_payload(data, id_map)
            self._restore_files(staging, manifest.get("file_manifest") or {}, restored, project_dir)
            self._insert_payload(restored)
            self.db.insert_project_event(
                restored_project_id,
                "project_package_imported",
                {
                    "original_project_id": original_project_id,
                    "restored_project_id": restored_project_id,
                    "remapped_ids": restored_project_id != original_project_id,
                    "source_package": package_file.name,
                },
            )
        return {
            "project": self.db.get_project(restored_project_id),
            "original_project_id": original_project_id,
            "restored_project_id": restored_project_id,
            "remapped_ids": restored_project_id != original_project_id,
        }

    def _project_payload(self, project_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            prompt_rows = conn.execute(
                "SELECT * FROM ai_prompt_runs WHERE project_id = ? ORDER BY generated_at ASC",
                (project_id,),
            ).fetchall()
            entities = conn.execute(
                "SELECT * FROM entities WHERE project_id = ? ORDER BY page_number ASC",
                (project_id,),
            ).fetchall()
        return {
            "project": self.db.get_project(project_id),
            "sheets": self.db.list_sheets(project_id),
            "entities": [dict(row) for row in entities],
            "findings": self.db.list_findings(project_id, sources=["ai"]),
            "ai_prompt_runs": [prompt_row_from_db(row) for row in prompt_rows],
            "ai_import_batches": self.db.list_ai_import_batches(project_id, limit=1000),
            "finding_events": self.db.list_finding_events(project_id),
            "exports": self.db.list_exports(project_id),
        }

    def _copy_safe_data_file(self, value: Any, target_dir: Path) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        source = Path(value).resolve()
        try:
            relative = source.relative_to(self.data_dir)
        except ValueError:
            return None
        public_safe = safe_public_data_asset_path(self.data_dir, relative.as_posix())
        if public_safe is None and "input" not in relative.parts:
            return None
        if not source.is_file():
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.copyfile(source, target)
        return target

    def _project_exists(self, project_id: str) -> bool:
        try:
            self.db.get_project(project_id)
        except KeyError:
            return False
        return True

    def _build_id_map(self, data: dict[str, Any], remap: bool) -> dict[str, dict[str, str]]:
        project_id = data["project"]["id"]
        maps = {
            "projects": {project_id: str(uuid.uuid4()) if remap else project_id},
            "sheets": {},
            "findings": {},
            "events": {},
            "batches": {},
            "prompts": {},
            "exports": {},
        }
        for collection, key in [
            ("sheets", "sheets"),
            ("findings", "findings"),
            ("finding_events", "events"),
            ("ai_import_batches", "batches"),
            ("ai_prompt_runs", "prompts"),
            ("exports", "exports"),
        ]:
            for item in data.get(collection, []):
                item_id = str(item.get("id") or "")
                if item_id:
                    maps[key][item_id] = str(uuid.uuid4()) if remap else item_id
        return maps

    def _remap_payload(self, data: dict[str, Any], id_map: dict[str, dict[str, str]]) -> dict[str, Any]:
        project_id = data["project"]["id"]
        restored_project_id = id_map["projects"][project_id]
        restored = json.loads(json.dumps(data))
        restored["project"]["id"] = restored_project_id
        restored["project"]["name"] = restored["project"].get("name") or "Restored AutoQC Project"
        if restored_project_id != project_id:
            restored["project"]["name"] = f"{restored['project']['name']} (restored)"
        for sheet in restored.get("sheets", []):
            sheet["_package_original_id"] = sheet.get("id")
            sheet["id"] = id_map["sheets"].get(sheet["id"], sheet["id"])
            sheet["project_id"] = restored_project_id
        for entity in restored.get("entities", []):
            if restored_project_id != project_id:
                entity["id"] = str(uuid.uuid4())
            entity["project_id"] = restored_project_id
            entity["sheet_id"] = id_map["sheets"].get(entity.get("sheet_id"), entity.get("sheet_id"))
        for finding in restored.get("findings", []):
            finding["id"] = id_map["findings"].get(finding["id"], finding["id"])
            finding["project_id"] = restored_project_id
            finding["sheet_id"] = id_map["sheets"].get(finding.get("sheet_id"), finding.get("sheet_id"))
            finding["ai_batch_id"] = id_map["batches"].get(finding.get("ai_batch_id"), finding.get("ai_batch_id"))
            finding["duplicate_of"] = id_map["findings"].get(finding.get("duplicate_of"), finding.get("duplicate_of"))
        for batch in restored.get("ai_import_batches", []):
            batch["id"] = id_map["batches"].get(batch["id"], batch["id"])
            batch["project_id"] = restored_project_id
            batch["prompt_id"] = id_map["prompts"].get(batch.get("prompt_id"), batch.get("prompt_id"))
        for prompt in restored.get("ai_prompt_runs", []):
            prompt["id"] = id_map["prompts"].get(prompt["id"], prompt["id"])
            prompt["project_id"] = restored_project_id
        for event in restored.get("finding_events", []):
            event["id"] = id_map["events"].get(event["id"], event["id"])
            event["project_id"] = restored_project_id
            event["finding_id"] = id_map["findings"].get(event.get("finding_id"), event.get("finding_id"))
        for export in restored.get("exports", []):
            export["_package_original_id"] = export.get("id")
            export["id"] = id_map["exports"].get(export["id"], export["id"])
            export["project_id"] = restored_project_id
        return restored

    def _restore_files(self, staging: Path, file_manifest: dict[str, Any], data: dict[str, Any], project_dir: Path) -> None:
        source_ref = file_manifest.get("source_pdf")
        if isinstance(source_ref, str):
            source = (staging / source_ref).resolve()
            if source.is_file() and source.suffix.lower() == ".pdf":
                target = project_dir / "input" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                data["project"]["source_pdf_path"] = str(target)
        sheet_images = file_manifest.get("sheet_images") if isinstance(file_manifest.get("sheet_images"), dict) else {}
        for sheet in data.get("sheets", []):
            image_ref = sheet_images.get(sheet.get("id")) or sheet_images.get(sheet.get("_package_original_id"))
            if isinstance(image_ref, str):
                source = (staging / image_ref).resolve()
                if source.is_file() and source.suffix.lower() == ".png":
                    target = project_dir / "sheets" / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    sheet["image_path"] = str(target)
        export_files = file_manifest.get("exports") if isinstance(file_manifest.get("exports"), dict) else {}
        for export in data.get("exports", []):
            restored_export_dir = project_dir / "exports" / export["id"]
            restored_export_dir.mkdir(parents=True, exist_ok=True)
            for key, file_ref in (export_files.get(export.get("id")) or export_files.get(export.get("_package_original_id")) or {}).items():
                source = (staging / file_ref).resolve()
                if source.is_file():
                    target = restored_export_dir / source.name
                    shutil.copyfile(source, target)
                    export[key] = str(target)
            export["export_dir"] = str(restored_export_dir)

    def _insert_payload(self, data: dict[str, Any]) -> None:
        project = data["project"]
        now = utc_now_iso()
        with self.db.connect() as conn:
            existing = conn.execute("SELECT id FROM projects WHERE id = ?", (project["id"],)).fetchone()
            if existing:
                raise ValueError("A project with this ID already exists. Import was remapped, but the remapped ID also collided.")
            conn.execute(
                """
                INSERT INTO projects (id, name, source_pdf_path, status, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project["id"],
                    project.get("name") or "Restored AutoQC Project",
                    project.get("source_pdf_path"),
                    project.get("status") or "ready",
                    project.get("summary"),
                    project.get("created_at") or now,
                    now,
                ),
            )
            for sheet in data.get("sheets", []):
                conn.execute(
                    """
                    INSERT INTO sheets (
                        id, project_id, page_number, drawing_number, sheet_title, revision, sheet_type,
                        extraction_status, ocr_status, image_path, text_content, width, height,
                        rotation, source_width, source_height, review_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sheet["id"],
                        project["id"],
                        sheet.get("page_number"),
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
                        sheet.get("rotation", 0),
                        sheet.get("source_width"),
                        sheet.get("source_height"),
                        sheet.get("review_status") or "ready",
                    ),
                )
            for entity in data.get("entities", []):
                conn.execute(
                    """
                    INSERT INTO entities (
                        id, project_id, sheet_id, entity_type, text, normalized_text, page_number,
                        bbox_json, confidence, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.get("id") or str(uuid.uuid4()),
                        project["id"],
                        entity.get("sheet_id"),
                        entity.get("entity_type"),
                        entity.get("text"),
                        entity.get("normalized_text"),
                        entity.get("page_number"),
                        entity.get("bbox_json") or (json.dumps(entity.get("bbox"), ensure_ascii=True) if entity.get("bbox") else None),
                        entity.get("confidence"),
                        entity.get("source"),
                    ),
                )
        self.db.replace_findings(project["id"], data.get("findings", []), sources=["ai"])
        with self.db.connect() as conn:
            for prompt in data.get("ai_prompt_runs", []):
                conn.execute(
                    """
                    INSERT INTO ai_prompt_runs (id, project_id, prompt_version, generated_at, sheet_index_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prompt["id"],
                        project["id"],
                        prompt.get("prompt_version"),
                        prompt.get("generated_at") or now,
                        json.dumps(prompt.get("sheet_index") or [], ensure_ascii=True),
                        json.dumps(prompt.get("metadata") or {}, ensure_ascii=True),
                    ),
                )
            for batch in data.get("ai_import_batches", []):
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
                        batch["id"],
                        project["id"],
                        batch.get("source_type"),
                        batch.get("prompt_version"),
                        batch.get("prompt_id"),
                        batch.get("raw_response_text"),
                        json.dumps(batch.get("parser_warnings") or [], ensure_ascii=True),
                        json.dumps(batch.get("parser_repairs") or [], ensure_ascii=True),
                        batch.get("candidate_count") or 0,
                        batch.get("valid_count") or 0,
                        batch.get("skipped_count") or 0,
                        batch.get("created_count") or 0,
                        batch.get("updated_count") or 0,
                        batch.get("duplicate_count") or 0,
                        batch.get("import_status") or "imported",
                        json.dumps(batch.get("preview"), ensure_ascii=True) if batch.get("preview") is not None else None,
                        json.dumps(batch.get("metadata") or {}, ensure_ascii=True),
                        batch.get("created_at") or now,
                        batch.get("imported_at"),
                    ),
                )
            for export in data.get("exports", []):
                conn.execute(
                    """
                    INSERT INTO exports (
                        id, project_id, export_dir, marked_pdf_path, csv_path, qa_report_path, xlsx_path,
                        json_path, summary_path, html_path, status_filter_json, validation_json, finding_count, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        export["id"],
                        project["id"],
                        export.get("export_dir"),
                        export.get("marked_pdf_path"),
                        export.get("csv_path"),
                        export.get("qa_report_path"),
                        export.get("xlsx_path"),
                        export.get("json_path"),
                        export.get("summary_path"),
                        export.get("html_path"),
                        json.dumps(export.get("status_filter") or [], ensure_ascii=True),
                        json.dumps(export.get("validation"), ensure_ascii=True) if export.get("validation") else None,
                        export.get("finding_count") or 0,
                        export.get("created_at") or now,
                    ),
                )
            for event in data.get("finding_events", []):
                conn.execute(
                    """
                    INSERT INTO finding_events (id, project_id, finding_id, stable_id, action, changes_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.get("id") or str(uuid.uuid4()),
                        project["id"],
                        event.get("finding_id"),
                        event.get("stable_id"),
                        event.get("action"),
                        json.dumps(event.get("changes") or {}, ensure_ascii=True),
                        event.get("created_at") or now,
                    ),
                )


def prompt_row_from_db(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["sheet_index"] = json.loads(item.pop("sheet_index_json") or "[]")
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    return item


def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise ValueError("Package contains an unsafe file path.") from exc
    archive.extractall(destination)


def safe_stem(name: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(name or "").strip())
    return value.strip("_") or "autoqc_project"
