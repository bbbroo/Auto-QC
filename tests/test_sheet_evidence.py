from __future__ import annotations

import json
import os
from pathlib import Path

import fitz

from backend.sheet_evidence.autopilot import parse_args, parse_page_ranges, run_autopilot
from backend.sheet_evidence.builder import SheetEvidenceBuilder, _build_fallback_packet, parse_drawing_index
from backend.sheet_evidence.cache import latest_run
from backend.sheet_evidence.classifier import classify_sheet, extract_identity
from backend.sheet_evidence.prompt_context import SOURCE_OF_TRUTH_WARNING, generate_enhanced_prompt_batches, page_prompt_context
from backend.sheet_evidence.recommendation import analyze_benchmark_run, find_latest_benchmark_run
from backend.sheet_evidence.references import extract_engineering_tokens, extract_references


def test_latest_benchmark_run_discovery(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    old = root / "20260101_000000"
    new = root / "20260102_000000"
    old.mkdir(parents=True)
    new.mkdir()
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    assert find_latest_benchmark_run(root) == new
    assert latest_run(root) == new


def test_benchmark_recommendation_prefers_pdfplumber_when_metrics_win(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "aggregate_summary.csv").write_text(
        "tool_name,pdf_name,pdf_path,pages_tested,ok_count,skipped_count,failed_count,reliability,average_heuristic_score,average_text_completeness_score,average_layout_score,average_table_title_revision_score\n"
        "pymupdf,test.pdf,test.pdf,2,2,0,0,1.0,60,60,70,10\n"
        "pdfplumber,test.pdf,test.pdf,2,2,0,0,1.0,80,85,90,55\n",
        encoding="utf-8",
    )
    (run / "metrics.csv").write_text(
        "tool_name,pdf_name,page_number,status,error,text_completeness_score,layout_score,table_title_revision_score\n"
        "pymupdf,test.pdf,1,ok,,60,70,10\n"
        "pdfplumber,test.pdf,1,ok,,85,90,55\n",
        encoding="utf-8",
    )
    (run / "report.md").write_text("No failed extractor rows.", encoding="utf-8")
    recommendation = analyze_benchmark_run(run)
    assert recommendation["primary_text_extractor"] == "pdfplumber"
    assert recommendation["primary_layout_extractor"] == "pdfplumber"
    assert recommendation["primary_table_extractor"] == "pdfplumber"
    assert recommendation["pdf_rendering_tool"] == "pymupdf"
    assert (run / "recommendation.json").exists()


def test_recommendation_fallback_if_only_pymupdf_available(tmp_path: Path) -> None:
    recommendation = analyze_benchmark_run(tmp_path / "missing", allow_fallback=True)
    assert recommendation["primary_text_extractor"] == "pymupdf"
    assert recommendation["fallback_strategy"]
    assert recommendation["confidence"] < 0.6


def test_evidence_packet_schema_and_output_writing(tmp_path: Path) -> None:
    pdf = tmp_path / "package.pdf"
    _write_pdf(
        pdf,
        [
            "DRAWING INDEX\nG001 COVER SHEET\nP005 PROPOSED P&ID\n",
            'DRAWING NO: P005 REV A\nPROPOSED P&ID\nSEE SHEET M008\nDETAIL A/S006\nPT-101 ON 4 INCH LINE\nGENERAL NOTE 1: VERIFY REGULATOR V-101.',
        ],
    )
    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )
    result = builder.build_pdfs([pdf], mode="full")
    packet = result["packets"][1]
    assert result["valid"] is True
    assert packet["pdf_name"] == "package.pdf"
    assert packet["page_number"] == 2
    assert packet["drawing_number"] == "P-005"
    assert packet["discipline"] in {"p_and_id", "p_and_id_symbols"}
    assert packet["page_width"] > 0
    assert packet["page_height"] > 0
    assert packet["quality"]["overall_score"] > 0
    assert "P-005" in {entry["drawing_number"] for entry in result["pdf_results"] and result["packets"]}
    assert Path(result["run_dir"]).joinpath("package", "pages", "page_002.json").exists()
    context = Path(result["run_dir"]).joinpath("package", "prompt_context", "page_002.md").read_text(encoding="utf-8")
    assert SOURCE_OF_TRUTH_WARNING in context


