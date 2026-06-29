from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    runs = [path for path in root.iterdir() if path.is_dir()]
    if not runs:
        return None
    return sorted(runs, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def load_page_packets(pdf_output_dir: Path) -> list[dict[str, Any]]:
    pages_dir = pdf_output_dir / "pages"
    packets: list[dict[str, Any]] = []
    if not pages_dir.exists():
        return packets
    for path in sorted(pages_dir.glob("page_*.json")):
        payload = read_json(path)
        if isinstance(payload, dict):
            packets.append(payload)
    return packets

