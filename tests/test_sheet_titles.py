from __future__ import annotations

from backend.app.services.classifier import TitleCandidate, extract_title_block, is_sane_sheet_title


def test_sheet_title_candidates_rank_metadata_adjacent_sources() -> None:
    block = extract_title_block(
        "DRAWING NO: EP312 REV: A",
        1,
        [
            TitleCandidate("PDF Package", "pdf_metadata", 0.42),
            TitleCandidate("Regulator Station Diagram", "bookmark", 0.82),
        ],
    )

    assert block.sheet_title == "Regulator Station Diagram"
    assert block.sheet_title_source == "bookmark"


def test_sheet_title_accepts_page_label_when_visible_title_is_missing() -> None:
    block = extract_title_block(
        "DRAWING NO: EP313 REV: A",
        2,
        [TitleCandidate("Meter Station Plan", "page_label", 0.56)],
    )

    assert block.sheet_title == "Meter Station Plan"
    assert block.sheet_title_source == "page_label"


def test_sheet_title_accepts_single_page_pdf_metadata_title() -> None:
    block = extract_title_block(
        "DRAWING NO: EP314 REV: A",
        1,
        [TitleCandidate("Regulator Station Details", "pdf_metadata", 0.66)],
    )

    assert block.sheet_title == "Regulator Station Details"
    assert block.sheet_title_source == "pdf_metadata"


def test_sheet_title_rejects_noisy_repeated_table_text() -> None:
    noisy = "BILL BILL " + "P&ID " * 6 + "CIVIL CIVIL FUEL BILL BILL HEAT AND"
    block = extract_title_block(
        f"DRAWING NO: EP312 REV: A\n{noisy}",
        2,
        [TitleCandidate(noisy, "bookmark", 0.82)],
    )

    assert not is_sane_sheet_title(noisy)
    assert block.sheet_title == "Unknown Sheet"
    assert block.sheet_title_source == "fallback"


def test_sheet_title_uses_normal_visible_title_block_text() -> None:
    block = extract_title_block("DRAWING NO: PID-100 REV: B\nTITLE: REGULATOR STATION DIAGRAM", 3)

    assert block.sheet_title == "REGULATOR STATION DIAGRAM"
    assert block.sheet_title_source == "title_block"
