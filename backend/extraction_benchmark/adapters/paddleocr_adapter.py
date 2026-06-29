from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.extraction_benchmark.adapters.base import OptionalDependencyAdapter, NormalizedResult, safe_name


class PaddleOCRAdapter(OptionalDependencyAdapter):
    tool_name = "paddleocr"
    package_names = ("paddleocr",)
    module_names = ("paddleocr",)

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        target_dir = output_dir / "paddleocr" / safe_name(pdf_path.stem) / f"page_{page_number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        image_path = _render_page(pdf_path, page_number, target_dir)
        output_json = target_dir / "ppstructure_result.json"
        code = (
            "import json, sys\n"
            "from paddleocr import PPStructure\n"
            "engine = PPStructure(show_log=False)\n"
            "result = engine(sys.argv[1])\n"
            "with open(sys.argv[2], 'w', encoding='utf-8') as f:\n"
            "    json.dump(result, f, ensure_ascii=False, default=str)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(image_path), str(output_json)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"PaddleOCR/PP-Structure command failed: {detail[-1000:]}")
        payload = json.loads(output_json.read_text(encoding="utf-8"))
        text = _flatten_ppstructure_text(payload)
        return {
            "text": text,
            "blocks": _ppstructure_blocks(payload),
            "metadata": {
                "image_path": str(image_path),
                "output_json": str(output_json),
                "stdout": completed.stdout[-4000:],
            },
        }


def _render_page(pdf_path: Path, page_number: int, target_dir: Path) -> Path:
    import fitz

    with fitz.open(pdf_path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"page {page_number} is outside PDF page range 1-{doc.page_count}")
        page = doc.load_page(page_number - 1)
        image_path = target_dir / "page.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
        pix.save(image_path)
        return image_path


def _flatten_ppstructure_text(payload: list[dict]) -> str:
    parts: list[str] = []
    items = payload if isinstance(payload, list) else []
    for item in items:
        text = item.get("res")
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(text, list):
            for row in text:
                if isinstance(row, dict) and row.get("text"):
                    parts.append(str(row["text"]))
                elif isinstance(row, list):
                    parts.append(" ".join(str(cell) for cell in row))
    return "\n".join(part for part in parts if part.strip())


def _ppstructure_blocks(payload: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    items = payload if isinstance(payload, list) else []
    for index, item in enumerate(items):
        bbox = item.get("bbox")
        block_type = str(item.get("type") or "unknown").lower()
        block_text = ""
        res = item.get("res")
        if isinstance(res, str):
            block_text = res
        elif isinstance(res, list):
            block_text = " ".join(str(row.get("text", "")) for row in res if isinstance(row, dict))
        blocks.append(
            {
                "type": "table" if "table" in block_type else "text",
                "text": block_text,
                "bbox": bbox,
                "confidence": None,
                "metadata": {"block_index": index, "raw_type": block_type},
            }
        )
    return blocks
