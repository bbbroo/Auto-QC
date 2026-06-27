from __future__ import annotations

import os
from pathlib import Path


class Settings:
    """Runtime settings for a local-first installation."""

    def __init__(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.repo_root = repo_root
        self.data_dir = Path(os.getenv("AUTOQC_DATA_DIR", repo_root / "data")).resolve()
        self.db_path = Path(os.getenv("AUTOQC_DB_PATH", self.data_dir / "autoqc.sqlite")).resolve()
        self.max_upload_mb = int(os.getenv("AUTOQC_MAX_UPLOAD_MB", "250"))
        self.ai_provider = os.getenv("AUTOQC_AI_PROVIDER", "").strip().lower()
        self.ai_model = os.getenv("AUTOQC_AI_MODEL", "").strip()
        self.ai_api_key = os.getenv("AUTOQC_AI_API_KEY", "").strip()

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()

