from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import fitz

from backend.app.config import AI_PROVIDER_BASE_URLS, settings
from backend.app.database import Database
from backend.app.models import (
    BulkFindingUpdate,
    ExportRequest,
    FindingUpdate,
    ManualAIImportRequest,
    ManualAIPreviewRequest,
    ManualPlacementRequest,
    MergeFindingRequest,
    RollbackRequest,
)
from backend.app.sample_pdf import ensure_default_sample_pdf
from backend.app.services.ai_review import AIReviewService, public_ai_import_batch
from backend.app.services.exports import ExportService
from backend.app.services.markup_memory import MEMORY_OUTCOMES, MarkupMemoryService
from backend.app.services.placement_coordinates import (
    display_rect_to_image_rect,
    display_rect_to_pdf_rect,
    image_rect_to_pdf_rect,
    normalized_rect,
    pdf_rect_to_image_rect,
    pdf_rect_to_display_rect,
)
from backend.app.services.pdf_processor import PDFProcessor
from backend.app.services.project_packages import MAX_PACKAGE_UNCOMPRESSED_BYTES, ProjectPackageService
from backend.app.services.review_coverage import project_review_coverage_summary
from backend.app.services.storage import safe_project_source_pdf_path, safe_public_data_asset_path


settings.ensure_dirs()
db = Database(settings.db_path)
db.init_schema()
processor = PDFProcessor(db, settings)
export_service = ExportService(db, settings.data_dir)
ai_review_service = AIReviewService(db, settings)
package_service = ProjectPackageService(db, settings.data_dir)
memory_service = MarkupMemoryService(db)
logger = logging.getLogger(__name__)
PDF_UPLOAD_CHUNK_BYTES = 1024 * 1024
PACKAGE_UPLOAD_MAX_BYTES = MAX_PACKAGE_UNCOMPRESSED_BYTES

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

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/data/{file_path:path}")
def data_asset(file_path: str) -> FileResponse:
    asset = safe_public_data_asset_path(settings.data_dir, file_path)
    if not asset or not asset.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(asset)


@app.get("/projects")
def list_projects(include_validation: bool = False) -> list[dict[str, Any]]:
    return [_enrich_project(project) for project in db.list_projects(include_validation=include_validation)]


@app.post("/projects")
async def create_project(
    name: str = Form(...),
    file: UploadFile | None = File(None),
    auto_review: bool = Form(True),
    project_type: str = Form("review"),
) -> dict[str, Any]:
    project = db.create_project(name=name, project_type=project_type)
    if file is not None:
        try:
            content = await _read_upload_bytes_limited(
                file,
                max_bytes=settings.max_upload_mb * 1024 * 1024,
                label="PDF upload",
            )
            processor.save_uploaded_pdf(project["id"], file.filename or "drawing_set.pdf", content)
            if auto_review:
                processor.process_project(project["id"])
        except HTTPException as exc:
            db.update_project(project["id"], status="failed", summary=str(exc.detail))
            raise
        except ValueError as exc:
            db.update_project(project["id"], status="failed", summary=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            message = f"Uploaded file could not be opened as a PDF: {exc}"
            db.update_project(project["id"], status="failed", summary=message)
            raise HTTPException(status_code=400, detail=message) from exc
        except Exception as exc:
            message = f"Drawing upload failed during automatic review: {exc}"
            db.update_project(project["id"], status="failed", summary=message)
            raise HTTPException(status_code=422, detail=message) from exc
    return get_project(project["id"])


@app.delete("/maintenance/validation-projects")
def delete_validation_projects() -> dict[str, Any]:
    project_ids = db.list_validation_project_ids()
    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    for project_id in project_ids:
        try:
            project = db.get_project(project_id)
            project_dir = _safe_project_dir_for_delete(project_id, project)
            db.delete_project(project_id)
            if project_dir.exists():
                shutil.rmtree(project_dir)
            deleted.append(project_id)
        except Exception as exc:
            errors.append({"project_id": project_id, "error": str(exc)})
    return {
        "deleted_count": len(deleted),
        "deleted_project_ids": deleted,
        "errors": errors,
        "remaining_by_type": db.count_projects_by_type(),
    }


@app.post("/maintenance/validation-projects/tag-generated")
def tag_generated_validation_projects(dry_run: bool = True) -> dict[str, Any]:
    return db.tag_generated_validation_projects(dry_run=dry_run)


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


@app.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, str]:
    try:
        project = db.get_project(project_id)
        project_dir = _safe_project_dir_for_delete(project_id, project)
        db.delete_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc

    if project_dir.exists():
        shutil.rmtree(project_dir)
    return {"status": "deleted"}