def test_full_evidence_coverage_outputs_are_present(tmp_path: Path) -> None:
    pdf = tmp_path / "coverage.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001", "DRAWING NO: P002", "DRAWING NO: M003"])
    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )
    result = builder.build_pdfs([pdf], mode="full")
    pdf_dir = Path(result["run_dir"]) / "coverage"
    assert result["valid"] is True
    assert result["processed_page_count"] == 3
    assert len(list((pdf_dir / "pages").glob("page_*.json"))) == 3
    assert (pdf_dir / "package_index.json").exists()
    assert (pdf_dir / "package_summary.md").exists()
    assert (pdf_dir / "evidence_build_summary.json").exists()
    assert len(list((pdf_dir / "prompt_context").glob("page_*.md"))) == 3


def test_identity_index_classification_references_and_tokens() -> None:
    text = (
        "DRAWING NO: P005 REV A\n"
        "PROPOSED P&ID\n"
        "SEE SHEET M008. SEE DRAWING P006. DETAIL X/S006. SECTION A/M003. REFER TO C003.\n"
        'PT-101 PSV-201 REG-101 V-101 6 INCH LINE 4\"-NG-1001 ASME B31.8\n'
    )
    identity = extract_identity(text, 5)
    classification = classify_sheet(text=text, drawing_number=identity["drawing_number"], sheet_title=identity["sheet_title"], page_number=5)
    refs = extract_references(text)
    eng = extract_engineering_tokens(text)
    index_entries = parse_drawing_index("P005 PROPOSED P&ID\nM008 MECHANICAL PLAN", 1)
    assert identity["drawing_number"] == "P-005"
    assert classification["discipline"] == "p_and_id"
    assert "P-006" in refs.sheet_references
    assert "DETAIL X/S-006" in refs.detail_references
    assert "SECTION A/M-003" in refs.section_references
    assert "PT-101" in eng.instrument_tags
    assert "V-101" in eng.valve_tags
    assert any(entry.drawing_number == "M-008" for entry in index_entries)


def test_prompt_context_never_claims_authority() -> None:
    packet = {
        "page_number": 10,
        "drawing_number": "P-005",
        "sheet_title": "Proposed P&ID",
        "discipline": "p_and_id",
        "quality": {"overall_score": 70, "warnings": []},
        "references": {"drawing_references": ["P-006"], "cross_references": ["M-008"]},
        "engineering_tokens": {"equipment_tags": ["REG-101"], "instrument_tags": ["PT-101"], "valve_tags": ["V-101"], "pipe_size_tokens": ["4 INCH"]},
        "text": {"important_text": ["SEE SHEET M008"], "notes": []},
        "tables": [],
    }
    context = page_prompt_context(packet)
    assert SOURCE_OF_TRUTH_WARNING in context
    assert "complete or authoritative" in context
    assert "Detected references: P-006, M-008" in context


def test_enhanced_prompt_batch_generation_and_index(tmp_path: Path) -> None:
    packets = [_packet(page) for page in range(1, 6)]
    result = generate_enhanced_prompt_batches(packets, tmp_path / "enhanced_prompts", pages_per_batch=2, max_prompt_chars=12000)
    assert result["batch_count"] == 3
    assert Path(result["batch_index"]).exists()
    assert (tmp_path / "enhanced_prompts" / "batch_index.json").exists()
    for batch in result["batches"]:
        text = Path(batch["path"]).read_text(encoding="utf-8")
        assert SOURCE_OF_TRUTH_WARNING in text
        assert "SCOPED REVIEW MODE: Page batch" in text
        assert "Return ONLY valid JSON" in text
        assert len(text) <= 12000


def test_enhanced_prompt_batch_size_limit_trims_context(tmp_path: Path) -> None:
    packet = _packet(1)
    packet["text"] = {"important_text": ["X" * 2000 for _ in range(20)], "notes": []}
    packet["tables"] = [{"type": "generic", "source": "test", "content": "Y" * 6000}]
    result = generate_enhanced_prompt_batches([packet], tmp_path / "enhanced_prompts", pages_per_batch=1, max_prompt_chars=5000)
    batch = result["batches"][0]
    text = Path(batch["path"]).read_text(encoding="utf-8")
    assert len(text) <= 5001
    assert SOURCE_OF_TRUTH_WARNING in text
    assert batch["char_count"] <= batch["max_prompt_chars"]


