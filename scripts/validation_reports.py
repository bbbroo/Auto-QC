from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.models import utc_now_iso


def write_validation_report(
    *,
    data_dir: Path,
    report_name: str,
    status: str,
    summary: str,
    checks: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, str]:
    """Write machine-readable and human-readable validation reports under data/."""

    reports_dir = Path(data_dir) / "validation_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(report_name)
    payload = {
        "report_name": report_name,
        "status": status,
        "summary": summary,
        "generated_at": utc_now_iso(),
        "checks": checks,
        "metrics": metrics or {},
        "artifacts": _redact_artifacts(artifacts or {}, Path(data_dir)),
        "limitations": limitations or [],
    }
    json_path = reports_dir / f"{safe_name}.json"
    md_path = reports_dir / f"{safe_name}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_markdown_report(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower()).strip("_")
    return safe or "autoqc_validation_report"


def _redact_artifacts(artifacts: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    data_root = data_dir.resolve()
    for key, value in artifacts.items():
        if isinstance(value, (str, Path)):
            redacted[key] = _relative_or_name(value, data_root)
        elif isinstance(value, list):
            redacted[key] = [_relative_or_name(item, data_root) if isinstance(item, (str, Path)) else item for item in value]
        else:
            redacted[key] = value
    return redacted


def _relative_or_name(value: str | Path, data_root: Path) -> str:
    text = str(value)
    try:
        path = Path(text).resolve()
        return path.relative_to(data_root).as_posix()
    except Exception:
        return Path(text).name if ("\\" in text or "/" in text) else text


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['report_name']}",
        "",
        f"- Status: {payload['status']}",
        f"- Generated: {payload['generated_at']}",
        f"- Summary: {payload['summary']}",
        "",
        "## Checks",
        "",
    ]
    for check in payload.get("checks", []):
        name = check.get("name", "Unnamed check")
        passed = "PASS" if check.get("passed") else "FAIL"
        detail = check.get("detail")
        lines.append(f"- {passed}: {name}{f' - {detail}' if detail else ''}")
    if payload.get("metrics"):
        lines.extend(["", "## Metrics", ""])
        for key, value in payload["metrics"].items():
            lines.append(f"- {key}: {value}")
    if payload.get("artifacts"):
        lines.extend(["", "## Artifacts", ""])
        for key, value in payload["artifacts"].items():
            lines.append(f"- {key}: {value}")
    if payload.get("limitations"):
        lines.extend(["", "## Limitations", ""])
        for item in payload["limitations"]:
            lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)
