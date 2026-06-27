from __future__ import annotations

import csv
import os
import json
from pathlib import Path

import fitz


def _configure_tmp_env(tmp_path: Path) -> None:
    os.environ["AUTOQC_DATA_DIR"] = str(tmp_path / "data")
    os.environ["AUTOQC_DB_PATH"] = str(tmp_path / "data" / "autoqc.sqlite")


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
    project = db.create_project("Pipeline Test", str(source_pdf))

    processor = PDFProcessor(db, settings)
    result = processor.process_project(project["id"])

    assert len(result["sheets"]) == 5
    assert result["findings"]
    assert any(item["category"] == "tag consistency" for item in result["findings"])

    export = ExportService(db, settings.data_dir).export_project(project["id"])
    marked_pdf = Path(export["export"]["marked_pdf_path"])
    assert marked_pdf.exists()
    assert Path(export["export"]["csv_path"]).exists()
    assert Path(export["export"]["xlsx_path"]).exists()
    assert Path(export["export"]["json_path"]).exists()
    assert Path(export["export"]["summary_path"]).exists()

    exported_findings = json.loads(Path(export["export"]["json_path"]).read_text(encoding="utf-8"))
    assert exported_findings
    assert all(item["status"] == "accepted" for item in exported_findings)

    with Path(export["export"]["csv_path"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(exported_findings)
    assert {"finding_id", "severity", "category", "comment"}.issubset(rows[0])

    with fitz.open(marked_pdf) as doc:
        annotation_count = 0
        for page in doc:
            annotation_count += sum(1 for _ in (page.annots() or []))
    assert annotation_count > 0
