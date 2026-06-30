from __future__ import annotations

import csv
import os
import json
import zipfile
from pathlib import Path

import fitz

ALLIANT_REPRO_PDF = Path.home() / "Downloads" / "2Pages from Pages from 20250508_Alliant Sheboygan Skid Upgrade_IFC.pdf"


def _configure_tmp_env(tmp_path: Path) -> None:
    os.environ["AUTOQC_DATA_DIR"] = str(tmp_path / "data")
    os.environ["AUTOQC_DB_PATH"] = str(tmp_path / "data" / "autoqc.sqlite")


def _finding_record(
    project_id: str,
    stable_id: str,
    *,
    source: str = "ai",
    status: str = "accepted",
    page_number: int = 1,
    sheet_id: str | None = None,
    title: str | None = None,
    target_text: str = "REGULATOR STATION",
) -> dict:
    return {
        "id": f"{stable_id}-id",
        "project_id": project_id,
        "sheet_id": sheet_id,
        "stable_id": stable_id,
        "title": title or f"{source.upper()} finding {stable_id}",
        "category": "drafting quality",
        "severity": "Minor",
        "confidence": 0.8,
        "page_number": page_number,
        "location": None,
        "involved_entities": [],
        "evidence": [
            {
                "observation": f"{source} evidence",
                "page_number": page_number,
                "text_excerpt": target_text,
                "markup_text": target_text,
                "confidence": 0.8,
            }
        ],
        "reasoning_summary": f"{source} reasoning",
        "suggested_correction": f"{source} correction",
        "comment_text": f"{source} comment for {target_text}",
        "status": status,
        "source": source,
    }


def _reviewed_pages(*pages: int, issue_counts: dict[int, int] | None = None) -> list[dict]:
    counts = issue_counts or {}
    return [
        {"page_number": page, "review_status": "complete", "issue_count": int(counts.get(page, 0))}
        for page in pages
    ]


def _create_synthetic_gas_pdf(path: Path) -> None:
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
            "Revise typo examples are visible on this sheet.",
        ],
        [
            "DRAWING NO: P-003 REV: B",
            "PIPING AND INSTRUMENTATION DIAGRAM",
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


def _create_rotated_gas_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=216, height=302)
    page.insert_text((72, 36), "ROTATED TARGET NOTE", fontsize=8)
    page.set_rotation(270)
    doc.save(path)
    doc.close()


def _create_project_with_uploaded_pdf(db, processor, name: str, source_pdf: Path) -> dict:
    project = db.create_project(name)
    processor.save_uploaded_pdf(project["id"], source_pdf.name, source_pdf.read_bytes())
    return project


def _assert_rect_close(actual: list[float], expected: list[float], tolerance: float = 0.5) -> None:
    assert len(actual) == len(expected) == 4
    for actual_value, expected_value in zip(actual, expected):
        assert abs(float(actual_value) - float(expected_value)) <= tolerance


def test_sheet_classifier_identifies_key_sheet_types() -> None:
    from backend.app.services.classifier import classify_sheet

    assert classify_sheet("PROCESS FLOW DIAGRAM\nRegulator station", 2, "PFD-100", "") == "pfd"
    assert classify_sheet("PIPING AND INSTRUMENTATION DIAGRAM", 3, "PID-100", "") == "p&id"
    assert classify_sheet("GENERAL ARRANGEMENT PLAN VIEW", 4, "L-100", "") == "layout"
    assert classify_sheet("DRAWING INDEX", 1, "C-001", "") == "drawing_index"


def test_entity_extractor_normalizes_tags_and_lines() -> None:
    from backend.app.services.extraction import extract_entities

    text = 'INLET VALVE V101 AND PT-101 ON LINE 4"-NG-1001. SEE P&ID PID-100.'
    entities = extract_entities("project", "sheet", 1, text)
    normalized = {(item["entity_type"], item["normalized_text"]) for item in entities}

    assert ("valve_tag", "V-101") in normalized
    assert ("instrument_tag", "PT-101") in normalized
    assert any(kind == "line_number" and "NG" in value for kind, value in normalized)
    assert ("drawing_reference", "PID-100") in normalized


def test_reasoning_good_station_has_no_major_or_critical() -> None:
    from backend.app.services.extraction import extract_entities
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "pfd",
            "project_id": "project",
            "page_number": 1,
            "drawing_number": "PFD-100",
            "sheet_title": "Process Flow Diagram",
            "revision": "A",
            "sheet_type": "pfd",
            "text_content": """
            DRAWING NO: PFD-100 REV: A PROCESS FLOW DIAGRAM
            INLET ISOLATION VALVE V-101, FILTER FLT-101, WORKER REGULATOR REG-101,
            MONITOR REGULATOR MON-101, BYPASS V-150, OUTLET ISOLATION VALVE V-102,
            VENT BDV-101, DRAIN D-101, PRESSURE GAUGE PI-101, PRESSURE TRANSMITTER PT-101,
            SENSING LINE TO DOWNSTREAM HEADER, OPP SETPOINT 60 PSIG, LINE 4-NG-1001.
            """,
        },
        {
            "id": "pid",
            "project_id": "project",
            "page_number": 2,
            "drawing_number": "PID-100",
            "sheet_title": "Piping and Instrumentation Diagram",
            "revision": "A",
            "sheet_type": "p&id",
            "text_content": """
            DRAWING NO: PID-100 REV: A PIPING AND INSTRUMENTATION DIAGRAM
            INLET ISOLATION VALVE V-101, FILTER FLT-101, WORKER REGULATOR REG-101,
            MONITOR REGULATOR MON-101, BYPASS V-150, OUTLET ISOLATION VALVE V-102,
            VENT BDV-101, DRAIN D-101, PRESSURE GAUGE PI-101, PRESSURE TRANSMITTER PT-101,
            SENSING LINE TO DOWNSTREAM HEADER, OPP SETPOINT 60 PSIG, LINE 4-NG-1001.
            """,
        },
    ]
    entities = []
    for sheet in sheets:
        entities.extend(extract_entities("project", sheet["id"], sheet["page_number"], sheet["text_content"]))

    findings = ReasoningEngine().review_project("project", sheets, entities)
    assert not [item for item in findings if item["severity"] in {"Critical", "Major"}]


def test_reasoning_flags_missing_bypass_and_opp() -> None:
    from backend.app.services.extraction import extract_entities
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "pid",
            "project_id": "project",
            "page_number": 1,
            "drawing_number": "PID-200",
            "sheet_title": "Piping and Instrumentation Diagram",
            "revision": "B",
            "sheet_type": "p&id",
            "text_content": """
            DRAWING NO: PID-200 REV: B PIPING AND INSTRUMENTATION DIAGRAM
            INLET ISOLATION VALVE V-101, FILTER FLT-101, WORKER REGULATOR REG-101,
            OUTLET ISOLATION VALVE V-102, VENT BDV-101, DRAIN D-101,
            PRESSURE GAUGE PI-101, SENSING LINE TO DOWNSTREAM HEADER.
            """,
        }
    ]
    entities = extract_entities("project", "pid", 1, sheets[0]["text_content"])

    findings = ReasoningEngine().review_project("project", sheets, entities)
    titles = {item["title"] for item in findings}

    assert "Bypass arrangement not clearly shown" in titles
    assert "Overpressure protection philosophy not clearly shown" in titles


def test_reasoning_flags_opp_indicator_without_setpoint_basis() -> None:
    from backend.app.services.extraction import extract_entities
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "pid",
            "project_id": "project",
            "page_number": 1,
            "drawing_number": "PID-300",
            "sheet_title": "Piping and Instrumentation Diagram",
            "revision": "A",
            "sheet_type": "p&id",
            "text_content": """
            DRAWING NO: PID-300 REV: A PIPING AND INSTRUMENTATION DIAGRAM
            INLET ISOLATION VALVE V-101, FILTER FLT-101, WORKER REGULATOR REG-101,
            MONITOR REGULATOR MON-101, OUTLET ISOLATION VALVE V-102, BYPASS V-150,
            VENT BDV-101, DRAIN D-101, PRESSURE GAUGE PI-101 60 PSIG,
            SENSING LINE TO DOWNSTREAM HEADER.
            """,
        }
    ]
    entities = extract_entities("project", "pid", 1, sheets[0]["text_content"])

    findings = ReasoningEngine().review_project("project", sheets, entities)
    titles = {item["title"] for item in findings}

    assert "Overpressure protection setpoint basis not clearly shown" in titles


def test_reasoning_flags_weak_extraction_for_visual_review() -> None:
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "sheet-1",
            "project_id": "project",
            "page_number": 1,
            "drawing_number": "UNKNOWN",
            "sheet_title": "Unknown Sheet",
            "revision": "UNKNOWN",
            "sheet_type": "unknown",
            "text_content": "",
            "extraction_status": "no_text",
            "ocr_status": "ocr_unavailable",
        }
    ]

    findings = ReasoningEngine().review_project("project", sheets, [])
    titles = {item["title"] for item in findings}

    assert "Some sheets need extraction/template review" in titles
    assert "Sheet extraction quality requires visual review" not in titles
    assert not any(
        item["comment_text"] == "Visually review this sheet. Text extraction/OCR appears weak, so automated QC coverage may be incomplete."
        for item in findings
    )


def test_reasoning_sample_scenarios() -> None:
    from backend.app.services.extraction import extract_entities
    from backend.app.services.reasoning import ReasoningEngine

    scenarios = json.loads(Path("samples/scenarios/regulator_station_scenarios.json").read_text(encoding="utf-8"))
    engine = ReasoningEngine()

    for scenario in scenarios:
        sheets = []
        entities = []
        for index, source_sheet in enumerate(scenario["sheets"], start=1):
            sheet = {
                "id": f"{scenario['name']}-{index}",
                "project_id": scenario["name"],
                "page_number": index,
                "drawing_number": source_sheet.get("drawing_number", "UNKNOWN"),
                "sheet_title": source_sheet.get("sheet_title", "Unknown Sheet"),
                "revision": source_sheet.get("revision") or "UNKNOWN",
                "sheet_type": source_sheet.get("sheet_type", "unknown"),
                "text_content": source_sheet["text"],
            }
            sheets.append(sheet)
            entities.extend(extract_entities(scenario["name"], sheet["id"], index, sheet["text_content"]))

        findings = engine.review_project(scenario["name"], sheets, entities)
        titles = [finding["title"] for finding in findings]
        if not scenario["expected_findings"]:
            assert findings == [], scenario["name"]
            continue

        for expected in scenario["expected_findings"]:
            assert any(expected["title_contains"].lower() in title.lower() for title in titles), (scenario["name"], expected, titles)


def test_replace_findings_merges_duplicate_stable_ids_before_insert(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Duplicate Stable ID Test")

    base = {
        "id": "finding-1",
        "project_id": project["id"],
        "sheet_id": None,
        "stable_id": "QC-DUPLICATE",
        "title": "Repeated text action item",
        "category": "drafting quality",
        "severity": "Minor",
        "confidence": 0.72,
        "page_number": 4,
        "location": None,
        "involved_entities": [],
        "evidence": [{"observation": "First duplicate observation."}],
        "reasoning_summary": "First reasoning.",
        "suggested_correction": "First correction.",
        "comment_text": "First comment.",
        "status": "accepted",
        "source": "rules",
    }
    duplicate = {
        **base,
        "id": "finding-2",
        "confidence": 0.91,
        "evidence": [{"observation": "Second duplicate observation."}],
        "reasoning_summary": "Second reasoning.",
        "suggested_correction": "Second correction.",
        "comment_text": "Second comment.",
    }

    db.replace_findings(project["id"], [base, duplicate])
    findings = db.list_findings(project["id"])

    assert len(findings) == 1
    assert findings[0]["stable_id"] == "QC-DUPLICATE"
    assert findings[0]["confidence"] == 0.91
    assert {item["observation"] for item in findings[0]["evidence"]} == {
        "First duplicate observation.",
        "Second duplicate observation.",
    }
    assert "Second comment." in findings[0]["comment_text"]


def test_readable_sheet_text_is_not_flagged_as_weak_extraction() -> None:
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "notes-sheet",
            "project_id": "project",
            "page_number": 1,
            "drawing_number": "N-100",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "text_content": "GENERAL NOTES SHEET REVISION A DRAWING N-100 PROJECT NOTES PLAN DETAIL SECTION SCALE DATE",
        }
    ]

    findings = ReasoningEngine().review_project("project", sheets, [])

    assert not any(finding["title"] == "Sheet extraction quality requires visual review" for finding in findings)


def test_title_block_revision_comments_are_aggregated_not_spammed() -> None:
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": f"rev-sheet-{page}",
            "project_id": "project",
            "page_number": page,
            "drawing_number": f"D-{page:03d}",
            "sheet_title": "Detail Sheet",
            "revision": "UNKNOWN",
            "sheet_type": "detail",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "text_content": f"DRAWING D-{page:03d} TITLE DETAIL SHEET REVISION FIELD CLIENT TITLE BLOCK FORMAT NOT PARSED",
        }
        for page in range(1, 5)
    ]

    findings = ReasoningEngine().review_project("project", sheets, [])
    revision_findings = [finding for finding in findings if "Revision" in finding["title"] or "revision" in finding["title"].lower()]

    assert len([finding for finding in revision_findings if finding["title"] == "Revision missing from package title block extraction"]) == 1
    assert not any(
        finding["comment_text"] == "Verify title block revision. Extraction found title-block context but did not identify the revision."
        for finding in findings
    )


def test_unknown_title_blocks_are_aggregated_not_spammed() -> None:
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": f"sheet-{page}",
            "project_id": "project",
            "page_number": page,
            "drawing_number": "UNKNOWN",
            "sheet_title": "Unknown Sheet",
            "revision": "UNKNOWN",
            "sheet_type": "detail",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "text_content": f"DETAIL SHEET {page} WITH READABLE CONSTRUCTION NOTES AND PLAN VIEW TEXT BUT CLIENT TITLE BLOCK FORMAT IS NOT PARSED",
        }
        for page in range(1, 6)
    ]

    findings = ReasoningEngine().review_project("project", sheets, [])
    drawing_number_findings = [finding for finding in findings if "Drawing number" in finding["title"]]

    assert len(drawing_number_findings) == 1
    assert drawing_number_findings[0]["title"] == "Drawing numbers not reliably extracted from package title blocks"
    assert "not 5 separate drawing comments" in drawing_number_findings[0]["evidence"][0]["observation"]
    assert not any(finding["comment_text"] == "Complete title block. Drawing number was not identified." for finding in findings)


