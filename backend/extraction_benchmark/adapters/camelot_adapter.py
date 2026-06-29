from __future__ import annotations

from pathlib import Path

from backend.extraction_benchmark.adapters.base import OptionalDependencyAdapter, NormalizedResult, command_path


class CamelotAdapter(OptionalDependencyAdapter):
    tool_name = "camelot"
    package_names = ("camelot-py",)
    module_names = ("camelot",)
    command_names = ("gswin64c", "gswin32c", "gs")

    def is_available(self) -> tuple[bool, str | None]:
        import importlib.util

        if importlib.util.find_spec("camelot") is None:
            return False, "Camelot is not installed (camelot-py)"
        return True, None

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        import camelot

        tables = camelot.read_pdf(str(pdf_path), pages=str(page_number), flavor="stream")
        normalized_tables = []
        for table_index, table in enumerate(tables):
            dataframe = table.df
            normalized_tables.append(
                {
                    "format": "csv",
                    "content": dataframe.to_csv(index=False, header=False),
                    "bbox": list(getattr(table, "_bbox", None) or []) or None,
                    "row_count": int(dataframe.shape[0]),
                    "column_count": int(dataframe.shape[1]),
                    "metadata": {
                        "table_index": table_index,
                        "accuracy": getattr(table, "accuracy", None),
                        "whitespace": getattr(table, "whitespace", None),
                    },
                }
            )
        return {
            "text": "",
            "blocks": [],
            "tables": normalized_tables,
            "metadata": {
                "flavor": "stream",
                "ghostscript_command": command_path(("gswin64c", "gswin32c", "gs")),
                "note": "Camelot adapter extracts tables only.",
            },
        }

