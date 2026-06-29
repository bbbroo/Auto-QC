from __future__ import annotations

from backend.extraction_benchmark.adapters.base import ExtractorAdapter
from backend.extraction_benchmark.adapters.camelot_adapter import CamelotAdapter
from backend.extraction_benchmark.adapters.docling_adapter import DoclingAdapter
from backend.extraction_benchmark.adapters.marker_adapter import MarkerAdapter
from backend.extraction_benchmark.adapters.mineru_adapter import MinerUAdapter
from backend.extraction_benchmark.adapters.paddleocr_adapter import PaddleOCRAdapter
from backend.extraction_benchmark.adapters.pdfplumber_adapter import PDFPlumberAdapter
from backend.extraction_benchmark.adapters.pymupdf_adapter import PyMuPDFAdapter
from backend.extraction_benchmark.adapters.surya_adapter import SuryaAdapter


ADAPTER_CLASSES: tuple[type[ExtractorAdapter], ...] = (
    PyMuPDFAdapter,
    PDFPlumberAdapter,
    CamelotAdapter,
    MinerUAdapter,
    DoclingAdapter,
    MarkerAdapter,
    PaddleOCRAdapter,
    SuryaAdapter,
)


def adapter_registry() -> dict[str, type[ExtractorAdapter]]:
    return {adapter.tool_name: adapter for adapter in ADAPTER_CLASSES}

