from __future__ import annotations

from backend.app.config import settings
from backend.app.database import Database
from backend.app.sample_pdf import ensure_default_sample_pdf
from backend.app.services.exports import ExportService
from backend.app.services.pdf_processor import PDFProcessor


if __name__ == "__main__":
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    sample_pdf = ensure_default_sample_pdf()
    project = db.create_project("Synthetic Regulator Station Sample", str(sample_pdf))
    result = PDFProcessor(db, settings).process_project(project["id"])
    export = ExportService(db, settings.data_dir).export_project(project["id"])
    print(f"Project: {project['id']}")
    print(f"Sheets: {len(result['sheets'])}")
    print(f"Findings: {len(result['findings'])}")
    print(f"Export directory: {export['export']['export_dir']}")