@app.post("/projects/{project_id}/project-package")
def export_project_package(project_id: str, include_source_pdf: bool = True) -> dict[str, Any]:
    try:
        db.get_project(project_id)
        return _public_project_package_export(package_service.export_project_package(project_id, include_source_pdf=include_source_pdf))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/project-package/{package_id}/download")
def download_project_package(project_id: str, package_id: str) -> FileResponse:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    path = package_service.package_path(project_id, package_id)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Project package not found")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/project-packages/import")
async def import_project_package(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "autoqc_project_package.zip").suffix.lower()
    if suffix != ".zip":
        raise HTTPException(status_code=400, detail="Import an AutoQC project package .zip file.")
    temp_path = await _write_upload_to_temp_file_limited(
        file,
        suffix=".zip",
        max_bytes=PACKAGE_UPLOAD_MAX_BYTES,
        label="Project package upload",
    )
    try:
        result = package_service.import_project_package(temp_path)
        result["project"] = _enrich_project(result["project"])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/project-packages/import/preview")
async def preview_project_package_import(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "autoqc_project_package.zip").suffix.lower()
    if suffix != ".zip":
        raise HTTPException(status_code=400, detail="Import an AutoQC project package .zip file.")
    temp_path = await _write_upload_to_temp_file_limited(
        file,
        suffix=".zip",
        max_bytes=PACKAGE_UPLOAD_MAX_BYTES,
        label="Project package upload",
    )
    try:
        preview = package_service.preview_project_package(temp_path)
        if not preview.get("valid"):
            return preview
        return preview
    finally:
        temp_path.unlink(missing_ok=True)


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
    return db.list_findings(project_id, sources=["ai"])


@app.post("/projects/{project_id}/findings/recalculate-placement")
def recalculate_finding_placement(project_id: str) -> dict[str, Any]:
    try:
        result = ai_review_service.recalculate_finding_locations(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["project"] = _enrich_project(result["project"])
    return result


@app.get("/ai/status")
def ai_status() -> dict[str, Any]:
    return ai_review_service.status()


@app.put("/ai/settings")
def save_ai_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    api_key = str(payload.get("api_key") or "").strip()
    model = str(payload.get("model") or "").strip()
    provider = str(payload.get("provider") or settings.ai_provider or "openai").strip().lower()
    provider = {"openai-compatible": "openai", "deep seek": "deepseek"}.get(provider, provider)
    provider_key = provider.replace("-", "").replace("_", "").replace(" ", "")
    if provider_key == "openaicompatible":
        provider = "openai"
    if provider_key == "deepseekai" or provider_key == "deepseek":
        provider = "deepseek"
    if provider not in AI_PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail="AI product must be OpenAI or DeepSeek.")
    base_url = str(payload.get("base_url") or AI_PROVIDER_BASE_URLS[provider]).strip()
    if not api_key and not settings.ai_api_key:
        raise HTTPException(status_code=400, detail="Enter an API key before running AI Deep Review.")
    if not model and not settings.ai_model:
        raise HTTPException(status_code=400, detail="Enter a model before running AI Deep Review.")
    settings.save_user_ai_settings(
        api_key=api_key or None,
        model=model or None,
        provider=provider,
        base_url=base_url,
    )
    return ai_review_service.status()


