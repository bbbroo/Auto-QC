from __future__ import annotations

from pathlib import Path

import fitz


def create_sample_pdf(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()

    pages = [
        (
            "C-001",
            "Cover Sheet and Drawing Index",
            "0",
            [
                "NATURAL GAS REGULATOR STATION SAMPLE",
                "DRAWING INDEX",
                "PFD-100 Process Flow Diagram",
                "PID-100 Piping and Instrumentation Diagram",
                "L-100 Station Layout",
                "N-100 General Notes",
            ],
        ),
        (
            "PFD-100",
            "Process Flow Diagram - Regulator Station",
            "A",
            [
                'LINE 4"-NG-1001 INLET GAS -> INLET ISOLATION VALVE V-101 -> FILTER FLT-101',
                "WORKER REGULATOR REG-101 -> OUTLET ISOLATION VALVE V-102 -> DOWNSTREAM LINE 4-NG-1002",
                "BYPASS V-150 SHOWN AROUND REGULATOR RUN",
                "PRESSURE GAUGE PI-101 UPSTREAM AND PI-102 DOWNSTREAM",
                "SEE P&ID PID-100 FOR CONTROL DETAILS",
            ],
        ),
        (
            "PID-100",
            "Piping and Instrumentation Diagram - Regulator Station",
            "A",
            [
                'LINE 4"-NG-1001 INLET GAS WITH INLET ISOLATION VALVE V-201',
                "FILTER FLT-101 AND WORKER REGULATOR REG-101",
                "MONITOR REGULATOR MON-101 INDICATED AS OPP METHOD",
                "OUTLET ISOLATION VALVE V-102 TO DOWNSTREAM LINE 4-NG-1002",
                "PRESSURE TRANSMITTER PT-101 AND PRESSURE GAUGE PI-102",
                "SENSING LINE FROM DOWNSTREAM HEADER TO REG-101 PILOT",
                "NOTE: OPP SETPOINT BASIS BY UTILITY STANDARD, VALUE TBD",
            ],
        ),
        (
            "L-100",
            "Station Layout",
            "A",
            [
                "GENERAL ARRANGEMENT PLAN VIEW",
                "INLET ISOLATION AND OUTLET ISOLATION LOCATED AT FENCE LINE",
                "VENT STACK SHOWN NORTH OF REGULATOR SKID",
                "DRAIN DETAIL NOT SHOWN ON THIS LAYOUT",
            ],
        ),
        (
            "N-100",
            "General Notes",
            "UNKNOWN",
            [
                "GENERAL NOTES",
                "VERIFY FINAL MAOP AND OPP SETPOINTS BEFORE ISSUE.",
                "ALL WELDING AND TESTING PER COMPANY SPECIFICATIONS.",
            ],
        ),
    ]

    for index, (drawing_no, title, rev, body_lines) in enumerate(pages, start=1):
        page = doc.new_page(width=792, height=612)
        _draw_border(page)
        page.insert_text((54, 54), "Natural Gas Engineering Copilot - Synthetic Sample", fontsize=12)
        page.insert_text((54, 82), title, fontsize=18)
        y = 130
        for line in body_lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 28
        _draw_title_block(page, drawing_no, title, rev, index, len(pages))
        if "Piping and Instrumentation" in title:
            _draw_simple_pid(page)
        if "Process Flow" in title:
            _draw_simple_pfd(page)

    doc.save(target)
    doc.close()
    return target


def default_sample_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "samples" / "synthetic_regulator_station.pdf"


def ensure_default_sample_pdf() -> Path:
    path = default_sample_path()
    if not path.exists():
        create_sample_pdf(path)
    return path


def _draw_border(page: fitz.Page) -> None:
    page.draw_rect(fitz.Rect(36, 36, 756, 576), color=(0, 0, 0), width=1)


def _draw_title_block(page: fitz.Page, drawing_no: str, title: str, rev: str, page_no: int, total: int) -> None:
    rect = fitz.Rect(430, 500, 756, 576)
    page.draw_rect(rect, color=(0, 0, 0), width=1)
    rows = [
        f"DRAWING NO: {drawing_no}",
        f"SHEET TITLE: {title}",
        f"REV: {rev}",
        "PROJECT NO: SAMPLE-001",
        f"SHEET: {page_no} OF {total}",
    ]
    y = 516
    for row in rows:
        page.insert_text((442, y), row, fontsize=8)
        y += 11


def _draw_simple_pfd(page: fitz.Page) -> None:
    y = 340
    points = [(90, y), (190, y), (290, y), (390, y), (500, y), (620, y)]
    for start, end in zip(points, points[1:]):
        page.draw_line(start, end, color=(0, 0, 0), width=1)
    labels = ["V-101", "FLT-101", "REG-101", "V-102"]
    for x, label in zip([150, 250, 350, 460], labels):
        page.draw_rect(fitz.Rect(x - 28, y - 18, x + 28, y + 18), color=(0, 0, 0), width=1)
        page.insert_text((x - 22, y + 4), label, fontsize=8)
    page.draw_line((250, y + 44), (460, y + 44), color=(0, 0, 0), width=1)
    page.insert_text((330, y + 60), "BYPASS V-150", fontsize=8)


def _draw_simple_pid(page: fitz.Page) -> None:
    y = 350
    page.draw_line((90, y), (650, y), color=(0, 0, 0), width=1)
    labels = ["V-201", "FLT-101", "REG-101", "MON-101", "V-102", "PT-101", "PI-102"]
    x = 115
    for label in labels:
        page.draw_rect(fitz.Rect(x - 24, y - 18, x + 24, y + 18), color=(0, 0, 0), width=1)
        page.insert_text((x - 20, y + 4), label, fontsize=7.5)
        x += 76
    page.draw_line((360, y), (360, y + 65), color=(0, 0, 0), width=0.8)
    page.insert_text((370, y + 62), "SENSING LINE", fontsize=8)

