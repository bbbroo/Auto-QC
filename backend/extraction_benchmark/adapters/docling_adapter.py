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


class DoclingAdapter(OptionalDependencyAdapter):
    tool_name = "docling"
    package_names = ("docling",)
    module_names = ("docling",)
    command_names = ("docling",)

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        target_dir = output_dir / "docling" / safe_name(pdf_path.stem) / f"page_{page_number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        command = command_path(self.command_names)
        if command:
            args = [command, str(pdf_path), "--to", "md", "--output", str(target_dir)]
            completed = run_subprocess(args, timeout_seconds=timeout_seconds, cwd=target_dir)
            if completed.returncode == 0:
                text, tables, metadata = collect_output_files(target_dir)
                metadata.update({"command": args, "stdout": completed.stdout[-4000:]})
                return {"text": text, "tables": tables, "metadata": metadata}

        try:
            from docling.document_converter import DocumentConverter

            converted = DocumentConverter().convert(str(pdf_path))
            document = converted.document
            text = document.export_to_markdown() if hasattr(document, "export_to_markdown") else str(document)
            return {
                "text": text,
                "metadata": {
                    "api": "docling.document_converter.DocumentConverter",
                    "page_filter_note": "Docling API conversion was run on the full PDF; this row records the requested benchmark page.",
                },
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"Docling execution failed: {exc}",
                "metadata": {"command_attempted": bool(command)},
            }