@app.get("/readiness")
def readiness() -> dict[str, Any]:
    checks = [
        _readiness_check("Backend API alive", True, f"Python {sys.version.split()[0]}"),
        _readiness_check("Database writable", _writable_file(settings.db_path.parent), str(settings.db_path)),
        _readiness_check("Data directory writable", _writable_file(settings.data_dir), str(settings.data_dir)),
        _readiness_check("Project source folder writable", _writable_file(settings.data_dir / "projects"), str(settings.data_dir / "projects")),
        _readiness_check("Export folders writable", _writable_file(settings.data_dir / "projects"), "exports are created under data/projects/<project-id>/exports"),
        _readiness_check(
            "Frontend app configured",
            (settings.repo_root / "frontend" / "package.json").exists() and (settings.repo_root / "frontend" / "src" / "App.tsx").exists(),
            "Running health does not require ports 8000/5173 to be free.",
        ),
        _readiness_check("Playwright/browser tests configured", (settings.repo_root / "frontend" / "playwright.config.ts").exists(), "run cd frontend; npm run test:e2e"),
    ]
    instructions = {
        "frontend_typecheck": "cd frontend; npm run typecheck",
        "frontend_build": "cd frontend; npm run build",
        "browser_tests": "cd frontend; npm run test:e2e",
        "backend_tests": "pytest",
        "full_doctor": "python scripts/doctor.py --full",
    }
    return {
        "status": "passed" if all(check["ok"] for check in checks) else "warning",
        "mode": "running_app_health",
        "summary": "Running app health checks. Port availability is checked by scripts/doctor.py before startup, not here.",
        "actor": "Local reviewer",
        "checks": checks,
        "instructions": instructions,
    }


@app.get("/ai-review/prompt-templates")
def list_prompt_templates() -> list[dict[str, Any]]:
    return ai_review_service.list_prompt_templates()


@app.get("/markup-memory/settings")
def get_markup_memory_settings() -> dict[str, Any]:
    return db.get_markup_memory_settings()


