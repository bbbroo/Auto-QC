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
from scripts.validation_reports import write_validation_report


def create_smoke_pdf(path: Path) -> None:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    pages = [
        [
            "DRAWING NO: G-001 REV: A",
            "REGULATOR STATION GENERAL NOTES",
            "INSTALL 12 Inlet Valve UPSTREAM OF FILTER FLT-101.",
            "MAOP 60 PSIG. OPP SETPOINT SHALL BE CONFIRMED BY ENGINEER.",
        ],
        [
            "DRAWING NO: N-002 REV: A",
            "GENERAL NOTES CONTINTUED",
            "PT-101 SENSING LINE TO DOWNSTREAM HEADER.",
        ],
    ]
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=12)
            y += 22
    doc.save(path)
    doc.close()


def main() -> None:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()

    smoke_pdf = settings.data_dir / "smoke" / "autoqc_ai_workflow_smoke.pdf"
    create_smoke_pdf(smoke_pdf)

    processor = PDFProcessor(db, settings)
    project = db.create_project("Smoke AI Workflow", project_type="validation")
    processor.save_uploaded_pdf(project["id"], smoke_pdf.name, smoke_pdf.read_bytes())
    processed = processor.process_project(project["id"])
    assert len(processed["sheets"]) == 2
    assert processed["findings"] == []

    ai_service = AIReviewService(db, settings)
    prompt = ai_service.generate_manual_prompt(project["id"])
    assert prompt["prompt_version"]
    assert "actual drawing package PDF must be attached/uploaded" in prompt["prompt"]

    sample_ai_response = json.dumps(
        {
            "reviewed_pages": [
                {"page_number": 1, "review_status": "complete", "issue_count": 1},
                {"page_number": 2, "review_status": "complete", "issue_count": 1},
            ],
            "updates": [
                {
                    "pageNumber": "Page 1",
                    "issue": "Valve size notation may need inch mark",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "target_text": '12" Inlet Valve',
                    "required_update": 'Confirm and revise valve text to 12" Inlet Valve if nominal size notation is intended.',
                    "rationale": "The page text reads like a valve size callout but omits inch-mark notation.",
                    "confidence": 0.82,
                },
                {
                    "pdf_page": "PDF page 2",
                    "issue": "Misspelling in notes heading",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "target_text": "CONTINTUED",
                    "required_update": 'Revise "CONTINTUED" to "CONTINUED".',
                    "rationale": "Visible spelling issue in the notes heading.",
                    "confidence": 0.96,
                },
            ]
        }
    )

    preview = ai_service.preview_manual_response(
        project["id"],
        sample_ai_response,
        source_type="manual_chat_prompt",
        prompt_version=prompt["prompt_version"],
        prompt_id=prompt["prompt_id"],
    )
    assert preview["valid_recoverable_updates"] == 2
    imported = ai_service.import_preview(project["id"], preview["batch_id"])
    assert imported["ai_updates_imported"] == 2

    findings = db.list_findings(project["id"], sources=["ai"])
    first = findings[0]
    db.update_finding(
        first["id"],
        {
            "status": "accepted",
            "comment_text": "Reviewer smoke edit: correct the cited drawing text if confirmed.",
            "reviewer_note": "Smoke workflow edited this finding before export.",
        },
    )

    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted", "needs_review"])
    export_record = export["export"]
    report = write_validation_report(
        data_dir=settings.data_dir,
        report_name="autoqc_smoke_ai_workflow",
        status="passed",
        summary="Synthetic PDF upload, extraction, manual AI preview/import, reviewer edit, and draft export passed.",
        checks=[
            {"name": "upload_and_extraction", "passed": len(processed["sheets"]) == 2, "detail": f"{len(processed['sheets'])} sheets extracted"},
            {"name": "no_deterministic_findings_created", "passed": processed["findings"] == [], "detail": "Upload/extraction produced no user-facing rule findings"},
            {"name": "manual_prompt_generated", "passed": bool(prompt["prompt_version"]), "detail": prompt["prompt_version"]},
            {"name": "preview_valid_updates", "passed": preview["valid_recoverable_updates"] == 2, "detail": f"batch {preview['batch_id']}"},
            {"name": "coverage_complete", "passed": preview["review_coverage_status"] == "complete", "detail": f"{preview['review_coverage_percent']}%"},
            {"name": "import_created_findings", "passed": imported["ai_updates_imported"] == 2, "detail": "2 AI updates imported"},
            {"name": "draft_export_created", "passed": export["findings_exported"] == 2, "detail": export["validation"]["status"]},
        ],
        metrics={
            "sheets_processed": len(processed["sheets"]),
            "valid_preview_updates": preview["valid_recoverable_updates"],
            "findings_imported": imported["ai_updates_imported"],
            "findings_exported": export["findings_exported"],
            "export_validation": export["validation"]["status"],
        },
        artifacts={
            "marked_pdf": export_record["marked_pdf_path"],
            "qa_report": export_record["qa_report_path"],
            "summary": export_record.get("summary_path"),
        },
        limitations=[
            "Synthetic smoke fixture checks workflow mechanics, not engineering correctness.",
            "AI response is representative fixture JSON, not a live external AI review.",
        ],
    )
    print("AutoQC AI workflow smoke succeeded")
    print(f"Project: {project['id']}")
    print(f"Sheets processed: {len(processed['sheets'])}")
    print(f"Preview batch: {preview['batch_id']}")
    print(f"AI updates imported: {imported['ai_updates_imported']}")
    print(f"Findings exported: {export['findings_exported']}")
    print(f"Marked PDF: {export_record['marked_pdf_path']}")
    print(f"QA report: {export_record['qa_report_path']}")
    print(f"Validation report: {report['markdown']}")


if __name__ == "__main__":
    main()
