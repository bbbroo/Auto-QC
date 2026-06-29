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


class MarkerAdapter(OptionalDependencyAdapter):
    tool_name = "marker"
    package_names = ("marker-pdf", "marker")
    module_names = ("marker",)
    command_names = ("marker_single", "marker")

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
                "error": "Marker package detected but no supported CLI command was found (marker_single or marker).",
            }

        target_dir = output_dir / "marker" / safe_name(pdf_path.stem) / f"page_{page_number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        if Path(command).name.lower().startswith("marker_single"):
            args = [command, str(pdf_path), "--output_dir", str(target_dir)]
        else:
            args = [command, str(pdf_path), str(target_dir)]
        completed = run_subprocess(args, timeout_seconds=timeout_seconds, cwd=target_dir)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Marker command failed: {detail[-1000:]}")
        text, tables, metadata = collect_output_files(target_dir)
        metadata.update(
            {
                "command": args,
                "stdout": completed.stdout[-4000:],
                "page_filter_note": "Marker CLI may process the full PDF; this row records the requested benchmark page.",
            }
        )
        return {"text": text, "tables": tables, "metadata": metadata}

