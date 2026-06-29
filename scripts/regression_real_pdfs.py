from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import settings
from backend.app.database import Database
from backend.app.main import app
from backend.app.services.ai_review import AIReviewService
from backend.app.services.exports import ExportService
from backend.app.services.pdf_processor import PDFProcessor
from scripts.validation_reports import write_validation_report


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def main() -> int:
    pdfs = sorted(EXAMPLES_DIR.glob("*.pdf"))
    if not pdfs:
        print("No example PDFs found under examples/. Skipping real-PDF regression.")
        settings.ensure_dirs()
        report = write_validation_report(
            data_dir=settings.data_dir,
            report_name="autoqc_real_pdf_regression",
            status="skipped",
            summary="No example PDFs were found under examples/.",
            checks=[{"name": "example_pdfs_available", "passed": False, "detail": "examples/*.pdf not found"}],
            limitations=["Real-PDF regression requires at least one non-private PDF under examples/."],
        )
        print(f"Validation report: {report['markdown']}")
        return 0

    limit = max(1, int(os.environ.get("AUTOQC_REAL_PDF_LIMIT", "1")))
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    processor = PDFProcessor(db, settings)
    ai_service = AIReviewService(db, settings)
    export_service = ExportService(db, settings.data_dir)
    client = TestClient(app)
    run_results: list[dict[str, object]] = []

    for source_pdf in pdfs[:limit]:
        start = time.perf_counter()
        project = db.create_project(f"Real PDF Regression - {source_pdf.stem[:60]}", project_type="validation")
        processor.save_uploaded_pdf(project["id"], source_pdf.name, source_pdf.read_bytes())
        processed = processor.process_project(project["id"])
        sheets = processed["sheets"]
        assert sheets, f"{source_pdf.name}: no pages extracted"
        assert all(sheet.get("image_path") and Path(sheet["image_path"]).exists() for sheet in sheets), f"{source_pdf.name}: missing page images"
        assert client.get(f"/projects/{project['id']}/source-pdf").status_code == 200

        prompt = ai_service.generate_manual_prompt(project["id"])
        assert prompt["prompt_metadata"]["sheet_count"] == len(sheets)
        assert prompt["prompt_metadata"]["review_scope"] == "package"

        all_pages = [int(sheet["page_number"]) for sheet in sheets]
        clean_response = {"reviewed_pages": reviewed_pages(all_pages), "updates": []}
        clean_preview = ai_service.preview_manual_response(project["id"], json.dumps(clean_response), prompt_id=prompt["prompt_id"])
        assert clean_preview["review_coverage_status"] == "complete"
        ai_service.import_preview(project["id"], clean_preview["batch_id"])

        if len(all_pages) > 1:
            partial = {"reviewed_pages": reviewed_pages(all_pages[:-1]), "updates": []}
            partial_preview = ai_service.preview_manual_response(project["id"], json.dumps(partial), prompt_id=prompt["prompt_id"])
            assert partial_preview["review_coverage_status"] != "complete"
            try:
                ai_service.import_preview(project["id"], partial_preview["batch_id"])
            except ValueError:
                pass
            else:
                raise AssertionError(f"{source_pdf.name}: partial coverage import was not blocked")

        target_page = first_text_sheet(sheets)
        target_text = first_target_text(target_page)
        update_response = {
            "reviewed_pages": reviewed_pages(all_pages, issue_page=int(target_page["page_number"])),
            "updates": [
                {
                    "page_number": int(target_page["page_number"]),
                    "issue": "Representative imported update for regression mechanics",
                    "target_text": target_text,
                    "required_update": "Reviewer regression placeholder update.",
                    "rationale": "Mechanical regression fixture; not an engineering conclusion.",
                    "category": "human review needed",
                    "severity": "Note",
                    "confidence": 0.8,
                }
            ],
        }
        imported = ai_service.import_manual_response(project["id"], json.dumps(update_response), prompt_id=prompt["prompt_id"])
        assert imported["ai_updates_imported"] == 1
        ai_service.recalculate_finding_locations(project["id"])
        for finding in db.list_findings(project["id"], sources=["ai"]):
            db.update_finding(finding["id"], {"status": "accepted"})

        export = export_service.export_project(project["id"], statuses=["accepted"], export_mode="draft")
        marked_pdf = Path(export["export"]["marked_pdf_path"])
        assert marked_pdf.exists()
        with fitz.open(marked_pdf) as marked_doc:
            assert marked_doc.page_count == len(sheets)
        try:
            export_service.export_project(project["id"], statuses=["accepted"], export_mode="final", final_export_confirmed=False)
        except ValueError as exc:
            assert "signoff" in str(exc).lower() or "confirmation" in str(exc).lower()
        else:
            raise AssertionError(f"{source_pdf.name}: final export without signoff was not blocked")
        final_export = export_service.export_project(
            project["id"],
            statuses=["accepted"],
            export_mode="final",
            final_export_confirmed=True,
            reviewer_name="Regression harness",
            acknowledge_validation_warnings=True,
        )
        final_pdf = Path(final_export["export"]["marked_pdf_path"])
        with fitz.open(final_pdf) as final_doc:
            assert final_doc.page_count == len(sheets)
        elapsed = time.perf_counter() - start
        run_results.append(
            {
                "pdf": source_pdf.name,
                "pages": len(sheets),
                "draft_validation": export["validation"]["status"],
                "final_validation": final_export["validation"]["status"],
                "elapsed_seconds": round(elapsed, 2),
                "marked_pdf": export["export"]["marked_pdf_path"],
                "final_pdf": final_export["export"]["marked_pdf_path"],
            }
        )
        print(
            f"PASS {source_pdf.name}: {len(sheets)} pages, "
            f"draft validation {export['validation']['status']}, "
            f"final validation {final_export['validation']['status']}, "
            f"{elapsed:.1f}s"
        )

    report = write_validation_report(
        data_dir=settings.data_dir,
        report_name="autoqc_real_pdf_regression",
        status="passed",
        summary=f"Mechanics-only regression passed for {len(run_results)} example PDF(s).",
        checks=[
            {
                "name": f"real_pdf_workflow_{index}",
                "passed": True,
                "detail": f"{item['pdf']}: {item['pages']} pages, draft {item['draft_validation']}, final {item['final_validation']}",
            }
            for index, item in enumerate(run_results, start=1)
        ],
        metrics={
            "pdfs_tested": len(run_results),
            "total_pages": sum(int(item["pages"]) for item in run_results),
            "max_elapsed_seconds": max(float(item["elapsed_seconds"]) for item in run_results),
        },
        artifacts={
            "pdfs": [item["pdf"] for item in run_results],
            "marked_pdfs": [item["marked_pdf"] for item in run_results],
            "final_pdfs": [item["final_pdf"] for item in run_results],
        },
        limitations=[
            "Real-PDF regression checks workflow mechanics only.",
            "Representative AI updates are synthetic placeholders and not engineering conclusions.",
        ],
    )
    print(f"Validation report: {report['markdown']}")
    return 0


def reviewed_pages(pages: list[int], issue_page: int | None = None) -> list[dict[str, int | str]]:
    return [
        {
            "page_number": page,
            "review_status": "complete",
            "issue_count": 1 if issue_page == page else 0,
        }
        for page in pages
    ]


def first_text_sheet(sheets: list[dict]) -> dict:
    for sheet in sheets:
        if str(sheet.get("text_content") or "").strip():
            return sheet
    return sheets[0]


def first_target_text(sheet: dict) -> str:
    for line in str(sheet.get("text_content") or "").splitlines():
        clean = " ".join(line.split())
        if len(clean) >= 4:
            return clean[:120]
    return str(sheet.get("drawing_number") or f"Page {sheet.get('page_number')}")


if __name__ == "__main__":
    raise SystemExit(main())
