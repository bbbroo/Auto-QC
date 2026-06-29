from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.database import Database


MEMORY_OUTCOMES = {
    "accepted",
    "rejected",
    "edited",
    "duplicate",
    "deferred",
    "needs_manual_placement",
    "needs_engineer_input",
    "exported",
}
POSITIVE_OUTCOMES = {"accepted", "edited", "exported"}
AVOID_OUTCOMES = {"rejected", "duplicate"}
PLACEMENT_OUTCOMES = {"needs_manual_placement"}
NEUTRAL_OUTCOMES = {"deferred", "needs_engineer_input"}


class MarkupMemoryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def collect_memory_from_finding(
        self,
        project_id: str,
        finding_id: str,
        outcome: str,
        *,
        source_type: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_outcome = _normalize_outcome(outcome)
        if normalized_outcome not in MEMORY_OUTCOMES:
            return None
        finding = self.db.get_finding(finding_id)
        if finding.get("project_id") != project_id:
            raise KeyError(finding_id)
        project = self.db.get_project(project_id)
        sheet = self._sheet_for_finding(project_id, finding)
        example = self._example_from_finding(
            project=project,
            finding=finding,
            sheet=sheet,
            outcome=normalized_outcome,
            source_type=source_type or ("export" if normalized_outcome == "exported" else "manual_edit"),
        )
        return self.db.upsert_markup_memory_example(example)

    def collect_exported_findings(self, project_id: str, findings: list[dict[str, Any]]) -> int:
        count = 0
        for finding in findings:
            finding_id = finding.get("id")
            if not finding_id:
                continue
            if self.collect_memory_from_finding(project_id, finding_id, "exported", source_type="export"):
                count += 1
        return count

    def get_relevant_memory_examples(
        self,
        project_id: str,
        limit: int = 8,
        *,
        include_rejected: bool = True,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.db.get_project(project_id)
        settings = settings or self.db.get_markup_memory_settings()
        positive_limit = _positive_int(limit, 8, 25)
        avoid_limit = _positive_int(settings.get("max_avoid_examples_per_prompt"), 5, 25)
        min_score = float(settings.get("min_usefulness_score") or 0)
        examples = self.db.list_markup_memory_examples(min_usefulness_score=min_score)
        if not settings.get("include_current_project_examples"):
            examples = [
                example
                for example in examples
                if example.get("source_project_id") != project_id
            ]
        context = self._project_context(project_id)

        include_positive_outcomes: set[str] = set()
        if settings.get("include_accepted_examples", True):
            include_positive_outcomes.update({"accepted", "exported"})
        if settings.get("include_edited_examples", True):
            include_positive_outcomes.add("edited")

        positive = [
            item
            for item in examples
            if item.get("status_outcome") in include_positive_outcomes
        ]
        avoid = [
            item
            for item in examples
            if include_rejected and item.get("status_outcome") in AVOID_OUTCOMES
        ]
        placement = [
            item
            for item in examples
            if item.get("status_outcome") in PLACEMENT_OUTCOMES
        ]

        return {
            "project_id": project_id,
            "positive_examples": self._rank_and_bound(positive, context, positive_limit),
            "avoid_examples": self._rank_and_bound(avoid, context, avoid_limit),
            "placement_examples": self._rank_and_bound(placement, context, min(3, positive_limit)),
            "settings": settings,
        }

    def build_markup_memory_prompt_context(
        self,
        project_id: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = settings or self.db.get_markup_memory_settings()
        retrieval = self.get_relevant_memory_examples(
            project_id,
            _positive_int(settings.get("max_examples_per_prompt"), 8, 25),
            include_rejected=bool(settings.get("include_rejected_examples", True)),
            settings=settings,
        )
        disabled_reasons = []
        if not settings.get("advanced_feature_enabled"):
            disabled_reasons.append("Advanced Features are disabled.")
        if not settings.get("enabled"):
            disabled_reasons.append("Markup Memory is disabled.")
        if not settings.get("include_in_prompts"):
            disabled_reasons.append("Markup Memory prompt injection is disabled.")

        if disabled_reasons:
            return {
                **retrieval,
                "enabled": False,
                "prompt_section": "",
                "disabled_reason": " ".join(disabled_reasons),
            }

        positive = retrieval["positive_examples"]
        avoid = retrieval["avoid_examples"]
        if not positive and not avoid:
            return {
                **retrieval,
                "enabled": False,
                "prompt_section": "",
                "disabled_reason": "No relevant Markup Memory examples were found.",
            }

        section = self._format_prompt_section(positive, avoid)
        return {
            **retrieval,
            "enabled": bool(section),
            "prompt_section": section,
            "disabled_reason": None,
        }

    def rebuild_memory_from_existing_findings(self) -> dict[str, Any]:
        projects = self.db.list_projects()
        created_or_updated = 0
        outcome_counts: dict[str, int] = {}
        for project in projects:
            project_id = project["id"]
            findings = self.db.list_findings(project_id, sources=["ai"])
            events = self.db.list_finding_events(project_id)
            edited_finding_ids = {
                event.get("finding_id")
                for event in events
                if event.get("action") in {"finding_edit", "bulk_update"}
                and isinstance(event.get("changes"), dict)
                and any(key != "status" for key in event["changes"])
            }
            exported_statuses = self._exported_statuses(project_id)
            for finding in findings:
                outcomes = self._rebuild_outcomes_for_finding(finding, edited_finding_ids, exported_statuses)
                for outcome in outcomes:
                    if self.collect_memory_from_finding(project_id, finding["id"], outcome):
                        created_or_updated += 1
                        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        return {
            "projects_scanned": len(projects),
            "memory_examples_upserted": created_or_updated,
            "outcome_counts": outcome_counts,
            "stats": self.db.markup_memory_stats(),
        }

    def clear_memory(self) -> dict[str, Any]:
        deleted = self.db.clear_markup_memory()
        return {"deleted": deleted, "stats": self.db.markup_memory_stats()}

    def _sheet_for_finding(self, project_id: str, finding: dict[str, Any]) -> dict[str, Any] | None:
        sheets = self.db.list_sheets(project_id)
        by_id = {sheet.get("id"): sheet for sheet in sheets}
        if finding.get("sheet_id") in by_id:
            return by_id[finding["sheet_id"]]
        try:
            page_number = int(finding.get("page_number") or 0)
        except (TypeError, ValueError):
            page_number = 0
        return next((sheet for sheet in sheets if sheet.get("page_number") == page_number), None)

    def _example_from_finding(
        self,
        *,
        project: dict[str, Any],
        finding: dict[str, Any],
        sheet: dict[str, Any] | None,
        outcome: str,
        source_type: str,
    ) -> dict[str, Any]:
        target_text = _first_evidence_text(finding, ["target_text", "markup_text", "text_excerpt"])
        required_update = _first_evidence_text(finding, ["required_update"]) or str(finding.get("suggested_correction") or "").strip()
        rationale = _first_evidence_text(finding, ["rationale"]) or str(finding.get("reasoning_summary") or "").strip()
        final_comment = str(finding.get("comment_text") or "").strip()
        source_pdf_name = _source_pdf_name(project)
        normalized = _normalize_search_text(
            " ".join(
                str(item or "")
                for item in [
                    source_pdf_name,
                    sheet.get("drawing_number") if sheet else None,
                    sheet.get("sheet_title") if sheet else None,
                    sheet.get("sheet_type") if sheet else None,
                    finding.get("category"),
                    finding.get("severity"),
                    target_text,
                    required_update,
                    final_comment,
                    rationale,
                    finding.get("reviewer_note"),
                ]
            )
        )
        tags = {
            "stable_id": finding.get("stable_id"),
            "source": finding.get("source"),
            "ai_batch_id": finding.get("ai_batch_id"),
            "prompt_version": finding.get("prompt_version"),
            "placement_status": finding.get("placement_status"),
            "duplicate_of": finding.get("duplicate_of"),
        }
        return {
            "source_project_id": project.get("id"),
            "source_finding_id": finding.get("id"),
            "source_pdf_name": source_pdf_name,
            "page_number": finding.get("page_number"),
            "sheet_id": finding.get("sheet_id"),
            "drawing_number": (sheet or {}).get("drawing_number"),
            "sheet_title": (sheet or {}).get("sheet_title"),
            "sheet_type": (sheet or {}).get("sheet_type"),
            "category": finding.get("category"),
            "severity": finding.get("severity"),
            "target_text": target_text,
            "required_update": required_update,
            "final_comment_text": final_comment,
            "rationale": rationale,
            "reviewer_note": finding.get("reviewer_note"),
            "status_outcome": outcome,
            "source_type": source_type,
            "normalized_search_text": normalized,
            "tags": {key: value for key, value in tags.items() if value},
            "original_ai_json": finding.get("original_ai_json"),
            "usefulness_score": _usefulness_score(finding, outcome, target_text, required_update, final_comment),
        }

    def _project_context(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        findings = self.db.list_findings(project_id, sources=["ai"])
        text_parts: list[str] = [str(project.get("name") or "")]
        sheet_types: set[str] = set()
        drawing_numbers: set[str] = set()
        for sheet in sheets:
            text_parts.extend(
                str(item or "")
                for item in [
                    sheet.get("drawing_number"),
                    sheet.get("sheet_title"),
                    sheet.get("sheet_type"),
                    sheet.get("text_content", "")[:1600],
                ]
            )
            if sheet.get("sheet_type"):
                sheet_types.add(str(sheet["sheet_type"]).lower())
            if sheet.get("drawing_number"):
                drawing_numbers.add(str(sheet["drawing_number"]).lower())
        categories = {str(finding.get("category") or "").lower() for finding in findings if finding.get("category")}
        for finding in findings[:80]:
            text_parts.extend(
                str(item or "")
                for item in [
                    finding.get("title"),
                    finding.get("category"),
                    finding.get("comment_text"),
                    finding.get("suggested_correction"),
                ]
            )
        normalized = _normalize_search_text(" ".join(text_parts))
        return {
            "project_id": project_id,
            "tokens": _token_set(normalized),
            "sheet_types": sheet_types,
            "drawing_numbers": drawing_numbers,
            "categories": categories,
        }

    def _rank_and_bound(
        self,
        examples: list[dict[str, Any]],
        context: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for example in examples:
            item = dict(example)
            item["similarity_score"] = round(_similarity_score(example, context), 4)
            scored.append(item)
        scored.sort(key=lambda item: (float(item.get("similarity_score") or 0), str(item.get("updated_at") or "")), reverse=True)
        deduped: list[dict[str, Any]] = []
        for item in scored:
            source_finding_id = str(item.get("source_finding_id") or item.get("id") or "")
            if source_finding_id in seen_source_ids:
                continue
            seen_source_ids.add(source_finding_id)
            deduped.append(_trim_example_for_api(item))
            if len(deduped) >= limit:
                break
        return deduped

    def _format_prompt_section(self, positive: list[dict[str, Any]], avoid: list[dict[str, Any]]) -> str:
        lines = [
            "Past Review Memory",
            "Use these past examples only as review guidance and wording examples. Do not copy or recreate an issue unless the same issue is visibly supported by the current attached PDF. The attached PDF remains the source of truth.",
            "",
        ]
        if positive:
            lines.append("Examples to emulate:")
            for index, example in enumerate(positive, start=1):
                lines.extend(_format_prompt_example(index, example))
            wording = _unique_nonempty(_field(example, "final_comment_text") for example in positive)[:3]
            if wording:
                lines.append("Common reviewer wording preferences:")
                for item in wording:
                    lines.append(f"- Prefer concise markup wording like: {_truncate(item, 180)}")
            lines.append("")
        if avoid:
            lines.append("Examples to avoid:")
            for index, example in enumerate(avoid, start=1):
                lines.extend(_format_prompt_example(index, example))
            false_positives = _unique_nonempty(_field(example, "target_text") or _field(example, "required_update") for example in avoid)[:4]
            if false_positives:
                lines.append("Common false positives to avoid:")
                for item in false_positives:
                    lines.append(f"- Do not report this pattern unless the current attached PDF clearly supports it: {_truncate(item, 160)}")
        return "\n".join(line.rstrip() for line in lines if line is not None).strip()

    def _exported_statuses(self, project_id: str) -> set[str]:
        statuses: set[str] = set()
        for export in self.db.list_exports(project_id):
            status_filter = export.get("status_filter") if isinstance(export.get("status_filter"), list) else []
            if status_filter:
                statuses.update(str(item) for item in status_filter)
            else:
                statuses.add("accepted")
        return statuses

    def _rebuild_outcomes_for_finding(
        self,
        finding: dict[str, Any],
        edited_finding_ids: set[Any],
        exported_statuses: set[str],
    ) -> list[str]:
        outcomes: list[str] = []
        status = _normalize_outcome(str(finding.get("status") or ""))
        if status in MEMORY_OUTCOMES and status != "needs_review":
            outcomes.append(status)
        if finding.get("id") in edited_finding_ids:
            outcomes.append("edited")
        if status in exported_statuses:
            outcomes.append("exported")
        return list(dict.fromkeys(outcomes))


def _normalize_outcome(outcome: str) -> str:
    return str(outcome or "").strip().lower().replace("-", "_").replace(" ", "_")


def _source_pdf_name(project: dict[str, Any]) -> str:
    source = str(project.get("source_pdf_path") or "").strip()
    if source:
        return Path(source).name
    return str(project.get("name") or "Unknown project")


def _first_evidence_text(finding: dict[str, Any], keys: list[str]) -> str:
    for item in finding.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
    return ""


def _normalize_search_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9][a-z0-9_&/#.-]*", str(value or "").lower()))


def _token_set(value: str) -> set[str]:
    return {token for token in _normalize_search_text(value).split() if len(token) >= 3 and token not in STOP_WORDS}


def _usefulness_score(
    finding: dict[str, Any],
    outcome: str,
    target_text: str,
    required_update: str,
    final_comment: str,
) -> float:
    score = {
        "accepted": 1.2,
        "edited": 1.35,
        "exported": 1.45,
        "rejected": 0.9,
        "duplicate": 0.8,
        "deferred": 0.55,
        "needs_manual_placement": 0.65,
        "needs_engineer_input": 0.6,
    }.get(outcome, 0.4)
    if target_text:
        score += 0.45
    if required_update:
        score += 0.4
    if final_comment:
        score += 0.35
    if finding.get("reviewer_note"):
        score += 0.2
    try:
        score += min(0.25, max(0.0, float(finding.get("confidence") or 0) * 0.25))
    except (TypeError, ValueError):
        pass
    return round(score, 3)


def _similarity_score(example: dict[str, Any], context: dict[str, Any]) -> float:
    score = float(example.get("usefulness_score") or 0)
    status = str(example.get("status_outcome") or "")
    score += {
        "exported": 1.0,
        "edited": 0.9,
        "accepted": 0.8,
        "rejected": 0.55,
        "duplicate": 0.5,
        "needs_manual_placement": 0.25,
    }.get(status, 0.0)
    category = str(example.get("category") or "").lower()
    if category and category in context.get("categories", set()):
        score += 0.75
    sheet_type = str(example.get("sheet_type") or "").lower()
    if sheet_type and sheet_type in context.get("sheet_types", set()):
        score += 0.65
    drawing_number = str(example.get("drawing_number") or "").lower()
    if drawing_number and drawing_number in context.get("drawing_numbers", set()):
        score += 0.35
    example_tokens = _token_set(str(example.get("normalized_search_text") or ""))
    context_tokens = context.get("tokens", set())
    overlap = len(example_tokens & context_tokens)
    if overlap:
        score += min(1.4, overlap * 0.16)
        score += min(0.6, overlap / max(1, math.sqrt(len(example_tokens) * max(1, len(context_tokens)))))
    if example.get("source_project_id") == context.get("project_id"):
        score += 0.2
    score += _recency_boost(example.get("updated_at"))
    return score


def _recency_boost(value: Any) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)
    return max(0.0, 0.35 - age_days / 730)


def _trim_example_for_api(example: dict[str, Any]) -> dict[str, Any]:
    out = dict(example)
    for key, limit in {
        "target_text": 220,
        "required_update": 220,
        "final_comment_text": 240,
        "rationale": 220,
        "reviewer_note": 180,
        "normalized_search_text": 400,
    }.items():
        if isinstance(out.get(key), str):
            out[key] = _truncate(out[key], limit)
    out.pop("original_ai_json", None)
    return out


def _format_prompt_example(index: int, example: dict[str, Any]) -> list[str]:
    prefix = (
        f"{index}. [{_field(example, 'status_outcome')}] "
        f"{_field(example, 'drawing_number') or 'Drawing unknown'}"
        f" page {_field(example, 'page_number') or '?'}"
        f" | {_field(example, 'category') or 'uncategorized'}"
        f" | {_field(example, 'severity') or 'severity unknown'}"
    )
    lines = [prefix]
    if _field(example, "sheet_title"):
        lines.append(f"   Sheet: {_truncate(_field(example, 'sheet_title'), 120)}")
    if _field(example, "target_text"):
        lines.append(f"   Target text: {_truncate(_field(example, 'target_text'), 180)}")
    if _field(example, "required_update"):
        lines.append(f"   Required update: {_truncate(_field(example, 'required_update'), 180)}")
    if _field(example, "final_comment_text"):
        lines.append(f"   Final wording: {_truncate(_field(example, 'final_comment_text'), 180)}")
    if _field(example, "rationale"):
        lines.append(f"   Rationale: {_truncate(_field(example, 'rationale'), 160)}")
    if _field(example, "reviewer_note"):
        lines.append(f"   Reviewer note: {_truncate(_field(example, 'reviewer_note'), 140)}")
    return lines


def _field(example: dict[str, Any], key: str) -> str:
    value = example.get(key)
    return " ".join(str(value).split()) if value is not None else ""


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _unique_nonempty(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _positive_int(value: Any, default: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(max_value, number))


STOP_WORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "not",
    "the",
    "this",
    "that",
    "with",
    "shall",
    "sheet",
    "drawing",
    "page",
    "update",
    "required",
    "review",
    "finding",
    "comment",
}
