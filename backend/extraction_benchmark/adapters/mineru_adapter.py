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


class MinerUAdapter(OptionalDependencyAdapter):
    tool_name = "mineru"
    package_names = ("magic-pdf", "mineru")
    module_names = ("magic_pdf", "mineru")
    command_names = ("mineru", "magic-pdf")

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
                "error": "MinerU package detected but no supported CLI command was found (mineru or magic-pdf).",
            }

        target_dir = output_dir / "mineru" / safe_name(pdf_path.stem) / f"page_{page_number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        command_name = Path(command).name.lower()
        if command_name.startswith("magic-pdf"):
            args = [command, "-p", str(pdf_path), "-o", str(target_dir), "-m", "auto"]
        else:
            args = [command, "-p", str(pdf_path), "-o", str(target_dir)]
        completed = run_subprocess(args, timeout_seconds=timeout_seconds, cwd=target_dir)
        if completed.returncode != 0:
            raise RuntimeError(_subprocess_error("MinerU", completed.stderr, completed.stdout))
        text, tables, metadata = collect_output_files(target_dir)
        metadata.update(
            {
                "command": args,
                "stdout": completed.stdout[-4000:],
                "page_filter_note": "MinerU CLI may process the full PDF; this row records the requested benchmark page.",
            }
        )
        return {"text": text, "tables": tables, "metadata": metadata}


def _subprocess_error(tool_name: str, stderr: str, stdout: str) -> str:
    detail = (stderr or stdout or "").strip()
    return f"{tool_name} command failed: {detail[-1000:]}"

