from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import time
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


NormalizedResult = dict[str, Any]

TEXT_OUTPUT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".html", ".htm", ".json"}


class ExtractorAdapter(ABC):
    """Common page-level extraction adapter contract."""

    tool_name = "unknown"
    package_names: tuple[str, ...] = ()
    module_names: tuple[str, ...] = ()
    command_names: tuple[str, ...] = ()

    def is_available(self) -> tuple[bool, str | None]:
        return True, None

    def tool_version(self) -> str | None:
        for package_name in self.package_names:
            try:
                return importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                continue
        for module_name in self.module_names:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                continue
            try:
                module = __import__(module_name)
                version = getattr(module, "__version__", None)
                if version:
                    return str(version)
            except Exception:
                continue
        return None

    def extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int = 120,
    ) -> NormalizedResult:
        started = time.perf_counter()
        try:
            available, reason = self.is_available()
        except Exception as exc:
            return self._result(
                pdf_path,
                page_number,
                status="skipped",
                error=f"availability check failed: {exc}",
                runtime_seconds=time.perf_counter() - started,
            )

        if not available:
            return self._result(
                pdf_path,
                page_number,
                status="skipped",
                error=reason or "extractor is not available",
                runtime_seconds=time.perf_counter() - started,
            )

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            partial = self._extract_page(pdf_path, page_number, output_dir, timeout_seconds) or {}
            return self._normalize_partial(
                pdf_path=pdf_path,
                page_number=page_number,
                partial=partial,
                runtime_seconds=time.perf_counter() - started,
            )
        except subprocess.TimeoutExpired as exc:
            return self._result(
                pdf_path,
                page_number,
                status="failed",
                error=f"timed out after {exc.timeout} seconds",
                runtime_seconds=time.perf_counter() - started,
                metadata={"error_type": type(exc).__name__},
            )
        except Exception as exc:
            return self._result(
                pdf_path,
                page_number,
                status="failed",
                error=str(exc),
                runtime_seconds=time.perf_counter() - started,
                metadata={
                    "error_type": type(exc).__name__,
                    "traceback_tail": traceback.format_exc(limit=5),
                },
            )

    @abstractmethod
    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        raise NotImplementedError

    def _normalize_partial(
        self,
        *,
        pdf_path: Path,
        page_number: int,
        partial: NormalizedResult,
        runtime_seconds: float,
    ) -> NormalizedResult:
        result = self._result(
            pdf_path,
            page_number,
            status=str(partial.get("status") or "ok"),
            error=partial.get("error"),
            runtime_seconds=runtime_seconds,
        )
        for key in ("text", "blocks", "tables", "images", "metadata"):
            if key in partial:
                result[key] = partial[key]
        if "tool_version" in partial:
            result["tool_version"] = partial["tool_version"]
        result["blocks"] = [normalize_block(block) for block in result.get("blocks") or []]
        result["tables"] = [normalize_table(table) for table in result.get("tables") or []]
        result["images"] = [normalize_image(image) for image in result.get("images") or []]
        result["metadata"] = dict(result.get("metadata") or {})
        return result

    def _result(
        self,
        pdf_path: Path,
        page_number: int,
        *,
        status: str,
        error: str | None,
        runtime_seconds: float,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedResult:
        return {
            "tool_name": self.tool_name,
            "tool_version": self.tool_version(),
            "pdf_path": str(pdf_path),
            "page_number": int(page_number),
            "status": status,
            "error": error,
            "runtime_seconds": float(runtime_seconds),
            "text": "",
            "blocks": [],
            "tables": [],
            "images": [],
            "metadata": dict(metadata or {}),
        }


class OptionalDependencyAdapter(ExtractorAdapter):
    """Availability helper for extractors that may be installed locally."""

    def is_available(self) -> tuple[bool, str | None]:
        module_available = any(importlib.util.find_spec(name) is not None for name in self.module_names)
        command_available = any(shutil.which(name) for name in self.command_names)
        if module_available or command_available:
            return True, None
        package_hint = ", ".join(self.package_names or self.module_names or self.command_names)
        return False, f"{self.tool_name} is not installed ({package_hint})"


def normalize_bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        values = list(value)
    except TypeError:
        return None
    if len(values) != 4:
        return None
    try:
        return [float(item) for item in values]
    except (TypeError, ValueError):
        return None


def normalize_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(block.get("type") or "unknown"),
        "text": str(block.get("text") or ""),
        "bbox": normalize_bbox(block.get("bbox")),
        "confidence": block.get("confidence"),
        "metadata": dict(block.get("metadata") or {}),
    }


def normalize_table(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": str(table.get("format") or "unknown"),
        "content": str(table.get("content") or ""),
        "bbox": normalize_bbox(table.get("bbox")),
        "row_count": _nullable_int(table.get("row_count")),
        "column_count": _nullable_int(table.get("column_count")),
    }


def normalize_image(image: dict[str, Any]) -> dict[str, Any]:
    return {
        "bbox": normalize_bbox(image.get("bbox")),
        "description": image.get("description"),
        "path": str(image["path"]) if image.get("path") else None,
    }


def command_path(command_names: tuple[str, ...]) -> str | None:
    for command_name in command_names:
        found = shutil.which(command_name)
        if found:
            return found
    return None


def run_subprocess(
    command: list[str],
    *,
    timeout_seconds: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def collect_output_files(output_dir: Path, max_total_bytes: int = 1_500_000) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    text_parts: list[str] = []
    tables: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    total_bytes = 0
    if not output_dir.exists():
        return "", tables, {"output_files": files}

    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        rel_path = str(path.relative_to(output_dir))
        files.append({"path": rel_path, "size_bytes": size})
        if path.suffix.lower() not in TEXT_OUTPUT_EXTENSIONS or total_bytes >= max_total_bytes:
            continue
        read_size = min(size, max_total_bytes - total_bytes)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:read_size]
        except Exception:
            continue
        total_bytes += len(content.encode("utf-8", errors="replace"))
        if content.strip():
            text_parts.append(f"\n\n--- {rel_path} ---\n{content}")
        if path.suffix.lower() in {".csv", ".tsv", ".html", ".htm", ".md", ".markdown"}:
            tables.append(
                {
                    "format": path.suffix.lower().lstrip("."),
                    "content": content,
                    "bbox": None,
                    "row_count": None,
                    "column_count": None,
                }
            )
    return "\n".join(text_parts).strip(), tables, {"output_files": files}


def safe_name(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    return clean.strip("._") or "unnamed"


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

