from __future__ import annotations

from pathlib import Path

import fitz

from backend.extraction_benchmark.adapters.base import ExtractorAdapter
from backend.extraction_benchmark.benchmark import parse_args, run_benchmark
from backend.extraction_benchmark.metrics import compute_metrics, score_metrics


class ShapeAdapter(ExtractorAdapter):
    tool_name = "shape"

    def _extract_page(self, pdf_path: Path, page_number: int, output_dir: Path, timeout_seconds: int) -> dict:
        return {
            "text": "DRAWING NO: G-001 REV A\nSEE SHEET P-005\nPT-101 ON 4 INCH LINE",
            "blocks": [
                {
                    "type": "text",
                    "text": "DRAWING NO: G-001",
                    "bbox": [1, 2, 3, 4],
                    "confidence": None,
                    "metadata": {},
                }
            ],
            "tables": [],
            "metadata": {"page_width": 100, "page_height": 200},
        }


def test_adapter_interface_shape(tmp_path: Path) -> None:
    result = ShapeAdapter().extract_page(tmp_path / "example.pdf", 1, tmp_path)

    assert result["tool_name"] == "shape"
    assert result["status"] == "ok"
    assert result["error"] is None
    assert result["runtime_seconds"] >= 0
    assert result["blocks"][0]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    for key in ("text", "blocks", "tables", "images", "metadata"):
        assert key in result


def test_metric_computation_and_scoring(tmp_path: Path) -> None:
    result = ShapeAdapter().extract_page(tmp_path / "example.pdf", 1, tmp_path)
    result["tables"] = [
        {
            "format": "csv",
            "content": "REV,DATE,BY,DESCRIPTION\nA,2026-01-01,AB,ISSUED\n",
            "bbox": [0, 0, 10, 10],
            "row_count": 2,
            "column_count": 4,
        }
    ]

    metrics = compute_metrics(result)

    assert metrics["character_count"] > 0
    assert metrics["drawing_reference_token_count"] >= 2
    assert metrics["equipment_tag_count"] >= 1
    assert metrics["pipe_size_token_count"] >= 1
    assert metrics["has_coordinate_data"] is True
    assert metrics["heuristic_score"] > 0
    assert score_metrics({**metrics, "status": "failed"})["heuristic_score"] == 0


def test_missing_optional_extractor_skips_cleanly(tmp_path: Path, monkeypatch) -> None:
    from backend.extraction_benchmark.adapters import base
    from backend.extraction_benchmark.adapters.mineru_adapter import MinerUAdapter

    monkeypatch.setattr(base.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(base.shutil, "which", lambda name: None)

    result = MinerUAdapter().extract_page(tmp_path / "example.pdf", 1, tmp_path)

    assert result["status"] == "skipped"
    assert "not installed" in result["error"]


def test_cli_argument_parsing() -> None:
    args = parse_args(
        [
            "--mode",
            "full",
            "--extractors",
            "pymupdf,pdfplumber",
            "--pages",
            "1,2,5",
            "--timeout-seconds",
            "30",
        ]
    )

    assert args.mode == "full"
    assert args.extractors == "pymupdf,pdfplumber"
    assert args.pages == "1,2,5"
    assert args.timeout_seconds == 30


def test_benchmark_continues_when_one_adapter_fails(tmp_path: Path) -> None:
    class OkAdapter(ExtractorAdapter):
        tool_name = "ok"

        def _extract_page(self, pdf_path: Path, page_number: int, output_dir: Path, timeout_seconds: int) -> dict:
            return {
                "text": "DRAWING NO: T-001 REV A REGULATOR PT-101",
                "blocks": [{"type": "text", "text": "DRAWING NO: T-001", "bbox": [0, 0, 1, 1]}],
                "metadata": {"page_width": 100, "page_height": 100},
            }

    class FailingAdapter(ExtractorAdapter):
        tool_name = "fail"

        def _extract_page(self, pdf_path: Path, page_number: int, output_dir: Path, timeout_seconds: int) -> dict:
            raise RuntimeError("simulated extractor failure")

    pdf_path = tmp_path / "tiny.pdf"
    _write_tiny_pdf(pdf_path)
    args = parse_args(
        [
            "--pdf",
            str(pdf_path),
            "--pages",
            "1",
            "--extractors",
            "ok,fail",
            "--output",
            str(tmp_path / "runs"),
        ]
    )

    result = run_benchmark(args, adapter_classes=(OkAdapter, FailingAdapter))

    statuses = {(row["tool_name"], row["status"]) for row in result["metrics"]}
    assert ("ok", "ok") in statuses
    assert ("fail", "failed") in statuses
    assert result["report_md"].exists()
    assert result["raw_jsonl"].exists()


def _write_tiny_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "DRAWING NO: T-001 REV A", fontsize=10)
    doc.save(path)
    doc.close()