@app.put("/markup-memory/settings")
def update_markup_memory_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return db.update_markup_memory_settings(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/markup-memory/stats")
def get_markup_memory_stats() -> dict[str, Any]:
    return db.markup_memory_stats()


@app.post("/markup-memory/rebuild")
def rebuild_markup_memory() -> dict[str, Any]:
    return memory_service.rebuild_memory_from_existing_findings()


@app.delete("/markup-memory")
def clear_markup_memory() -> dict[str, Any]:
    return memory_service.clear_memory()


@app.get("/projects/{project_id}/markup-memory/relevant")
def get_project_markup_memory_examples(
    project_id: str,
    limit: int = 8,
    include_rejected: bool = True,
) -> dict[str, Any]:
    try:
        return memory_service.get_relevant_memory_examples(project_id, limit=limit, include_rejected=include_rejected)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.get("/projects/{project_id}/markup-memory/preview")
def preview_project_markup_memory_context(project_id: str) -> dict[str, Any]:
    try:
        return memory_service.build_markup_memory_prompt_context(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/projects/{project_id}/ai-review")
def run_ai_review(project_id: str) -> dict[str, Any]:
    try:
        result = ai_review_service.review_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI review failed: {exc}") from exc
    result["project"] = _enrich_project(result["project"])
    return result


@app.get("/projects/{project_id}/ai-review/manual-prompt")
def get_manual_ai_prompt(
    project_id: str,
    template_id: str | None = None,
    review_depth: str | None = None,
    review_scope: str | None = None,
    page_number: int | None = None,
    page_numbers: str | None = None,
    batch_size: int | None = None,
) -> dict[str, Any]:
    try:
        return ai_review_service.generate_manual_prompt(
            project_id,
            template_id=template_id,
            review_depth=review_depth,
            review_scope=review_scope,
            page_number=page_number,
            page_numbers=page_numbers,
            batch_size=batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/ai-review/manual-review-plan")
def get_manual_review_plan(project_id: str, batch_size: int | None = None) -> dict[str, Any]:
    try:
        return ai_review_service.build_manual_review_plan(project_id, batch_size=batch_size)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/projects/{project_id}/ai-review/import")
def import_manual_ai_response(project_id: str, request: ManualAIImportRequest) -> dict[str, Any]:
    try:
        if request.preview_id:
            result = ai_review_service.import_preview(project_id, request.preview_id)
        else:
            result = ai_review_service.import_manual_response(
                project_id,
                request.response_text or "",
                source_type=request.source_type,
                prompt_version=request.prompt_version,
                prompt_id=request.prompt_id,
                review_modality=request.review_modality,
                audit_of_batch_id=request.audit_of_batch_id,
                audit_round=request.audit_round,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["project"] = _enrich_project(result["project"])
    return result


@app.post("/projects/{project_id}/ai-review/preview")
def preview_manual_ai_response(project_id: str, request: ManualAIPreviewRequest) -> dict[str, Any]:
    try:
        return ai_review_service.preview_manual_response(
            project_id,
            request.response_text,
            source_type=request.source_type,
            prompt_version=request.prompt_version,
            prompt_id=request.prompt_id,
            review_modality=request.review_modality,
            audit_of_batch_id=request.audit_of_batch_id,
            audit_round=request.audit_round,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/ai-review/import-batches")
def list_ai_import_batches(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return [public_ai_import_batch(batch) for batch in db.list_ai_import_batches(project_id)]


@app.post("/projects/{project_id}/ai-review/import-batches/{batch_id}/rollback-preview")
def preview_ai_import_batch_rollback(project_id: str, batch_id: str) -> dict[str, Any]:
    try:
        db.get_project(project_id)
        return db.rollback_import_batch(project_id, batch_id, confirm=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project or import batch not found") from exc


@app.post("/projects/{project_id}/ai-review/import-batches/{batch_id}/rollback")
def rollback_ai_import_batch(project_id: str, batch_id: str, request: RollbackRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Rollback requires confirmation.")
    try:
        result = db.rollback_import_batch(project_id, batch_id, confirm=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project or import batch not found") from exc
    result["project"] = _enrich_project(db.get_project(project_id))
    result["findings"] = db.list_findings(project_id, sources=["ai"])
    return result


@app.post("/projects/{project_id}/findings/bulk/rollback-latest-status")
def rollback_latest_bulk_status_update(project_id: str, request: RollbackRequest) -> dict[str, Any]:
    try:
        db.get_project(project_id)
        return db.rollback_latest_bulk_status_update(project_id, confirm=request.confirm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.get("/projects/{project_id}/events")
def list_project_events(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return [_public_project_event(event) for event in db.list_finding_events(project_id)]


@app.patch("/findings/bulk")
def bulk_update_findings(update: BulkFindingUpdate) -> dict[str, Any]:
    for finding_id in update.finding_ids:
        _get_ai_finding_or_404(finding_id)
    fields = update.update.model_dump(exclude_unset=True)
    try:
        updated = db.bulk_update_findings(
            update.finding_ids,
            fields,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Finding not found: {exc.args[0]}") from exc
    outcome = _memory_outcome_for_update(fields)
    if outcome:
        for finding in updated:
            _collect_memory_safely(finding["project_id"], finding["id"], outcome)
    return {"updated": updated, "count": len(updated)}


@app.post("/findings/{finding_id}/merge")
def merge_finding(finding_id: str, request: MergeFindingRequest) -> dict[str, Any]:
    _get_ai_finding_or_404(finding_id)
    _get_ai_finding_or_404(request.target_finding_id)
    try:
        result = db.merge_finding_into(finding_id, request.target_finding_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _collect_memory_safely(result["duplicate"]["project_id"], result["duplicate"]["id"], "duplicate")
    return result


@app.patch("/findings/{finding_id}")
def update_finding(finding_id: str, update: FindingUpdate) -> dict[str, Any]:
    _get_ai_finding_or_404(finding_id)
    fields = update.model_dump(exclude_unset=True)
    try:
        finding = db.update_finding(finding_id, fields)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc
    outcome = _memory_outcome_for_update(fields)
    if outcome:
        _collect_memory_safely(finding["project_id"], finding["id"], outcome)
    return finding


@app.post("/findings/{finding_id}/manual-placement")
def save_manual_finding_placement(finding_id: str, request: ManualPlacementRequest) -> dict[str, Any]:
    finding = _get_ai_finding_or_404(finding_id)
    try:
        input_rect = normalized_rect([float(value) for value in request.rect])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Manual placement rectangle must contain four numbers.") from exc
    if input_rect[2] - input_rect[0] < 2 or input_rect[3] - input_rect[1] < 2:
        raise HTTPException(status_code=400, detail="Manual placement rectangle is too small.")

    sheet = next((item for item in db.list_sheets(finding["project_id"]) if int(item.get("page_number") or 0) == request.page_number), {})
    geometry = _manual_placement_geometry(finding["project_id"], request.page_number, sheet, request)
    source_width = geometry["source_width"]
    source_height = geometry["source_height"]
    display_width = geometry["display_width"]
    display_height = geometry["display_height"]
    image_width = geometry["image_width"]
    image_height = geometry["image_height"]
    rotation = geometry["page_rotation"]

    if request.coordinate_space == "image_pixel" and (image_width <= 0 or image_height <= 0):
        raise HTTPException(status_code=400, detail="Manual image-pixel placement requires image_width and image_height.")

    if request.coordinate_space == "pdf_unrotated":
        pdf_rect = input_rect
        page_display_rect = pdf_rect_to_display_rect(
            pdf_rect,
            source_width=source_width,
            source_height=source_height,
            rotation=rotation,
        )
        image_rect = pdf_rect_to_image_rect(
            pdf_rect,
            image_width=image_width or display_width,
            image_height=image_height or display_height,
            source_width=source_width,
            source_height=source_height,
            display_width=display_width,
            display_height=display_height,
            rotation=rotation,
        )
        stored_display_rect = page_display_rect
    elif request.coordinate_space == "display_rotated":
        page_display_rect = input_rect
        pdf_rect = display_rect_to_pdf_rect(
            page_display_rect,
            source_width=source_width,
            source_height=source_height,
            rotation=rotation,
        )
        image_rect = display_rect_to_image_rect(
            page_display_rect,
            image_width=image_width or display_width,
            image_height=image_height or display_height,
            display_width=display_width,
            display_height=display_height,
        )
        stored_display_rect = page_display_rect
    else:
        image_rect = input_rect
        page_display_rect = []
        pdf_rect = image_rect_to_pdf_rect(
            image_rect,
            image_width=image_width,
            image_height=image_height,
            source_width=source_width,
            source_height=source_height,
            display_width=display_width,
            display_height=display_height,
            rotation=rotation,
        )
        page_display_rect = pdf_rect_to_display_rect(
            pdf_rect,
            source_width=source_width,
            source_height=source_height,
            rotation=rotation,
        )
        stored_display_rect = image_rect

    location = {
        "bbox": image_rect,
        "origin": "top_left",
        "method": "manual_placement",
        "coordinate_space": "image_pixel",
        "manual_image_rect": image_rect,
        "pdf_rect": pdf_rect,
        "page_rotation": rotation,
        "source_width": round(source_width, 2),
        "source_height": round(source_height, 2),
        "page_display_width": round(display_width, 2),
        "page_display_height": round(display_height, 2),
        "image_width": round(image_width, 2),
        "image_height": round(image_height, 2),
    }
    placement_details = {
        "placement_status": "manual_placement",
        "target_found": True,
        "exported": True,
        "manual_placement_needed": False,
        "method": "manual_placement",
        "coordinate_space": "image_pixel",
        "input_coordinate_space": request.coordinate_space,
        "manual_image_rect_json": image_rect,
        "rect_json": pdf_rect,
        "pdf_rect_json": pdf_rect,
        "display_rect_json": stored_display_rect,
        "page_display_rect_json": page_display_rect,
        "page_rotation": rotation,
        "source_width": round(source_width, 2),
        "source_height": round(source_height, 2),
        "page_display_width": round(display_width, 2),
        "page_display_height": round(display_height, 2),
        "image_width": round(image_width, 2),
        "image_height": round(image_height, 2),
        "note": "Reviewer manually placed this markup rectangle in AutoQC.",
    }
    try:
        updated = db.update_finding_manual_placement(finding_id, request.page_number, location, placement_details)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc
    _collect_memory_safely(finding["project_id"], finding_id, "edited")
    return updated


@app.delete("/findings/{finding_id}")
def delete_finding(finding_id: str) -> dict[str, str]:
    _get_ai_finding_or_404(finding_id)
    db.delete_finding(finding_id)
    return {"status": "deleted"}


@app.post("/projects/{project_id}/exports")
def export_project(
    project_id: str,
    request: ExportRequest | None = Body(None),
    accepted_only: bool = True,
) -> dict[str, Any]:
    try:
        if request and request.statuses == []:
            raise ValueError("Choose at least one finding status to export.")
        statuses = request.statuses if request and request.statuses is not None else None
        resolved_accepted_only = request.accepted_only if request and request.accepted_only is not None else accepted_only
        result = export_service.export_project(
            project_id,
            accepted_only=resolved_accepted_only,
            statuses=statuses,
            export_mode=request.export_mode if request else "draft",
            reviewer_name=request.reviewer_name if request else None,
            final_export_confirmed=bool(request.final_export_confirmed) if request else False,
            acknowledge_validation_warnings=bool(request.acknowledge_validation_warnings) if request else False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    export = result["export"]
    files = {
        "marked_pdf": _data_url(export.get("marked_pdf_path")),
        "csv": _data_url(export.get("csv_path")),
        "qa_report": _data_url(export.get("qa_report_path") or export.get("csv_path")),
        "xlsx": _data_url(export.get("xlsx_path")),
        "json": _data_url(export.get("json_path")),
        "summary": _data_url(export.get("summary_path")),
        "html": _data_url(export.get("html_path")),
    }
    return {
        "export": _public_export_record(export),
        "files": files,
        "findings_exported": result["findings_exported"],
        "placement_summary": result.get("placement_summary"),
        "validation": result.get("validation"),
        "export_mode": result.get("export_mode"),
        "review_coverage": result.get("review_coverage"),
        "signoff": result.get("signoff"),
    }


@app.get("/projects/{project_id}/source-pdf")
def source_pdf(project_id: str) -> FileResponse:
    try:
        project = db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    source = _safe_project_source_pdf_path(project_id, project)
    if not source or not source.exists():
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(source, media_type="application/pdf")


def _enrich_project(project: dict[str, Any]) -> dict[str, Any]:
    project = dict(project)
    project["project_type"] = project.get("project_type") or "review"
    source = project.get("source_pdf_path")
    project["source_pdf_url"] = f"/projects/{project['id']}/source-pdf" if source else None
    project["source_pdf_path"] = None
    try:
        findings = db.list_findings(project["id"], sources=["ai"])
    except Exception:
        findings = []
    project["finding_count"] = len(findings)
    project["findings_count"] = len(findings)
    project["finding_status_counts"] = _count_by(findings, "status")
    project["finding_severity_counts"] = _count_by(findings, "severity")
    project["finding_category_counts"] = _count_by(findings, "category")
    try:
        project["review_coverage"] = project_review_coverage_summary(
            db.list_sheets(project["id"]),
            db.list_ai_import_batches(project["id"], limit=1000),
        )
    except Exception:
        project["review_coverage"] = None
    return project


def _public_export_record(export: dict[str, Any]) -> dict[str, Any]:
    item = dict(export)
    item["export_dir"] = None
    for key in ["marked_pdf_path", "csv_path", "qa_report_path", "xlsx_path", "json_path", "summary_path", "html_path"]:
        item[key] = _data_url(export.get(key))
    return item


def _public_project_package_export(result: dict[str, Any]) -> dict[str, Any]:
    item = dict(result)
    item["path"] = None
    return item


def _public_project_event(event: dict[str, Any]) -> dict[str, Any]:
    item = dict(event)
    if isinstance(item.get("changes"), dict):
        item["changes"] = _sanitize_public_change_values(item["changes"])
    return item


def _sanitize_public_change_values(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str) and (_looks_like_local_path_key(str(key)) or _looks_like_local_path(item)):
                sanitized[key] = _redacted_path_label(item)
            else:
                sanitized[key] = _sanitize_public_change_values(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_change_values(item) for item in value]
    return value


def _looks_like_local_path_key(key: str) -> bool:
    normalized = key.lower()
    return normalized.endswith("_dir") or "path" in normalized or "directory" in normalized


def _looks_like_local_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\") or bool(re.match(r"^/(Users|home|var|tmp|mnt)/", value))


def _redacted_path_label(value: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", value) if part]
    filename = parts[-1] if parts else ""
    return f"[local path hidden: {filename}]" if filename else "[local path hidden]"


async def _read_upload_bytes_limited(file: UploadFile, *, max_bytes: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(PDF_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"{label} exceeds {max_bytes // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _write_upload_to_temp_file_limited(file: UploadFile, *, suffix: str, max_bytes: int, label: str) -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(handle.name)
    try:
        total = 0
        while True:
            chunk = await file.read(PDF_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail=f"{label} exceeds {max_bytes // (1024 * 1024)} MB limit.")
            handle.write(chunk)
    except Exception:
        handle.close()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        if not handle.closed:
            handle.close()
    return temp_path


def _enrich_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    sheet = dict(sheet)
    sheet["image_url"] = _data_url(sheet.get("image_path"))
    if not sheet.get("source_width") or not sheet.get("source_height"):
        sheet.update(_source_page_geometry(sheet))
    return sheet


def _source_page_geometry(sheet: dict[str, Any]) -> dict[str, Any]:
    try:
        project_id = str(sheet.get("project_id") or "")
        project = db.get_project(project_id)
        source = safe_project_source_pdf_path(settings.data_dir, project_id, project.get("source_pdf_path"))
        page_index = int(sheet.get("page_number") or 0) - 1
        if source is None or page_index < 0:
            return {}
        with fitz.open(source) as doc:
            if page_index >= len(doc):
                return {}
            page = doc[page_index]
            return {
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "rotation": int(page.rotation or 0),
                "source_width": float(page.cropbox.width),
                "source_height": float(page.cropbox.height),
            }
    except Exception:
        return {}


def _manual_placement_geometry(
    project_id: str,
    page_number: int,
    sheet: dict[str, Any],
    request: ManualPlacementRequest,
) -> dict[str, float | int]:
    source_geometry = _source_page_geometry({"project_id": project_id, "page_number": page_number})
    rotation = int(source_geometry.get("rotation") or sheet.get("rotation") or request.page_rotation or 0) % 360
    source_width = float(source_geometry.get("source_width") or sheet.get("source_width") or request.source_width or sheet.get("width") or 0)
    source_height = float(source_geometry.get("source_height") or sheet.get("source_height") or request.source_height or sheet.get("height") or 0)
    natural_display_width = source_height if rotation in {90, 270} else source_width
    natural_display_height = source_width if rotation in {90, 270} else source_height
    display_width = float(source_geometry.get("width") or sheet.get("width") or request.display_width or natural_display_width or source_width or 0)
    display_height = float(source_geometry.get("height") or sheet.get("height") or request.display_height or natural_display_height or source_height or 0)
    stored_image_width, stored_image_height = _sheet_image_dimensions(sheet)
    image_width = float(request.image_width or stored_image_width or 0)
    image_height = float(request.image_height or stored_image_height or 0)
    if image_width <= 0:
        image_width = display_width
    if image_height <= 0:
        image_height = display_height
    return {
        "source_width": source_width,
        "source_height": source_height,
        "display_width": display_width,
        "display_height": display_height,
        "image_width": image_width,
        "image_height": image_height,
        "page_rotation": rotation,
    }


def _sheet_image_dimensions(sheet: dict[str, Any]) -> tuple[float | None, float | None]:
    image_path = sheet.get("image_path")
    if not image_path:
        return None, None
    try:
        pixmap = fitz.Pixmap(str(image_path))
        return float(pixmap.width), float(pixmap.height)
    except Exception:
        return None, None


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _readiness_check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _writable_file(path: Path) -> bool:
    try:
        target_dir = path if path.suffix == "" else path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / ".autoqc-readiness-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _safe_project_dir_for_delete(project_id: str, project: dict[str, Any]) -> Path:
    project_dir = processor.project_dir(project_id).resolve()
    data_dir = settings.data_dir.resolve()
    try:
        project_dir.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=500, detail="Project storage path is outside the data directory")

    return project_dir


def _safe_project_source_pdf_path(project_id: str, project: dict[str, Any]) -> Path | None:
    return safe_project_source_pdf_path(settings.data_dir, project_id, project.get("source_pdf_path"))


def _get_ai_finding_or_404(finding_id: str) -> dict[str, Any]:
    try:
        finding = db.get_finding(finding_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Finding not found") from exc
    if finding.get("source") != "ai":
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


def _memory_outcome_for_update(fields: dict[str, Any]) -> str | None:
    status = str(fields.get("status") or "").strip()
    if status in MEMORY_OUTCOMES and status != "needs_review":
        return status
    edited_fields = set(fields) - {"status"}
    if edited_fields:
        return "edited"
    return None


def _collect_memory_safely(project_id: str, finding_id: str, outcome: str) -> None:
    try:
        memory_service.collect_memory_from_finding(project_id, finding_id, outcome)
    except Exception as exc:
        logger.warning(
            "Markup Memory capture failed for project_id=%s finding_id=%s outcome=%s: %s",
            project_id,
            finding_id,
            outcome,
            exc,
            exc_info=True,
        )
        return


def _data_url(path: str | None) -> str | None:
    if not path:
        return None
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(settings.data_dir)
    except ValueError:
        return None
    return f"/data/{relative.as_posix()}"
