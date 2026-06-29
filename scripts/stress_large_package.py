from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import settings
from backend.app.database import Database
from backend.app.services.ai_review import AIReviewService
from backend.app.services.exports import ExportService
from backend.app.services.pdf_processor import PDFProcessor
from scripts.validation_reports import write_validation_report


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
    start = time.perf_counter()
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
    reviewed_pages = [
        {"page_number": sheet["page_number"], "review_status": "complete", "issue_count": 1}
        for sheet in processed["sheets"]
    ]
    imported = ai_service.import_manual_response(project["id"], json.dumps({"reviewed_pages": reviewed_pages, "updates": updates}))
    for finding in db.list_findings(project["id"], sources=["ai"]):
        db.update_finding(finding["id"], {"status": "accepted"})
    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"])
    elapsed = time.perf_counter() - start
    report = write_validation_report(
        data_dir=settings.data_dir,
        report_name="autoqc_large_package_stress",
        status="passed",
        summary="Large/wide synthetic package upload, import, placement, and draft export completed.",
        checks=[
            {"name": "wide_pdf_extracted", "passed": len(processed["sheets"]) == 24, "detail": f"{len(processed['sheets'])} sheets"},
            {"name": "reviewed_pages_complete", "passed": imported["batch"]["metadata"]["review_coverage"]["review_coverage_status"] == "complete", "detail": "All synthetic pages confirmed"},
            {"name": "ai_updates_imported", "passed": imported["ai_updates_imported"] == len(processed["sheets"]), "detail": f"{imported['ai_updates_imported']} imported"},
            {"name": "draft_export_created", "passed": export["findings_exported"] == len(processed["sheets"]), "detail": export["validation"]["status"]},
            {"name": "marked_pdf_reopened", "passed": export["validation"]["marked_page_count"] == len(processed["sheets"]), "detail": f"{export['validation']['marked_page_count']} marked pages"},
        ],
        metrics={
            "sheets": len(processed["sheets"]),
            "findings_imported": imported["ai_updates_imported"],
            "findings_exported": export["findings_exported"],
            "validation": export["validation"]["status"],
            "elapsed_seconds": round(elapsed, 2),
        },
        artifacts={
            "source_pdf": source_pdf,
            "marked_pdf": export["export"]["marked_pdf_path"],
            "summary": export["export"].get("summary_path"),
        },
        limitations=[
            "Synthetic stress fixture verifies large-package mechanics and timing only.",
            "It does not assert natural gas engineering correctness.",
        ],
    )

    print("AutoQC large/wide stress fixture complete")
    print(f"Project: {project['id']}")
    print(f"Sheets: {len(processed['sheets'])}")
    print(f"Findings imported: {imported['ai_updates_imported']}")
    print(f"Findings exported: {export['findings_exported']}")
    print(f"Validation: {export['validation']['status']}")
    print(f"Marked PDF: {export['export']['marked_pdf_path']}")
    print(f"Elapsed seconds: {elapsed:.1f}")
    print(f"Validation report: {report['markdown']}")


if __name__ == "__main__":
    main()
