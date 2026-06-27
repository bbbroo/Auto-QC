from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.database import Database
from backend.app.models import FindingUpdate
from backend.app.sample_pdf import ensure_default_sample_pdf
from backend.app.services.exports import ExportService
from backend.app.services.pdf_processor import PDFProcessor


settings.ensure_dirs()
db = Database(settings.db_path)
db.init_schema()
processor = PDFProcessor(db, settings)
export_service = ExportService(db, settings.data_dir)

app = FastAPI(
    title="Natural Gas Engineering Copilot",
    description="Local-first drawing QC assistant for natural gas regulator station PDF drawing sets.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return [_enrich_project(project) for project in db.list_projects()]


@app.post("/projects")
async def create_project(
    name: str = Form(...),
    file: UploadFile | None = File(None),
    auto_review: bool = Form(True),
) -> dict[str, Any]:
    project = db.create_project(name=name)
    if file is not None:
        content = await file.read()
        processor.save_uploaded_pdf(project["id"], file.filename or "drawing_set.pdf", content)
        if auto_review:
            processor.process_project(project["id"])
    return get_project(project["id"])


@app.post("/sample-project")
def create_sample_project() -> dict[str, Any]:
    project = db.create_project("Synthetic Regulator Station Sample")
    sample_pdf = ensure_default_sample_pdf()
    processor.copy_sample_pdf(project["id"], sample_pdf)
    processor.process_project(project["id"])
    return get_project(project["id"])


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return _enrich_project(db.get_project(project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/projects/{project_id}/review")
def run_review(project_id: str) -> dict[str, Any]:
    try:
        result = processor.process_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["project"] = _enrich_project(result["project"])
    result["sheets"] = [_enrich_sheet(sheet) for sheet in result["sheets"]]
    return result


@app.get("/projects/{project_id}/sheets")
def list_sheets(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return [_enrich_sheet(sheet) for sheet in db.list_sheets(project_id)]


@app.get("/projects/{project_id}/entities")
def list_entities(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return db.list_entities(project_id)


@app.get("/projects/{project_id}/findings")
def list_findings(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return db.list_findings(project_id)


@app.patch("/findings/{finding_id}")
def update_finding(finding_id: str, update: FindingUpdate) -> dict[str, Any]:
    try:
        return db.update_finding(finding_id, update.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc


@app.delete("/findings/{finding_id}")
def delete_finding(finding_id: str) -> dict[str, str]:
    try:
        db.get_finding(finding_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc
    db.delete_finding(finding_id)
    return {"status": "deleted"}


@app.post("/projects/{project_id}/exports")
def export_project(project_id: str, accepted_only: bool = True) -> dict[str, Any]:
    try:
        result = export_service.export_project(project_id, accepted_only=accepted_only)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    export = result["export"]
    files = {
        "marked_pdf": _data_url(export.get("marked_pdf_path")),
        "csv": _data_url(export.get("csv_path")),
        "xlsx": _data_url(export.get("xlsx_path")),
        "json": _data_url(export.get("json_path")),
        "summary": _data_url(export.get("summary_path")),
    }
    return {"export": export, "files": files, "findings_exported": result["findings_exported"]}


@app.get("/projects/{project_id}/source-pdf")
def source_pdf(project_id: str) -> FileResponse:
    try:
        project = db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    source = project.get("source_pdf_path")
    if not source or not Path(source).exists():
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(source, media_type="application/pdf")


def _enrich_project(project: dict[str, Any]) -> dict[str, Any]:
    project = dict(project)
    source = project.get("source_pdf_path")
    project["source_pdf_url"] = _data_url(source) if source else None
    return project


def _enrich_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    sheet = dict(sheet)
    sheet["image_url"] = _data_url(sheet.get("image_path"))
    return sheet


def _data_url(path: str | None) -> str | None:
    if not path:
        return None
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(settings.data_dir)
    except ValueError:
        return None
    return f"/data/{relative.as_posix()}"

