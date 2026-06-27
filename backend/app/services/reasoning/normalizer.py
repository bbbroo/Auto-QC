from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from backend.app.models import FindingStatus, Severity, utc_now_iso
from backend.app.services.reasoning.engine import CandidateFinding


def stable_hash(parts: list[str | None], length: int = 10) -> str:
    joined = "|".join(part or "" for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length].upper()


def normalize_comment(text: str, max_length: int = 360) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) > max_length:
        return clean[: max_length - 3].rstrip() + "..."
    return clean


def status_for_confidence(confidence: float) -> str:
    return FindingStatus.ACCEPTED.value if confidence >= 0.72 else FindingStatus.NEEDS_REVIEW.value


def normalize_candidate(project_id: str, candidate: CandidateFinding) -> dict[str, Any]:
    confidence = round(max(0.05, min(0.98, candidate.confidence)), 2)
    now = utc_now_iso()
    stable_id = "QC-" + stable_hash(
        [
            project_id,
            candidate.rule_id,
            candidate.sheet_id,
            candidate.title.lower(),
            ",".join(sorted(candidate.involved_entities)),
        ]
    )
    return {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "sheet_id": candidate.sheet_id,
        "stable_id": stable_id,
        "title": candidate.title,
        "category": candidate.category,
        "severity": candidate.severity.value if isinstance(candidate.severity, Severity) else str(candidate.severity),
        "confidence": confidence,
        "page_number": candidate.page_number,
        "location": candidate.location,
        "involved_entities": candidate.involved_entities,
        "evidence": candidate.evidence,
        "reasoning_summary": candidate.reasoning_summary,
        "suggested_correction": candidate.suggested_correction,
        "comment_text": normalize_comment(candidate.comment_text),
        "status": status_for_confidence(confidence),
        "source": candidate.source,
        "created_at": now,
        "updated_at": now,
    }
