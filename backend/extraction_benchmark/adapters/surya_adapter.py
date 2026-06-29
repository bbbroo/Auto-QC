from __future__ import annotations

from pathlib import Path

from backend.extraction_benchmark.adapters.base import (
    OptionalDependencyAdapter,
    NormalizedResult,
    collect_output_files,
    command_path,
    run_subprocess,
    safe_name,
)


class SuryaAdapter(OptionalDependencyAdapter):
    tool_name = "surya"
    package_names = ("surya-ocr", "surya")
    module_names = ("surya",)
    command_names = ("surya_ocr", "surya")

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        command = command_path(self.command_names)
        if not command:
            return {
                "status": "skipped",
                "error": "Surya package detected but no supported CLI command was found (surya_ocr or surya).",
            }
        target_dir = output_dir / "surya" / safe_name(pdf_path.stem) / f"page_{page_number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        image_path = _render_page(pdf_path, page_number, target_dir)
        args = [command, str(image_path), "--output_dir", str(target_dir)]
        completed = run_subprocess(args, timeout_seconds=timeout_seconds, cwd=target_dir)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Surya command failed: {detail[-1000:]}")
        text, tables, metadata = collect_output_files(target_dir)
        metadata.update({"command": args, "stdout": completed.stdout[-4000:], "image_path": str(image_path)})
        return {"text": text, "tables": tables, "metadata": metadata}


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