def test_enhanced_prompt_falls_back_if_evidence_generation_fails(tmp_path: Path, monkeypatch) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    monkeypatch.setenv("AUTOQC_USE_SHEET_EVIDENCE", "true")
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Prompt fallback")
    db.insert_sheet(
        {
            "id": "sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "P-001",
            "sheet_title": "P&ID",
            "revision": "A",
            "sheet_type": "p&id",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "VISIBLE TEXT THAT MUST NOT ENTER PROMPT",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    payload = AIReviewService(db, settings).generate_manual_prompt(project["id"])
    assert payload["prompt_metadata"]["sheet_evidence_enabled"] is True
    assert payload["prompt_metadata"]["sheet_evidence_included"] is False
    assert payload["prompt_metadata"]["sheet_evidence_warnings"]
    assert "VISIBLE TEXT THAT MUST NOT ENTER PROMPT" not in payload["prompt"]
    assert "Required response schema" in payload["prompt"]


def test_manual_prompt_keeps_sheet_evidence_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    monkeypatch.delenv("AUTOQC_USE_SHEET_EVIDENCE", raising=False)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Default prompt")
    db.insert_sheet(
        {
            "id": "sheet-default-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "G-002",
            "sheet_title": "GENERAL NOTES",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "legacy app extraction should not enter the prompt by default",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    service = AIReviewService(db, settings)
    payload = service.generate_manual_prompt(project["id"])
    assert payload["prompt_metadata"]["sheet_evidence_enabled"] is False
    assert payload["prompt_metadata"]["sheet_evidence_included"] is False
    assert "# AutoQC Enhanced Manual Review Prompt Batch" not in payload["prompt"]
    assert "legacy app extraction should not enter the prompt by default" not in payload["prompt"]

    first_pass_response = json.dumps(
        {
            "schema_version": "autoqc-ai-updates-v1",
            "reviewed_pages": [{"page_number": 1, "review_status": "complete", "issue_count": 1}],
            "updates": [
                {
                    "issue": "Typo in note",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "page_number": 1,
                    "target_text": "GENERAL NOTES",
                    "required_update": "Correct the visible typo.",
                    "rationale": "Visible drafting issue.",
                    "confidence": 0.9,
                }
            ],
        }
    )
    preview = service.preview_manual_response(project["id"], first_pass_response, prompt_id=payload["prompt_id"])
    assert preview["review_modality"] == "manual_pdf_attached_external"
    assert preview["missed_issue_audit"]["available"] is True
    assert preview["missed_issue_audit"]["prior_import_batch_id"] == preview["batch_id"]
    assert preview["missed_issue_audit"]["next_source_type"] == "missed_issue_audit"
    assert "missed-issue audit reviewer" in preview["missed_issue_audit_prompt"]
    assert "only additional issues" in preview["missed_issue_audit_prompt"]
    assert "Prior AI JSON to avoid duplicating" in preview["missed_issue_audit_prompt"]
    assert "GENERAL NOTES" in preview["missed_issue_audit_prompt"]

    second_pass_response = json.dumps(
        {
            "schema_version": "autoqc-ai-updates-v1",
            "reviewed_pages": [{"page_number": 1, "review_status": "complete", "issue_count": 1}],
            "updates": [
                {
                    "issue": "Second pass issue",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "page_number": 1,
                    "target_text": "GENERAL NOTES",
                    "required_update": "Clarify a separate visible note.",
                    "rationale": "Found during missed-issue audit.",
                    "confidence": 0.8,
                }
            ],
        }
    )
    audit_preview = service.preview_manual_response(
        project["id"],
        second_pass_response,
        source_type="missed_issue_audit",
        audit_of_batch_id=preview["batch_id"],
        audit_round=1,
    )
    assert audit_preview["source_type"] == "missed_issue_audit"
    assert audit_preview["audit_of_batch_id"] == preview["batch_id"]
    assert audit_preview["audit_round"] == 1
    assert audit_preview["missed_issue_audit"]["available"] is False

    imported = service.import_preview(project["id"], audit_preview["batch_id"])
    audit_batch = db.get_ai_import_batch(imported["batch"]["id"], project_id=project["id"])
    assert audit_batch["metadata"]["review_modality"] == "manual_pdf_attached_external"
    assert audit_batch["metadata"]["audit_of_batch_id"] == preview["batch_id"]
    assert audit_batch["metadata"]["audit_round"] == 1
    assert audit_batch["metadata"]["audit_yield_count"] == 1


def test_sheet_evidence_prompt_context_warns_when_app_cap_truncates_scope(tmp_path: Path, monkeypatch) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    monkeypatch.setenv("AUTOQC_USE_SHEET_EVIDENCE", "true")
    monkeypatch.setenv("AUTOQC_SHEET_EVIDENCE_PROMPT_MAX_PAGES", "2")
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Capped evidence")
    input_dir = settings.data_dir / "projects" / project["id"] / "input"
    input_dir.mkdir(parents=True)
    source_pdf = input_dir / "capped.pdf"
    _write_pdf(source_pdf, ["DRAWING NO: G001", "DRAWING NO: G002", "DRAWING NO: G003"])
    db.update_project(project["id"], source_pdf_path=str(source_pdf))
    for page in [1, 2, 3]:
        db.insert_sheet(
            {
                "id": f"cap-sheet-{page}",
                "project_id": project["id"],
                "page_number": page,
                "drawing_number": f"G-{page:03d}",
                "sheet_title": f"Sheet {page}",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"SHEET {page}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )

    context = AIReviewService(db, settings).build_sheet_evidence_prompt_context(project["id"], {"scope_pages": [1, 2, 3]})

    assert context["enabled"] is True
    assert context["included"] is True
    assert context["packet_count"] == 2
    assert context["scope_page_count"] == 3
    assert context["truncated_page_count"] == 1
    assert any("capped at 2 pages" in warning for warning in context["warnings"])


def test_autopilot_argument_parsing_and_no_benchmark_required_run(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001 REV A\nGENERAL NOTES\nSEE SHEET P005"])
    args = parse_args(["--pdf", str(pdf), "--no-benchmark-required", "--max-pages", "1", "--output", str(tmp_path / "out")])
    summary = run_autopilot(args)
    assert summary["processed_page_count"] == 1
    assert summary["valid"] is True
    assert Path(summary["enhanced_prompt_preview"]).exists()


def test_autopilot_cli_flags_for_full_pages_and_batches(tmp_path: Path) -> None:
    args = parse_args([
        "--pdf-dir",
        str(tmp_path),
        "--full",
        "--pages",
        "1,3-4",
        "--generate-enhanced-prompts",
        "--pages-per-batch",
        "2",
        "--max-prompt-chars",
        "9000",
    ])
    assert args.full is True
    assert args.generate_enhanced_prompts is True
    assert args.pages_per_batch == 2
    assert args.max_prompt_chars == 9000
    assert parse_page_ranges(args.pages) == [1, 3, 4]


def test_autopilot_generates_enhanced_prompt_batches(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001 REV A", "DRAWING NO: P002 REV A", "DRAWING NO: M003 REV A"])
    args = parse_args([
        "--pdf",
        str(pdf),
        "--no-benchmark-required",
        "--full",
        "--generate-enhanced-prompts",
        "--pages-per-batch",
        "2",
        "--output",
        str(tmp_path / "out"),
    ])
    summary = run_autopilot(args)
    batches = summary["enhanced_prompt_batches"]
    assert summary["valid"] is True
    assert batches["batch_count"] == 2
    assert Path(batches["batch_index"]).exists()
    assert all(Path(batch["path"]).exists() for batch in batches["batches"])
    first_prompt = Path(batches["batches"][0]["path"]).read_text(encoding="utf-8")
    assert "autoqc-ai-updates-v1" in first_prompt
    assert "reviewed_pages must include every page listed in this batch" in first_prompt
    assert "required_update" in first_prompt
    assert "rationale" in first_prompt
    assert "numeric confidence" in first_prompt


def _packet(page: int) -> dict[str, object]:
    return {
        "pdf_name": "package.pdf",
        "page_number": page,
        "drawing_number": f"P-{page:03d}",
        "sheet_title": f"Sheet {page}",
        "discipline": "p_and_id",
        "quality": {"overall_score": 70, "warnings": []},
        "references": {"drawing_references": [], "cross_references": []},
        "engineering_tokens": {"equipment_tags": [], "instrument_tags": [], "valve_tags": [], "pipe_size_tokens": []},
        "text": {"important_text": ["VERIFY VISIBLE PDF CONTENT"], "notes": []},
        "tables": [],
    }


def _write_pdf(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    for page_text in pages:
        page = doc.new_page(width=612, height=792)
        y = 72
        for line in page_text.splitlines():
            page.insert_text((72, y), line, fontsize=12)
            y += 20
    doc.save(path)
    doc.close()


def test_page_failure_fallback(tmp_path: Path, monkeypatch) -> None:
    """Verify that a page failure creates a fallback packet and does not abort the whole PDF."""
    pdf = tmp_path / "faulty.pdf"
    _write_pdf(pdf, ["PAGE ONE DRAWING NO: G001", "PAGE TWO DRAWING NO: P002", "PAGE THREE DRAWING NO: M003"])

    # Monkeypatch build_page_packet to raise on page 2
    original_build = SheetEvidenceBuilder.build_page_packet

    def _failing_build(self, pdf_path, page_number, page_count, *, debug_dir, image_dir):
        if page_number == 2:
            raise RuntimeError("Simulated extraction failure on page 2")
        return original_build(self, pdf_path, page_number, page_count, debug_dir=debug_dir, image_dir=image_dir)

    monkeypatch.setattr(SheetEvidenceBuilder, "build_page_packet", _failing_build)

    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )
    result = builder.build_pdfs([pdf], mode="full")
    packets = result["packets"]
    pdf_dir = Path(result["run_dir"]) / "faulty"

    # Should have 3 packets (2 good, 1 fallback)
    assert len(packets) == 3
    assert result["processed_page_count"] == 3

    # Page 1 should be normal
    assert packets[0]["page_number"] == 1
    assert not packets[0].get("extraction_failed", False)

    # Page 2 should be fallback
    fallback = packets[1]
    assert fallback["page_number"] == 2
    assert fallback.get("extraction_failed") is True
    assert "Simulated extraction failure on page 2" in fallback.get("extraction_error", "")
    assert fallback["drawing_number"] == "UNKNOWN"
    assert fallback["page_width"] > 0  # PyMuPDF still provides dimensions

    # Page 3 should be normal
    assert packets[2]["page_number"] == 3
    assert not packets[2].get("extraction_failed", False)

    # All page JSON files should exist
    assert (pdf_dir / "pages" / "page_001.json").exists()
    assert (pdf_dir / "pages" / "page_002.json").exists()
    assert (pdf_dir / "pages" / "page_003.json").exists()

    # Fallback JSON should have extraction_failed
    fallback_json = json.loads((pdf_dir / "pages" / "page_002.json").read_text(encoding="utf-8"))
    assert fallback_json.get("extraction_failed") is True

    # Fallback prompt context should have source-of-truth warning
    fallback_context = (pdf_dir / "prompt_context" / "page_002.md").read_text(encoding="utf-8")
    assert SOURCE_OF_TRUTH_WARNING in fallback_context

    # failed_pages should be reported
    assert result.get("failed_pages") == [2]


def test_resumable_page_reuse(tmp_path: Path) -> None:
    """Verify that re-running without --force reuses existing page JSONs and regenerates missing prompt context."""
    pdf = tmp_path / "resume.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001", "DRAWING NO: P002", "DRAWING NO: M003"])

    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )

    # First run
    result1 = builder.build_pdfs([pdf], mode="full", run_id="test_resume_run")
    pdf_dir = Path(result1["run_dir"]) / "resume"
    assert (pdf_dir / "pages" / "page_001.json").exists()

    # Second run with same run_id, no --force - should reuse existing
    result2 = builder.build_pdfs([pdf], mode="full", run_id="test_resume_run")
    assert result2["processed_page_count"] == 3
    assert result2["valid"] is True

    # Remove prompt context for page 2, re-run to test regeneration
    (pdf_dir / "prompt_context" / "page_002.md").unlink()
    assert not (pdf_dir / "prompt_context" / "page_002.md").exists()

    result3 = builder.build_pdfs([pdf], mode="full", run_id="test_resume_run")
    # Prompt context should be regenerated
    assert (pdf_dir / "prompt_context" / "page_002.md").exists()
    context = (pdf_dir / "prompt_context" / "page_002.md").read_text(encoding="utf-8")
    assert SOURCE_OF_TRUTH_WARNING in context

    # Force should re-process
    (pdf_dir / "pages" / "page_003.json").unlink()
    builder.build_pdfs([pdf], mode="full", run_id="test_resume_run", force=True)
    assert (pdf_dir / "pages" / "page_003.json").exists()


def test_build_fallback_packet_structure(tmp_path: Path) -> None:
    """Verify _build_fallback_packet returns correct structure."""
    pdf = tmp_path / "fallback_test.pdf"
    _write_pdf(pdf, ["TEST CONTENT"])
    packet = _build_fallback_packet(pdf, 1, 1, "test error")
    assert packet["extraction_failed"] is True
    assert packet["extraction_error"] == "test error"
    assert packet["page_number"] == 1
    assert packet["page_count"] == 1
    assert packet["pdf_name"] == "fallback_test.pdf"
    assert packet["page_width"] > 0
    assert packet["page_height"] > 0
    assert packet["text"]["full_text"] == ""
    assert packet["references"]["drawing_references"] == []
    assert packet["engineering_tokens"]["equipment_tags"] == []


def test_validate_pdf_output_detects_missing_files(tmp_path: Path) -> None:
    """Verify validate_pdf_output correctly flags missing outputs."""
    from backend.sheet_evidence.builder import validate_pdf_output

    pdf = tmp_path / "test.pdf"
    _write_pdf(pdf, ["PAGE ONE"])
    pdf_dir = tmp_path / "output"
    pdf_dir.mkdir()
    (pdf_dir / "pages").mkdir()
    (pdf_dir / "prompt_context").mkdir()

    selected_pages = [1]
    packets = [_build_fallback_packet(pdf, 1, 1, "test")]

    # Missing package_summary.md
    validation = validate_pdf_output(pdf, 1, selected_pages, packets, pdf_dir)
    checks = {v["name"]: v["passed"] for v in validation}
    assert not checks["package summary exists"]
    assert not checks["package index exists"]
    assert not checks["evidence build summary exists"]

    # Add required files
    (pdf_dir / "package_summary.md").write_text("# Summary")
    (pdf_dir / "package_index.json").write_text("{}")
    (pdf_dir / "evidence_build_summary.json").write_text("{}")

    validation = validate_pdf_output(pdf, 1, selected_pages, packets, pdf_dir)
    checks = {v["name"]: v["passed"] for v in validation}
    assert checks["package summary exists"]
    assert checks["package index exists"]
    assert checks["evidence build summary exists"]


def test_enhanced_prompt_batch_source_of_truth_warning(tmp_path: Path) -> None:
    """Verify every enhanced prompt batch contains the source-of-truth warning."""
    packets = [_packet(page) for page in range(1, 4)]
    result = generate_enhanced_prompt_batches(packets, tmp_path / "enhanced_prompts", pages_per_batch=1, max_prompt_chars=12000)
    for batch in result["batches"]:
        assert batch["source_of_truth_warning_present"] is True
        text = Path(batch["path"]).read_text(encoding="utf-8")
        assert SOURCE_OF_TRUTH_WARNING in text
        # Verify manual review instructions are included
        assert "SCOPED REVIEW MODE: Page batch" in text
        assert "Return ONLY valid JSON" in text


def test_full_evidence_coverage_page_not_selected_if_limited(tmp_path: Path) -> None:
    """Verify that full mode with max_pages limits correctly reports validation."""
    pdf = tmp_path / "limited.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001", "DRAWING NO: P002", "DRAWING NO: M003", "DRAWING NO: E004", "DRAWING NO: S005"])
    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )
    result = builder.build_pdfs([pdf], mode="full", max_pages=3)
    pdf_dir = Path(result["run_dir"]) / "limited"
    assert result["processed_page_count"] == 3
    assert len(list((pdf_dir / "pages").glob("page_*.json"))) == 3
    assert result["valid"] is True


def test_resumable_force_flag_reprocesses(tmp_path: Path) -> None:
    """Verify --force re-processes pages even if they already exist."""
    pdf = tmp_path / "force_reprocess.pdf"
    _write_pdf(pdf, ["DRAWING NO: G001", "DRAWING NO: P002"])

    builder = SheetEvidenceBuilder(
        recommendation={"primary_text_extractor": "pymupdf", "primary_layout_extractor": "pymupdf", "primary_table_extractor": "pymupdf"},
        output_root=tmp_path / "evidence",
    )

    # First run
    r1 = builder.build_pdfs([pdf], mode="full", run_id="force_test")
    pdf_dir = Path(r1["run_dir"]) / "force_reprocess"
    page1_path = pdf_dir / "pages" / "page_001.json"

    # Tamper with the JSON to make it identifiable
    original = json.loads(page1_path.read_text(encoding="utf-8"))
    original["_tampered"] = True
    page1_path.write_text(json.dumps(original), encoding="utf-8")

    # Re-run without force - should reuse the tampered file
    r2 = builder.build_pdfs([pdf], mode="full", run_id="force_test")
    reused = json.loads(page1_path.read_text(encoding="utf-8"))
    assert reused.get("_tampered") is True

    # Re-run with force - should re-process and overwrite
    r3 = builder.build_pdfs([pdf], mode="full", run_id="force_test", force=True)
    fresh = json.loads(page1_path.read_text(encoding="utf-8"))
    assert fresh.get("_tampered") is None