def test_ai_review_service_adds_structured_ai_findings(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    class FakeAIClient:
        def review(self, payload: dict) -> dict:
            assert payload["sheets"]
            assert "avoid" in payload["review_guidance"]
            return {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "findings": [
                    {
                        "title": "Possible typo in construction note",
                        "severity": "Minor",
                        "category": "drafting quality",
                        "page_number": 1,
                        "evidence_text": "CONTINTUED",
                        "comment_text": "Correct spelling from CONTINTUED to CONTINUED.",
                        "suggested_correction": "Revise the note heading spelling.",
                        "reasoning_summary": "AI found a likely typo in readable drawing text.",
                        "confidence": 0.93,
                    }
                ]
            }

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("AI Review Test")
    sheet = {
        "id": "sheet-ai-1",
        "project_id": project["id"],
        "page_number": 1,
        "drawing_number": "N-100",
        "sheet_title": "General Notes",
        "revision": "A",
        "sheet_type": "notes",
        "extraction_status": "text_extracted",
        "ocr_status": "not_required",
        "image_path": None,
        "text_content": "GENERAL NOTES CONTINTUED",
        "width": 100.0,
        "height": 100.0,
        "review_status": "ready",
    }
    db.insert_sheet(sheet)

    result = AIReviewService(db, settings, client=FakeAIClient()).review_project(project["id"])

    assert result["ai_findings_created"] == 1
    findings = db.list_findings(project["id"])
    assert any(finding["source"] == "ai" for finding in findings)
    assert any("CONTINTUED" in finding["comment_text"] for finding in findings)


def test_manual_ai_prompt_and_import_flow(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Manual AI Test")
    db.insert_sheet(
        {
            "id": "manual-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-200",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "GENERAL NOTES CONTINTUED",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    prompt = service.generate_manual_prompt(project["id"])["prompt"]
    response = '''```json
    {
      "reviewed_pages": [
        {"page_number": 1, "review_status": "complete", "issue_count": 1}
      ],
      "updates": [
        {
          "issue": "Misspelling in note",
          "severity": "Minor",
          "category": "drafting quality",
          "page_number": 1,
          "target_text": "CONTINTUED",
          "required_update": "Correct CONTINTUED to CONTINUED.",
          "rationale": "Manual AI review found a spelling issue.",
          "confidence": 0.91
        }
      ]
    }
    ```'''

    assert "ChatGPT or Copilot" in prompt
    assert "AI Deep Manual Review engine for AutoQC" in prompt
    assert "autoqc-chat-prompt-v4-exhaustive-manual" in prompt
    assert "Review depth: Exhaustive Manual-Style Review" in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "actual drawing package PDF must be attached/uploaded" in prompt
    assert '"updates"' in prompt
    assert "AutoQC will convert your updates into markups" in prompt
    assert "MANDATORY REVIEW METHOD" in prompt
    assert "Read the extracted page text for the entire sheet" in prompt
    assert "Visually inspect the rendered sheet image" in prompt
    assert "PACKAGE-LEVEL REVIEW METHOD" in prompt
    assert "HARD NO-TRIAGE RULE" in prompt
    assert "INCOMPLETE REVIEW RULE" in prompt
    assert "Do not triage, sample, skim" in prompt
    assert "Every sheet must receive the same baseline review method" in prompt
    assert "Full exhaustive manual-style review could not be completed" in prompt
    assert "Only report issues supported by visible evidence" in prompt
    assert "Do not invent" in prompt
    assert "Do not report OCR, parser, extraction-quality" in prompt
    assert "AI RESPONSE SELF-CHECK BEFORE FINAL JSON" in prompt
    assert "Every update has exact target_text copied from the attached PDF" in prompt
    assert "No update relies on unsupported assumptions" in prompt
    assert "Final reminder: Use the attached PDF" in prompt
    assert '"text":' not in prompt
    assert "text_content" not in prompt
    assert "entities_sample" not in prompt
    assert "existing_findings_summary" not in prompt
    assert "extraction_status" not in prompt
    assert "ocr_status" not in prompt
    assert "GENERAL NOTES CONTINTUED" not in prompt

    result = service.import_manual_response(project["id"], response)
    findings = db.list_findings(project["id"])

    assert result["ai_findings_created"] == 1
    assert result["quality_report"]["total_updates_parsed"] == 1
    assert result["quality_report"]["total_importable_updates"] == 1
    assert result["quality_report"]["imported_findings"] == 1
    assert result["quality_report"]["pages_with_returned_updates"] == [1]
    assert result["quality_report"]["pages_with_imported_updates"] == [1]
    assert result["quality_report"]["pages_without_returned_updates"] == []
    assert any(finding["source"] == "ai" for finding in findings)
    assert any("Update required:" in finding["comment_text"] for finding in findings)
    assert any("CONTINTUED" in finding["evidence"][0].get("markup_text", "") for finding in findings)
    assert all(finding["status"] == "needs_review" for finding in findings)


def test_import_quality_report_counts_duplicates_and_missing_fields(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Import Quality Test")
    db.insert_sheet(
        {
            "id": "quality-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-300",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "GENERAL NOTES CONTINTUED",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    db.insert_sheet(
        {
            "id": "quality-sheet-2",
            "project_id": project["id"],
            "page_number": 2,
            "drawing_number": "N-301",
            "sheet_title": "General Notes Continued",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "SECOND PAGE NOTES",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    response = json.dumps(
        {
            "reviewed_pages": _reviewed_pages(1, 2, issue_counts={1: 1}),
            "updates": [
                {
                    "issue": "Typo",
                    "page_number": 1,
                    "target_text": "CONTINTUED",
                    "required_update": "Correct spelling.",
                    "rationale": "Visible typo.",
                    "confidence": 0.4,
                },
                {
                    "issue": "Typo",
                    "page_number": 1,
                    "target_text": "CONTINTUED",
                    "required_update": "Correct spelling.",
                    "rationale": "Visible typo.",
                    "confidence": 0.92,
                },
                {
                    "issue": "No page",
                    "target_text": "CONTINTUED",
                    "required_update": "Correct spelling.",
                    "rationale": "Missing page should skip.",
                    "confidence": 0.92,
                },
            ]
        }
    )
    preview = AIReviewService(db, settings).preview_manual_response(project["id"], response)
    report = preview["quality_report"]

    assert report["total_updates_parsed"] == 3
    assert report["total_importable_updates"] == 1
    assert report["skipped_updates"] == 2
    assert report["duplicate_count"] == 1
    assert report["missing_page_number_count"] == 1
    assert report["low_confidence_count"] == 1
    assert report["page_count"] == 2
    assert report["pages_with_returned_updates"] == [1]
    assert report["pages_with_importable_updates"] == [1]
    assert report["pages_without_returned_updates"] == [2]

    imported = AIReviewService(db, settings).import_preview(project["id"], preview["batch_id"])
    import_report = imported["quality_report"]
    assert imported["ai_updates_imported"] == 1
    assert import_report["pages_with_returned_updates"] == [1]
    assert import_report["pages_with_imported_updates"] == [1]
    assert import_report["pages_without_returned_updates"] == [2]
    assert len(db.list_findings(project["id"], sources=["ai"])) == 1


def test_manual_prompt_for_large_package_requires_single_output_sheet_by_sheet_deep_dive(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Large Package Prompt Test")
    for page_number in range(1, 13):
        db.insert_sheet(
            {
                "id": f"large-package-sheet-{page_number}",
                "project_id": project["id"],
                "page_number": page_number,
                "drawing_number": f"G-{page_number:03d}",
                "sheet_title": f"Sheet {page_number}",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"VISIBLE TEXT THAT MUST NOT ENTER PROMPT {page_number}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )

    prompt_payload = AIReviewService(db, settings).generate_manual_prompt(project["id"], review_depth="exhaustive")
    prompt = prompt_payload["prompt"]
    metadata = prompt_payload["prompt_metadata"]

    assert metadata["review_strategy"] == "sheet_by_sheet_deep_dive_single_output"
    assert metadata["single_output_required"] is True
    assert metadata["sheet_by_sheet_required"] is True
    assert metadata["sheet_count"] == 12
    assert metadata["sheet_index_count"] == 12
    assert metadata["included_full_extracted_text"] is False
    assert "MANDATORY REVIEW METHOD" in prompt
    assert "PACKAGE-LEVEL REVIEW METHOD" in prompt
    assert "HARD NO-TRIAGE RULE" in prompt
    assert "INCOMPLETE REVIEW RULE" in prompt
    assert "Do not triage, sample, skim" in prompt
    assert "Every sheet must receive the same baseline review method" in prompt
    assert "actual drawing package PDF must be attached/uploaded" in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "Only report issues supported by visible evidence" in prompt
    assert "schema_version" in prompt
    incomplete_review_error = """{
"schema_version": "autoqc-ai-updates-v1",
"updates": [],
"error": "Full exhaustive manual-style review could not be completed. Attach a readable PDF package or split the package into smaller review batches."
}"""
    assert incomplete_review_error in prompt
    assert "sheet_index" in prompt
    assert "VISIBLE TEXT THAT MUST NOT ENTER PROMPT" not in prompt
    assert '"text":' not in prompt


def test_hybrid_review_plan_batches_large_package_and_flags_deep_dives(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Hybrid 100 Page Plan")
    dense_text = " ".join(["REVISION DRAWING NO NOTE TABLE ITEM QTY DESCRIPTION TAG V-101"] * 260)
    for page_number in range(1, 101):
        db.insert_sheet(
            {
                "id": f"hybrid-sheet-{page_number}",
                "project_id": project["id"],
                "page_number": page_number,
                "drawing_number": f"G-{page_number:03d}",
                "sheet_title": f"Sheet {page_number}",
                "revision": "A",
                "sheet_type": "notes" if page_number == 5 else "detail" if page_number == 6 else "layout",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": dense_text if page_number in {5, 6} else f"LIGHT SHEET {page_number}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    db.insert_entities(
        [
            {
                "id": f"entity-{index}",
                "project_id": project["id"],
                "sheet_id": "hybrid-sheet-6",
                "entity_type": "drawing_reference",
                "text": f"PID-{index:03d}",
                "normalized_text": f"PID-{index:03d}",
                "page_number": 6,
                "bbox": None,
                "confidence": 0.8,
                "source": "pdf_text",
            }
            for index in range(25)
        ]
    )

    plan = AIReviewService(db, settings).build_manual_review_plan(project["id"], batch_size=8)

    assert plan["batch_size"] == 8
    assert len(plan["batches"]) == 13
    assert plan["batches"][0]["page_numbers"] == list(range(1, 9))
    flagged_pages = {item["page_number"] for item in plan["deep_dive_candidates"]}
    assert {5, 6}.issubset(flagged_pages)
    page_6 = next(item for item in plan["deep_dive_candidates"] if item["page_number"] == 6)
    assert "high tag/reference count" in page_6["reasons"]


def test_scoped_prompt_and_zero_update_review_confirmation_import(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Scoped Zero Update")
    for page_number in range(1, 4):
        db.insert_sheet(
            {
                "id": f"scoped-sheet-{page_number}",
                "project_id": project["id"],
                "page_number": page_number,
                "drawing_number": f"S-{page_number:03d}",
                "sheet_title": f"Scoped Sheet {page_number}",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"SCOPED SHEET {page_number}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    service = AIReviewService(db, settings)

    prompt_payload = service.generate_manual_prompt(
        project["id"],
        review_scope="batch",
        page_numbers=[1, 2],
        batch_size=8,
    )
    prompt = prompt_payload["prompt"]
    metadata = prompt_payload["prompt_metadata"]

    assert metadata["review_strategy"] == "adaptive_batch_review"
    assert metadata["review_scope"] == "batch"
    assert metadata["scope_pages"] == [1, 2]
    assert metadata["batch_size"] == 8
    assert "SCOPED REVIEW MODE: Adaptive page batch" in prompt
    assert "Review only these PDF pages: 1, 2" in prompt
    assert "reviewed_pages" in prompt

    preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "schema_version": "autoqc-ai-updates-v1",
                "reviewed_pages": [
                    {"page_number": 1, "review_status": "complete", "issue_count": 0},
                    {"page_number": 2, "review_status": "complete", "issue_count": 0},
                ],
                "updates": [],
            }
        ),
        prompt_version=prompt_payload["prompt_version"],
        prompt_id=prompt_payload["prompt_id"],
    )

    assert preview["valid_recoverable_updates"] == 0
    assert preview["scoped_review_complete"] is True
    assert preview["quality_report"]["page_count"] == 2
    assert preview["quality_report"]["pages_reviewed"] == [1, 2]
    imported = service.import_preview(project["id"], preview["batch_id"])
    assert imported["ai_updates_imported"] == 0
    assert imported["batch"]["import_status"] == "imported"
    assert db.list_findings(project["id"], sources=["ai"]) == []


def test_scoped_batch_imports_merge_additively(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Scoped Additive Imports")
    for page_number in range(1, 3):
        db.insert_sheet(
            {
                "id": f"additive-sheet-{page_number}",
                "project_id": project["id"],
                "page_number": page_number,
                "drawing_number": f"A-{page_number:03d}",
                "sheet_title": f"Additive Sheet {page_number}",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"TARGET PAGE {page_number}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    service = AIReviewService(db, settings)
    first_prompt = service.generate_manual_prompt(project["id"], review_scope="batch", page_numbers=[1], batch_size=8)
    second_prompt = service.generate_manual_prompt(project["id"], review_scope="sheet", page_number=2, batch_size=8)

    first = service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": [{"page_number": 1, "review_status": "complete", "issue_count": 1}],
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "First scoped issue",
                        "target_text": "TARGET PAGE 1",
                        "required_update": "Clarify first target.",
                        "rationale": "Scoped first batch.",
                        "confidence": 0.8,
                    }
                ],
            }
        ),
        prompt_version=first_prompt["prompt_version"],
        prompt_id=first_prompt["prompt_id"],
    )
    second = service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": [{"page_number": 2, "review_status": "complete", "issue_count": 1}],
                "updates": [
                    {
                        "page_number": 2,
                        "issue": "Second scoped issue",
                        "target_text": "TARGET PAGE 2",
                        "required_update": "Clarify second target.",
                        "rationale": "Scoped sheet deep dive.",
                        "confidence": 0.81,
                    }
                ],
            }
        ),
        prompt_version=second_prompt["prompt_version"],
        prompt_id=second_prompt["prompt_id"],
    )

    assert first["ai_updates_imported"] == 1
    assert second["ai_updates_imported"] == 1
    findings = db.list_findings(project["id"], sources=["ai"])
    assert len(findings) == 2
    assert {finding["page_number"] for finding in findings} == {1, 2}


def test_manual_placement_endpoint_updates_existing_finding_without_creating_findings(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/projects", data={"name": "Manual Placement API"}).json()
    main.db.insert_sheet(
        {
            "id": "manual-placement-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-301",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "GENERAL NOTES",
            "width": 612.0,
            "height": 792.0,
            "source_width": 612.0,
            "source_height": 792.0,
            "review_status": "ready",
        }
    )
    finding = _finding_record(project["id"], "manual-placement-finding", source="ai", status="needs_review", sheet_id="manual-placement-sheet-1")
    main.db.replace_findings(project["id"], [finding], sources=["ai"])
    stored = main.db.list_findings(project["id"], sources=["ai"])[0]

    response = client.post(
        f"/findings/{stored['id']}/manual-placement",
        json={"page_number": 1, "rect": [72, 80, 180, 124]},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["placement_status"] == "manual_placement"
    assert updated["location"]["coordinate_space"] == "image_pixel"
    assert updated["location"]["bbox"] == [72.0, 80.0, 180.0, 124.0]
    assert updated["placement_details"]["manual_image_rect_json"] == [72.0, 80.0, 180.0, 124.0]
    assert updated["placement_details"]["display_rect_json"] == [72.0, 80.0, 180.0, 124.0]
    assert updated["placement_details"]["pdf_rect_json"] == [72.0, 80.0, 180.0, 124.0]
    assert len(main.db.list_findings(project["id"], sources=["ai"])) == 1
    assert any(event["action"] == "manual_placement_saved" for event in main.db.list_finding_events(project["id"]))


def test_validation_projects_are_hidden_by_default_and_cleanup_is_scoped(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    reviewer_project = client.post("/projects", data={"name": "Reviewer Package"}).json()
    validation_project = client.post(
        "/projects",
        data={"name": "Smoke AI Workflow", "project_type": "validation"},
    ).json()
    legacy_generated_project = client.post("/projects", data={"name": "Large Wide Stress Fixture"}).json()
    validation_dir = Path(main.settings.data_dir) / "projects" / validation_project["id"]
    validation_dir.mkdir(parents=True)
    (validation_dir / "generated.txt").write_text("validation artifact", encoding="utf-8")

    default_projects = client.get("/projects").json()
    assert {project["id"] for project in default_projects} == {reviewer_project["id"], legacy_generated_project["id"]}

    dry_run = client.post("/maintenance/validation-projects/tag-generated?dry_run=true")
    assert dry_run.status_code == 200
    assert dry_run.json()["matched_project_ids"] == [legacy_generated_project["id"]]
    assert client.get(f"/projects/{legacy_generated_project['id']}").json()["project_type"] == "review"

    tagged = client.post("/maintenance/validation-projects/tag-generated?dry_run=false")
    assert tagged.status_code == 200
    assert tagged.json()["tagged_count"] == 1
    assert tagged.json()["matched_project_ids"] == [legacy_generated_project["id"]]

    default_projects = client.get("/projects").json()
    assert [project["id"] for project in default_projects] == [reviewer_project["id"]]
    assert default_projects[0]["project_type"] == "review"

    all_projects = client.get("/projects?include_validation=true").json()
    assert {project["id"] for project in all_projects} == {reviewer_project["id"], validation_project["id"], legacy_generated_project["id"]}
    assert next(project for project in all_projects if project["id"] == validation_project["id"])["project_type"] == "validation"
    assert next(project for project in all_projects if project["id"] == legacy_generated_project["id"])["project_type"] == "validation"

    cleanup = client.delete("/maintenance/validation-projects")
    assert cleanup.status_code == 200
    payload = cleanup.json()
    assert payload["deleted_count"] == 2
    assert validation_project["id"] in payload["deleted_project_ids"]
    assert legacy_generated_project["id"] in payload["deleted_project_ids"]
    assert not validation_dir.exists()
    assert client.get(f"/projects/{reviewer_project['id']}").status_code == 200
    assert client.get(f"/projects/{validation_project['id']}").status_code == 404
    assert client.get(f"/projects/{legacy_generated_project['id']}").status_code == 404


def test_manual_placement_endpoint_converts_rotated_display_rect_to_pdf_coordinates(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/projects", data={"name": "Manual Placement Rotation API"}).json()
    main.db.insert_sheet(
        {
            "id": "manual-placement-rotated-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-302",
            "sheet_title": "Rotated Sheet",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "ROTATED SHEET",
            "width": 792.0,
            "height": 612.0,
            "rotation": 90,
            "source_width": 612.0,
            "source_height": 792.0,
            "review_status": "ready",
        }
    )
    finding = _finding_record(
        project["id"],
        "manual-placement-rotated-finding",
        source="ai",
        status="needs_review",
        sheet_id="manual-placement-rotated-sheet-1",
    )
    main.db.replace_findings(project["id"], [finding], sources=["ai"])
    stored = main.db.list_findings(project["id"], sources=["ai"])[0]

    response = client.post(
        f"/findings/{stored['id']}/manual-placement",
        json={"page_number": 1, "rect": [100, 200, 180, 260], "coordinate_space": "display_rotated"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["placement_status"] == "manual_placement"
    assert updated["location"]["coordinate_space"] == "image_pixel"
    assert updated["location"]["bbox"] == [100.0, 200.0, 180.0, 260.0]
    assert updated["placement_details"]["manual_image_rect_json"] == [100.0, 200.0, 180.0, 260.0]
    assert updated["placement_details"]["rect_json"] == [200.0, 612.0, 260.0, 692.0]
    assert updated["placement_details"]["pdf_rect_json"] == [200.0, 612.0, 260.0, 692.0]
    assert updated["placement_details"]["display_rect_json"] == [100.0, 200.0, 180.0, 260.0]

    pdf_space_response = client.post(
        f"/findings/{stored['id']}/manual-placement",
        json={"page_number": 1, "rect": [72, 80, 180, 124], "coordinate_space": "pdf_unrotated"},
    )
    assert pdf_space_response.status_code == 200
    pdf_space_updated = pdf_space_response.json()
    assert pdf_space_updated["location"]["coordinate_space"] == "image_pixel"
    assert pdf_space_updated["location"]["bbox"] == [668.0, 72.0, 712.0, 180.0]
    assert pdf_space_updated["placement_details"]["manual_image_rect_json"] == [668.0, 72.0, 712.0, 180.0]
    assert pdf_space_updated["placement_details"]["rect_json"] == [72.0, 80.0, 180.0, 124.0]
    assert pdf_space_updated["placement_details"]["display_rect_json"] == [668.0, 72.0, 712.0, 180.0]


def _create_alliant_manual_placement_project(tmp_path: Path, monkeypatch, name: str):
    import importlib
    import sys

    from fastapi.testclient import TestClient

    assert ALLIANT_REPRO_PDF.exists(), f"Missing repro PDF: {ALLIANT_REPRO_PDF}"
    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/projects", data={"name": name}).json()
    main.processor.save_uploaded_pdf(project["id"], ALLIANT_REPRO_PDF.name, ALLIANT_REPRO_PDF.read_bytes())
    main.processor.process_project(project["id"])
    sheet = main.db.list_sheets(project["id"])[0]
    pixmap = fitz.Pixmap(sheet["image_path"])
    image_width = float(pixmap.width)
    image_height = float(pixmap.height)

    finding = _finding_record(
        project["id"],
        f"{name.lower().replace(' ', '-')}-manual",
        source="ai",
        status="needs_review",
        page_number=1,
        sheet_id=sheet["id"],
        target_text="MANUAL REPRO TARGET",
    )
    main.db.replace_findings(project["id"], [finding], sources=["ai"])
    stored = main.db.list_findings(project["id"], sources=["ai"])[0]
    manual_rect = [400.0, 300.0, 800.0, 500.0]
    response = client.post(
        f"/findings/{stored['id']}/manual-placement",
        json={
            "page_number": 1,
            "coordinate_space": "image_pixel",
            "rect": manual_rect,
            "image_width": image_width,
            "image_height": image_height,
        },
    )
    assert response.status_code == 200, response.text
    return main, client, project, sheet, response.json(), manual_rect, image_width, image_height


def test_manual_image_pixel_placement_roundtrips_on_alliant_bluebeam_repro(tmp_path: Path, monkeypatch) -> None:
    from backend.app.services.placement_coordinates import pdf_rect_to_image_rect

    main, _client, _project, sheet, updated, manual_rect, image_width, image_height = _create_alliant_manual_placement_project(
        tmp_path,
        monkeypatch,
        "Alliant Manual Roundtrip",
    )

    assert int(sheet["rotation"]) == 270
    assert float(sheet["width"]) == 3024.0
    assert float(sheet["height"]) == 2160.0
    assert float(sheet["source_width"]) == 2160.0
    assert float(sheet["source_height"]) == 3024.0
    assert image_width == 4839.0
    assert image_height == 3456.0

    placement = updated["placement_details"]
    assert updated["location"]["coordinate_space"] == "image_pixel"
    assert placement["coordinate_space"] == "image_pixel"
    assert placement["manual_image_rect_json"] == manual_rect
    assert placement["display_rect_json"] == manual_rect
    assert placement["page_rotation"] == 270

    pdf_rect = placement["pdf_rect_json"]
    assert 0 <= pdf_rect[0] < pdf_rect[2] <= placement["source_width"]
    assert 0 <= pdf_rect[1] < pdf_rect[3] <= placement["source_height"]

    roundtrip = pdf_rect_to_image_rect(
        pdf_rect,
        image_width=image_width,
        image_height=image_height,
        source_width=placement["source_width"],
        source_height=placement["source_height"],
        display_width=placement["page_display_width"],
        display_height=placement["page_display_height"],
        rotation=placement["page_rotation"],
    )
    _assert_rect_close(roundtrip, manual_rect, tolerance=0.2)
    assert len(main.db.list_findings(updated["project_id"], sources=["ai"])) == 1


def test_export_uses_manual_image_pixel_placement_on_alliant_bluebeam_repro(tmp_path: Path, monkeypatch) -> None:
    main, _client, project, _sheet, updated, _manual_rect, _image_width, _image_height = _create_alliant_manual_placement_project(
        tmp_path,
        monkeypatch,
        "Alliant Manual Export",
    )
    accepted = main.db.update_finding(updated["id"], {"status": "accepted", "comment_text": "Reviewer note for manual Alliant placement."})

    export = main.export_service.export_project(project["id"])
    assert export["placement_summary"]["manual_placement"] == 1
    assert export["placement_summary"]["target_cloud_created"] == 1
    assert export["placement_summary"]["cloud_plus_note"] == 1

    exported = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    exported_placement = exported[0]["placement_details"]
    pdf_rect = exported_placement["pdf_rect_json"]
    assert exported_placement["manual_image_rect_json"] == accepted["placement_details"]["manual_image_rect_json"]
    assert exported_placement["display_rect_json"] == accepted["placement_details"]["manual_image_rect_json"]

    with fitz.open(Path(export["export"]["marked_pdf_path"])) as marked_doc:
        assert marked_doc.page_count == 1
        page = marked_doc[0]
        annotations = list(page.annots() or [])
        square_annotations = [annotation for annotation in annotations if annotation.type[1] == "Square"]
        text_annotations = [annotation for annotation in annotations if annotation.type[1] == "Text"]
        assert len(square_annotations) == 1
        assert len(text_annotations) == 1
        assert "Reviewer note for manual Alliant placement." in (text_annotations[0].info.get("content") or "")

        expected_cloud_rect = [
            max(0.0, pdf_rect[0] - 4.0),
            max(0.0, pdf_rect[1] - 4.0),
            min(float(page.cropbox.width), pdf_rect[2] + 4.0),
            min(float(page.cropbox.height), pdf_rect[3] + 4.0),
        ]
        square_rect = square_annotations[0].rect
        _assert_rect_close(
            [
                (square_rect.x0 + square_rect.x1) / 2,
                (square_rect.y0 + square_rect.y1) / 2,
                0.0,
                0.0,
            ],
            [
                (expected_cloud_rect[0] + expected_cloud_rect[2]) / 2,
                (expected_cloud_rect[1] + expected_cloud_rect[3]) / 2,
                0.0,
                0.0,
            ],
            tolerance=1.0,
        )
        assert square_rect.x0 <= expected_cloud_rect[0]
        assert square_rect.y0 <= expected_cloud_rect[1]
        assert square_rect.x1 >= expected_cloud_rect[2]
        assert square_rect.y1 >= expected_cloud_rect[3]
        _assert_rect_close(
            [square_rect.x0, square_rect.y0, square_rect.x1, square_rect.y1],
            expected_cloud_rect,
            tolerance=12.0,
        )


def test_removed_tracker_routes_are_not_public_workflow(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/projects", data={"name": "Removed tracker API"}).json()
    removed_word = "check" + "list"

    assert client.get(f"/{removed_word}s/templates").status_code == 404
    assert client.get(f"/projects/{project['id']}/{removed_word}").status_code == 404
    assert client.post(
        f"/projects/{project['id']}/{removed_word}/select",
        json={f"{removed_word}_id": "legacy"},
    ).status_code == 404
    assert client.patch(
        f"/projects/{project['id']}/{removed_word}/items/legacy",
        json={"status": "checked"},
    ).status_code == 404


def test_markup_memory_captures_route_status_edits_and_upserts(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project_response = client.post("/projects", data={"name": "Markup Memory API Test"})
    assert project_response.status_code == 200
    project = project_response.json()
    main.db.insert_sheet(
        {
            "id": "memory-api-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-210",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "ORIGINAL TARGET FINAL TARGET",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    main.db.replace_findings(
        project["id"],
        [
            _finding_record(
                project["id"],
                "memory-api-accepted",
                source="ai",
                status="needs_review",
                sheet_id="memory-api-sheet-1",
                target_text="ORIGINAL TARGET",
            ),
            _finding_record(
                project["id"],
                "memory-api-rejected",
                source="ai",
                status="needs_review",
                sheet_id="memory-api-sheet-1",
                target_text="FALSE POSITIVE TARGET",
            ),
        ],
        sources=["ai"],
    )
    findings = {finding["stable_id"]: finding for finding in main.db.list_findings(project["id"], sources=["ai"])}

    accepted_response = client.patch(
        f"/findings/{findings['memory-api-accepted']['id']}",
        json={
            "target_text": "FINAL TARGET",
            "required_update": "Use reviewer final required update.",
            "comment_text": "Reviewer final exported wording.",
            "reviewer_note": "Edited before accepting.",
            "status": "accepted",
        },
    )
    assert accepted_response.status_code == 200
    rejected_response = client.patch(f"/findings/{findings['memory-api-rejected']['id']}", json={"status": "rejected"})
    assert rejected_response.status_code == 200
    second_accept = client.patch(
        f"/findings/{findings['memory-api-accepted']['id']}",
        json={"comment_text": "Reviewer final exported wording v2.", "status": "accepted"},
    )
    assert second_accept.status_code == 200

    examples = main.db.list_markup_memory_examples()
    accepted_examples = [example for example in examples if example["status_outcome"] == "accepted"]
    rejected_examples = [example for example in examples if example["status_outcome"] == "rejected"]
    assert len(accepted_examples) == 1
    assert len(rejected_examples) == 1
    assert accepted_examples[0]["target_text"] == "FINAL TARGET"
    assert accepted_examples[0]["required_update"] == "Use reviewer final required update."
    assert accepted_examples[0]["final_comment_text"] == "Reviewer final exported wording v2."
    assert rejected_examples[0]["target_text"] == "FALSE POSITIVE TARGET"
    stats = client.get("/markup-memory/stats").json()
    assert stats["accepted_examples"] == 1
    assert stats["rejected_examples"] == 1


def test_markup_memory_capture_failure_does_not_block_status_update(tmp_path: Path, monkeypatch, caplog) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/projects", data={"name": "Markup Memory Failure Test"}).json()
    main.db.replace_findings(
        project["id"],
        [_finding_record(project["id"], "memory-failure-example", source="ai", status="needs_review")],
        sources=["ai"],
    )
    finding = main.db.list_findings(project["id"], sources=["ai"])[0]

    def raise_memory_failure(*_args, **_kwargs):
        raise RuntimeError("forced memory failure")

    monkeypatch.setattr(main.memory_service, "collect_memory_from_finding", raise_memory_failure)
    caplog.set_level("WARNING")

    response = client.patch(f"/findings/{finding['id']}", json={"status": "accepted"})

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert main.db.get_finding(finding["id"])["status"] == "accepted"
    assert "Markup Memory capture failed" in caplog.text
    assert "forced memory failure" in caplog.text


def test_markup_memory_prompt_gates_and_avoid_guidance(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.markup_memory import MarkupMemoryService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Markup Memory Prompt Test")
    db.insert_sheet(
        {
            "id": "memory-prompt-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "P-310",
            "sheet_title": "Piping and Instrumentation Diagram",
            "revision": "A",
            "sheet_type": "p&id",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "PT-101 SENSING LINE FALSE TITLE BLOCK WARNING",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    accepted = _finding_record(
        project["id"],
        "memory-prompt-accepted",
        source="ai",
        status="accepted",
        sheet_id="memory-prompt-sheet-1",
        target_text="PT-101 SENSING LINE",
        title="Accepted sensing-line wording",
    )
    rejected = _finding_record(
        project["id"],
        "memory-prompt-rejected",
        source="ai",
        status="rejected",
        sheet_id="memory-prompt-sheet-1",
        target_text="FALSE TITLE BLOCK WARNING",
        title="Rejected metadata-only title block issue",
    )
    db.replace_findings(project["id"], [accepted, rejected], sources=["ai"])
    service = MarkupMemoryService(db)
    stored = {finding["stable_id"]: finding for finding in db.list_findings(project["id"], sources=["ai"])}
    service.collect_memory_from_finding(project["id"], stored["memory-prompt-accepted"]["id"], "accepted")
    service.collect_memory_from_finding(project["id"], stored["memory-prompt-rejected"]["id"], "rejected")

    prompt_disabled = AIReviewService(db, settings).generate_manual_prompt(project["id"])["prompt"]
    assert "Past Review Memory" not in prompt_disabled

    db.update_markup_memory_settings(
        {
            "advanced_feature_enabled": True,
            "enabled": True,
            "include_in_prompts": True,
            "include_rejected_examples": True,
            "include_current_project_examples": True,
        }
    )
    prompt_enabled = AIReviewService(db, settings).generate_manual_prompt(project["id"])["prompt"]
    assert "Past Review Memory" in prompt_enabled
    assert "Use these past examples only as review guidance" in prompt_enabled
    assert "The attached PDF remains the source of truth" in prompt_enabled
    assert "Examples to emulate" in prompt_enabled
    assert "Examples to avoid" in prompt_enabled
    assert "PT-101 SENSING LINE" in prompt_enabled
    assert "FALSE TITLE BLOCK WARNING" in prompt_enabled

    db.update_markup_memory_settings({"include_in_prompts": False})
    prompt_disabled_again = AIReviewService(db, settings).generate_manual_prompt(project["id"])["prompt"]
    assert "Past Review Memory" not in prompt_disabled_again


def test_markup_memory_excludes_current_project_examples_by_default(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.markup_memory import MarkupMemoryService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    current_project = db.create_project("Current Project Memory Bias Test")
    prior_project = db.create_project("Prior Project Memory Source")
    for project, sheet_id, target in [
        (current_project, "current-memory-sheet", "CURRENT PROJECT TARGET"),
        (prior_project, "prior-memory-sheet", "PRIOR PROJECT TARGET"),
    ]:
        db.insert_sheet(
            {
                "id": sheet_id,
                "project_id": project["id"],
                "page_number": 1,
                "drawing_number": "N-510",
                "sheet_title": "General Notes",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"{target} REGULATOR STATION MEMORY",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    db.replace_findings(
        current_project["id"],
        [
            _finding_record(
                current_project["id"],
                "current-memory-example",
                source="ai",
                status="accepted",
                sheet_id="current-memory-sheet",
                target_text="CURRENT PROJECT TARGET",
            )
        ],
        sources=["ai"],
    )
    db.replace_findings(
        prior_project["id"],
        [
            _finding_record(
                prior_project["id"],
                "prior-memory-example",
                source="ai",
                status="accepted",
                sheet_id="prior-memory-sheet",
                target_text="PRIOR PROJECT TARGET",
            )
        ],
        sources=["ai"],
    )
    memory = MarkupMemoryService(db)
    for project in [current_project, prior_project]:
        for finding in db.list_findings(project["id"], sources=["ai"]):
            memory.collect_memory_from_finding(project["id"], finding["id"], "accepted")

    db.update_markup_memory_settings(
        {
            "advanced_feature_enabled": True,
            "enabled": True,
            "include_in_prompts": True,
        }
    )
    default_context = memory.build_markup_memory_prompt_context(current_project["id"])
    default_prompt_section = default_context["prompt_section"]
    assert "PRIOR PROJECT TARGET" in default_prompt_section
    assert "CURRENT PROJECT TARGET" not in default_prompt_section

    db.update_markup_memory_settings({"include_current_project_examples": True})
    included_context = memory.build_markup_memory_prompt_context(current_project["id"])
    included_prompt_section = included_context["prompt_section"]
    assert "CURRENT PROJECT TARGET" in included_prompt_section
    assert "PRIOR PROJECT TARGET" in included_prompt_section


def test_markup_memory_prompt_context_is_bounded_and_truncated(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.markup_memory import MarkupMemoryService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Markup Memory Bounds Test")
    db.insert_sheet(
        {
            "id": "memory-bounds-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "M-410",
            "sheet_title": "Mechanical Plan",
            "revision": "A",
            "sheet_type": "layout",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "LAYOUT TARGET " * 80,
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    findings = []
    for index in range(6):
        findings.append(
            _finding_record(
                project["id"],
                f"memory-bound-accepted-{index}",
                source="ai",
                status="accepted",
                sheet_id="memory-bounds-sheet-1",
                target_text=f"LAYOUT TARGET {index}",
                title=f"Accepted bounded example {index}",
            )
        )
    for index in range(3):
        findings.append(
            _finding_record(
                project["id"],
                f"memory-bound-rejected-{index}",
                source="ai",
                status="rejected",
                sheet_id="memory-bounds-sheet-1",
                target_text=f"AVOID TARGET {index}",
                title=f"Rejected bounded example {index}",
            )
        )
    db.replace_findings(project["id"], findings, sources=["ai"])
    stored = db.list_findings(project["id"], sources=["ai"])
    for finding in stored:
        db.update_finding(
            finding["id"],
            {
                "comment_text": f"Final memory comment for {finding['stable_id']} " + ("X" * 520),
            },
        )
    service = MarkupMemoryService(db)
    for finding in db.list_findings(project["id"], sources=["ai"]):
        service.collect_memory_from_finding(project["id"], finding["id"], finding["status"])
    db.update_markup_memory_settings(
        {
            "advanced_feature_enabled": True,
            "enabled": True,
            "include_in_prompts": True,
            "include_current_project_examples": True,
            "max_examples_per_prompt": 2,
            "max_avoid_examples_per_prompt": 1,
        }
    )

    context = service.build_markup_memory_prompt_context(project["id"])

    assert context["enabled"] is True
    assert len(context["positive_examples"]) == 2
    assert len(context["avoid_examples"]) == 1
    assert "...[trimmed" not in context["prompt_section"]
    assert "X" * 260 not in context["prompt_section"]


def test_markup_memory_rebuild_clear_and_export_capture(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.markup_memory import MarkupMemoryService
    from backend.app.services.pdf_processor import PDFProcessor

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "memory-export.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Markup Memory Export Test", source_pdf)
    processor.process_project(project["id"])
    imported = AIReviewService(db, settings).import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Memory export issue",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Clarify memory export note.",
                        "rationale": "Export capture coverage.",
                        "confidence": 0.82,
                    }
                ]
            }
        ),
    )
    finding_id = imported["imported_finding_ids"][0]
    db.update_finding(finding_id, {"comment_text": "Edited final memory wording."})
    db.update_finding(finding_id, {"status": "accepted"})

    rebuild = MarkupMemoryService(db).rebuild_memory_from_existing_findings()
    assert rebuild["memory_examples_upserted"] >= 2
    assert rebuild["stats"]["accepted_examples"] == 1
    assert rebuild["stats"]["edited_examples"] == 1

    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"])
    assert export["validation"]["status"] in {"passed", "warning"}
    stats_after_export = db.markup_memory_stats()
    assert stats_after_export["exported_examples"] == 1

    clear = MarkupMemoryService(db).clear_memory()
    assert clear["deleted"] >= 3
    assert clear["stats"]["total_memory_examples"] == 0


def test_manual_ai_import_repairs_common_chat_json_errors(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Loose AI JSON Test")
    db.insert_sheet(
        {
            "id": "loose-json-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "M-100",
            "sheet_title": "Mechanical Details",
            "revision": "A",
            "sheet_type": "detail",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "2\" VENT STACK",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    response = '''Here is the update JSON:
    {
      "reviewed_pages": [
        {"page_number": 1, "review_status": "complete", "issue_count": 1}
      ],
      "updates": [
        {
          "issue": "Vent note needs clarification",
          "severity": "Minor",
          "category": "notes and specifications",
          "page_number": 1,
          "target_text": "2" VENT STACK",
          "required_update": "Clarify whether this is a 2-inch vent stack and match project notation.",
          "rationale": "Unescaped inch marks often make Chat output invalid JSON, but the app should still import the update.",
          "confidence": 0.82,
        }
      ]
    }
    '''

    result = AIReviewService(db, settings).import_manual_response(project["id"], response)
    findings = db.list_findings(project["id"])

    assert result["ai_findings_created"] == 1
    assert any("2\" VENT STACK" in finding["comment_text"] for finding in findings)
    assert any(finding["source"] == "ai" for finding in findings)


def test_ai_preview_confirm_import_prompt_metadata_and_batch_history(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    source_pdf = tmp_path / "synthetic-gas.pdf"
    _create_synthetic_gas_pdf(source_pdf)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    with source_pdf.open("rb") as handle:
        project_response = client.post(
            "/projects",
            data={"name": "Golden AI Workflow", "auto_review": "true"},
            files={"file": ("synthetic-gas.pdf", handle, "application/pdf")},
        )
    assert project_response.status_code == 200
    project = project_response.json()
    assert project["sheet_count"] == 3
    assert project["finding_count"] == 0

    prompt_response = client.get(f"/projects/{project['id']}/ai-review/manual-prompt")
    assert prompt_response.status_code == 200
    prompt_payload = prompt_response.json()
    prompt = prompt_payload["prompt"]
    assert prompt_payload["prompt_version"] == "autoqc-chat-prompt-v4-exhaustive-manual"
    assert prompt_payload["prompt_metadata"]["included_full_extracted_text"] is False
    assert prompt_payload["prompt_metadata"]["review_strategy"] == "sheet_by_sheet_deep_dive_single_output"
    assert prompt_payload["prompt_metadata"]["single_output_required"] is True
    assert prompt_payload["prompt_metadata"]["sheet_by_sheet_required"] is True
    assert prompt_payload["prompt_metadata"]["sheet_count"] == 3
    assert "actual drawing package PDF must be attached/uploaded" in prompt
    assert "MANDATORY REVIEW METHOD" in prompt
    assert "HARD NO-TRIAGE RULE" in prompt
    assert "INCOMPLETE REVIEW RULE" in prompt
    assert "sheet_index" in prompt
    assert '"text":' not in prompt
    assert "# AutoQC Enhanced Manual Review Prompt Batch" not in prompt
    assert "INSTALL 12 Inlet Valve" not in prompt
    assert "included_sheet_evidence_context" in prompt

    ai_response = json.dumps(
        {
            "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1, 2: 1}),
            "updates": [
                {
                    "pageNumber": "Page 1",
                    "issue": "Valve notation should include inch mark",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "target_text": '12" Inlet Valve',
                    "required_update": 'Revise to 12" Inlet Valve if this is intended as nominal size notation.',
                    "rationale": "The drawing text omits the inch mark.",
                    "confidence": 0.82,
                },
                {
                    "pdf_page": "PDF page 2",
                    "issue": "Misspelling in general notes",
                    "severity": "Minor",
                    "category": "drafting quality",
                    "target_text": "CONTINTUED",
                    "required_update": 'Revise "CONTINTUED" to "CONTINUED".',
                    "rationale": "Visible typo in note heading.",
                    "confidence": 0.97,
                },
                {
                    "page": 1,
                    "issue": "Duplicate valve notation",
                    "target_text": '12" Inlet Valve',
                    "required_update": 'Revise to 12" Inlet Valve if this is intended as nominal size notation.',
                    "confidence": 0.82,
                },
            ]
        }
    )

    preview_response = client.post(
        f"/projects/{project['id']}/ai-review/preview",
        json={
            "response_text": ai_response,
            "prompt_version": prompt_payload["prompt_version"],
            "prompt_id": prompt_payload["prompt_id"],
            "source_type": "chatgpt",
        },
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["total_candidate_updates"] == 3
    assert preview["valid_recoverable_updates"] == 2
    assert preview["skipped_updates"] == 1
    assert any(update["action"] == "update_existing" for update in preview["updates"]) is False
    assert any(update["action"] == "duplicate_in_response" for update in preview["updates"])
    assert any("pageNumber" in warning for warning in preview["warnings"])

    import_response = client.post(
        f"/projects/{project['id']}/ai-review/import",
        json={"preview_id": preview["batch_id"]},
    )
    assert import_response.status_code == 200
    imported = import_response.json()
    assert imported["ai_updates_imported"] == 2
    assert imported["batch"]["import_status"] == "imported"

    findings = client.get(f"/projects/{project['id']}/findings").json()
    assert len(findings) == 2
    assert all(finding["source"] == "ai" for finding in findings)
    assert all(finding["ai_batch_id"] == preview["batch_id"] for finding in findings)
    assert all(finding["prompt_version"] == "autoqc-chat-prompt-v4-exhaustive-manual" for finding in findings)
    assert all(finding["original_ai_json"] for finding in findings)

    batches = client.get(f"/projects/{project['id']}/ai-review/import-batches").json()
    assert batches[0]["id"] == preview["batch_id"]
    assert batches[0]["valid_count"] == 2
    assert batches[0]["duplicate_count"] == 1


def test_project_delete_removes_package_records_and_files(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    source_pdf = tmp_path / "synthetic-gas.pdf"
    _create_synthetic_gas_pdf(source_pdf)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    with source_pdf.open("rb") as handle:
        project_response = client.post(
            "/projects",
            data={"name": "Delete Me Package", "auto_review": "true"},
            files={"file": ("synthetic-gas.pdf", handle, "application/pdf")},
        )

    assert project_response.status_code == 200
    project = project_response.json()
    project_dir = tmp_path / "data" / "projects" / project["id"]
    assert project_dir.exists()
    assert client.get(f"/projects/{project['id']}/sheets").status_code == 200

    delete_response = client.delete(f"/projects/{project['id']}")

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    assert not project_dir.exists()
    assert client.get(f"/projects/{project['id']}").status_code == 404
    assert client.get(f"/projects/{project['id']}/sheets").status_code == 404
    assert client.delete(f"/projects/{project['id']}").status_code == 404
    assert all(item["id"] != project["id"] for item in client.get("/projects").json())


def test_ai_preview_reports_zero_importable_updates_with_clear_error(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Empty Preview Test")
    db.insert_sheet(
        {
            "id": "empty-preview-sheet",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "G-001",
            "sheet_title": "Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "REGULATOR STATION",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    preview = service.preview_manual_response(project["id"], '{"updates":[]}')
    assert preview["valid_recoverable_updates"] == 0
    assert preview["review_coverage_status"] == "not_confirmed"
    try:
        service.import_preview(project["id"], preview["batch_id"])
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected import to reject empty unconfirmed coverage")

    batches = db.list_ai_import_batches(project["id"])
    assert batches[0]["import_status"] == "previewed"
    assert batches[0]["valid_count"] == 0


def test_ai_preview_rejects_missing_target_text_but_imports_valid_updates(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Partial AI Preview Test")
    db.insert_sheet(
        {
            "id": "partial-preview-sheet",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "G-001",
            "sheet_title": "Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "REGULATOR STATION CONTINTUED",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Visible typo",
                        "target_text": "CONTINTUED",
                        "required_update": "Revise CONTINTUED to CONTINUED.",
                        "rationale": "The typo is visible on the attached sheet.",
                        "severity": "Minor",
                        "category": "drafting quality",
                        "confidence": 0.9,
                    },
                    {
                        "page_number": 1,
                        "issue": "Missing anchor",
                        "target_text": "   ",
                        "required_update": "Clarify the note.",
                        "rationale": "This update is missing the exact drawing text anchor.",
                        "severity": "Minor",
                        "category": "drafting quality",
                        "confidence": 0.7,
                    },
                ]
            }
        ),
    )

    assert preview["total_candidate_updates"] == 2
    assert preview["valid_recoverable_updates"] == 1
    assert preview["skipped_updates"] == 1
    rejected = next(update for update in preview["updates"] if not update["will_import"])
    assert rejected["missing_or_weak_fields"] == ["target_text"]
    assert "target_text" in rejected["skipped_reason"]
    assert any("target_text" in warning for warning in preview["warnings"])

    imported = service.import_preview(project["id"], preview["batch_id"])
    findings = db.list_findings(project["id"], sources=["ai"])

    assert imported["ai_updates_imported"] == 1
    assert len(findings) == 1
    assert findings[0]["evidence"][0]["target_text"] == "CONTINTUED"
    batches = db.list_ai_import_batches(project["id"])
    assert batches[0]["import_status"] == "imported"
    assert batches[0]["valid_count"] == 1
    assert batches[0]["skipped_count"] == 1


def test_ai_preview_rejects_structured_evidence_without_string_target_text(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Structured Evidence Preview Test")
    db.insert_sheet(
        {
            "id": "structured-evidence-sheet",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-001",
            "sheet_title": "Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "VERIFY CLEARANCE",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Structured evidence only",
                        "evidence": [{"observation": "Reviewer should not use this dict as target text."}],
                        "required_update": "Clarify the clearance note.",
                        "confidence": 0.7,
                    }
                ],
            }
        ),
    )
    assert preview["valid_recoverable_updates"] == 0

    batch = db.list_ai_import_batches(project["id"])[0]
    skipped = batch["preview"]["updates"][0]
    assert skipped["will_import"] is False
    assert skipped["missing_or_weak_fields"] == ["target_text"]


def test_manual_ai_import_recovers_multiple_malformed_chat_updates(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Multi Loose AI JSON Test")
    for page in [4, 16, 20]:
        db.insert_sheet(
            {
                "id": f"multi-loose-sheet-{page}",
                "project_id": project["id"],
                "page_number": page,
                "drawing_number": f"S-{page}",
                "sheet_title": "Drawing Sheet",
                "revision": "A",
                "sheet_type": "detail",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": "APPROVED PILL RESPONSE PLAN CONTINTUED ENCLOSURE FROM SETLING INSTRUMENT COLUMS",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    response = '''{"reviewed_pages":[{"page_number":4,"review_status":"complete","issue_count":2},{"page_number":16,"review_status":"complete","issue_count":0},{"page_number":20,"review_status":"complete","issue_count":1}],"updates":[
        {"issue":"Spill response plan appears misspelled.","severity":"Major","category":"safety and operability","page_number":4,"target_text":"APPROVED PILL RESPONSE PLAN","required_update":"Revise to "APPROVED SPILL RESPONSE PLAN" unless intentional.","rationale":"Safety note wording appears incorrect.","confidence":0.94},
        {"issue":"Electrical safety heading contains a misspelling.","severity":"Minor","category":"drafting quality","page_number":4,"target_text":"2. ELECTRICAL SAFETY REQUIREMENTS (CONTINTUED):","required_update":"Revise "CONTINTUED" to "CONTINUED".","rationale":"Visible spelling issue.","confidence":0.99},
        {"issue":"Construction note contains misspelled columns.","severity":"Minor","category":"drafting quality","page_number":20,"target_text":"INSTRUMENT COLUMS","required_update":"Revise "COLUMS" to "COLUMNS".","rationale":"Visible spelling issue.","confidence":0.96}
    ]}'''

    result = AIReviewService(db, settings).import_manual_response(project["id"], response)
    findings = db.list_findings(project["id"], sources=["ai"])

    assert result["ai_findings_created"] == 3
    assert len(findings) == 3
    assert {finding["page_number"] for finding in findings} == {4, 20}


def test_manual_ai_import_accepts_page_aliases_and_reports_empty_updates(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Manual AI Alias Test")
    db.insert_sheet(
        {
            "id": "alias-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "A-100",
            "sheet_title": "Plan",
            "revision": "A",
            "sheet_type": "layout",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "VERIFY CLEARANCE",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    result = service.import_manual_response(
        project["id"],
        '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1}],"updates":[{"page":"Page 1","issue":"Clearance note vague","target_text":"VERIFY CLEARANCE","required_update":"Clarify required clearance.","confidence":0.8}]}',
    )

    assert result["ai_findings_created"] == 1

    try:
        service.import_manual_response(project["id"], '{"updates":[]}')
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected empty AI updates to raise a visible error")


def test_manual_ai_import_handles_single_objects_arrays_examples_and_page_strings(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Manual AI Parser Edge Test")
    for page in [1, 16]:
        db.insert_sheet(
            {
                "id": f"parser-sheet-{page}",
                "project_id": project["id"],
                "page_number": page,
                "drawing_number": f"N-{200 + page}",
                "sheet_title": "Parser Sheet",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": "VERIFY CLEARANCE MAOP",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )

    service = AIReviewService(db, settings)
    response = '''
    Example only:
    {"updates":[]}

    Actual JSON:
    {"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":16,"review_status":"complete","issue_count":0}],"updates":{"page":"Drawing N-201, page 1","issue":"Clearance note vague","target_text":"VERIFY CLEARANCE","required_update":"Clarify clearance.","confidence":0.8}}
    '''
    result = service.import_manual_response(project["id"], response)
    assert result["ai_findings_created"] == 1
    assert db.list_findings(project["id"], sources=["ai"])[0]["page_number"] == 1

    array_result = service.import_manual_response(
        project["id"],
        '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":16,"review_status":"complete","issue_count":1}],"updates":[{"pdf_page":"PDF page 16","issue":"MAOP note vague","target_text":"MAOP","required_update":"Add MAOP basis.","confidence":0.8}]}',
    )
    assert array_result["ai_findings_created"] == 1
    assert {finding["page_number"] for finding in db.list_findings(project["id"], sources=["ai"])} == {1, 16}


def test_manual_ai_reimport_preserves_status_but_refreshes_ai_content(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Manual AI Reimport Test")
    db.insert_sheet(
        {
            "id": "reimport-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "N-300",
            "sheet_title": "General Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "VERIFY CLEARANCE",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )

    service = AIReviewService(db, settings)
    service.import_manual_response(
        project["id"],
        '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1}],"updates":[{"page_number":1,"issue":"Old issue wording","severity":"Minor","category":"drafting quality","target_text":"VERIFY CLEARANCE","required_update":"Old update text.","rationale":"Old rationale.","confidence":0.7}]}',
    )
    first = db.list_findings(project["id"], sources=["ai"])[0]
    db.update_finding(first["id"], {"status": "rejected"})

    service.import_manual_response(
        project["id"],
        '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1}],"updates":[{"page_number":1,"issue":"New issue wording","severity":"Major","category":"safety and operability","target_text":"VERIFY CLEARANCE","required_update":"New update text.","rationale":"New rationale.","confidence":0.9}]}',
    )
    findings = db.list_findings(project["id"], sources=["ai"])

    assert len(findings) == 1
    assert findings[0]["id"] == first["id"]
    assert findings[0]["stable_id"] == first["stable_id"]
    assert findings[0]["status"] == "rejected"
    assert findings[0]["title"] == "New issue wording"
    assert findings[0]["severity"] == "Major"
    assert findings[0]["category"] == "safety and operability"
    assert "New update text" in findings[0]["suggested_correction"]
    assert "New rationale" in findings[0]["reasoning_summary"]


def test_ai_import_preserves_non_ai_rows_but_active_routes_ignore_them(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/sample-project").json()

    ai_finding = _finding_record(project["id"], "QC-AI-ACTIVE", source="ai", status="accepted", target_text="REGULATOR STATION")
    rule_finding = _finding_record(project["id"], "QC-RULE-HIDDEN", source="rules", status="accepted", target_text="RULE ONLY")
    main.db.replace_findings(project["id"], [ai_finding, rule_finding])

    assert main.db.get_project(project["id"])["finding_count"] == 1
    assert len(main.db.list_findings(project["id"])) == 2
    assert client.get(f"/projects/{project['id']}").json()["finding_count"] == 1
    assert client.get("/projects").json()[0]["finding_count"] == 1

    listed = client.get(f"/projects/{project['id']}/findings").json()
    assert [finding["stable_id"] for finding in listed] == ["QC-AI-ACTIVE"]

    assert client.patch(f"/findings/{rule_finding['id']}", json={"status": "rejected"}).status_code == 404
    assert client.patch("/findings/bulk", json={"finding_ids": [rule_finding["id"]], "update": {"status": "rejected"}}).status_code == 404
    assert client.delete(f"/findings/{rule_finding['id']}").status_code == 404

    import_response = client.post(
        f"/projects/{project['id']}/ai-review/import",
        json={"response_text": '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":2,"review_status":"complete","issue_count":0},{"page_number":3,"review_status":"complete","issue_count":0},{"page_number":4,"review_status":"complete","issue_count":0},{"page_number":5,"review_status":"complete","issue_count":0}],"updates":[{"page_number":1,"issue":"Imported AI only","target_text":"REGULATOR STATION","required_update":"Clarify note.","confidence":0.8}]}'},
    )
    assert import_response.status_code == 200
    assert any(finding["stable_id"] == "QC-RULE-HIDDEN" for finding in main.db.list_findings(project["id"]))

    export_response = client.post(f"/projects/{project['id']}/exports", json={"statuses": ["accepted", "needs_review"]})
    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["files"]["json"]
    assert str(tmp_path) not in json.dumps(export_payload)
    stored_export = main.db.list_exports(project["id"])[0]
    exported = json.loads(Path(stored_export["json_path"]).read_text(encoding="utf-8"))

    assert exported
    assert all(finding["source"] == "ai" for finding in exported)
    assert "QC-RULE-HIDDEN" not in {finding["stable_id"] for finding in exported}


def test_review_rerun_preserves_status_and_comment_edits(tmp_path: Path) -> None:
    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.sample_pdf import create_sample_pdf
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.pdf_processor import PDFProcessor

    _configure_tmp_env(tmp_path)
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "sample.pdf"
    create_sample_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Rerun Preservation Test", source_pdf)

    first = processor.process_project(project["id"])
    target = first["findings"][0] if first["findings"] else None
    assert target is None

    AIReviewService(db, settings).import_manual_response(
        project["id"],
        '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":2,"review_status":"complete","issue_count":0},{"page_number":3,"review_status":"complete","issue_count":0},{"page_number":4,"review_status":"complete","issue_count":0},{"page_number":5,"review_status":"complete","issue_count":0}],"updates":[{"page_number":1,"issue":"AI rerun preservation","target_text":"REGULATOR STATION","required_update":"Clarify station note.","confidence":0.8}]}',
    )
    imported = db.list_findings(project["id"], sources=["ai"])[0]
    db.update_finding(imported["id"], {"status": "accepted", "comment_text": "Reviewer edited PDF comment."})

    second = processor.process_project(project["id"])
    events = db.list_finding_events(project["id"])
    preserved = db.list_findings(project["id"], sources=["ai"])[0]

    assert len(second["findings"]) == 1
    assert preserved["id"] == imported["id"]
    assert preserved["stable_id"] == imported["stable_id"]
    assert preserved["status"] == "accepted"
    assert preserved["comment_text"] == "Reviewer edited PDF comment."
    assert preserved["source"] == "ai"
    assert db.list_findings(project["id"], sources=["rules"]) == []
    assert not any(event["action"] == "rerun_preserved_review" for event in events)


def test_upload_project_with_pdf_auto_reviews_and_returns_project(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    from backend.app.sample_pdf import create_sample_pdf

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    source_pdf = tmp_path / "upload.pdf"
    create_sample_pdf(source_pdf)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    with source_pdf.open("rb") as handle:
        response = client.post(
            "/projects",
            data={"name": "Uploaded Drawing", "auto_review": "true"},
            files={"file": ("upload.pdf", handle, "application/pdf")},
        )

    assert response.status_code == 200
    project = response.json()
    assert project["status"] == "ready"
    assert project["sheet_count"] >= 1
    assert project["finding_count"] == 0

    sheets_response = client.get(f"/projects/{project['id']}/sheets")
    assert sheets_response.status_code == 200
    assert sheets_response.json()


def test_upload_project_rejects_non_pdf_without_500(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    response = client.post(
        "/projects",
        data={"name": "Bad Upload", "auto_review": "true"},
        files={"file": ("bad.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file must be a PDF drawing set."

    fake_pdf_response = client.post(
        "/projects",
        data={"name": "Fake PDF Upload", "auto_review": "false"},
        files={"file": ("fake.pdf", b"%PDF-1.7\nthis is not a readable pdf", "application/pdf")},
    )

    assert fake_pdf_response.status_code == 400
    assert "valid PDF drawing set" in fake_pdf_response.json()["detail"]


def test_upload_routes_enforce_size_limits_before_processing(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    monkeypatch.setenv("AUTOQC_MAX_UPLOAD_MB", "1")
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    oversized_pdf = b"%PDF-1.7\n" + (b"x" * (1024 * 1024 + 1))
    pdf_response = client.post(
        "/projects",
        data={"name": "Oversized PDF", "auto_review": "false"},
        files={"file": ("oversized.pdf", oversized_pdf, "application/pdf")},
    )
    assert pdf_response.status_code == 413
    assert "exceeds 1 MB limit" in pdf_response.json()["detail"]

    monkeypatch.setattr(main, "PACKAGE_UPLOAD_MAX_BYTES", 16)
    package_response = client.post(
        "/project-packages/import/preview",
        files={"file": ("oversized.zip", b"x" * 32, "application/zip")},
    )
    assert package_response.status_code == 413
    assert "Project package upload exceeds" in package_response.json()["detail"]


def test_export_endpoint_accepts_status_body_and_returns_file_links(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    project_response = client.post("/sample-project")
    assert project_response.status_code == 200
    project = project_response.json()
    import_response = client.post(
        f"/projects/{project['id']}/ai-review/import",
        json={"response_text": '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":2,"review_status":"complete","issue_count":0},{"page_number":3,"review_status":"complete","issue_count":0},{"page_number":4,"review_status":"complete","issue_count":0},{"page_number":5,"review_status":"complete","issue_count":0}],"updates":[{"page_number":1,"issue":"AI export test","target_text":"REGULATOR STATION","required_update":"Clarify station note.","confidence":0.8}]}'},
    )
    assert import_response.status_code == 200

    findings_response = client.get(f"/projects/{project['id']}/findings")
    assert findings_response.status_code == 200
    findings = findings_response.json()
    assert findings

    target = findings[0]
    patch_response = client.patch(f"/findings/{target['id']}", json={"status": "needs_review"})
    assert patch_response.status_code == 200

    export_response = client.post(
        f"/projects/{project['id']}/exports",
        json={"statuses": ["needs_review"]},
    )
    assert export_response.status_code == 200
    payload = export_response.json()

    assert payload["findings_exported"] >= 1
    assert payload["files"]["marked_pdf"]
    assert payload["files"]["json"]
    assert payload["files"]["html"]
    assert payload["export"]["export_dir"] is None
    assert payload["export"]["marked_pdf_path"] == payload["files"]["marked_pdf"]
    assert str(tmp_path) not in json.dumps(payload)

    package_response = client.post(f"/projects/{project['id']}/project-package")
    assert package_response.status_code == 200
    package_payload = package_response.json()
    assert package_payload["path"] is None
    assert package_payload["download_url"]
    assert str(tmp_path) not in json.dumps(package_payload)

    events_response = client.get(f"/projects/{project['id']}/events")
    assert events_response.status_code == 200
    assert str(tmp_path) not in json.dumps(events_response.json())


def test_bulk_update_endpoint_updates_findings_and_records_events(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    project = client.post("/sample-project").json()
    import_response = client.post(
        f"/projects/{project['id']}/ai-review/import",
        json={"response_text": '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":2,"review_status":"complete","issue_count":1},{"page_number":3,"review_status":"complete","issue_count":0},{"page_number":4,"review_status":"complete","issue_count":0},{"page_number":5,"review_status":"complete","issue_count":0}],"updates":[{"page_number":1,"issue":"AI bulk test 1","target_text":"REGULATOR STATION","required_update":"Clarify station note.","confidence":0.8},{"page_number":2,"issue":"AI bulk test 2","target_text":"MAOP","required_update":"Verify MAOP note.","confidence":0.8}]}'},
    )
    assert import_response.status_code == 200
    findings = client.get(f"/projects/{project['id']}/findings").json()
    target_ids = [finding["id"] for finding in findings[:2]]

    response = client.patch("/findings/bulk", json={"finding_ids": target_ids, "update": {"status": "rejected"}})
    assert response.status_code == 200
    payload = response.json()

    assert payload["count"] == len(target_ids)
    assert {item["status"] for item in payload["updated"]} == {"rejected"}

    events_response = client.get(f"/projects/{project['id']}/events")
    assert events_response.status_code == 200
    assert any(event["action"] == "bulk_update" for event in events_response.json())


def test_finding_normalizer_clamps_status_comment_and_enum_severity() -> None:
    from backend.app.models import FindingStatus, Severity
    from backend.app.services.reasoning.engine import CandidateFinding
    from backend.app.services.reasoning.normalizer import normalize_candidate

    candidate = CandidateFinding(
        rule_id="normalizer.test",
        title="Normalizer check",
        category="drafting quality",
        severity=Severity.MAJOR,
        confidence=1.25,
        sheet_id="sheet-1",
        page_number=3,
        evidence=[{"observation": "Observed normalization behavior."}],
        reasoning_summary="Reasoning",
        suggested_correction="Correction",
        comment_text=(" Confirm   spacing and truncation.\n" * 30),
        involved_entities=["b", "a"],
    )

    first = normalize_candidate("project", candidate)
    second = normalize_candidate("project", candidate)

    assert first["stable_id"] == second["stable_id"]
    assert first["severity"] == Severity.MAJOR.value
    assert type(first["severity"]) is str
    assert first["confidence"] == 0.98
    assert first["status"] == FindingStatus.ACCEPTED.value
    assert len(first["comment_text"]) <= 360
    assert "  " not in first["comment_text"]


def test_reasoning_normalization_dedupes_candidates() -> None:
    from backend.app.models import FindingStatus, Severity
    from backend.app.services.reasoning.engine import CandidateFinding, ReasoningEngine

    first = CandidateFinding(
        rule_id="drafting.same",
        title="Repeated tag appears on sheet",
        category="drafting quality",
        severity=Severity.MINOR,
        confidence=0.64,
        sheet_id="sheet-1",
        page_number=1,
        evidence=[{"observation": "First observation."}],
        reasoning_summary="First",
        suggested_correction="Verify tag.",
        comment_text=" Verify   duplicate tag. ",
    )
    second = CandidateFinding(
        rule_id="drafting.same.again",
        title="Repeated tag appears on sheet",
        category="drafting quality",
        severity=Severity.MAJOR,
        confidence=0.9,
        sheet_id="sheet-1",
        page_number=1,
        evidence=[{"observation": "Second observation."}],
        reasoning_summary="Second",
        suggested_correction="Verify tag.",
        comment_text="Verify duplicate tag.",
    )

    findings = ReasoningEngine()._normalize_and_dedupe("project", [first, second])

    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == Severity.MAJOR.value
    assert type(finding["severity"]) is str
    assert finding["confidence"] == 0.9
    assert finding["status"] == FindingStatus.ACCEPTED.value
    assert finding["comment_text"] == "Verify duplicate tag."
    assert {item["observation"] for item in finding["evidence"]} == {"First observation.", "Second observation."}


def test_reasoning_flags_text_action_items_from_nicor_example() -> None:
    from backend.app.services.reasoning import ReasoningEngine

    sheets = [
        {
            "id": "comed-notes",
            "project_id": "project",
            "page_number": 4,
            "drawing_number": "E1924B-4",
            "sheet_title": "ComEd Notes",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "text_content": """
            ELECTRICAL SAFETY REQUIREMENTS (CONTINTUED)
            NO HAZARDOUS MATERIALS MAY BE STORED, USED FOR TRANSFERRED ON COMED PROPERTY.
            APPROVED PILL RESPONSE PLAN. GROUND CLEARANCE POSSES A SAFETY HAZARD.
            NICOR SHALL NOTIFY COMED A MINIMUM OF 4-WEEK PRIOR TO COMMENCING WORK.
            1.1. IF FOR ANY REASON NICOR SHALL CONTACT COMED.
            1.1. ANY AND ALL DRAIN TILES ENCOUNTERED DURING CONSTRUCTION SHALL BE REPAIRED.
            """,
        }
    ]

    findings = ReasoningEngine().review_project("project", sheets, [])
    titles = {finding["title"] for finding in findings}
    evidence_markup = [
        evidence.get("markup_text")
        for finding in findings
        for evidence in finding.get("evidence", [])
        if isinstance(evidence, dict)
    ]

    assert "Misspelling in note heading" in titles
    assert "Likely missing leading letter in spill-response note" in titles
    assert "Awkward or incorrect wording in material handling note" in titles
    assert "Likely typo in clearance hazard note" in titles
    assert "Grammar issue in notice requirement" in titles
    assert "Duplicate note section number on sheet" in titles
    assert "CONTINTUED" in evidence_markup


def test_pdf_export_rejects_empty_infinite_and_offpage_rects() -> None:
    from backend.app.services.exports import _safe_annotation_rect

    page_bounds = fitz.Rect(0, 0, 200, 100)

    assert _safe_annotation_rect(fitz.Rect(0, 0, 0, 0), page_bounds) is None
    assert _safe_annotation_rect(fitz.Rect(float("inf"), 0, 10, 10), page_bounds) is None
    assert _safe_annotation_rect(fitz.Rect(300, 300, 320, 320), page_bounds) is None

    clipped = _safe_annotation_rect(fitz.Rect(-20, -20, 20, 20), page_bounds)
    assert clipped is not None
    assert clipped.x0 >= page_bounds.x0
    assert clipped.y0 >= page_bounds.y0
    assert clipped.x1 <= page_bounds.x1
    assert clipped.y1 <= page_bounds.y1


def test_marked_pdf_export_survives_bad_rectangles(tmp_path: Path) -> None:
    from backend.app.services.exports import ExportService

    source_pdf = tmp_path / "source.pdf"
    target_pdf = tmp_path / "marked.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ELECTRICAL SAFETY REQUIREMENTS (CONTINTUED)")
    doc.save(source_pdf)
    doc.close()

    findings = [
        {
            "stable_id": "QC-EMPTY",
            "comment_text": "Empty rectangle should fall back to a page note.",
            "severity": "Minor",
            "category": "drafting quality",
            "page_number": 1,
            "location": {"x0": 10, "y0": 10, "x1": 10, "y1": 10},
            "evidence": [],
        },
        {
            "stable_id": "QC-INFINITE",
            "comment_text": "Infinite rectangle should fall back to a page note.",
            "severity": "Minor",
            "category": "drafting quality",
            "page_number": 1,
            "location": [float("inf"), 0, 20, 20],
            "evidence": [],
        },
        {
            "stable_id": "QC-SEARCH",
            "comment_text": "Search rectangle should be sanitized before annotation.",
            "severity": "Minor",
            "category": "drafting quality",
            "page_number": 1,
            "location": None,
            "evidence": [{"markup_text": "CONTINTUED", "text_excerpt": "SAFETY REQUIREMENTS (CONTINTUED)"}],
        },
    ]

    ExportService.__new__(ExportService)._write_marked_pdf(source_pdf, target_pdf, findings)

    assert target_pdf.exists()
    with fitz.open(target_pdf) as marked:
        page = marked[0]
        annotation_count = sum(1 for _ in (page.annots() or []))
    assert annotation_count >= 3


def test_pdf_export_searches_evidence_text_for_markup_rect(tmp_path: Path) -> None:
    from backend.app.services.exports import _evidence_search_rect

    pdf_path = tmp_path / "text-action.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ELECTRICAL SAFETY REQUIREMENTS (CONTINTUED)")
    doc.save(pdf_path)
    doc.close()

    with fitz.open(pdf_path) as check_doc:
        rect = _evidence_search_rect(
            check_doc[0],
            {"evidence": [{"markup_text": "CONTINTUED", "text_excerpt": "SAFETY REQUIREMENTS (CONTINTUED)"}]},
        )

    assert rect is not None
    assert rect.width > 0
    assert rect.height > 0


def test_edited_ai_finding_fields_persist_and_drive_export_register(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "synthetic-gas.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Editable AI Export Test", source_pdf)
    processor.process_project(project["id"])

    AIReviewService(db, settings).import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Original AI issue",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Original AI update.",
                        "rationale": "Original AI rationale.",
                        "category": "drafting quality",
                        "severity": "Minor",
                        "confidence": 0.8,
                    }
                ]
            }
        ),
    )
    finding = db.list_findings(project["id"], sources=["ai"])[0]
    updated = db.update_finding(
        finding["id"],
        {
            "status": "accepted",
            "page_number": 1,
            "target_text": "REGULATOR STATION",
            "comment_text": "Reviewer final PDF comment.",
            "required_update": "Reviewer required update.",
            "rationale": "Reviewer rationale for export.",
            "category": "notes and specifications",
            "severity": "Major",
            "reviewer_note": "Internal reviewer note.",
        },
    )

    assert updated["status"] == "accepted"
    assert updated["suggested_correction"] == "Reviewer required update."
    assert updated["reasoning_summary"] == "Reviewer rationale for export."
    assert updated["reviewer_note"] == "Internal reviewer note."
    assert updated["original_ai_json"]["issue"] == "Original AI issue"

    export = ExportService(db, settings.data_dir).export_project(project["id"])
    exported = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    assert exported[0]["comment_text"] == "Reviewer final PDF comment."
    assert exported[0]["suggested_correction"] == "Reviewer required update."
    assert exported[0]["reasoning_summary"] == "Reviewer rationale for export."
    assert exported[0]["placement_status"] == "exact_target_found"
    assert export["placement_summary"]["target_cloud_created"] == 1
    assert export["placement_summary"]["cloud_plus_note"] == 1

    with fitz.open(Path(export["export"]["marked_pdf_path"])) as marked_doc:
        page = marked_doc[0]
        annotation_types = [annot.type[1] for annot in page.annots() or []]
        assert len(annotation_types) >= 2
        assert "Square" in annotation_types
        assert "Text" in annotation_types

    with Path(export["export"]["qa_report_path"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["final_exported_comment"] == "Reviewer final PDF comment."
    assert rows[0]["required_update"] == "Reviewer required update."
    assert rows[0]["rationale"] == "Reviewer rationale for export."
    assert rows[0]["reviewer_note"] == "Internal reviewer note."
    assert rows[0]["placement_status"] == "exact_target_found"
    assert rows[0]["target_text_found"] == "True"


def test_export_records_fuzzy_and_page_level_placement_without_crashing(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "synthetic-gas.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Placement Export Test", source_pdf)
    processor.process_project(project["id"])

    ai_service = AIReviewService(db, settings)
    ai_service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1, 2: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Fuzzy inch mark target",
                        "target_text": '12" Inlet Valve',
                        "required_update": "Confirm inch mark notation.",
                        "rationale": "Target text has inch-mark punctuation not present in the extracted PDF text.",
                        "category": "drafting quality",
                        "severity": "Minor",
                        "confidence": 0.8,
                    },
                    {
                        "page_number": 2,
                        "issue": "Missing target",
                        "target_text": "NOT PRESENT TARGET TEXT",
                        "required_update": "Add missing note if confirmed.",
                        "rationale": "This should fall back to a page-level note.",
                        "category": "human review needed",
                        "severity": "Note",
                        "confidence": 0.55,
                    },
                ]
            }
        ),
    )
    placement_refresh = ai_service.recalculate_finding_locations(project["id"])
    assert placement_refresh["summary"]["fuzzy_target_found"] == 1
    assert placement_refresh["summary"]["page_level_fallback"] == 1
    for finding in db.list_findings(project["id"], sources=["ai"]):
        db.update_finding(finding["id"], {"status": "accepted"})

    export = ExportService(db, settings.data_dir).export_project(project["id"])
    assert export["placement_summary"]["fuzzy_target_found"] == 1
    assert export["placement_summary"]["page_level_fallback"] == 1
    assert export["placement_summary"]["target_cloud_created"] == 1
    assert export["placement_summary"]["cloud_plus_note"] == 1
    assert export["placement_summary"]["sticky_note_fallback"] == 1
    marked_pdf = Path(export["export"]["marked_pdf_path"])
    assert marked_pdf.exists()

    exported = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    statuses = {finding["title"]: finding["placement_status"] for finding in exported}
    assert statuses["Fuzzy inch mark target"] == "fuzzy_target_found"
    assert statuses["Missing target"] == "page_level_fallback"

    with Path(export["export"]["qa_report_path"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_title = {row["rationale"]: row for row in rows}
    missing_row = by_title["This should fall back to a page-level note."]
    assert missing_row["target_text_found"] == "False"
    assert missing_row["manual_placement_needed"] == "True"
    assert missing_row["finding_exported"] == "True"


def test_rotated_pdf_placement_stores_display_rect_for_viewer_focus(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "rotated-gas.pdf"
    _create_rotated_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Rotated Placement Test", source_pdf)
    processor.process_project(project["id"])

    sheet = db.list_sheets(project["id"])[0]
    assert sheet["rotation"] == 270
    assert sheet["width"] == 302
    assert sheet["height"] == 216
    assert sheet["source_width"] == 216
    assert sheet["source_height"] == 302

    ai_service = AIReviewService(db, settings)
    ai_service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Rotated target",
                        "target_text": "ROTATED TARGET NOTE",
                        "required_update": "Verify rotated placement.",
                        "rationale": "The target text is on a rotated source page.",
                        "category": "drafting quality",
                        "severity": "Minor",
                        "confidence": 0.8,
                    }
                ]
            }
        ),
    )
    placement_refresh = ai_service.recalculate_finding_locations(project["id"])
    assert placement_refresh["summary"]["exact_target_found"] == 1
    finding = db.list_findings(project["id"], sources=["ai"])[0]
    details = finding["placement_details"]
    assert details["page_rotation"] == 270
    assert details["source_width"] == 216
    assert details["source_height"] == 302
    assert details["display_rect_json"] != details["rect_json"]
    display_x0, display_y0, display_x1, display_y1 = details["display_rect_json"]
    assert 0 <= display_x0 < display_x1 <= sheet["width"]
    assert 0 <= display_y0 < display_y1 <= sheet["height"]

    db.update_finding(finding["id"], {"status": "accepted"})
    export = ExportService(db, settings.data_dir).export_project(project["id"])
    assert export["placement_summary"]["exact_target_found"] == 1
    exported = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    assert exported[0]["placement_details"]["display_rect_json"] == details["display_rect_json"]


def test_pdf_ingestion_reasoning_and_export(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.sample_pdf import create_sample_pdf
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()

    source_pdf = tmp_path / "sample.pdf"
    create_sample_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Pipeline Test", source_pdf)
    result = processor.process_project(project["id"])

    assert len(result["sheets"]) == 5
    assert result["findings"] == []
    from backend.app.services.ai_review import AIReviewService

    AIReviewService(db, settings).import_manual_response(
        project["id"],
        json.dumps({"reviewed_pages": _reviewed_pages(1, 2, 3, 4, 5, issue_counts={1: 1}), "updates": [{"page_number": 1, "issue": "AI pipeline export", "target_text": "REGULATOR STATION", "required_update": "Clarify station note.", "confidence": 0.8}]}),
    )

    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["needs_review"])
    marked_pdf = Path(export["export"]["marked_pdf_path"])
    assert marked_pdf.exists()
    assert Path(export["export"]["csv_path"]).exists()
    assert Path(export["export"]["xlsx_path"]).exists()
    assert Path(export["export"]["json_path"]).exists()
    assert Path(export["export"]["summary_path"]).exists()

    exported_findings = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    assert exported_findings
    assert all(item["status"] == "needs_review" for item in exported_findings)

    with Path(export["export"]["csv_path"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(exported_findings)
    assert {"finding_id", "severity", "category", "target_text", "comment"}.issubset(rows[0])
    assert rows[0]["target_text"]

    with fitz.open(marked_pdf) as doc:
        annotation_count = 0
        annotation_types: set[str] = set()
        for page in doc:
            for annot in page.annots() or []:
                annotation_count += 1
                annotation_types.add(annot.type[1])
    assert annotation_count >= len(exported_findings)
    assert "Text" in annotation_types
    assert "Square" in annotation_types


def test_health_ai_status_entities_and_source_pdf_endpoints(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    monkeypatch.delenv("AUTOQC_AI_API_KEY", raising=False)
    monkeypatch.delenv("AUTOQC_AI_MODEL", raising=False)
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    ai_status = client.get("/ai/status")
    assert ai_status.status_code == 200
    assert ai_status.json()["configured"] is False

    project_response = client.post("/sample-project")
    assert project_response.status_code == 200
    project = project_response.json()

    entities_response = client.get(f"/projects/{project['id']}/entities")
    assert entities_response.status_code == 200
    assert isinstance(entities_response.json(), list)

    source_pdf_response = client.get(f"/projects/{project['id']}/source-pdf")
    assert source_pdf_response.status_code == 200
    assert source_pdf_response.headers["content-type"].startswith("application/pdf")
    assert source_pdf_response.content.startswith(b"%PDF")

    missing_source_response = client.get("/projects/not-a-real-project/source-pdf")
    assert missing_source_response.status_code == 404


def test_api_invalid_ids_payload_limits_and_empty_export_errors(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    from backend.app.models import MAX_AI_RESPONSE_CHARS

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    missing_project_routes = [
        ("GET", "/projects/not-a-project"),
        ("GET", "/projects/not-a-project/sheets"),
        ("GET", "/projects/not-a-project/findings"),
        ("GET", "/projects/not-a-project/entities"),
        ("GET", "/projects/not-a-project/events"),
        ("GET", "/projects/not-a-project/ai-review/manual-prompt"),
        ("GET", "/projects/not-a-project/ai-review/import-batches"),
        ("POST", "/projects/not-a-project/ai-review/preview"),
        ("POST", "/projects/not-a-project/exports"),
    ]
    for method, route in missing_project_routes:
        if method == "GET":
            response = client.get(route)
        elif route.endswith("/preview"):
            response = client.post(route, json={"response_text": '{"updates":[]}'})
        else:
            response = client.post(route, json={"statuses": ["accepted"]})
        assert response.status_code == 404
        assert "Project not found" in response.text

    assert client.patch("/findings/not-a-finding", json={"status": "accepted"}).status_code == 404
    assert client.delete("/findings/not-a-finding").status_code == 404
    assert client.patch("/findings/bulk", json={"finding_ids": ["not-a-finding"], "update": {"status": "accepted"}}).status_code == 404

    project_response = client.post("/sample-project")
    assert project_response.status_code == 200
    project = project_response.json()

    empty_export = client.post(f"/projects/{project['id']}/exports", json={"statuses": ["accepted"]})
    assert empty_export.status_code == 400
    assert "No AI findings match" in empty_export.text

    empty_statuses_export = client.post(f"/projects/{project['id']}/exports", json={"statuses": []})
    assert empty_statuses_export.status_code == 422

    too_large_preview = client.post(
        f"/projects/{project['id']}/ai-review/preview",
        json={"response_text": "x" * (MAX_AI_RESPONSE_CHARS + 1)},
    )
    assert too_large_preview.status_code == 422
    assert "String should have at most" in too_large_preview.text

    missing_preview = client.post(
        f"/projects/{project['id']}/ai-review/import",
        json={"preview_id": "not-a-preview"},
    )
    assert missing_preview.status_code == 400
    assert "AI import preview not found" in missing_preview.text

    preview_response = client.post(
        f"/projects/{project['id']}/ai-review/preview",
        json={
            "response_text": '{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":1},{"page_number":2,"review_status":"complete","issue_count":0},{"page_number":3,"review_status":"complete","issue_count":0},{"page_number":4,"review_status":"complete","issue_count":0},{"page_number":5,"review_status":"complete","issue_count":0}],"updates":[{"page_number":1,"issue":"Replay test","target_text":"REGULATOR STATION","required_update":"Clarify station note.","confidence":0.8}]}'
        },
    )
    assert preview_response.status_code == 200
    preview_id = preview_response.json()["batch_id"]
    first_import = client.post(f"/projects/{project['id']}/ai-review/import", json={"preview_id": preview_id})
    assert first_import.status_code == 200
    replay_import = client.post(f"/projects/{project['id']}/ai-review/import", json={"preview_id": preview_id})
    assert replay_import.status_code == 400
    assert "run Preview AI Updates again" in replay_import.text


def test_upload_filename_and_source_pdf_serving_are_path_safe(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)

    source_pdf = tmp_path / "synthetic-gas.pdf"
    _create_synthetic_gas_pdf(source_pdf)

    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)
    with source_pdf.open("rb") as handle:
        project_response = client.post(
            "/projects",
            data={"name": "Unsafe Filename Package", "auto_review": "true"},
            files={"file": ("..\\..\\evil.pdf", handle, "application/pdf")},
        )

    assert project_response.status_code == 200
    project = project_response.json()
    project_dir = (tmp_path / "data" / "projects" / project["id"]).resolve()
    assert project["source_pdf_path"] is None
    assert project["source_pdf_url"] == f"/projects/{project['id']}/source-pdf"
    stored_project = main.db.get_project(project["id"])
    source_path = Path(stored_project["source_pdf_path"]).resolve()
    assert source_path.name == ".._.._evil.pdf"
    source_path.relative_to(project_dir / "input")
    assert client.get(f"/projects/{project['id']}/source-pdf").status_code == 200
    sheets = client.get(f"/projects/{project['id']}/sheets").json()
    image_response = client.get(sheets[0]["image_url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert client.get("/data/autoqc.sqlite").status_code == 404
    assert client.get(f"/data/projects/{project['id']}/input/{source_path.name}").status_code == 404

    outside_pdf = tmp_path / "outside.pdf"
    _create_synthetic_gas_pdf(outside_pdf)
    unsafe_project = main.db.create_project("Unsafe Source PDF", str(outside_pdf))

    unsafe_source_response = client.get(f"/projects/{unsafe_project['id']}/source-pdf")
    assert unsafe_source_response.status_code == 404
    assert "Source PDF not found" in unsafe_source_response.text
    try:
        main.processor.process_project(unsafe_project["id"])
    except ValueError as exc:
        assert "outside the project input directory" in str(exc)
    else:
        raise AssertionError("Expected processing an unsafe source path to fail")

    try:
        main.export_service.export_project(unsafe_project["id"], statuses=["accepted"])
    except ValueError as exc:
        assert "outside the project input directory" in str(exc)
    else:
        raise AssertionError("Expected exporting an unsafe source path to fail")


def test_project_package_export_import_roundtrip_remaps_on_collision(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor
    from backend.app.services.project_packages import ProjectPackageService

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "roundtrip.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Package Roundtrip", source_pdf)
    processor.process_project(project["id"])

    ai_service = AIReviewService(db, settings)
    ai_service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "schema_version": "autoqc-ai-updates-v1",
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Package test finding",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Clarify package roundtrip note.",
                        "rationale": "Roundtrip coverage.",
                        "confidence": 0.82,
                    }
                ],
            }
        ),
    )
    finding = db.list_findings(project["id"], sources=["ai"])[0]
    db.update_finding(finding["id"], {"status": "accepted", "reviewer_note": "Keep this edit."})
    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"])
    assert export["validation"]["status"] in {"passed", "warning"}
    export_event = next(event for event in db.list_finding_events(project["id"]) if event["action"] == "export_created")
    assert "export_dir" not in export_event["changes"]
    assert str(settings.data_dir) not in json.dumps(export_event["changes"])
    db.insert_project_event(
        project["id"],
        "legacy_path_event",
        {
            "export_dir": str(settings.data_dir / "projects" / project["id"] / "exports" / "legacy"),
            "nested": {"source_pdf_path": str(source_pdf)},
        },
    )

    package_service = ProjectPackageService(db, settings.data_dir)
    package = package_service.export_project_package(project["id"])
    package_event = next(event for event in db.list_finding_events(project["id"]) if event["action"] == "project_package_exported")
    assert package_event["changes"]["package_filename"] == package["filename"]
    assert "package_path" not in package_event["changes"]
    assert str(settings.data_dir) not in json.dumps(package_event["changes"])
    with zipfile.ZipFile(Path(package["path"])) as archive:
        packaged_payload = json.loads(archive.read("project.json").decode("utf-8"))
    assert packaged_payload["project"]["source_pdf_path"] is None
    assert all(sheet.get("image_path") is None for sheet in packaged_payload["sheets"])
    assert all(export_record.get("marked_pdf_path") is None for export_record in packaged_payload["exports"])
    assert str(settings.data_dir) not in json.dumps(packaged_payload["finding_events"])
    assert str(source_pdf) not in json.dumps(packaged_payload["finding_events"])
    preview = package_service.preview_project_package(Path(package["path"]))
    assert preview["valid"] is True
    assert preview["source_pdf_included"] is True
    assert preview["source_pdf_valid"] is True
    imported = package_service.import_project_package(Path(package["path"]))

    assert imported["original_project_id"] == project["id"]
    assert imported["restored_project_id"] != project["id"]
    restored_id = imported["restored_project_id"]
    assert len(db.list_sheets(restored_id)) == len(db.list_sheets(project["id"]))
    restored_findings = db.list_findings(restored_id, sources=["ai"])
    assert len(restored_findings) == 1
    assert restored_findings[0]["status"] == "accepted"
    assert restored_findings[0]["reviewer_note"] == "Keep this edit."
    assert db.list_ai_import_batches(restored_id)
    assert db.list_exports(restored_id)
    assert any(event["action"] == "project_package_imported" for event in db.list_finding_events(restored_id))


def test_review_coverage_gates_manual_import_scopes_and_clean_pages(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.review_coverage import project_review_coverage_summary

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Coverage Gate Test")
    for page in [1, 2, 3]:
        db.insert_sheet(
            {
                "id": f"coverage-sheet-{page}",
                "project_id": project["id"],
                "page_number": page,
                "drawing_number": f"C-{page}",
                "sheet_title": "Coverage",
                "revision": "A",
                "sheet_type": "notes",
                "extraction_status": "text_extracted",
                "ocr_status": "not_required",
                "image_path": None,
                "text_content": f"TARGET {page}",
                "width": 100.0,
                "height": 100.0,
                "review_status": "ready",
            }
        )
    service = AIReviewService(db, settings)

    clean = service.import_manual_response(project["id"], json.dumps({"reviewed_pages": _reviewed_pages(1, 2, 3), "updates": []}))
    assert clean["ai_updates_imported"] == 0
    assert clean["batch"]["metadata"]["clean_review_pages"] == [1, 2, 3]
    assert project_review_coverage_summary(db.list_sheets(project["id"]), db.list_ai_import_batches(project["id"]))["review_coverage_status"] == "complete"

    skipped_update_clean = service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3),
                "updates": [{"page_number": 2, "issue": "Skipped update without target", "required_update": "Clarify."}],
            }
        ),
    )
    assert skipped_update_clean["ai_updates_imported"] == 0
    assert skipped_update_clean["batch"]["metadata"]["clean_review_pages"] == [1, 3]

    missing_preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "updates": [{"page_number": 1, "issue": "Partial", "target_text": "TARGET 1", "required_update": "Clarify.", "confidence": 0.8}],
            }
        ),
    )
    assert missing_preview["review_coverage_status"] == "incomplete"
    try:
        service.import_preview(project["id"], missing_preview["batch_id"])
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected missing whole-package reviewed_pages to block import")

    batch_prompt = service.generate_manual_prompt(project["id"], review_scope="batch", page_numbers=[1, 2])
    batch_preview = service.preview_manual_response(
        project["id"],
        json.dumps({"reviewed_pages": _reviewed_pages(1), "updates": []}),
        prompt_id=batch_prompt["prompt_id"],
        prompt_version=batch_prompt["prompt_version"],
    )
    assert batch_preview["missing_review_pages"] == [2]
    try:
        service.import_preview(project["id"], batch_preview["batch_id"])
    except ValueError:
        pass
    else:
        raise AssertionError("Expected missing batch page to block import")

    sheet_prompt = service.generate_manual_prompt(project["id"], review_scope="sheet", page_number=2)
    single = service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(2, issue_counts={2: 1}),
                "updates": [{"page_number": 2, "issue": "Single sheet", "target_text": "TARGET 2", "required_update": "Clarify.", "confidence": 0.8}],
            }
        ),
        prompt_id=sheet_prompt["prompt_id"],
        prompt_version=sheet_prompt["prompt_version"],
    )
    assert single["ai_updates_imported"] == 1

    try:
        service.import_manual_response(
            project["id"],
            json.dumps({"updates": [{"page_number": 3, "issue": "No coverage", "target_text": "TARGET 3", "required_update": "Clarify.", "confidence": 0.8}]}),
        )
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected updates without reviewed_pages to block import")


def test_direct_ai_review_is_text_context_only_and_cannot_bypass_coverage(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    class CompleteFakeAI:
        def review(self, payload: dict) -> dict:
            return {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "updates": [{"page_number": 1, "issue": "Direct", "target_text": "TARGET 1", "required_update": "Clarify.", "confidence": 0.8}],
            }

    class IncompleteFakeAI:
        def review(self, payload: dict) -> dict:
            return {
                "updates": [{"page_number": 1, "issue": "Direct", "target_text": "TARGET 1", "required_update": "Clarify.", "confidence": 0.8}],
            }

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Direct AI Coverage Test")
    db.insert_sheet(
        {
            "id": "direct-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "D-1",
            "sheet_title": "Direct",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "TARGET 1",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    result = AIReviewService(db, settings, client=CompleteFakeAI()).review_project(project["id"])
    assert result["direct_review_mode"] == "text_context_only"
    assert result["review_modality"] == "text_context_only"
    batch = db.get_ai_import_batch(result["batch"]["id"], project_id=project["id"])
    assert batch["metadata"]["direct_review_mode"] == "text_context_only"
    assert batch["metadata"]["review_modality"] == "text_context_only"
    assert batch["metadata"]["ai_tool"] == "direct_ai_review"
    assert batch["metadata"]["ai_provider"]
    assert batch["metadata"]["warnings"]
    assert "raw_response_text" not in result["batch"]

    project2 = db.create_project("Direct AI Block Test")
    db.insert_sheet({**db.list_sheets(project["id"])[0], "id": "direct-block-sheet", "project_id": project2["id"]})
    try:
        AIReviewService(db, settings, client=IncompleteFakeAI()).review_project(project2["id"])
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected direct AI review without reviewed_pages to be blocked")

    class CappedFakeAI:
        def review(self, payload: dict) -> dict:
            assert len(payload.get("sheets") or []) == 1
            return {
                "reviewed_pages": _reviewed_pages(1, 2, issue_counts={1: 1}),
                "updates": [{"page_number": 1, "issue": "Capped", "target_text": "TARGET 1", "required_update": "Clarify.", "confidence": 0.8}],
            }

    capped_settings = Settings()
    capped_settings.ai_max_sheets = 1
    capped_settings.ensure_dirs()
    capped_project = db.create_project("Direct AI Capped Test")
    for page in [1, 2]:
        db.insert_sheet({**db.list_sheets(project["id"])[0], "id": f"direct-cap-sheet-{page}", "project_id": capped_project["id"], "page_number": page, "text_content": f"TARGET {page}"})
    capped = AIReviewService(db, capped_settings, client=CappedFakeAI()).review_project(capped_project["id"])
    capped_batch = db.get_ai_import_batch(capped["batch"]["id"], project_id=capped_project["id"])
    assert capped["direct_review_sheet_limit_applied"] is True
    assert capped_batch["metadata"]["direct_review_sent_pages"] == [1]
    assert capped_batch["metadata"]["review_coverage"]["expected_review_pages"] == [1]
    from backend.app.services.review_coverage import project_review_coverage_summary

    package_coverage = project_review_coverage_summary(db.list_sheets(capped_project["id"]), db.list_ai_import_batches(capped_project["id"]))
    assert package_coverage["review_coverage_status"] == "incomplete"
    assert package_coverage["missing_review_pages"] == [2]


def test_raw_ai_response_is_preserved_server_side_but_redacted_from_batch_api(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)
    main = importlib.import_module("backend.app.main")
    client = TestClient(main.app)

    project = main.db.create_project("Raw Response Trace")
    main.db.insert_sheet(
        {
            "id": "raw-response-sheet",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "RAW-1",
            "sheet_title": "Raw",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "RAW TARGET",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    raw_response = '```json\n{"reviewed_pages":[{"page_number":1,"review_status":"complete","issue_count":0}],"updates":[]}\n```'
    preview = client.post(f"/projects/{project['id']}/ai-review/preview", json={"response_text": raw_response}).json()
    assert preview["batch"]["raw_response_stored"] is True
    assert preview["batch"]["raw_response_length"] == len(raw_response)
    assert "raw_response_text" not in preview["batch"]

    stored = main.db.get_ai_import_batch(preview["batch_id"], project_id=project["id"])
    assert stored["raw_response_text"] == raw_response
    assert stored["metadata"]["ai_tool"] == "manual_chat_prompt"
    assert stored["metadata"]["ai_provider"] == "manual_external"
    batches = client.get(f"/projects/{project['id']}/ai-review/import-batches").json()
    assert batches[0]["raw_response_stored"] is True
    assert batches[0]["raw_response_length"] == len(raw_response)
    assert "raw_response_text" not in batches[0]


def test_direct_ai_warning_is_included_in_export_summary(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    class DirectFakeAI:
        def review(self, payload: dict) -> dict:
            return {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [{"page_number": 1, "issue": "Direct export warning", "target_text": "REGULATOR STATION", "required_update": "Clarify station note.", "confidence": 0.8}],
            }

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "direct-warning.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Direct Warning Export", source_pdf)
    processor.process_project(project["id"])
    imported = AIReviewService(db, settings, client=DirectFakeAI()).review_project(project["id"])
    db.update_finding(imported["imported_finding_ids"][0], {"status": "accepted"})
    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"], export_mode="draft")
    summary = Path(export["export"]["summary_path"]).read_text(encoding="utf-8")
    assert "Direct AI Review findings are text-context-only" in summary


def test_final_export_modes_gate_readiness_and_include_signoff(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "final-export.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Final Export Test", source_pdf)
    processor.process_project(project["id"])
    service = AIReviewService(db, settings)
    imported = service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [{"page_number": 1, "issue": "Final export", "target_text": "REGULATOR STATION", "required_update": "Clarify.", "confidence": 0.8}],
            }
        ),
    )
    finding_id = imported["imported_finding_ids"][0]
    draft = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["needs_review"], export_mode="draft", accepted_only=False)
    assert draft["export_mode"] == "draft"
    assert "_draft_" in Path(draft["export"]["marked_pdf_path"]).name

    db.update_finding(finding_id, {"status": "accepted"})
    final = ExportService(db, settings.data_dir).export_project(
        project["id"],
        export_mode="final",
        statuses=["accepted"],
        final_export_confirmed=True,
        reviewer_name="QA Lead",
    )
    assert final["export_mode"] == "final"
    assert "_final_" in Path(final["export"]["marked_pdf_path"]).name
    assert final["signoff"]["reviewer_name"] == "QA Lead"
    assert final["review_coverage"]["review_coverage_status"] == "complete"
    assert "Export validation" in Path(final["export"]["summary_path"]).read_text(encoding="utf-8")

    incomplete_project = db.create_project("Incomplete Final Export")
    processor.copy_sample_pdf(incomplete_project["id"], source_pdf)
    processor.process_project(incomplete_project["id"])
    manual_finding = _finding_record(incomplete_project["id"], "manual-final-block", source="ai", status="accepted", target_text="REGULATOR STATION")
    db.replace_findings(incomplete_project["id"], [manual_finding], sources=["ai"])
    try:
        ExportService(db, settings.data_dir).export_project(incomplete_project["id"], export_mode="final", statuses=["accepted"], final_export_confirmed=True)
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected final export to block incomplete coverage")

    db.update_finding_placement(finding_id, "manual_placement_needed", {"placement_status": "manual_placement_needed"})
    try:
        ExportService(db, settings.data_dir).export_project(project["id"], export_mode="final", statuses=["accepted"], final_export_confirmed=True)
    except ValueError as exc:
        assert "manual placement" in str(exc)
    else:
        raise AssertionError("Expected final export to block manual placement needed")


def test_project_package_import_preview_validation_rejects_bad_packages(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.project_packages import ProjectPackageService

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    service = ProjectPackageService(db, settings.data_dir)

    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_text("not zip", encoding="utf-8")
    assert service.preview_project_package(bad_zip)["valid"] is False

    traversal_zip = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal_zip, "w") as archive:
        archive.writestr("../evil.json", "{}")
    traversal = service.preview_project_package(traversal_zip)
    assert traversal["valid"] is False
    assert any("unsafe" in error or "traversal" in error for error in traversal["errors"])

    missing_zip = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing_zip, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "bad"}))
    missing = service.preview_project_package(missing_zip)
    assert missing["valid"] is False
    assert any("project.json" in error for error in missing["errors"])

    invalid_pdf_zip = tmp_path / "invalid-pdf.zip"
    project_payload = {
        "project": {"id": "package-invalid-pdf", "name": "Invalid PDF"},
        "sheets": [],
        "entities": [],
        "findings": [],
        "ai_prompt_runs": [],
        "ai_import_batches": [],
        "finding_events": [],
        "exports": [],
    }
    with zipfile.ZipFile(invalid_pdf_zip, "w") as archive:
        archive.writestr("files/source_pdf/source.pdf", b"not a pdf")
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": "autoqc-project-package-v1",
                    "project_id": "package-invalid-pdf",
                    "project_name": "Invalid PDF",
                    "file_manifest": {"source_pdf": "files/source_pdf/source.pdf", "sheet_images": {}, "exports": {}},
                }
            ),
        )
        archive.writestr("project.json", json.dumps(project_payload))
    invalid_pdf = service.preview_project_package(invalid_pdf_zip)
    assert invalid_pdf["valid"] is False
    assert any("readable PDF" in error for error in invalid_pdf["errors"])

    checksum_zip = tmp_path / "checksum-mismatch.zip"
    checksum_payload = {
        "project": {"id": "package-checksum-mismatch", "name": "Checksum Mismatch"},
        "sheets": [],
        "entities": [],
        "findings": [],
        "ai_prompt_runs": [],
        "ai_import_batches": [],
        "finding_events": [],
        "exports": [],
    }
    with zipfile.ZipFile(checksum_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": "autoqc-project-package-v1",
                    "project_id": "package-checksum-mismatch",
                    "project_name": "Checksum Mismatch",
                    "file_manifest": {"source_pdf": None, "sheet_images": {}, "exports": {}},
                    "checksums": {"project.json": "0" * 64},
                }
            ),
        )
        archive.writestr("project.json", json.dumps(checksum_payload))
    checksum_preview = service.preview_project_package(checksum_zip)
    assert checksum_preview["valid"] is False
    assert any("Checksum mismatch" in error for error in checksum_preview["errors"])

    restore_failure_zip = tmp_path / "restore-failure.zip"
    restore_payload = {
        "project": {"id": "package-restore-failure", "name": "Restore Failure"},
        "sheets": [],
        "entities": [],
        "findings": [],
        "ai_prompt_runs": [],
        "ai_import_batches": [],
        "finding_events": [],
        "exports": [],
    }
    with zipfile.ZipFile(restore_failure_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": "autoqc-project-package-v1",
                    "project_id": "package-restore-failure",
                    "project_name": "Restore Failure",
                    "file_manifest": {"source_pdf": None, "sheet_images": {}, "exports": {}},
                }
            ),
        )
        archive.writestr("project.json", json.dumps(restore_payload))

    def fail_insert(_payload: dict) -> None:
        raise RuntimeError("simulated restore insert failure")

    service._insert_payload = fail_insert  # type: ignore[method-assign]
    try:
        service.import_project_package(restore_failure_zip)
    except RuntimeError as exc:
        assert "simulated restore insert failure" in str(exc)
    else:
        raise AssertionError("Expected simulated restore failure")
    assert not (settings.data_dir / "projects" / "package-restore-failure").exists()
    try:
        db.get_project("package-restore-failure")
    except KeyError:
        pass
    else:
        raise AssertionError("Failed package restore left a project row behind")


def test_legacy_projects_and_packages_with_missing_new_metadata_fail_gracefully(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor
    from backend.app.services.project_packages import ProjectPackageService

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "legacy.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Legacy Metadata Project", source_pdf)
    processor.process_project(project["id"])
    finding = _finding_record(project["id"], "legacy-ai-finding", source="ai", status="accepted", target_text="REGULATOR STATION")
    db.replace_findings(project["id"], [finding], sources=["ai"])
    db.create_ai_import_batch(
        project["id"],
        {
            "source_type": "manual_chat_prompt",
            "prompt_version": "legacy",
            "import_status": "imported",
            "raw_response_text": '{"updates":[]}',
            "preview": {"updates": []},
            "metadata": {},
        },
    )

    draft = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"], export_mode="draft")
    assert draft["export_mode"] == "draft"
    try:
        ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"], export_mode="final", final_export_confirmed=True)
    except ValueError as exc:
        assert "review coverage" in str(exc)
    else:
        raise AssertionError("Expected legacy project final export to fail coverage readiness")

    legacy_package = tmp_path / "legacy-package.zip"
    with zipfile.ZipFile(legacy_package, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": "autoqc-project-package-v1",
                    "project_id": "legacy-package-project",
                    "project_name": "Legacy Package",
                    "file_manifest": {"source_pdf": None, "sheet_images": {}, "exports": {}},
                }
            ),
        )
        archive.writestr("project.json", json.dumps({"project": {"id": "legacy-package-project", "name": "Legacy Package"}}))
    preview = ProjectPackageService(db, settings.data_dir).preview_project_package(legacy_package)
    assert preview["valid"] is True
    assert any("missing optional collection" in warning for warning in preview["warnings"])


def test_readiness_running_health_does_not_report_port_available_checks(tmp_path: Path, monkeypatch) -> None:
    import importlib
    import sys

    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTOQC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOQC_DB_PATH", str(tmp_path / "data" / "autoqc.sqlite"))
    sys.modules.pop("backend.app.main", None)
    sys.modules.pop("backend.app.config", None)
    main = importlib.import_module("backend.app.main")
    payload = TestClient(main.app).get("/readiness").json()
    assert payload["mode"] == "running_app_health"
    assert not any("Port 8000 available" == check["name"] or "Port 5173 available" == check["name"] for check in payload["checks"])


def test_validation_report_writer_creates_json_and_markdown_with_redacted_paths(tmp_path: Path) -> None:
    from scripts.validation_reports import write_validation_report

    data_dir = tmp_path / "data"
    artifact = data_dir / "projects" / "project-1" / "exports" / "marked.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"%PDF-placeholder")

    report = write_validation_report(
        data_dir=data_dir,
        report_name="AutoQC Test Validation",
        status="passed",
        summary="Report writer smoke test.",
        checks=[{"name": "example_check", "passed": True, "detail": "ok"}],
        artifacts={"marked_pdf": artifact},
    )

    json_report = json.loads(Path(report["json"]).read_text(encoding="utf-8"))
    markdown_report = Path(report["markdown"]).read_text(encoding="utf-8")
    assert json_report["artifacts"]["marked_pdf"] == "projects/project-1/exports/marked.pdf"
    assert "PASS: example_check" in markdown_report


def test_gold_corpus_evaluator_reports_review_quality_metrics(tmp_path: Path) -> None:
    from scripts.evaluate_gold_corpus import evaluate_corpus

    corpus = {
        "schema_version": "autoqc-gold-corpus-v2",
        "cases": [
            {
                "case_id": "case-1",
                "expected_findings": [
                    {
                        "page_number": 1,
                        "target_text": "CONTINTUED",
                        "severity": "Minor",
                        "category": "drafting quality",
                        "expected_placement_status": "exact_target_found",
                    },
                    {"page_number": 2, "target_text": "MISSING OPP", "severity": "Major", "category": "overpressure protection"},
                ],
                "known_false_positives": [{"page_number": 3, "target_text": "GENERAL NOTES"}],
                "missed_findings": [{"page_number": 4, "target_text": "UNRESOLVED DETAIL"}],
                "actual_findings": [
                    {
                        "page_number": 1,
                        "target_text": "CONTINTUED",
                        "severity": "Minor",
                        "category": "drafting quality",
                        "placement_status": "exact_target_found",
                        "reviewer_disposition": "accepted",
                        "source_type": "manual_chat_prompt",
                    },
                    {
                        "page_number": 3,
                        "target_text": "GENERAL NOTES",
                        "severity": "Note",
                        "category": "drafting quality",
                        "placement_status": "manual_placement_needed",
                        "reviewer_disposition": "rejected",
                        "source_type": "manual_chat_prompt",
                    },
                    {
                        "page_number": 4,
                        "target_text": "UNRESOLVED DETAIL",
                        "severity": "Minor",
                        "category": "drawing coordination",
                        "placement_status": "page_level_fallback",
                        "reviewer_disposition": "needs_manual_placement",
                        "source_type": "missed_issue_audit",
                        "audit_of_batch_id": "batch-1",
                    },
                ],
            }
        ]
    }
    corpus_path = tmp_path / "gold.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")

    report = evaluate_corpus(corpus_path)

    assert report["case_count"] == 1
    assert report["expected_total"] == 2
    assert report["matched_total"] == 1
    assert report["missed_total"] == 1
    assert report["declared_missed_issue_total"] == 1
    assert report["known_false_positive_total"] == 1
    assert report["recall"] == 0.5
    assert report["precision"] == 0.3333
    assert report["placement_accuracy"] == 1.0
    assert report["reviewer_disposition_totals"]["accepted"] == 1
    assert report["reviewer_disposition_totals"]["rejected"] == 1
    assert report["manual_placement_burden_total"] == 2
    assert report["second_pass_audit_yield_total"] == 1


def test_import_batch_rollback_removes_only_findings_created_by_that_batch(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "rollback.pdf"
    _create_synthetic_gas_pdf(source_pdf)
    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Rollback Batch", source_pdf)
    processor.process_project(project["id"])
    ai_service = AIReviewService(db, settings)

    first = ai_service.import_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Existing issue",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Clarify station heading.",
                        "rationale": "First import.",
                        "confidence": 0.8,
                    }
                ]
            }
        ),
    )
    existing_id = first["imported_finding_ids"][0]
    db.update_finding(existing_id, {"status": "accepted"})

    second_preview = ai_service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, 2, 3, issue_counts={1: 1, 2: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "Existing issue",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Clarify station heading.",
                        "rationale": "Second import updates existing stable ID.",
                        "confidence": 0.81,
                    },
                    {
                        "page_number": 2,
                        "issue": "New rollback issue",
                        "target_text": "CONTINTUED",
                        "required_update": "Correct the typo.",
                        "rationale": "Second import creates this one.",
                        "confidence": 0.9,
                    },
                ]
            }
        ),
    )
    ai_service.import_preview(project["id"], second_preview["batch_id"])
    assert len(db.list_findings(project["id"], sources=["ai"])) == 2

    rollback_preview = db.rollback_import_batch(project["id"], second_preview["batch_id"], confirm=False)
    assert rollback_preview["findings_to_remove"] == 1
    assert rollback_preview["will_delete_unrelated_findings"] is False
    rollback = db.rollback_import_batch(project["id"], second_preview["batch_id"], confirm=True)
    assert rollback["findings_removed"] == 1
    remaining = db.list_findings(project["id"], sources=["ai"])
    assert len(remaining) == 1
    assert remaining[0]["stable_id"] == db.get_finding(existing_id)["stable_id"]
    assert any(event["action"] == "ai_import_batch_rolled_back" for event in db.list_finding_events(project["id"]))


def test_import_failure_after_finding_replace_restores_prior_state(tmp_path: Path, monkeypatch) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Import Failure Recovery")
    db.insert_sheet(
        {
            "id": "failure-recovery-sheet",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "FAIL-1",
            "sheet_title": "Failure Recovery",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "TARGET ONE",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    existing = _finding_record(project["id"], "existing-before-failure", source="ai", status="accepted", target_text="EXISTING TARGET")
    db.replace_findings(project["id"], [existing], sources=["ai"])
    service = AIReviewService(db, settings)
    preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "reviewed_pages": _reviewed_pages(1, issue_counts={1: 1}),
                "updates": [
                    {
                        "page_number": 1,
                        "issue": "New finding that should roll back",
                        "target_text": "TARGET ONE",
                        "required_update": "Clarify target one.",
                        "confidence": 0.8,
                    }
                ],
            }
        ),
    )
    original_update_batch = db.update_ai_import_batch

    def fail_imported_batch(batch_id: str, fields: dict) -> dict:
        if fields.get("import_status") == "imported":
            raise RuntimeError("simulated batch write failure")
        return original_update_batch(batch_id, fields)

    monkeypatch.setattr(db, "update_ai_import_batch", fail_imported_batch)
    try:
        service.import_preview(project["id"], preview["batch_id"])
    except RuntimeError as exc:
        assert "simulated batch write failure" in str(exc)
    else:
        raise AssertionError("Expected simulated import batch write failure")

    restored = db.list_findings(project["id"], sources=["ai"])
    assert [finding["stable_id"] for finding in restored] == ["existing-before-failure"]
    failed_batch = db.get_ai_import_batch(preview["batch_id"], project_id=project["id"])
    assert failed_batch["import_status"] == "failed"
    assert failed_batch["metadata"]["import_failure"]["recovery"] == "restored_prior_ai_findings"
    assert any(event["action"] == "ai_import_failed" for event in db.list_finding_events(project["id"]))


def test_prompt_template_schema_modes_and_duplicate_preview(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Prompt Template Test")
    db.insert_sheet(
        {
            "id": "template-sheet-1",
            "project_id": project["id"],
            "page_number": 1,
            "drawing_number": "G-001",
            "sheet_title": "General",
            "revision": "A",
            "sheet_type": "notes",
            "extraction_status": "text_extracted",
            "ocr_status": "not_required",
            "image_path": None,
            "text_content": "REGULATOR STATION CONTINTUED",
            "width": 100.0,
            "height": 100.0,
            "review_status": "ready",
        }
    )
    service = AIReviewService(db, settings)
    templates = service.list_prompt_templates()
    template_ids = {item["id"] for item in templates}
    assert "xcel-package" in template_ids
    assert "comprehensive" in template_ids

    xcel_template = next(item for item in templates if item["id"] == "xcel-package")
    xcel_prompt = service.generate_manual_prompt(project["id"], template_id=xcel_template["id"])
    xcel_prompt_text = xcel_prompt["prompt"].lower()
    assert xcel_template["name"] in xcel_prompt["prompt"]
    assert "xcel engineering package qc r0" in xcel_prompt_text
    assert "xcel engineering package review requirements" in xcel_prompt_text

    comprehensive_template = next(item for item in templates if item["id"] == "comprehensive")
    comprehensive_prompt = service.generate_manual_prompt(project["id"], template_id=comprehensive_template["id"])
    assert comprehensive_template["name"] in comprehensive_prompt["prompt"]
    comprehensive_prompt_text = comprehensive_prompt["prompt"].lower()
    assert "regulator station" in comprehensive_prompt_text
    assert "xcel engineering package review requirements" in comprehensive_prompt_text
    assert "drawing coordination" in comprehensive_prompt_text
    assert "title block" in comprehensive_prompt_text
    assert "hard no-triage rule" in comprehensive_prompt_text
    assert "incomplete review rule" in comprehensive_prompt_text
    assert "do not triage, sample, skim" in comprehensive_prompt_text
    assert "every sheet must receive the same baseline review method" in comprehensive_prompt_text
    assert "full exhaustive manual-style review could not be completed" in comprehensive_prompt_text
    assert "required response schema" in comprehensive_prompt_text
    assert "standard review" not in comprehensive_prompt_text
    assert "balance coverage and response size" not in comprehensive_prompt_text
    assert "prioritize high-risk sheets" not in comprehensive_prompt_text
    assert comprehensive_prompt_text.count("sample") == comprehensive_prompt_text.count("do not triage, sample, skim")

    template = next(item for item in templates if item["id"] == "drawing-coordination")
    prompt = service.generate_manual_prompt(project["id"], template_id=template["id"])
    assert template["name"] in prompt["prompt"]
    assert prompt["prompt_version"] == template["version"]

    preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            [
                {
                    "page_number": 1,
                    "issue": "Duplicate typo",
                    "target_text": "CONTINTUED",
                    "required_update": "Correct typo.",
                    "rationale": "Visible typo.",
                    "confidence": 0.9,
                },
                {
                    "page_number": 1,
                    "issue": "Duplicate typo",
                    "target_text": "CONTINTUED",
                    "required_update": "Correct typo.",
                    "rationale": "Visible typo repeated.",
                    "confidence": 0.9,
                },
            ]
        ),
        prompt_version=prompt["prompt_version"],
        prompt_id=prompt["prompt_id"],
    )
    assert preview["parser_mode"] == "raw_array"
    assert preview["schema_version"] == "autoqc-ai-updates-v1"
    assert preview["duplicate_updates"] == 1
    assert preview["updates"][1]["duplicate_kind"] == "exact"
    batch = db.get_ai_import_batch(preview["batch_id"], project_id=project["id"])
    assert batch["metadata"]["prompt_template_name"] == template["name"]

    findings_preview = service.preview_manual_response(
        project["id"],
        json.dumps(
            {
                "findings": [
                    {
                        "page_number": 1,
                        "issue": "Findings wrapper",
                        "target_text": "REGULATOR STATION",
                        "required_update": "Clarify heading.",
                        "rationale": "Wrapper shape.",
                        "confidence": 0.8,
                    }
                ]
            }
        ),
    )
    assert findings_preview["parser_mode"] == "findings_wrapper"

    bad_preview = service.preview_manual_response(
        project["id"],
        json.dumps({"reviewed_pages": _reviewed_pages(1), "updates": [{"page_number": 1, "issue": "Bad item", "required_update": "No target."}]}),
    )
    assert bad_preview["valid_recoverable_updates"] == 0
    assert "target_text" in bad_preview["updates"][0]["skipped_reason"]


def test_merge_duplicate_preserves_original_evidence_and_hides_duplicate(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    project = db.create_project("Merge Duplicate Test")
    target = _finding_record(project["id"], "ai-target", source="ai", status="needs_review", target_text="REGULATOR STATION")
    duplicate = _finding_record(project["id"], "ai-duplicate", source="ai", status="needs_review", target_text="REGULATOR STATION GENERAL NOTES")
    db.replace_findings(project["id"], [target, duplicate], sources=["ai"])

    stored = {finding["stable_id"]: finding for finding in db.list_findings(project["id"], sources=["ai"])}
    result = db.merge_finding_into(stored["ai-duplicate"]["id"], stored["ai-target"]["id"])

    assert result["duplicate"]["status"] == "duplicate"
    assert result["duplicate"]["duplicate_of"] == stored["ai-target"]["id"]
    assert any(item.get("source_stable_id") == "ai-duplicate" for item in result["target"]["evidence"])
    actions = {event["action"] for event in db.list_finding_events(project["id"])}
    assert "finding_marked_duplicate" in actions
    assert "finding_merged_duplicate_evidence" in actions


def test_large_wide_package_stress_import_and_export(tmp_path: Path) -> None:
    _configure_tmp_env(tmp_path)

    from backend.app.config import Settings
    from backend.app.database import Database
    from backend.app.services.ai_review import AIReviewService
    from backend.app.services.exports import ExportService
    from backend.app.services.pdf_processor import PDFProcessor

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init_schema()
    source_pdf = tmp_path / "large-wide.pdf"
    doc = fitz.open()
    for page_number in range(1, 13):
        page = doc.new_page(width=1728, height=1116)
        page.insert_text((72, 72), f"DRAWING NO: WIDE-{page_number:03d} REV: A", fontsize=14)
        page.insert_text((72, 104), f"LONG TARGET TEXT PAGE {page_number} REGULATOR STATION COORDINATION NOTE WITH VERY LONG DRAWING NUMBER WIDE-{page_number:03d}-ALPHA-BETA-GAMMA", fontsize=12)
        page.insert_text((72, 136), f"FUZZY ANCHOR PAGE {page_number} PIPE TAG V-{page_number:03d}-A/B/C AND SCADA SIGNAL PT-{page_number:03d}", fontsize=12)
    doc.save(source_pdf)
    doc.close()

    processor = PDFProcessor(db, settings)
    project = _create_project_with_uploaded_pdf(db, processor, "Large Wide Stress", source_pdf)
    processed = processor.process_project(project["id"])
    assert len(processed["sheets"]) == 12
    updates = []
    for page_number in range(1, 13):
        updates.extend(
            [
                {
                    "page_number": page_number,
                    "issue": f"Long target text review {page_number}",
                    "target_text": f"LONG TARGET TEXT PAGE {page_number} REGULATOR STATION COORDINATION NOTE WITH VERY LONG DRAWING NUMBER WIDE-{page_number:03d}-ALPHA-BETA-GAMMA",
                    "required_update": "Confirm the long coordination note remains correct.",
                    "rationale": "Stress test for long target text.",
                    "confidence": 0.8,
                },
                {
                    "page_number": page_number,
                    "issue": f"Fuzzy target review {page_number}",
                    "target_text": f"FUZZY ANCHOR PAGE {page_number} PIPE TAG",
                    "required_update": "Confirm tag coordination.",
                    "rationale": "Stress test for fuzzy target placement.",
                    "confidence": 0.75,
                },
                {
                    "page_number": page_number,
                    "issue": f"Page-level review {page_number}",
                    "target_text": f"NOT PRESENT PAGE LEVEL TARGET {page_number}",
                    "required_update": "Reviewer should manually place if confirmed.",
                    "rationale": "Stress test for page-level fallback.",
                    "confidence": 0.55,
                },
            ]
        )
    imported = AIReviewService(db, settings).import_manual_response(
        project["id"],
        json.dumps({"reviewed_pages": _reviewed_pages(*range(1, 13), issue_counts={page: 3 for page in range(1, 13)}), "updates": updates}),
    )
    assert imported["ai_updates_imported"] == 36
    for finding in db.list_findings(project["id"], sources=["ai"]):
        db.update_finding(finding["id"], {"status": "accepted"})
    export = ExportService(db, settings.data_dir).export_project(project["id"], statuses=["accepted"])
    assert export["findings_exported"] == 36
    assert Path(export["export"]["marked_pdf_path"]).exists()
    assert export["validation"]["source_page_count"] == 12
    assert export["validation"]["marked_page_count"] == 12
    assert export["placement_summary"]["page_level_fallback"] >= 12
