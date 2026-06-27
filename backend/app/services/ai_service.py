from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings


@dataclass
class AIReviewService:
    """Optional AI hook.

    The app is deterministic and fully usable without this service. When configured,
    callers can use it to append structured, evidence-backed candidate findings.
    The current implementation deliberately returns no findings unless a concrete
    provider adapter is installed, which keeps local test runs reproducible.
    """

    settings: Settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ai_provider and self.settings.ai_api_key)

    def structured_review(self, task_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        # Provider adapters should live here and must return candidate findings
        # with explicit evidence. Invalid or unsupported output is ignored by
        # the deterministic normalizer.
        return []

