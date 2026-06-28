from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import settings
from backend.app.database import Database
from backend.app.services.ai_review import AIReviewService
from backend.app.services.exports import ExportService
from backend.app.services.pdf_processor import PDFProcessor


def create_large_wide_pdf(path: Path, pages: int = 24) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    doc = fitz.open()
    for page_number in range(1, pages + 1):
        page = doc.new_page(width=1728, height=1116)
        y = 72
        lines = [
            f"DRAWING NO: WIDE-{page_number:03d} REV: A",
            f"WIDE ENGINEERING PACKAGE PAGE {page_number}",
            f"LONG TARGET TEXT PAGE {page_number} REGULATOR STATION COORDINATION NOTE WITH DRAWING REFERENCE PID-{page_number:03d} AND VERY LONG TAG TRAIN V-{page_number:03d}-A/B/C",
            f"PAGE LEVEL REVIEW ANCHOR {page_number}",
        ]
        for line in lines:
            page.insert_text((72, y), line, fontsize=14)
            y += 28
    doc.save(path)
    doc.close()


def main() -> None:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = settings.data_dir / "stress" / "large_wide_autoqc_fixture.pdf"
    create_large_wide_pdf(source_pdf)

    processor = PDFProcessor(db, settings)
    project = db.create_project("Large Wide Stress Fixture")
    processor.save_uploaded_pdf(project["id"], source_pdf.name, source_pdf.read_bytes())
    processed = processor.process_project(project["id"])

    updates = []
    for sheet in processed["sheets"]:
        page_number = sheet["page_number"]
        updates.append(
            {
                "page_number": page_number,
                "issue": f"Long coordination note on page {page_number}",
                "target_text": f"LONG TARGET TEXT PAGE {page_number} REGULATOR STATION COORDINATION NOTE WITH DRAWING REFERENCE PID-{page_number:03d}",
                "required_update": f"Confirm coordination for PID-{page_number:03d} and update the long note if the reference is stale.",
                "rationale": "Synthetic stress update for wide engineering sheets.",
                "category": "drawing coordination",
                "severity": "Minor",
                "confidence": 0.8,
            }
        )
    ai_service = AIReviewService(db, settings)
    imported = ai_service.import_manual_response(project["id"], json.dumps({"updates": updates}))
    for finding in db.list_findings(project["id"], sources=["ai"]):
        db.update_finding(finding["id"], {"status": "accepted"})
    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"])

    print("AutoQC large/wide stress fixture complete")
    print(f"Project: {project['id']}")
    print(f"Sheets: {len(processed['sheets'])}")
    print(f"Findings imported: {imported['ai_updates_imported']}")
    print(f"Findings exported: {export['findings_exported']}")
    print(f"Validation: {export['validation']['status']}")
    print(f"Marked PDF: {export['export']['marked_pdf_path']}")


if __name__ == "__main__":
    main()
