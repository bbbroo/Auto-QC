from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import settings
from backend.app.database import Database
from backend.app.sample_pdf import ensure_default_sample_pdf
from backend.app.services.pdf_processor import PDFProcessor


if __name__ == "__main__":
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    sample_pdf = ensure_default_sample_pdf()
    project = db.create_project("Synthetic Regulator Station Sample")
    processor = PDFProcessor(db, settings)
    processor.copy_sample_pdf(project["id"], sample_pdf)
    result = processor.process_project(project["id"])
    print(f"Project: {project['id']}")
    print(f"Sheets: {len(result['sheets'])}")
    print(f"Findings: {len(result['findings'])}")
    print("Export: skipped because the active workflow has no AI findings until Chat Prompt JSON is imported.")
