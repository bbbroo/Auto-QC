from __future__ import annotations

from pathlib import Path


def project_dir(data_dir: Path, project_id: str) -> Path:
    return Path(data_dir).resolve() / "projects" / project_id


def project_input_dir(data_dir: Path, project_id: str) -> Path:
    return project_dir(data_dir, project_id) / "input"


def safe_project_source_pdf_path(data_dir: Path, project_id: str, source_pdf_path: str | None) -> Path | None:
    if not source_pdf_path:
        return None
    source_path = Path(source_pdf_path).resolve()
    input_dir = project_input_dir(data_dir, project_id).resolve()
    try:
        source_path.relative_to(input_dir)
    except ValueError:
        return None
    if source_path.suffix.lower() != ".pdf":
        return None
    return source_path


def require_project_source_pdf_path(data_dir: Path, project_id: str, source_pdf_path: str | None) -> Path:
    source_path = safe_project_source_pdf_path(data_dir, project_id, source_pdf_path)
    if source_path is None:
        raise ValueError("Project source PDF path is outside the project input directory")
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    return source_path


def safe_public_data_asset_path(data_dir: Path, file_path: str) -> Path | None:
    data_root = Path(data_dir).resolve()
    resolved = (data_root / file_path).resolve()
    try:
        relative = resolved.relative_to(data_root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 4 or parts[0] != "projects":
        return None
    if parts[2] == "sheets":
        return resolved if resolved.suffix.lower() == ".png" else None
    if parts[2] == "exports" and len(parts) >= 5:
        allowed = {".pdf", ".csv", ".xlsx", ".json", ".md", ".html"}
        return resolved if resolved.suffix.lower() in allowed else None
    return None
