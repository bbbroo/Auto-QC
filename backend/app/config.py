from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

AI_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}
DEFAULT_AI_PROVIDER = "openai"


class Settings:
    """Runtime settings for a local-first installation."""

    def __init__(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.repo_root = repo_root
        self.data_dir = Path(os.getenv("AUTOQC_DATA_DIR", repo_root / "data")).resolve()
        self.db_path = Path(os.getenv("AUTOQC_DB_PATH", self.data_dir / "autoqc.sqlite")).resolve()
        self.max_upload_mb = int(os.getenv("AUTOQC_MAX_UPLOAD_MB", "250"))
        self.user_ai_settings_path = _user_ai_settings_path()
        saved_ai = {} if os.getenv("PYTEST_CURRENT_TEST") else _load_json(self.user_ai_settings_path)
        self.ai_provider = _normalize_ai_provider(_setting_value("AUTOQC_AI_PROVIDER", saved_ai, "provider", DEFAULT_AI_PROVIDER))
        self.ai_model = _setting_value("AUTOQC_AI_MODEL", saved_ai, "model", "")
        self.ai_api_key = _setting_value("AUTOQC_AI_API_KEY", saved_ai, "api_key", "")
        self.ai_base_url = _setting_value(
            "AUTOQC_AI_BASE_URL",
            saved_ai,
            "base_url",
            AI_PROVIDER_BASE_URLS[self.ai_provider],
        )
        self.ai_timeout_seconds = float(os.getenv("AUTOQC_AI_TIMEOUT_SECONDS", "60"))
        self.ai_max_sheets = int(os.getenv("AUTOQC_AI_MAX_SHEETS", "20"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_ai_settings_path.parent.mkdir(parents=True, exist_ok=True)

    def save_user_ai_settings(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Persist AI settings for the current OS user on this machine only."""

        current = _load_json(self.user_ai_settings_path)
        if api_key is not None:
            current["api_key"] = api_key.strip()
        if model is not None:
            current["model"] = model.strip()
        selected_provider = _normalize_ai_provider(provider if provider is not None else str(current.get("provider") or DEFAULT_AI_PROVIDER))
        current["provider"] = selected_provider
        if base_url is not None and base_url.strip():
            current["base_url"] = base_url.strip()
        elif provider is not None:
            current["base_url"] = AI_PROVIDER_BASE_URLS[selected_provider]

        self.user_ai_settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_ai_settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

        self.ai_api_key = _setting_value("AUTOQC_AI_API_KEY", current, "api_key", "")
        self.ai_model = _setting_value("AUTOQC_AI_MODEL", current, "model", "")
        self.ai_provider = _normalize_ai_provider(_setting_value("AUTOQC_AI_PROVIDER", current, "provider", DEFAULT_AI_PROVIDER))
        self.ai_base_url = _setting_value(
            "AUTOQC_AI_BASE_URL",
            current,
            "base_url",
            AI_PROVIDER_BASE_URLS[self.ai_provider],
        )
        return current


def _normalize_ai_provider(value: str | None) -> str:
    provider = (value or DEFAULT_AI_PROVIDER).strip().lower()
    aliases = {
        "openai-compatible": "openai",
        "open_ai": "openai",
        "deep seek": "deepseek",
        "deep_seek": "deepseek",
    }
    provider = aliases.get(provider, provider)
    compact = provider.replace("-", "").replace("_", "").replace(" ", "")
    if compact == "openaicompatible":
        return "openai"
    if compact == "deepseekai":
        return "deepseek"
    return provider if provider in AI_PROVIDER_BASE_URLS else DEFAULT_AI_PROVIDER


def _setting_value(env_name: str, saved: dict[str, Any], key: str, default: str) -> str:
    env_value = os.getenv(env_name)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    saved_value = saved.get(key)
    if saved_value is not None and str(saved_value).strip():
        return str(saved_value).strip()
    return default


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


def _user_ai_settings_path() -> Path:
    configured = os.getenv("AUTOQC_USER_AI_SETTINGS_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "AutoQC" / "user-ai-settings.json"
    return Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / "autoqc" / "user-ai-settings.json"


settings = Settings()
