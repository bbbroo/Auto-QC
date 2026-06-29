from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from typing import Any, Protocol

import fitz
import httpx

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import FindingCategory, FindingStatus, Severity, utc_now_iso
from backend.app.services.exports import _evidence_search_result
from backend.app.services.markup_memory import MarkupMemoryService
from backend.app.services.prompt_templates import PromptTemplateManager
from backend.app.services.reasoning.engine import CandidateFinding, ReasoningEngine
from backend.app.services.review_coverage import (
    build_review_coverage_summary,
    clean_pages_from_preview,
    expected_review_pages_for_scope,
    project_review_coverage_summary,
)
from backend.app.services.storage import require_project_source_pdf_path
from backend.sheet_evidence.builder import SheetEvidenceBuilder
from backend.sheet_evidence.prompt_context import package_prompt_context
from backend.sheet_evidence.recommendation import analyze_benchmark_run, find_latest_benchmark_run


CHAT_PROMPT_VERSION = "autoqc-chat-prompt-v4-exhaustive-manual"
DEFAULT_IMPORT_SOURCE = "manual_chat_prompt"
DEFAULT_MANUAL_BATCH_SIZE = 8
ALLOWED_MANUAL_BATCH_SIZES = {3, 5, 8, 10}
TEXT_HEAVY_DEEP_DIVE_CHARS = 2500
HIGH_ENTITY_DEEP_DIVE_COUNT = 20
DEEP_DIVE_SHEET_TYPES = {"notes", "drawing_index", "p&id", "detail"}
PROMPT_DEPTH_OPTIONS: dict[str, dict[str, str]] = {
    "fast": {
        "label": "Fast Smoke/Test Review (Non-Production)",
        "instruction": "Use only for controlled app smoke tests; production deep/comprehensive reviews should use the exhaustive manual template.",
    },
    "standard": {
        "label": "Focused Review (Non-Exhaustive)",
        "instruction": "Use only for an intentionally narrow non-production check. Production package review should use exhaustive manual review.",
    },
    "comprehensive": {
        "label": "Exhaustive Manual-Style Review",
        "instruction": "Full sheet-by-sheet manual review of the attached PDF package and return the incomplete-review error instead of partial findings if the full review cannot be completed.",
    },
    "exhaustive": {
        "label": "Exhaustive Manual-Style Review",
        "instruction": "Full sheet-by-sheet manual review of the attached PDF package with no partial findings.",
    },
}


def _mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def utc_now_iso_safe() -> str:
    return utc_now_iso()


class AIClient(Protocol):
    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.ai_api_key or not self.settings.ai_model:
            raise ValueError("AI review is not configured. Enter an API key and model from the AI Deep Review button, or set AUTOQC_AI_API_KEY and AUTOQC_AI_MODEL.")
        body = {
            "model": self.settings.ai_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.ai_api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.settings.ai_timeout_seconds) as client:
            response = client.post(self.settings.ai_base_url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        return parse_json_object(extract_message_content(data))


class AIReviewService:
    def __init__(self, db: Database, settings: Settings, client: AIClient | None = None) -> None:
        self.db = db
        self.settings = settings
        self.client = client or OpenAICompatibleClient(settings)
        self.reasoning = ReasoningEngine()
        self.templates = PromptTemplateManager(settings.data_dir)
        self.markup_memory = MarkupMemoryService(db)

    def status(self) -> dict[str, Any]:
        configured = bool(self.settings.ai_api_key and self.settings.ai_model)
        return {
            "configured": configured,
            "provider": self.settings.ai_provider or "openai",
            "model": self.settings.ai_model or None,
            "base_url": self.settings.ai_base_url,
            "max_sheets": self.settings.ai_max_sheets,
            "manual_bridge_enabled": True,
            "api_key_saved": bool(self.settings.ai_api_key),
            "api_key_hint": _mask_api_key(self.settings.ai_api_key),
            "settings_path": str(self.settings.user_ai_settings_path),
            "available_providers": ["openai", "deepseek"],
        }

    def list_prompt_templates(self) -> list[dict[str, Any]]:
        return self.templates.list_templates()

    def generate_manual_prompt(
        self,
        project_id: str,
        template_id: str | None = None,
        review_depth: str | None = None,
        review_scope: str | None = None,
        page_number: int | None = None,
        page_numbers: str | list[int] | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        entities = self.db.list_entities(project_id)
        existing = self.db.list_findings(project_id, sources=["ai"])
        template = self.templates.get_template(template_id)
        scope = resolve_manual_review_scope(sheets, review_scope, page_number, page_numbers, batch_size)
        payload = build_ai_payload(
            project,
            sheets,
            entities,
            existing,
            max(self.settings.ai_max_sheets, len(sheets)),
            scope_pages=scope.get("scope_pages"),
            review_scope=scope["review_scope"],
        )
        context = manual_prompt_context(payload)
        prompt_version = str(template.get("version") or CHAT_PROMPT_VERSION)
        memory_context = self.markup_memory.build_markup_memory_prompt_context(project_id)
        sheet_evidence_context = self.build_sheet_evidence_prompt_context(project_id, scope)
        depth = normalize_prompt_depth(review_depth)
        prompt_metadata = {
            "included_full_extracted_text": False,
            "sheet_index_count": len(context.get("sheet_index", [])),
            "sheet_count": len(sheets),
            "scope_sheet_count": len(payload.get("sheets", [])),
            "review_strategy": scope["review_strategy"],
            "review_scope": scope["review_scope"],
            "scope_pages": scope.get("scope_pages") or [],
            "scope_label": scope.get("scope_label"),
            "batch_size": scope.get("batch_size"),
            "batch_index": scope.get("batch_index"),
            "batch_count": scope.get("batch_count"),
            "deep_dive_reason": scope.get("deep_dive_reason"),
            "single_output_required": scope["review_scope"] == "package",
            "sheet_by_sheet_required": True,
            "source_of_truth": "attached_pdf",
            "prompt_template_id": template.get("id"),
            "prompt_template_name": template.get("name"),
            "prompt_template_version": prompt_version,
            "review_depth": depth["label"],
            "markup_memory_enabled": bool(memory_context.get("enabled")),
            "markup_memory_positive_examples": len(memory_context.get("positive_examples") or []),
            "markup_memory_avoid_examples": len(memory_context.get("avoid_examples") or []),
            "sheet_evidence_enabled": bool(sheet_evidence_context.get("enabled")),
            "sheet_evidence_included": bool(sheet_evidence_context.get("included")),
            "sheet_evidence_packet_count": int(sheet_evidence_context.get("packet_count") or 0),
            "sheet_evidence_output_dir": sheet_evidence_context.get("output_dir"),
            "sheet_evidence_warnings": sheet_evidence_context.get("warnings") or [],
        }
        prompt_run = self.db.insert_ai_prompt_run(
            project_id,
            prompt_version,
            context.get("sheet_index", []),
            prompt_metadata,
        )
        prompt = build_manual_prompt(
            payload,
            prompt_run,
            template,
            markup_memory_context=memory_context,
            sheet_evidence_context=sheet_evidence_context,
            review_depth=depth,
            scope=scope,
        )
        return {
            "project_id": project_id,
            "prompt_id": prompt_run["id"],
            "prompt_version": prompt_version,
            "generated_at": prompt_run["generated_at"],
            "prompt": prompt,
            "payload_sheet_count": len(payload.get("sheets", [])),
            "instructions": "Copy this prompt into ChatGPT or Copilot Chat. Paste the returned JSON into AutoQC using Import AI Response.",
            "prompt_metadata": prompt_metadata,
            "review_plan": self.build_manual_review_plan(project_id, batch_size=scope.get("batch_size") or DEFAULT_MANUAL_BATCH_SIZE),
        }

    def build_manual_review_plan(self, project_id: str, batch_size: int | None = None) -> dict[str, Any]:
        self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        entities = self.db.list_entities(project_id)
        batches = self.db.list_ai_import_batches(project_id, limit=500)
        return build_hybrid_review_plan(project_id, sheets, entities, batches, batch_size)

    def build_sheet_evidence_prompt_context(self, project_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        if not getattr(self.settings, "use_sheet_evidence", False):
            return {"enabled": False, "included": False, "prompt_section": "", "warnings": ["Sheet Evidence Builder is disabled."]}
        try:
            project = self.db.get_project(project_id)
            sheets = self.db.list_sheets(project_id)
            source_path = require_project_source_pdf_path(self.settings.data_dir, project_id, project.get("source_pdf_path"))
            scope_pages = [int(page) for page in scope.get("scope_pages") or [] if _positive_int(page)]
            if not scope_pages:
                scope_pages = [int(sheet.get("page_number") or 0) for sheet in sheets if _positive_int(sheet.get("page_number"))]
            max_pages = int(getattr(self.settings, "sheet_evidence_prompt_max_pages", 80) or 0)
            if max_pages > 0:
                scope_pages = scope_pages[:max_pages]
            benchmark_root = self.settings.repo_root / ".local" / "autoqc_extraction_benchmark"
            recommendation = analyze_benchmark_run(find_latest_benchmark_run(benchmark_root), allow_fallback=True)
            output_root = self.settings.repo_root / ".local" / "autoqc_sheet_evidence" / "app_prompts"
            builder = SheetEvidenceBuilder(recommendation=recommendation, output_root=output_root)
            result = builder.build_pdfs([source_path], mode="full", pages=scope_pages or None, max_pages=None)
            packets = result.get("packets") or []
            return {
                "enabled": True,
                "included": bool(packets),
                "prompt_section": package_prompt_context(packets),
                "packet_count": len(packets),
                "output_dir": result.get("run_dir"),
                "warnings": [item.get("name") for item in result.get("validation", []) if not item.get("passed")],
            }
        except Exception as exc:
            return {
                "enabled": True,
                "included": False,
                "prompt_section": "",
                "packet_count": 0,
                "output_dir": None,
                "warnings": [f"Sheet Evidence Builder failed safely: {exc}"],
            }

    def preview_manual_response(
        self,
        project_id: str,
        response_text: str,
        source_type: str = DEFAULT_IMPORT_SOURCE,
        prompt_version: str | None = None,
        prompt_id: str | None = None,
    ) -> dict[str, Any]:
        self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        existing = self.db.list_findings(project_id, sources=["ai"])
        batch_id = str(uuid.uuid4())
        parser_report = parse_json_object_with_report(response_text)
        ai_response = parser_report["data"]
        prompt_metadata = prompt_metadata_for_import(self.db, project_id, prompt_id)
        parser_metadata = {
            "schema_version": parser_report.get("schema_version"),
            "parser_mode": parser_report.get("parser_mode"),
            "response_shape": parser_report.get("response_shape"),
            "ai_tool": "manual_chat_prompt",
            "ai_provider": "manual_external",
            "ai_model": None,
            **prompt_metadata,
        }
        preview = build_import_preview(
            project_id=project_id,
            sheets=sheets,
            response=ai_response,
            existing_findings=existing,
            parser_repairs=parser_report["repairs"],
            parser_warnings=parser_report["warnings"],
            batch_id=batch_id,
            prompt_version=prompt_version or CHAT_PROMPT_VERSION,
            source_type=source_type,
            prompt_id=prompt_id,
            parser_metadata=parser_metadata,
        )
        batch = self.db.create_ai_import_batch(
            project_id,
            {
                "id": batch_id,
                "source_type": source_type,
                "prompt_version": prompt_version or CHAT_PROMPT_VERSION,
                "prompt_id": prompt_id,
                "raw_response_text": response_text,
                "parser_warnings": preview["warnings"],
                "parser_repairs": preview["parser_repairs_applied"],
                "candidate_count": preview["total_candidate_updates"],
                "valid_count": preview["valid_recoverable_updates"],
                "skipped_count": preview["skipped_updates"],
                "duplicate_count": preview["duplicate_updates"],
                "import_status": "previewed",
                "preview": preview,
                "metadata": parser_metadata,
            },
        )
        batch_summary = dict(batch)
        batch_summary.pop("preview", None)
        batch_summary = public_ai_import_batch(batch_summary)
        preview["batch"] = batch_summary
        preview["batch_id"] = batch["id"]
        return preview

    def import_manual_response(
        self,
        project_id: str,
        response_text: str,
        source_type: str = DEFAULT_IMPORT_SOURCE,
        prompt_version: str | None = None,
        prompt_id: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_manual_response(project_id, response_text, source_type, prompt_version, prompt_id)
        return self.import_preview(project_id, preview["batch_id"])

    def import_preview(self, project_id: str, preview_id: str) -> dict[str, Any]:
        self.db.get_project(project_id)
        try:
            batch = self.db.get_ai_import_batch(preview_id, project_id=project_id)
        except KeyError as exc:
            raise ValueError("AI import preview not found. Run Preview AI Updates again before importing.") from exc
        if batch.get("import_status") != "previewed":
            raise ValueError(f"AI import preview is {batch.get('import_status')}; run Preview AI Updates again before importing.")
        preview = batch.get("preview") or {}
        if not preview:
            raise ValueError("AI import preview was not found or has expired. Run Preview AI Updates again.")
        ensure_preview_review_coverage_complete(preview)
        ai_findings = [
            item.get("finding")
            for item in preview.get("updates", [])
            if isinstance(item, dict) and item.get("will_import") and isinstance(item.get("finding"), dict)
        ]
        ai_findings = [finding for finding in ai_findings if finding]
        ai_findings = self._enrich_imported_finding_locations(project_id, ai_findings)
        if not ai_findings:
            if preview.get("scoped_review_complete"):
                quality_report = build_import_quality_report(preview, [], self.db.list_sheets(project_id))
                batch_metadata = dict(batch.get("metadata") or {})
                batch_metadata["quality_report"] = quality_report
                batch_metadata["review_coverage"] = preview.get("review_coverage")
                batch_metadata["clean_review_pages"] = clean_pages_from_preview(preview)
                batch = self.db.update_ai_import_batch(
                    preview_id,
                    {
                        "created_count": 0,
                        "updated_count": 0,
                        "duplicate_count": int(preview.get("duplicate_updates") or 0),
                        "import_status": "imported",
                        "metadata": batch_metadata,
                        "imported_at": utc_now_iso_safe(),
                    },
                )
                self.db.insert_project_event(
                    project_id,
                    "review_coverage_confirmed",
                    {
                        "batch_id": preview_id,
                        "review_coverage": preview.get("review_coverage"),
                        "clean_review_pages": clean_pages_from_preview(preview),
                    },
                )
                return {
                    "project": self.db.get_project(project_id),
                    "ai_findings_created": 0,
                    "ai_updates_imported": 0,
                    "raw_ai_count": int(preview.get("total_candidate_updates") or 0),
                    "imported_stable_ids": [],
                    "imported_finding_ids": [],
                    "batch": public_ai_import_batch(batch),
                    "quality_report": quality_report,
                    "findings": self.db.list_findings(project_id, sources=["ai"]),
                }
            raise ValueError("AI import preview contains zero valid updates to import. Run preview again and review the warnings.")
        existing = self.db.list_findings(project_id, sources=["ai"])
        existing_by_stable = {finding.get("stable_id"): finding for finding in existing}
        created_count = sum(1 for finding in ai_findings if finding.get("stable_id") not in existing_by_stable)
        updated_count = sum(1 for finding in ai_findings if finding.get("stable_id") in existing_by_stable)
        try:
            self.db.replace_findings(project_id, merge_existing_ai_findings(existing, ai_findings), sources=["ai"])
            stored_imported = _find_by_stable_ids(self.db.list_findings(project_id, sources=["ai"]), ai_findings)
            quality_report = build_import_quality_report(preview, stored_imported, self.db.list_sheets(project_id))
            batch_metadata = dict(batch.get("metadata") or {})
            batch_metadata["quality_report"] = quality_report
            batch_metadata["review_coverage"] = preview.get("review_coverage")
            batch_metadata["clean_review_pages"] = clean_pages_from_preview(preview)
            batch = self.db.update_ai_import_batch(
                preview_id,
                {
                    "created_count": created_count,
                    "updated_count": updated_count,
                    "duplicate_count": int(preview.get("duplicate_updates") or 0),
                    "import_status": "imported",
                    "metadata": batch_metadata,
                    "imported_at": utc_now_iso_safe(),
                },
            )
        except Exception as exc:
            self._recover_failed_import(
                project_id,
                batch_id=preview_id,
                existing_findings=existing,
                preview=preview,
                metadata=batch.get("metadata") if isinstance(batch.get("metadata"), dict) else {},
                error=exc,
                source_type=batch.get("source_type") or preview.get("source_type") or "unknown",
                prompt_version=batch.get("prompt_version") or preview.get("prompt_version"),
                prompt_id=batch.get("prompt_id"),
                batch_exists=True,
            )
            raise
        self.db.insert_project_event(
            project_id,
            "review_coverage_confirmed",
            {
                "batch_id": preview_id,
                "review_coverage": preview.get("review_coverage"),
                "clean_review_pages": clean_pages_from_preview(preview),
            },
        )
        return {
            "project": self.db.get_project(project_id),
            "ai_findings_created": len(ai_findings),
            "ai_updates_imported": len(ai_findings),
            "raw_ai_count": int(preview.get("total_candidate_updates") or len(ai_findings)),
            "imported_stable_ids": [finding["stable_id"] for finding in ai_findings],
            "imported_finding_ids": [finding["id"] for finding in stored_imported],
            "batch": public_ai_import_batch(batch),
            "quality_report": quality_report,
            "findings": self.db.list_findings(project_id, sources=["ai"]),
        }

    def _enrich_imported_finding_locations(self, project_id: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not findings:
            return findings

        try:
            project = self.db.get_project(project_id)
            source_pdf = require_project_source_pdf_path(self.settings.data_dir, project_id, project.get("source_pdf_path"))
        except Exception:
            return findings

        try:
            with fitz.open(source_pdf) as doc:
                for finding in findings:
                    if finding.get("location"):
                        continue
                    placement = self._calculate_finding_placement(doc, finding)
                    if _placement_has_focus_rect(placement):
                        finding["placement_status"] = placement.get("placement_status")
                        finding["placement_details"] = {key: value for key, value in placement.items() if key != "rect"}
        except Exception:
            return findings

        return findings

    def recalculate_finding_locations(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        source_pdf = require_project_source_pdf_path(self.settings.data_dir, project_id, project.get("source_pdf_path"))
        findings = self.db.list_findings(project_id, sources=["ai"])
        summary = _empty_placement_summary()
        updated_count = 0

        with fitz.open(source_pdf) as doc:
            for finding in findings:
                placement = self._calculate_finding_placement(doc, finding)
                status = str(placement.get("placement_status") or "manual_placement_needed")
                summary[status] = int(summary.get(status, 0)) + 1
                if finding.get("id"):
                    self.db.update_finding_placement(finding["id"], status, {key: value for key, value in placement.items() if key != "rect"})
                    updated_count += 1

        refreshed = self.db.list_findings(project_id, sources=["ai"])
        self.db.insert_project_event(
            project_id,
            "placement_recalculated",
            {"updated_count": updated_count, "summary": summary},
        )
        return {
            "project": project,
            "findings": refreshed,
            "summary": summary,
            "updated_count": updated_count,
            "total_findings": len(findings),
        }

    def _calculate_finding_placement(self, doc: fitz.Document, finding: dict[str, Any]) -> dict[str, Any]:
        try:
            page_number = int(finding.get("page_number") or 0)
        except (TypeError, ValueError):
            return {
                "placement_status": "manual_placement_needed",
                "target_found": False,
                "exported": False,
                "manual_placement_needed": True,
                "method": "invalid_page",
                "note": "Finding has no valid PDF page number.",
            }
        if page_number < 1 or page_number > len(doc):
            return {
                "placement_status": "manual_placement_needed",
                "target_found": False,
                "exported": False,
                "manual_placement_needed": True,
                "method": "invalid_page",
                "note": f"Page {page_number} is outside the source PDF page range.",
            }
        placement = _evidence_search_result(doc[page_number - 1], finding)
        if placement.get("placement_status") in {"exact_target_found", "fuzzy_target_found"}:
            return placement
        has_target = any(_candidate_has_text(evidence) for evidence in finding.get("evidence") or [])
        return {
            "placement_status": "page_level_fallback" if has_target else "manual_placement_needed",
            "target_found": False,
            "exported": False,
            "manual_placement_needed": True,
            "method": "page_note" if has_target else "missing_target_text",
            "note": "Target text was not found; finding remains page-level." if has_target else "No target text was available for placement.",
        }

    def review_project(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        entities = self.db.list_entities(project_id)
        existing = self.db.list_findings(project_id, sources=["ai"])
        payload = build_ai_payload(project, sheets, entities, existing, self.settings.ai_max_sheets)
        ai_response = self.client.review(payload)
        batch_id = str(uuid.uuid4())
        direct_cap_applied = len(payload.get("sheets") or []) < len(sheets)
        sent_pages = [
            int(sheet.get("page_number"))
            for sheet in payload.get("sheets") or []
            if _positive_int(sheet.get("page_number"))
        ]
        direct_warnings = [
            "Direct AI Review is experimental and text-context-only. It is not equivalent to the manual PDF-attached Chat Prompt workflow.",
        ]
        if direct_cap_applied:
            direct_warnings.append(
                f"Direct AI Review sent {len(payload.get('sheets') or [])} of {len(sheets)} sheets because AUTOQC_AI_MAX_SHEETS is {self.settings.ai_max_sheets}."
            )
        parser_metadata = {
            "schema_version": schema_version_from_response(ai_response),
            "parser_mode": "direct_ai_response",
            "response_shape": response_shape_from_response(ai_response),
            "review_scope": "batch" if direct_cap_applied else "package",
            "scope_pages": sent_pages if direct_cap_applied else [],
            "source_of_truth": "extracted_text_context",
            "ai_tool": "direct_ai_review",
            "ai_provider": self.settings.ai_provider or "openai",
            "ai_model": self.settings.ai_model or None,
            "direct_review_mode": "text_context_only",
            "direct_review_warning": direct_warnings[0],
            "direct_review_sheet_limit_applied": direct_cap_applied,
            "direct_review_sent_sheet_count": len(payload.get("sheets") or []),
            "direct_review_total_sheet_count": len(sheets),
            "direct_review_sent_pages": sent_pages,
            "ai_max_sheets": self.settings.ai_max_sheets,
        }
        preview = build_import_preview(
            project_id=project_id,
            sheets=sheets,
            response=ai_response,
            existing_findings=existing,
            parser_repairs=[],
            parser_warnings=direct_warnings,
            batch_id=batch_id,
            prompt_version="direct_ai_review",
            source_type="direct_ai",
            prompt_id=None,
            parser_metadata=parser_metadata,
        )
        ensure_preview_review_coverage_complete(preview)
        ai_findings = [
            item["finding"]
            for item in preview.get("updates", [])
            if isinstance(item, dict) and item.get("will_import") and isinstance(item.get("finding"), dict)
        ]
        ai_findings = self._enrich_imported_finding_locations(project_id, ai_findings)
        quality_report = build_import_quality_report(preview, ai_findings, sheets)
        batch_metadata = {
            **parser_metadata,
            "warnings": direct_warnings,
            "quality_report": quality_report,
            "review_coverage": preview.get("review_coverage"),
            "clean_review_pages": clean_pages_from_preview(preview),
        }
        batch_payload = {
            "id": batch_id,
            "source_type": "direct_ai",
            "prompt_version": "direct_ai_review",
            "raw_response_text": json.dumps(ai_response, ensure_ascii=True),
            "parser_warnings": preview["warnings"],
            "parser_repairs": preview["parser_repairs_applied"],
            "candidate_count": preview["total_candidate_updates"],
            "valid_count": preview["valid_recoverable_updates"],
            "skipped_count": preview["skipped_updates"],
            "created_count": sum(1 for finding in ai_findings if finding.get("stable_id") not in {item.get("stable_id") for item in existing}),
            "updated_count": sum(1 for finding in ai_findings if finding.get("stable_id") in {item.get("stable_id") for item in existing}),
            "duplicate_count": preview["duplicate_updates"],
            "import_status": "imported",
            "imported_at": utc_now_iso_safe(),
            "preview": preview,
            "metadata": batch_metadata,
        }
        try:
            self.db.replace_findings(project_id, merge_existing_ai_findings(existing, ai_findings), sources=["ai"])
            batch = self.db.create_ai_import_batch(project_id, batch_payload)
        except Exception as exc:
            self._recover_failed_import(
                project_id,
                batch_id=batch_id,
                existing_findings=existing,
                preview=preview,
                metadata=batch_metadata,
                error=exc,
                source_type="direct_ai",
                prompt_version="direct_ai_review",
                prompt_id=None,
                batch_exists=False,
                raw_response_text=batch_payload["raw_response_text"],
            )
            raise
        stored_imported = _find_by_stable_ids(self.db.list_findings(project_id, sources=["ai"]), ai_findings)
        return {
            "project": self.db.get_project(project_id),
            "direct_review_mode": "text_context_only",
            "direct_review_sheet_limit_applied": direct_cap_applied,
            "direct_review_sent_sheet_count": len(payload.get("sheets") or []),
            "direct_review_total_sheet_count": len(sheets),
            "warnings": direct_warnings,
            "ai_findings_created": len(ai_findings),
            "ai_updates_imported": len(ai_findings),
            "raw_ai_count": len(coerce_findings(ai_response)),
            "imported_stable_ids": [finding["stable_id"] for finding in ai_findings],
            "imported_finding_ids": [finding["id"] for finding in stored_imported],
            "batch": public_ai_import_batch(batch),
            "quality_report": quality_report,
            "findings": self.db.list_findings(project_id, sources=["ai"]),
        }

    def _recover_failed_import(
        self,
        project_id: str,
        *,
        batch_id: str,
        existing_findings: list[dict[str, Any]],
        preview: dict[str, Any],
        metadata: dict[str, Any],
        error: Exception,
        source_type: str,
        prompt_version: str | None,
        prompt_id: str | None,
        batch_exists: bool,
        raw_response_text: str | None = None,
    ) -> None:
        failed_at = utc_now_iso_safe()
        failure_metadata = {
            **(metadata or {}),
            "import_failure": {
                "message": str(error),
                "failed_at": failed_at,
                "recovery": "restored_prior_ai_findings",
            },
            "review_coverage": preview.get("review_coverage"),
        }
        try:
            self.db.replace_findings(project_id, existing_findings, sources=["ai"])
        except Exception:
            failure_metadata["import_failure"]["recovery"] = "restore_prior_ai_findings_failed"
        try:
            if batch_exists:
                self.db.update_ai_import_batch(
                    batch_id,
                    {
                        "import_status": "failed",
                        "metadata": failure_metadata,
                    },
                )
            else:
                self.db.create_ai_import_batch(
                    project_id,
                    {
                        "id": batch_id,
                        "source_type": source_type,
                        "prompt_version": prompt_version,
                        "prompt_id": prompt_id,
                        "raw_response_text": raw_response_text,
                        "parser_warnings": preview.get("warnings") or [],
                        "parser_repairs": preview.get("parser_repairs_applied") or [],
                        "candidate_count": preview.get("total_candidate_updates") or 0,
                        "valid_count": preview.get("valid_recoverable_updates") or 0,
                        "skipped_count": preview.get("skipped_updates") or 0,
                        "duplicate_count": preview.get("duplicate_updates") or 0,
                        "import_status": "failed",
                        "preview": preview,
                        "metadata": failure_metadata,
                    },
                )
            self.db.insert_project_event(
                project_id,
                "ai_import_failed",
                {"batch_id": batch_id, "source_type": source_type, "message": str(error)},
            )
        except Exception:
            pass


def public_ai_import_batch(batch: dict[str, Any]) -> dict[str, Any]:
    item = dict(batch)
    raw = item.pop("raw_response_text", None)
    raw_text = raw if isinstance(raw, str) else ""
    item["raw_response_stored"] = bool(raw_text)
    item["raw_response_length"] = len(raw_text)
    item["raw_response_sha256"] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else None
    return item


def _find_by_stable_ids(stored_findings: list[dict[str, Any]], imported_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    imported_stable_ids = {finding["stable_id"] for finding in imported_findings}
    return [finding for finding in stored_findings if finding.get("stable_id") in imported_stable_ids]


def ensure_preview_review_coverage_complete(preview: dict[str, Any]) -> None:
    coverage = preview.get("review_coverage") if isinstance(preview.get("review_coverage"), dict) else preview
    status = str(coverage.get("review_coverage_status") or "not_confirmed")
    if status == "complete":
        return
    missing = coverage.get("missing_review_pages") or []
    incomplete = coverage.get("incomplete_review_pages") or []
    not_readable = coverage.get("not_readable_pages") or []
    details = []
    if missing:
        details.append(f"missing reviewed_pages confirmation for pages {format_page_list([int(page) for page in missing])}")
    if incomplete:
        details.append(f"incomplete pages {format_page_list([int(page) for page in incomplete])}")
    if not_readable:
        details.append(f"not-readable pages {format_page_list([int(page) for page in not_readable])}")
    if not details:
        details.append("reviewed_pages was not confirmed")
    raise ValueError(
        "AI import blocked because review coverage is "
        f"{status}. AutoQC requires every expected page to be listed in reviewed_pages with review_status complete before import. "
        + "; ".join(details)
        + "."
    )


def prompt_metadata_for_import(db: Database, project_id: str, prompt_id: str | None) -> dict[str, Any]:
    if not prompt_id:
        return {}
    try:
        prompt_run = db.get_ai_prompt_run(prompt_id, project_id=project_id)
    except KeyError:
        return {}
    metadata = prompt_run.get("metadata") if isinstance(prompt_run.get("metadata"), dict) else {}
    return {
        key: metadata.get(key)
        for key in [
            "prompt_template_id",
            "prompt_template_name",
            "prompt_template_version",
            "review_strategy",
            "review_scope",
            "scope_pages",
            "scope_label",
            "scope_sheet_count",
            "batch_size",
            "batch_index",
            "batch_count",
            "deep_dive_reason",
        ]
        if metadata.get(key)
    }


def merge_existing_ai_findings(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    incoming_stable_ids = {finding["stable_id"] for finding in incoming}
    return [finding for finding in existing if finding.get("stable_id") not in incoming_stable_ids] + incoming


SYSTEM_PROMPT = """You are an expert natural gas drawing QC reviewer using extracted text context only. Return only valid JSON with reviewed_pages and a top-level updates array. Identify drawing updates needed; do not write finished markup comments. Create specific, evidence-backed updates only. Avoid repeated title-block, parser, or OCR noise. Every update must include issue, severity, category, page_number, target_text, required_update, rationale, and confidence. Every reviewed page must be listed in reviewed_pages with review_status complete, incomplete, or not_readable."""


def build_ai_payload(
    project: dict[str, Any],
    sheets: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    existing_findings: list[dict[str, Any]],
    max_sheets: int,
    scope_pages: list[int] | None = None,
    review_scope: str = "package",
) -> dict[str, Any]:
    sheet_payload = []
    scope_set = {int(page) for page in scope_pages or []}
    selected_sheets = [
        sheet
        for sheet in sheets
        if not scope_set or int(sheet.get("page_number") or 0) in scope_set
    ][:max_sheets]
    for sheet in selected_sheets:
        sheet_payload.append(
            {
                "sheet_id": sheet.get("id"),
                "page_number": sheet.get("page_number"),
                "drawing_number": sheet.get("drawing_number"),
                "sheet_title": sheet.get("sheet_title"),
                "revision": sheet.get("revision"),
                "sheet_type": sheet.get("sheet_type"),
                "extraction_status": sheet.get("extraction_status"),
                "ocr_status": sheet.get("ocr_status"),
                "text": trim_text(sheet.get("text_content") or "", 6500),
            }
        )
    return {
        "task": "Perform an expert AI QC review of a natural gas drawing package. Return only JSON drawing updates.",
        "project": {"id": project.get("id"), "name": project.get("name"), "sheet_count": len(sheets)},
        "scope": {
            "review_scope": review_scope,
            "scope_pages": sorted(scope_set),
            "scope_sheet_count": len(selected_sheets),
            "full_package_sheet_count": len(sheets),
        },
        "review_guidance": {
            "find": [
                "real discrepancies between sheets, tags, notes, and drawing references",
                "misspellings, grammar issues, ambiguous notes, duplicate notes, and unclear construction requirements",
                "natural gas engineering concerns around regulator stations, overpressure protection, bypasses, vents, drains, sensing lines, and instrumentation",
            ],
            "avoid": [
                "generic comments",
                "repeated comments for the same issue",
                "title-block spam based only on UNKNOWN parser values",
                "updates without target text or a page number",
            ],
        },
        "schema": {
            "updates": [
                {
                    "issue": "short description of the issue",
                    "severity": "Critical | Major | Minor | Note",
                    "category": "drafting quality | drawing coordination | title block and revision | notes and specifications | instrumentation | overpressure protection | safety and operability | regulator station design | missing information | human review needed",
                    "page_number": 1,
                    "target_text": "exact quote/callout/note from the drawing",
                    "required_update": "specific update needed on the drawing",
                    "rationale": "why this update is needed",
                    "confidence": 0.0,
                }
            ]
        },
        "sheets": sheet_payload,
        "entities_sample": [
            {
                "type": item.get("entity_type"),
                "text": item.get("text"),
                "normalized_text": item.get("normalized_text"),
                "page_number": item.get("page_number"),
            }
            for item in entities
            if not scope_set or int(item.get("page_number") or 0) in scope_set
        ][:250],
        "existing_findings_summary": [
            {"title": item.get("title"), "page_number": item.get("page_number"), "comment_text": item.get("comment_text")}
            for item in existing_findings
            if not scope_set or int(item.get("page_number") or 0) in scope_set
        ][:80],
    }


def build_manual_prompt(
    payload: dict[str, Any],
    prompt_run: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
    markup_memory_context: dict[str, Any] | None = None,
    sheet_evidence_context: dict[str, Any] | None = None,
    review_depth: dict[str, str] | None = None,
    scope: dict[str, Any] | None = None,
) -> str:
    context = manual_prompt_context(payload)
    template = template or {}
    if prompt_run:
        context["prompt"] = {
            "prompt_id": prompt_run.get("id"),
            "prompt_version": prompt_run.get("prompt_version"),
            "generated_at": prompt_run.get("generated_at"),
            "included_full_extracted_text": False,
            "prompt_template": {
                "id": template.get("id"),
                "name": template.get("name"),
                "version": template.get("version") or prompt_run.get("prompt_version"),
            },
        }
    review_priorities = template.get("review_priorities") if isinstance(template.get("review_priorities"), list) else []
    priority_lines = "\n".join(f"- {clean_text(item, '', 600)}" for item in review_priorities if str(item).strip())
    if not priority_lines:
        priority_lines = (
            "- Discrepancies between sheets, tags, notes, references, and drawing callouts.\n"
            "- Misspellings, grammar issues, unclear notes, duplicate notes, and conflicting requirements.\n"
            "- Natural gas regulator station review items only when visible evidence exists in the attached PDF."
        )
    review_depth = review_depth or normalize_prompt_depth(template.get("review_depth") if template else None)
    memory_section = ""
    if markup_memory_context and markup_memory_context.get("enabled") and markup_memory_context.get("prompt_section"):
        memory_section = f"\n\n{markup_memory_context['prompt_section']}\n"
    sheet_evidence_section = ""
    if sheet_evidence_context and sheet_evidence_context.get("included") and sheet_evidence_context.get("prompt_section"):
        sheet_evidence_section = f"\n\n{sheet_evidence_context['prompt_section']}\n"
    scope = scope or {
        "review_scope": str((payload.get("scope") or {}).get("review_scope") or "package"),
        "scope_pages": (payload.get("scope") or {}).get("scope_pages") or [],
        "scope_label": "Full package",
    }
    scope_section = build_scope_prompt_section(scope)
    return (
        "You are acting as the AI Deep Manual Review engine for AutoQC, a natural gas drawing QC tracker. This prompt is intended to be pasted into ChatGPT or Copilot Chat.\n"
        f"Prompt version: {context.get('prompt', {}).get('prompt_version', CHAT_PROMPT_VERSION)}.\n\n"
        f"Prompt template: {template.get('name', 'Default AutoQC Deep Review prompt')} ({template.get('id', 'default-deep-review')}).\n\n"
        f"Review depth: {review_depth['label']}. {review_depth['instruction']}\n"
        "Review every visible sheet, note, callout, table, title block, revision block, plan, detail, section, diagram, PFD, P&ID, BOM, legend, symbol, and drawing reference in the attached PDF package.\n"
        "Do not triage, sample, skim, or only review high-risk sheets.\n\n"
        "IMPORTANT: The actual drawing package PDF must be attached/uploaded to this chat. Review the attached PDF package itself. Do not rely on this prompt alone as the drawing source of truth.\n\n"
        f"{scope_section}\n"
        "Return ONLY valid JSON. Do not use markdown. Do not include commentary before or after the JSON.\n\n"
        "Your job is to identify drawing updates needed. Do not write finished PDF markup comments. AutoQC will convert your updates into markups after I paste your JSON back into the app.\n\n"
        "Review priorities:\n"
        f"{priority_lines}\n\n"
        "MANDATORY REVIEW METHOD:\n"
        "You must perform a deep manual-style review of the entire attached PDF package, regardless of sheet count.\n\n"
        "For every sheet in the package:\n\n"
        "1. Read the extracted page text for the entire sheet.\n"
        "2. Visually inspect the rendered sheet image.\n"
        "3. Review the title block, drawing number, sheet title, revision, issue date, revision block, clouds, triangles, and visible sheet identifiers.\n"
        "4. Review all visible notes, callouts, tables, legends, references, bubbles, tags, symbols, dimensions, labels, and section/detail references.\n"
        "5. Compare the extracted text against the visible sheet image before reporting issues.\n"
        "6. Only report issues with visible evidence on the attached PDF sheet.\n"
        "7. Do not skip sheets because the package is long.\n"
        "8. Do not rely only on text extraction for sheets with diagrams, plans, tables, title blocks, PFDs, P&IDs, or visual coordination information.\n"
        "9. Do not rely only on the rendered image when extracted text is available for notes or tables.\n"
        "10. If you cannot review every sheet with both extracted text and visual inspection, return an incomplete-review error instead of producing partial findings.\n\n"
        "PACKAGE-LEVEL REVIEW METHOD:\n"
        "After reviewing sheets individually, perform cross-sheet coordination checks across the full package:\n\n"
        "1. Drawing references and sheet references.\n"
        "2. Section/detail callouts and destination details.\n"
        "3. Tags, line numbers, equipment identifiers, valve numbers, instrument tags, SCADA tags, regulator tags, relief/OPP references, and BOM item numbers.\n"
        "4. General notes versus plans/details/PFD/P&ID requirements.\n"
        "5. Sheet index, drawing titles, drawing numbers, revision information, and visible title block consistency.\n"
        "6. PFD/P&ID/plan/detail/isometric/BOM coordination.\n"
        "7. Civil, mechanical, structural, electrical, environmental, and permitting coordination where visible.\n"
        "8. Duplicate, stale, conflicting, or copy-pasted notes across sheets.\n"
        "9. Missing or inconsistent references only when visibly supported by the attached PDF.\n\n"
        "HARD NO-TRIAGE RULE:\n"
        "Do not say or imply that long packages require prioritization. Do not review only likely issue sheets. Do not skip low-risk sheets. Do not only review notes sheets, P&IDs, or plans. Every sheet must receive the same baseline review method: extracted text review plus rendered visual inspection.\n\n"
        "INCOMPLETE REVIEW RULE:\n"
        "If the PDF package is not attached, not readable, only partially accessible, too large to inspect completely, missing rendered page images, missing usable extracted text for critical text-heavy sheets, or otherwise cannot be reviewed sheet-by-sheet using the mandatory review method, return this JSON exactly:\n\n"
        "{\n"
        "\"schema_version\": \"autoqc-ai-updates-v1\",\n"
        "\"updates\": [],\n"
        "\"error\": \"Full exhaustive manual-style review could not be completed. Attach a readable PDF package or split the package into smaller review batches.\"\n"
        "}\n\n"
        "If the package is readable but too long to complete in one response, do not provide partial findings. Return the incomplete-review error above.\n\n"
        "Source-of-truth rules:\n"
        "- The attached PDF is the source of truth.\n"
        "- AutoQC context, metadata, sheet index, parser output, OCR status, and UNKNOWN values are navigation only.\n"
        "- Do not report OCR, parser, extraction-quality, or UNKNOWN metadata issues as drawing updates.\n"
        "- Title block/revision issues only when visibly supported by the attached PDF.\n"
        "- Every update must have page_number.\n"
        "- Every update must have target_text copied exactly from the attached PDF.\n"
        "- Every response must include reviewed_pages for the requested scope so AutoQC can tell reviewed-clean pages from skipped pages.\n"
        "- Only report issues supported by visible evidence.\n"
        "- Do not invent code requirements, company standards, missing equipment, missing sheets, design defects, or title-block problems from general expectations.\n"
        "- If evidence is uncertain, either skip the item or use category \"human review needed\" with a clear uncertainty rationale.\n"
        "- If there are no good updates after completing the full exhaustive review, return:\n"
        "  {\"schema_version\": \"autoqc-ai-updates-v1\", \"updates\": [], \"reviewed_pages\": [{\"page_number\": 1, \"review_status\": \"complete\", \"issue_count\": 0}]}\n\n"
        f"{memory_section}"
        f"{sheet_evidence_section}"
        "Required response schema:\n"
        "{\n"
        "  \"schema_version\": \"autoqc-ai-updates-v1\",\n"
        "  \"reviewed_pages\": [\n"
        "    {\n"
        "      \"page_number\": 1,\n"
        "      \"review_status\": \"complete | incomplete | not_readable\",\n"
        "      \"issue_count\": 0,\n"
        "      \"notes\": \"optional short note if incomplete or not_readable\"\n"
        "    }\n"
        "  ],\n"
        "  \"updates\": [\n"
        "    {\n"
        "      \"issue\": \"short description of the issue\",\n"
        "      \"severity\": \"Critical | Major | Minor | Note\",\n"
        "      \"category\": \"drafting quality | drawing coordination | title block and revision | notes and specifications | instrumentation | overpressure protection | safety and operability | regulator station design | missing information | human review needed\",\n"
        "      \"page_number\": 1,\n"
        "      \"target_text\": \"exact text/callout/note from the attached PDF that needs to change\",\n"
        "      \"required_update\": \"specific update needed on the drawing\",\n"
        "      \"rationale\": \"why this update is needed\",\n"
        "      \"confidence\": 0.0\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "AI RESPONSE SELF-CHECK BEFORE FINAL JSON:\nBefore returning JSON, silently verify:\n\n"
        "1. Every sheet in the attached PDF was reviewed using both extracted text and visual inspection.\n"
        "2. Every update is supported by visible evidence in the attached PDF.\n"
        "3. Every update has page_number.\n"
        "4. Every update has exact target_text copied from the attached PDF.\n"
        "5. Every update has required_update and rationale.\n"
        "6. reviewed_pages includes every requested page in this prompt's scope.\n"
        "7. No update relies only on parser metadata, sheet index data, OCR/extraction status, or UNKNOWN metadata.\n"
        "8. No update relies on unsupported assumptions, invented code requirements, invented company standards, or design expectations not visibly supported by the attached PDF.\n"
        "9. No title block/revision item is included unless visibly supported in the attached PDF.\n"
        "10. No issue is included merely because a checklist item is generally expected.\n"
        "11. If the full manual-style review was not completed for every requested page, return the incomplete-review error instead of partial findings.\n\n"
        "Minimal AutoQC project context only, not the drawing source of truth:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Final reminder: Use the attached PDF, not the sheet index, as evidence. Return only the JSON object with the updates array."
    )


def normalize_prompt_depth(value: Any) -> dict[str, str]:
    if value is None:
        return PROMPT_DEPTH_OPTIONS["exhaustive"]
    text = str(value or "standard").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "fast-review": "fast",
        "fast": "fast",
        "standard-review": "standard",
        "standard": "standard",
        "comprehensive-review": "comprehensive",
        "comprehensive": "comprehensive",
        "exhaustive-manual-style-review": "exhaustive",
        "exhaustive-deep-review": "exhaustive",
        "exhaustive": "exhaustive",
        "deep": "exhaustive",
    }
    key = aliases.get(text, "standard")
    return PROMPT_DEPTH_OPTIONS[key]


def manual_prompt_context(payload: dict[str, Any]) -> dict[str, Any]:
    sheets = payload.get("sheets") if isinstance(payload.get("sheets"), list) else []
    return {
        "project": payload.get("project") if isinstance(payload.get("project"), dict) else {},
        "attachment_required": True,
        "instruction": "Attach/upload the actual drawing package PDF to ChatGPT or Copilot Chat with this prompt.",
        "sheet_index": [
            {
                "page_number": sheet.get("page_number"),
                "drawing_number": sheet.get("drawing_number"),
                "sheet_title": sheet.get("sheet_title"),
                "revision": sheet.get("revision"),
                "sheet_type": sheet.get("sheet_type"),
            }
            for sheet in sheets
        ],
        "scope": payload.get("scope") if isinstance(payload.get("scope"), dict) else {"review_scope": "package"},
    }


def build_scope_prompt_section(scope: dict[str, Any]) -> str:
    review_scope = str(scope.get("review_scope") or "package")
    pages = [int(page) for page in scope.get("scope_pages") or [] if _positive_int(page)]
    label = str(scope.get("scope_label") or format_scope_label(pages) or "Full package")
    if review_scope == "sheet" and pages:
        reasons = scope.get("deep_dive_reason")
        reason_text = f" Deep-dive reason: {reasons}." if reasons else ""
        return (
            "SCOPED REVIEW MODE: Single-sheet deep dive.\n"
            f"Review only PDF page {pages[0]} ({label}). The full PDF is attached only for navigation and cross-reference context.\n"
            "Slow down on this one sheet. Check spelling, notes, tables, references, tags, title block, revisions, callouts, dimensions, symbols, and visible coordination issues.\n"
            "Do not return updates from other pages unless the cited target_text is on this requested page."
            f"{reason_text}\n"
            f"reviewed_pages must include page {pages[0]} with review_status complete, incomplete, or not_readable."
        )
    if review_scope == "batch" and pages:
        return (
            "SCOPED REVIEW MODE: Adaptive page batch.\n"
            f"Review only these PDF pages: {format_page_list(pages)} ({label}). The full PDF is attached only for navigation and cross-reference context.\n"
            "Use other pages only to verify references from the requested pages. Do not report updates whose target_text is outside the requested page list.\n"
            "Review each requested page independently enough that reviewed_pages can confirm every requested page."
        )
    return (
        "SCOPED REVIEW MODE: Whole package.\n"
        "Review the entire attached PDF package. For very large packages, AutoQC may instead generate adaptive batch or single-sheet prompts to improve recall."
    )


def resolve_manual_review_scope(
    sheets: list[dict[str, Any]],
    review_scope: str | None,
    page_number: int | None,
    page_numbers: str | list[int] | None,
    batch_size: int | None,
) -> dict[str, Any]:
    sorted_sheets = sorted(sheets, key=lambda item: int(item.get("page_number") or 0))
    valid_pages = [int(sheet.get("page_number") or 0) for sheet in sorted_sheets if _positive_int(sheet.get("page_number"))]
    valid_page_set = set(valid_pages)
    normalized_scope = normalize_review_scope(review_scope)
    normalized_batch_size = normalize_manual_batch_size(batch_size)
    parsed_pages = parse_page_numbers(page_numbers)
    if page_number is not None:
        parsed_pages = [int(page_number), *parsed_pages]
    parsed_pages = [page for page in list(dict.fromkeys(parsed_pages)) if page in valid_page_set]

    if normalized_scope == "sheet":
        if not parsed_pages:
            raise ValueError("Choose a PDF page number before generating a single-sheet deep-dive prompt.")
        page = parsed_pages[0]
        sheet = next((item for item in sorted_sheets if int(item.get("page_number") or 0) == page), None)
        return {
            "review_scope": "sheet",
            "review_strategy": "single_sheet_deep_dive",
            "scope_pages": [page],
            "scope_label": sheet_scope_label(sheet, [page]),
            "batch_size": 1,
            "batch_index": None,
            "batch_count": None,
            "deep_dive_reason": deep_dive_reason_text(sheet, []),
        }

    if normalized_scope == "batch":
        if not parsed_pages:
            parsed_pages = valid_pages[:normalized_batch_size]
        if not parsed_pages:
            raise ValueError("No valid PDF pages were available for the batch prompt.")
        batches = chunk_pages(valid_pages, normalized_batch_size)
        batch_index = next((index for index, batch in enumerate(batches, start=1) if parsed_pages[0] in batch), None)
        return {
            "review_scope": "batch",
            "review_strategy": "adaptive_batch_review",
            "scope_pages": parsed_pages,
            "scope_label": format_scope_label(parsed_pages),
            "batch_size": normalized_batch_size,
            "batch_index": batch_index,
            "batch_count": len(batches),
            "deep_dive_reason": None,
        }

    return {
        "review_scope": "package",
        "review_strategy": "sheet_by_sheet_deep_dive_single_output",
        "scope_pages": [],
        "scope_label": "Full package",
        "batch_size": normalized_batch_size,
        "batch_index": None,
        "batch_count": len(chunk_pages(valid_pages, normalized_batch_size)),
        "deep_dive_reason": None,
    }


def build_hybrid_review_plan(
    project_id: str,
    sheets: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    import_batches: list[dict[str, Any]],
    batch_size: int | None = None,
) -> dict[str, Any]:
    normalized_batch_size = normalize_manual_batch_size(batch_size)
    sorted_sheets = sorted(sheets, key=lambda item: int(item.get("page_number") or 0))
    pages = [int(sheet.get("page_number") or 0) for sheet in sorted_sheets if _positive_int(sheet.get("page_number"))]
    page_statuses = page_review_statuses(import_batches)
    page_updates = pages_with_imported_or_importable_updates(import_batches)
    batches = []
    for index, page_group in enumerate(chunk_pages(pages, normalized_batch_size), start=1):
        reviewed = [page for page in page_group if page_statuses.get(page) == "reviewed"]
        status = "reviewed" if len(reviewed) == len(page_group) else "partial" if reviewed else "unreviewed"
        batches.append(
            {
                "id": f"batch-{index:03d}",
                "label": format_scope_label(page_group),
                "page_numbers": page_group,
                "batch_index": index,
                "batch_count": len(chunk_pages(pages, normalized_batch_size)),
                "status": status,
                "reviewed_pages": reviewed,
            }
        )

    entities_by_page: dict[int, int] = {}
    for entity in entities:
        page = _positive_int(entity.get("page_number"))
        if page:
            entities_by_page[page] = entities_by_page.get(page, 0) + 1

    deep_dive_candidates = []
    for sheet in sorted_sheets:
        page = _positive_int(sheet.get("page_number"))
        if not page:
            continue
        reasons = deep_dive_reasons(sheet, entities_by_page.get(page, 0))
        if reasons and page_statuses.get(page) == "reviewed" and page not in page_updates and any("text-heavy" in reason for reason in reasons):
            reasons.append("prior batch returned no updates for this dense page")
        if not reasons:
            continue
        deep_dive_candidates.append(
            {
                "sheet_id": sheet.get("id"),
                "page_number": page,
                "drawing_number": sheet.get("drawing_number"),
                "sheet_title": sheet.get("sheet_title"),
                "sheet_type": sheet.get("sheet_type"),
                "label": sheet_scope_label(sheet, [page]),
                "reasons": reasons,
                "score": len(reasons),
                "status": "reviewed" if page_statuses.get(page) == "sheet_reviewed" else "unreviewed",
            }
        )

    reviewed_pages = sorted(page for page, status in page_statuses.items() if status in {"reviewed", "sheet_reviewed"})
    review_coverage = project_review_coverage_summary(sheets, import_batches)
    return {
        "project_id": project_id,
        "sheet_count": len(sorted_sheets),
        "batch_size": normalized_batch_size,
        "batches": batches,
        "deep_dive_candidates": sorted(deep_dive_candidates, key=lambda item: (-int(item.get("score") or 0), int(item.get("page_number") or 0))),
        "reviewed_pages": reviewed_pages,
        "unreviewed_pages": [page for page in pages if page not in reviewed_pages],
        "review_coverage": review_coverage,
        "review_coverage_status": review_coverage["review_coverage_status"],
        "review_coverage_percent": review_coverage["review_coverage_percent"],
    }


def normalize_review_scope(value: str | None) -> str:
    normalized = str(value or "package").strip().lower().replace("_", "-")
    if normalized in {"adaptive", "adaptive-batch", "batch", "batches"}:
        return "batch"
    if normalized in {"page", "single", "sheet", "single-sheet", "deep-dive"}:
        return "sheet"
    return "package"


def normalize_manual_batch_size(value: int | None) -> int:
    try:
        size = int(value or DEFAULT_MANUAL_BATCH_SIZE)
    except (TypeError, ValueError):
        size = DEFAULT_MANUAL_BATCH_SIZE
    if size in ALLOWED_MANUAL_BATCH_SIZES:
        return size
    return min(ALLOWED_MANUAL_BATCH_SIZES, key=lambda allowed: abs(allowed - size))


def parse_page_numbers(value: str | list[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.findall(r"\d+", str(value))
    pages: list[int] = []
    for raw in raw_values:
        page = _positive_int(raw)
        if page and page not in pages:
            pages.append(page)
    return pages


def chunk_pages(pages: list[int], batch_size: int) -> list[list[int]]:
    if batch_size <= 0:
        batch_size = DEFAULT_MANUAL_BATCH_SIZE
    return [pages[index : index + batch_size] for index in range(0, len(pages), batch_size)]


def format_page_list(pages: list[int]) -> str:
    return ", ".join(str(page) for page in pages)


def format_scope_label(pages: list[int]) -> str:
    if not pages:
        return "Full package"
    if len(pages) == 1:
        return f"Page {pages[0]}"
    return f"Pages {pages[0]}-{pages[-1]}" if pages == list(range(pages[0], pages[-1] + 1)) else f"Pages {format_page_list(pages)}"


def sheet_scope_label(sheet: dict[str, Any] | None, pages: list[int]) -> str:
    if not sheet:
        return format_scope_label(pages)
    drawing_number = str(sheet.get("drawing_number") or "").strip()
    title = str(sheet.get("sheet_title") or "").strip()
    label = format_scope_label(pages)
    if drawing_number and drawing_number.upper() not in {"UNKNOWN", "N/A", "NA"}:
        label = f"{label} {drawing_number}"
    if title and title.lower() not in {"unknown", "unknown sheet"}:
        label = f"{label} - {title}"
    return label


def deep_dive_reason_text(sheet: dict[str, Any] | None, fallback: list[str]) -> str | None:
    reasons = deep_dive_reasons(sheet or {}, 0) or fallback
    return "; ".join(reasons) if reasons else None


def deep_dive_reasons(sheet: dict[str, Any], entity_count: int) -> list[str]:
    text = str(sheet.get("text_content") or "")
    sheet_type = str(sheet.get("sheet_type") or "").lower()
    extraction_status = str(sheet.get("extraction_status") or "").lower()
    ocr_status = str(sheet.get("ocr_status") or "").lower()
    reasons: list[str] = []
    if len(text) >= TEXT_HEAVY_DEEP_DIVE_CHARS:
        reasons.append("text-heavy sheet")
    if sheet_type in DEEP_DIVE_SHEET_TYPES:
        reasons.append(f"{sheet_type} sheet type")
    if table_heavy_text(text):
        reasons.append("BOM/table-heavy content")
    if titleblock_revision_heavy_text(text):
        reasons.append("title-block/revision-heavy content")
    if entity_count >= HIGH_ENTITY_DEEP_DIVE_COUNT:
        reasons.append("high tag/reference count")
    if extraction_status in {"no_text", "weak_text", "failed"} or ocr_status in {"ocr_unavailable", "failed"}:
        reasons.append("weak extraction/OCR status")
    return list(dict.fromkeys(reasons))


def table_heavy_text(text: str) -> bool:
    lower = text.lower()
    if any(token in lower for token in ["bill of material", "bill of materials", "bom", "item no", "qty", "quantity"]):
        return True
    return len(re.findall(r"\b(?:item|qty|quantity|description|material|size|spec)\b", lower)) >= 8


def titleblock_revision_heavy_text(text: str) -> bool:
    lower = text.lower()
    return len(re.findall(r"\b(?:revision|rev|date|drawn|checked|approved|title block|sheet title|drawing no)\b", lower)) >= 6


def page_review_statuses(import_batches: list[dict[str, Any]]) -> dict[int, str]:
    statuses: dict[int, str] = {}
    for batch in import_batches:
        if batch.get("import_status") != "imported":
            continue
        metadata = batch.get("metadata") if isinstance(batch.get("metadata"), dict) else {}
        preview = batch.get("preview") if isinstance(batch.get("preview"), dict) else {}
        review_scope = str(metadata.get("review_scope") or preview.get("review_scope") or "")
        for page in reviewed_pages_from_preview(preview):
            statuses[page] = "sheet_reviewed" if review_scope == "sheet" else "reviewed"
    return statuses


def reviewed_pages_from_preview(preview: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    coverage = preview.get("review_coverage") if isinstance(preview.get("review_coverage"), dict) else {}
    for page in coverage.get("reviewed_pages_confirmed") or []:
        page_number = _positive_int(page)
        if page_number and page_number not in pages:
            pages.append(page_number)
    if pages:
        return pages
    for item in preview.get("reviewed_pages") or []:
        if not isinstance(item, dict):
            continue
        page = _positive_int(item.get("page_number"))
        status = str(item.get("review_status") or "").lower()
        if page and status == "complete" and page not in pages:
            pages.append(page)
    return pages


def pages_with_imported_or_importable_updates(import_batches: list[dict[str, Any]]) -> set[int]:
    pages: set[int] = set()
    for batch in import_batches:
        preview = batch.get("preview") if isinstance(batch.get("preview"), dict) else {}
        for update in preview.get("updates") or []:
            if isinstance(update, dict) and update.get("will_import") and _positive_int(update.get("page_number")):
                pages.add(int(update["page_number"]))
    return pages


def build_import_preview(
    project_id: str,
    sheets: list[dict[str, Any]],
    response: dict[str, Any],
    existing_findings: list[dict[str, Any]],
    parser_repairs: list[str],
    parser_warnings: list[str],
    batch_id: str,
    prompt_version: str | None,
    source_type: str,
    prompt_id: str | None,
    parser_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = coerce_findings(response)
    updates: list[dict[str, Any]] = []
    warnings = list(dict.fromkeys(parser_warnings))
    parser_metadata = parser_metadata or {}
    review_scope = parser_metadata.get("review_scope") or "package"
    scope_pages = normalize_scope_pages(parser_metadata.get("scope_pages"), sheets)
    expected_review_pages = expected_review_pages_for_scope(
        sheets,
        review_scope=review_scope,
        scope_pages=scope_pages,
    )
    reviewed_pages = normalize_reviewed_pages(response.get("reviewed_pages"), sheets)
    coverage = build_review_coverage_summary(expected_review_pages, reviewed_pages)
    reviewed_page_numbers = list(coverage["reviewed_pages_confirmed"])
    pages_without_review_confirmation = list(coverage["missing_review_pages"])
    scoped_review_complete = coverage["review_coverage_status"] == "complete"
    if not items and response.get("error"):
        warnings.append(f"AI response error: {clean_text(response.get('error'), 'Unknown AI response error.')}")
    if not items and not scoped_review_complete:
        warnings.append("No updates array or update-shaped objects were found in the AI response.")
    if pages_without_review_confirmation:
        warnings.append(
            f"AI response did not confirm every expected page in reviewed_pages. Missing: {format_page_list(pages_without_review_confirmation)}."
        )
    if coverage["incomplete_review_pages"]:
        warnings.append(
            f"AI marked these expected pages incomplete: {format_page_list(coverage['incomplete_review_pages'])}."
        )
    if coverage["not_readable_pages"]:
        warnings.append(
            f"AI marked these expected pages not readable: {format_page_list(coverage['not_readable_pages'])}."
        )

    existing_by_stable = {finding.get("stable_id"): finding for finding in existing_findings}
    seen_stable_ids: set[str] = set()
    seen_signatures: dict[str, int] = {}
    duplicate_updates = 0
    for index, item in enumerate(items, start=1):
        preview_item = preview_ai_update_item(
            project_id=project_id,
            sheets=sheets,
            item=item,
            index=index,
            batch_id=batch_id,
            prompt_version=prompt_version,
            source_type=source_type,
            prompt_id=prompt_id,
        )
        stable_id = preview_item.get("stable_id")
        signature = duplicate_signature(preview_item)
        if preview_item.get("valid") and stable_id:
            likely_duplicate = likely_duplicate_preview(preview_item, updates)
            if stable_id in seen_stable_ids or (signature and signature in seen_signatures):
                duplicate_updates += 1
                preview_item["will_import"] = False
                preview_item["action"] = "duplicate_in_response"
                preview_item["duplicate_kind"] = "exact"
                preview_item["duplicate_reason"] = "Same page, target text, and required update as another update in this response."
                preview_item["related_update_indices"] = [seen_signatures.get(signature, index - 1)] if signature and signature in seen_signatures else []
                preview_item["skipped_reason"] = "Exact duplicate of another update in this pasted response."
                preview_item.setdefault("warnings", []).append("Exact duplicate in this response; only the first copy will import.")
            else:
                seen_stable_ids.add(stable_id)
                if signature:
                    seen_signatures[signature] = index
                matched = existing_by_stable.get(stable_id)
                preview_item["will_import"] = True
                preview_item["action"] = "update_existing" if matched else "create_new"
                preview_item["existing_finding_id"] = matched.get("id") if matched else None
                preview_item["stable_id_match"] = bool(matched)
                if likely_duplicate:
                    duplicate_updates += 1
                    preview_item["duplicate_kind"] = likely_duplicate["kind"]
                    preview_item["duplicate_reason"] = likely_duplicate["reason"]
                    preview_item["related_update_indices"] = likely_duplicate["indices"]
                    preview_item.setdefault("warnings", []).append(likely_duplicate["reason"])
        updates.append(preview_item)

    valid_count = sum(1 for item in updates if item.get("will_import"))
    skipped_count = len(updates) - valid_count
    update_warnings = [
        f"Update {item['index']}: {warning}"
        for item in updates
        for warning in item.get("warnings", [])
        if warning
    ]
    warnings = list(dict.fromkeys(warnings + update_warnings))
    preview = {
        "project_id": project_id,
        "source_type": source_type,
        "prompt_version": prompt_version,
        "prompt_id": prompt_id,
        "schema_version": parser_metadata.get("schema_version") or response.get("schema_version") or "autoqc-ai-updates-v1",
        "parser_mode": parser_metadata.get("parser_mode") or "unknown",
        "response_shape": parser_metadata.get("response_shape") or "unknown",
        "review_scope": review_scope,
        "review_strategy": parser_metadata.get("review_strategy"),
        "scope_pages": scope_pages,
        "scope_label": parser_metadata.get("scope_label"),
        "expected_review_pages": expected_review_pages,
        "reviewed_pages": reviewed_pages,
        "reviewed_page_numbers": reviewed_page_numbers,
        "reviewed_pages_confirmed": reviewed_page_numbers,
        "missing_review_pages": coverage["missing_review_pages"],
        "incomplete_review_pages": coverage["incomplete_review_pages"],
        "not_readable_pages": coverage["not_readable_pages"],
        "review_coverage_status": coverage["review_coverage_status"],
        "review_coverage_percent": coverage["review_coverage_percent"],
        "review_coverage": coverage,
        "pages_without_review_confirmation": pages_without_review_confirmation,
        "scoped_review_complete": scoped_review_complete,
        "total_candidate_updates": len(items),
        "valid_recoverable_updates": valid_count,
        "skipped_updates": skipped_count,
        "duplicate_updates": duplicate_updates,
        "parser_repairs_applied": list(dict.fromkeys(parser_repairs)),
        "warnings": warnings,
        "updates": updates,
    }
    preview["quality_report"] = build_import_quality_report(preview, sheets=sheets)
    return preview


def build_import_quality_report(
    preview: dict[str, Any],
    imported_findings: list[dict[str, Any]] | None = None,
    sheets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    updates = [item for item in preview.get("updates", []) if isinstance(item, dict)]
    imported_findings = imported_findings or []
    page_numbers = sorted(
        {
            int(sheet.get("page_number"))
            for sheet in (sheets or [])
            if isinstance(sheet, dict) and _positive_int(sheet.get("page_number"))
        }
    )
    scoped_pages = [
        int(page)
        for page in preview.get("scope_pages") or []
        if _positive_int(page)
    ]
    if scoped_pages:
        page_numbers = sorted(set(scoped_pages))
    returned_pages = sorted(
        {
            int(update.get("page_number"))
            for update in updates
            if _positive_int(update.get("page_number"))
        }
    )
    reviewed_pages = sorted(
        {
            int(item.get("page_number"))
            for item in preview.get("reviewed_pages") or []
            if isinstance(item, dict) and item.get("review_status") == "complete" and _positive_int(item.get("page_number"))
        }
    )
    importable_pages = sorted(
        {
            int(update.get("page_number"))
            for update in updates
            if update.get("will_import") and _positive_int(update.get("page_number"))
        }
    )
    imported_pages = sorted(
        {
            int(finding.get("page_number"))
            for finding in imported_findings
            if isinstance(finding, dict) and _positive_int(finding.get("page_number"))
        }
    )
    coverage_pages = imported_pages or importable_pages
    review_coverage = preview.get("review_coverage") if isinstance(preview.get("review_coverage"), dict) else {}
    pages_without_returned_updates = [page for page in page_numbers if page not in returned_pages]
    placement_statuses: list[str] = []
    for finding in imported_findings:
        if not isinstance(finding, dict):
            continue
        details = finding.get("placement_details")
        details_status = details.get("placement_status") if isinstance(details, dict) else None
        placement_statuses.append(str(finding.get("placement_status") or details_status or ""))
    missing_page = 0
    missing_target = 0
    low_confidence = 0
    for update in updates:
        fields = set(update.get("missing_or_weak_fields") or [])
        if not update.get("page_number") or "page_number" in fields:
            missing_page += 1
        if not clean_text(update.get("target_text"), "") or "target_text" in fields:
            missing_target += 1
        confidence = update.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < 0.6:
            low_confidence += 1

    exact = sum(1 for status in placement_statuses if status in {"exact_target_found", "manual_placement"})
    return {
        "total_updates_parsed": int(preview.get("total_candidate_updates") or len(updates)),
        "total_importable_updates": int(preview.get("valid_recoverable_updates") or 0),
        "imported_findings": len(imported_findings),
        "skipped_updates": int(preview.get("skipped_updates") or 0),
        "duplicate_count": int(preview.get("duplicate_updates") or 0),
        "missing_page_number_count": missing_page,
        "missing_target_text_count": missing_target,
        "exact_placement_count": exact,
        "fuzzy_placement_count": sum(1 for status in placement_statuses if status == "fuzzy_target_found"),
        "page_level_fallback_count": sum(1 for status in placement_statuses if status == "page_level_fallback"),
        "manual_placement_needed_count": sum(1 for status in placement_statuses if status == "manual_placement_needed"),
        "low_confidence_count": low_confidence,
        "page_count": len(page_numbers),
        "expected_review_pages": review_coverage.get("expected_review_pages") or page_numbers,
        "reviewed_pages_confirmed": review_coverage.get("reviewed_pages_confirmed") or reviewed_pages,
        "missing_review_pages": review_coverage.get("missing_review_pages") or list(preview.get("pages_without_review_confirmation") or []),
        "incomplete_review_pages": review_coverage.get("incomplete_review_pages") or [],
        "not_readable_pages": review_coverage.get("not_readable_pages") or [],
        "review_coverage_status": review_coverage.get("review_coverage_status") or ("complete" if bool(preview.get("scoped_review_complete")) else "not_confirmed"),
        "review_coverage_percent": review_coverage.get("review_coverage_percent") or 0.0,
        "pages_with_returned_updates": returned_pages,
        "pages_with_importable_updates": importable_pages,
        "pages_with_imported_updates": imported_pages,
        "pages_with_updates": coverage_pages,
        "pages_reviewed": reviewed_pages,
        "pages_without_review_confirmation": list(preview.get("pages_without_review_confirmation") or []),
        "scoped_review_complete": bool(preview.get("scoped_review_complete")),
        "pages_without_returned_updates": pages_without_returned_updates,
        "pages_with_returned_updates_count": len(returned_pages),
        "pages_with_imported_updates_count": len(coverage_pages),
        "pages_without_returned_updates_count": len(pages_without_returned_updates),
        "warnings": list(preview.get("warnings") or []),
        "errors": [],
    }


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_scope_pages(value: Any, sheets: list[dict[str, Any]]) -> list[int]:
    valid_pages = {
        int(sheet.get("page_number"))
        for sheet in sheets
        if isinstance(sheet, dict) and _positive_int(sheet.get("page_number"))
    }
    pages = parse_page_numbers(value)
    return [page for page in pages if not valid_pages or page in valid_pages]


def normalize_reviewed_pages(value: Any, sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    valid_pages = {
        int(sheet.get("page_number"))
        for sheet in sheets
        if isinstance(sheet, dict) and _positive_int(sheet.get("page_number"))
    }
    reviewed: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            _, raw_page = first_present(item, ["page_number", "page", "pdf_page", "page_no", "pageNumber"])
            page = coerce_page_number(raw_page)
            raw_status = str(item.get("review_status") or item.get("status") or "complete").strip().lower()
            issue_count_value = item.get("issue_count")
            notes = clean_text(item.get("notes") or item.get("note"), "", max_length=240)
        else:
            page = coerce_page_number(item)
            raw_status = "complete"
            issue_count_value = None
            notes = ""
        if not page or (valid_pages and page not in valid_pages):
            continue
        status = {
            "done": "complete",
            "complete": "complete",
            "completed": "complete",
            "clean": "complete",
            "none": "complete",
            "incomplete": "incomplete",
            "partial": "incomplete",
            "not_readable": "not_readable",
            "not-readable": "not_readable",
            "unreadable": "not_readable",
        }.get(raw_status, "complete")
        try:
            issue_count = int(issue_count_value if issue_count_value is not None else 0)
        except (TypeError, ValueError):
            issue_count = 0
        reviewed.append(
            {
                "page_number": page,
                "review_status": status,
                "issue_count": max(0, issue_count),
                "notes": notes,
            }
        )
    deduped: dict[int, dict[str, Any]] = {}
    for item in reviewed:
        deduped[int(item["page_number"])] = item
    return [deduped[page] for page in sorted(deduped)]


def duplicate_signature(preview_item: dict[str, Any]) -> str | None:
    page = preview_item.get("page_number")
    target = normalize_duplicate_text(preview_item.get("target_text"))
    update = normalize_duplicate_text(preview_item.get("required_update"))
    if not page or not target or not update:
        return None
    return f"{page}|{target}|{update}"


def likely_duplicate_preview(preview_item: dict[str, Any], previous_updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    page = preview_item.get("page_number")
    if not page:
        return None
    target = normalize_duplicate_text(preview_item.get("target_text"))
    issue = normalize_duplicate_text(preview_item.get("issue"))
    likely_indices: list[int] = []
    title_indices: list[int] = []
    for previous in previous_updates:
        if not previous.get("valid") or previous.get("page_number") != page:
            continue
        previous_target = normalize_duplicate_text(previous.get("target_text"))
        previous_issue = normalize_duplicate_text(previous.get("issue"))
        if target and previous_target and similar_text(target, previous_target):
            likely_indices.append(int(previous.get("index") or 0))
        if issue and previous_issue and issue == previous_issue:
            title_indices.append(int(previous.get("index") or 0))
    if likely_indices:
        return {
            "kind": "likely",
            "reason": "Likely duplicate: same page with similar target text.",
            "indices": [index for index in likely_indices if index],
        }
    if title_indices:
        return {
            "kind": "same_page_same_issue",
            "reason": "Possible duplicate: same page and same issue title.",
            "indices": [index for index in title_indices if index],
        }
    return None


def normalize_duplicate_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def similar_text(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 12 and len(right) >= 12 and (left in right or right in left):
        return True
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    return overlap >= 0.72


def preview_ai_update_item(
    project_id: str,
    sheets: list[dict[str, Any]],
    item: Any,
    index: int,
    batch_id: str | None,
    prompt_version: str | None,
    source_type: str,
    prompt_id: str | None,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "index": index,
            "valid": False,
            "will_import": False,
            "action": "skipped",
            "warnings": ["Update item was not a JSON object."],
            "missing_or_weak_fields": ["object"],
            "skipped_reason": "Update item was not a JSON object.",
        }
    candidate, fields, warnings, missing = candidate_from_ai_item(
        project_id=project_id,
        sheets=sheets,
        item=item,
        batch_id=batch_id,
        prompt_version=prompt_version,
        source_type=source_type,
        prompt_id=prompt_id,
    )
    preview = {
        "index": index,
        "valid": candidate is not None,
        "will_import": False,
        "action": "skipped",
        "warnings": warnings,
        "missing_or_weak_fields": missing,
        **fields,
    }
    if candidate is None:
        preview["skipped_reason"] = fields.get("skipped_reason") or "Update could not be normalized into an AutoQC finding."
        return preview
    finding = ReasoningEngine()._normalize_and_dedupe(project_id, [candidate])[0]
    finding["status"] = FindingStatus.NEEDS_REVIEW.value
    finding["original_ai_json"] = item
    finding["ai_batch_id"] = batch_id
    finding["prompt_version"] = prompt_version
    preview["stable_id"] = finding["stable_id"]
    preview["finding"] = finding
    return preview


def normalize_ai_findings(
    project_id: str,
    sheets: list[dict[str, Any]],
    response: dict[str, Any],
    batch_id: str | None = None,
    prompt_version: str | None = None,
) -> list[dict[str, Any]]:
    preview = build_import_preview(
        project_id=project_id,
        sheets=sheets,
        response=response,
        existing_findings=[],
        parser_repairs=[],
        parser_warnings=[],
        batch_id=batch_id or str(uuid.uuid4()),
        prompt_version=prompt_version,
        source_type="unknown",
        prompt_id=None,
    )
    return [
        item["finding"]
        for item in preview.get("updates", [])
        if isinstance(item, dict) and item.get("will_import") and isinstance(item.get("finding"), dict)
    ]


def candidate_from_ai_item(
    project_id: str,
    sheets: list[dict[str, Any]],
    item: dict[str, Any],
    batch_id: str | None,
    prompt_version: str | None,
    source_type: str,
    prompt_id: str | None,
) -> tuple[CandidateFinding | None, dict[str, Any], list[str], list[str]]:
    sheet_by_page = {int(sheet.get("page_number") or 0): sheet for sheet in sheets}
    warnings: list[str] = []
    missing: list[str] = []
    page_key, page_value = first_present(item, ["page_number", "page", "sheet_page", "pdf_page", "page_no", "pageNumber"])
    page_number = coerce_page_number(page_value)
    if page_key and page_key != "page_number":
        warnings.append(f"Normalized page alias '{page_key}' to page_number.")
    if isinstance(page_value, str) and page_number is not None:
        warnings.append(f"Normalized page string '{page_value}' to page {page_number}.")
    if page_number is None and len(sheets) == 1:
        page_number = int(sheets[0].get("page_number") or 1)
        warnings.append("No page number supplied; used the only sheet in the project.")
    fields: dict[str, Any] = {
        "page_number": page_number,
        "raw_page": page_value,
    }
    if page_number is None:
        missing.append("page_number")
        fields["skipped_reason"] = "Missing or unreadable page number."
        return None, fields, warnings, missing
    if page_number not in sheet_by_page:
        fields["skipped_reason"] = f"Page {page_number} is not in this PDF package."
        warnings.append(fields["skipped_reason"])
        return None, fields, warnings, missing

    sheet = sheet_by_page[page_number]
    update_text = clean_text(
        item.get("required_update") or item.get("recommended_update") or item.get("update_needed") or item.get("change_needed"),
        "",
    )
    issue = clean_text(item.get("issue") or item.get("title"), "AI drawing update needed")
    title = clean_text(item.get("title") or item.get("issue"), "AI drawing update needed")
    evidence_text = clean_text(first_string_present(item, ["target_text", "evidence_text", "existing_text", "source_text"]), "")
    if not evidence_text:
        structured_evidence = item.get("evidence")
        if isinstance(structured_evidence, dict):
            evidence_text = clean_text(first_string_present(structured_evidence, ["target_text", "markup_text", "text_excerpt", "text"]), "")
        elif isinstance(structured_evidence, list):
            for evidence_item in structured_evidence:
                if isinstance(evidence_item, dict):
                    evidence_text = clean_text(first_string_present(evidence_item, ["target_text", "markup_text", "text_excerpt", "text"]), "")
                    if evidence_text:
                        break
    rationale = clean_text(item.get("rationale") or item.get("reasoning_summary") or item.get("reasoning"), "")
    comment = build_markup_comment(issue, evidence_text, update_text) if update_text else clean_text(
        item.get("comment_text") or item.get("comment"),
        "Review this AI finding.",
    )
    confidence = coerce_confidence(item.get("confidence"))
    category = coerce_category(item.get("category"))
    severity = coerce_severity(item.get("severity"))
    fields.update(
        {
            "issue": issue,
            "target_text": evidence_text,
            "required_update": update_text,
            "rationale": rationale,
            "category": category,
            "severity": severity,
            "confidence": confidence,
        }
    )
    if not update_text and comment == "Review this AI finding.":
        missing.append("required_update")
        fields["skipped_reason"] = "Missing required_update or usable comment text."
        return None, fields, warnings, missing
    if not evidence_text:
        missing.append("target_text")
        fields["skipped_reason"] = "Missing or blank target_text. AI updates must cite exact drawing text for markup placement."
        warnings.append(fields["skipped_reason"])
        return None, fields, warnings, missing
    if not update_text:
        missing.append("required_update")
        warnings.append("Missing required_update; using supplied comment text as the finding comment.")
    if not rationale:
        missing.append("rationale")
        warnings.append("Missing rationale; using a generic AI rationale.")
    if not item.get("category"):
        missing.append("category")
        warnings.append("Missing category; defaulted to human review needed.")
    if not item.get("severity"):
        missing.append("severity")
        warnings.append("Missing severity; defaulted to Minor.")
    if item.get("confidence") is None:
        missing.append("confidence")
        warnings.append("Missing confidence; defaulted to 0.65.")

    evidence_item = {
        "observation": f"AI reviewer cited evidence on page {page_number}.",
        "sheet_id": sheet["id"],
        "page_number": page_number,
        "text_excerpt": evidence_text or comment[:220],
        "entity_ids": [],
        "confidence": confidence,
        "markup_text": evidence_text[:220] if evidence_text else None,
        "target_text": evidence_text or None,
        "required_update": update_text or None,
        "rationale": rationale or None,
        "ai_batch_id": batch_id,
        "prompt_version": prompt_version,
        "prompt_id": prompt_id,
        "source_type": source_type,
    }
    return (
        CandidateFinding(
            rule_id=stable_ai_rule_id(page_number, evidence_text, update_text or comment),
            title=title,
            category=category,
            severity=severity,
            confidence=confidence,
            sheet_id=sheet["id"],
            page_number=page_number,
            evidence=[evidence_item],
            reasoning_summary=rationale or "AI reviewer identified this issue from the drawing text/context.",
            suggested_correction=clean_text(
                update_text or item.get("suggested_correction") or item.get("correction"),
                "Review and correct the cited issue if confirmed.",
            ),
            comment_text=comment,
            source="ai",
        ),
        fields,
        warnings,
        missing,
    )


def stable_ai_rule_id(page_number: int, target_text: str, update_text: str) -> str:
    anchor = target_text or update_text
    return f"ai.deep_review.page_{page_number}.{slug(anchor)}"


def build_markup_comment(issue: str, target_text: str, update_text: str) -> str:
    if target_text:
        return clean_text(f"Update required: {issue}. Change/correct '{target_text}' to: {update_text}", "Review AI update.", max_length=520)
    return clean_text(f"Update required: {issue}. Required update: {update_text}", "Review AI update.", max_length=520)


def extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    if isinstance(data.get("content"), str):
        return data["content"]
    return json.dumps(data)


def parse_json_object(content: str) -> dict[str, Any]:
    return parse_json_object_with_report(content)["data"]


def parse_json_object_with_report(content: str) -> dict[str, Any]:
    last_error: json.JSONDecodeError | ValueError | SyntaxError | None = None
    parsed_values: list[tuple[dict[str, Any], list[str]]] = []
    base_repairs = detect_response_repairs(content)
    for candidate in json_like_candidates(content):
        candidate_repairs = list(base_repairs)
        if candidate.strip() != normalize_chat_text(content).strip():
            candidate_repairs.append("Ignored prose outside the JSON payload.")
        for prepared in repair_candidates(candidate):
            prepared_repairs = list(candidate_repairs)
            if prepared != candidate.strip():
                prepared_repairs.append("Removed trailing commas.")
            try:
                value = json.loads(prepared)
            except json.JSONDecodeError as exc:
                last_error = exc
            else:
                normalized, normalization_repairs = normalize_response_value_with_repairs(value)
                if normalized is not None:
                    parsed_values.append((normalized, prepared_repairs + normalization_repairs))
                    continue
                last_error = ValueError("AI response JSON must be an object, array of updates, or update-shaped object")

            try:
                value = ast.literal_eval(prepared)
            except (ValueError, SyntaxError) as exc:
                last_error = exc
            else:
                normalized, normalization_repairs = normalize_response_value_with_repairs(value)
                if normalized is not None:
                    parsed_values.append((normalized, prepared_repairs + ["Accepted Python-style JSON-like syntax."] + normalization_repairs))
                    continue
                last_error = ValueError("AI response JSON must be an object, array of updates, or update-shaped object")

    preferred = best_response_value_with_repairs(parsed_values)
    if preferred is not None:
        data, repairs = preferred
        if "reviewed_pages" not in data:
            loose_reviewed_pages = parse_loose_reviewed_pages(content)
            if loose_reviewed_pages:
                data["reviewed_pages"] = loose_reviewed_pages
                repairs.append("Recovered loose reviewed_pages confirmation objects.")
        warnings = []
        if data.get("error"):
            warnings.append(f"AI response included error: {clean_text(data.get('error'), 'Unknown AI error')}")
        unique_repairs = list(dict.fromkeys(repairs))
        return {
            "data": data,
            "repairs": unique_repairs,
            "warnings": warnings,
            "schema_version": schema_version_from_response(data),
            "parser_mode": parser_mode_from_response(data, unique_repairs),
            "response_shape": response_shape_from_response(data),
        }

    loose_updates = parse_loose_updates(content)
    if loose_updates:
        repairs = list(dict.fromkeys(base_repairs + ["Recovered loose malformed update objects."]))
        data = {"updates": loose_updates}
        loose_reviewed_pages = parse_loose_reviewed_pages(content)
        if loose_reviewed_pages:
            data["reviewed_pages"] = loose_reviewed_pages
            repairs.append("Recovered loose reviewed_pages confirmation objects.")
        return {
            "data": data,
            "repairs": repairs,
            "warnings": [],
            "schema_version": schema_version_from_response(data),
            "parser_mode": "loose_recovery",
            "response_shape": "loose_updates",
        }

    if isinstance(last_error, json.JSONDecodeError):
        snippet = error_snippet(last_error.doc, last_error.pos)
        raise ValueError(
            f"AI response was not valid JSON and could not be repaired near character {last_error.pos}: {snippet}"
        ) from last_error
    raise ValueError("AI response did not contain valid JSON or recoverable update data")


def detect_response_repairs(content: str) -> list[str]:
    text = str(content or "")
    repairs: list[str] = []
    if re.search(r"```(?:json|JSON)?\s*.*?```", text, flags=re.S):
        repairs.append("Removed markdown code fence.")
    if normalize_chat_text(text) != text.strip().replace("\ufeff", ""):
        repairs.append("Normalized smart quotes or pasted Unicode punctuation.")
    if re.search(r",\s*([}\]])", text):
        repairs.append("Removed trailing commas.")
    if text.find("{") > 0 or (text.rfind("}") >= 0 and text.rfind("}") < len(text.strip()) - 1):
        repairs.append("Ignored prose outside the JSON payload.")
    return list(dict.fromkeys(repairs))


def schema_version_from_response(data: dict[str, Any]) -> str:
    value = data.get("schema_version") or data.get("autoqc_schema_version") or data.get("version")
    return str(value or "autoqc-ai-updates-v1")


def response_shape_from_response(data: dict[str, Any]) -> str:
    if isinstance(data.get("updates"), list):
        return "updates"
    if isinstance(data.get("findings"), list):
        return "findings"
    if isinstance(data.get("items"), list):
        return "items"
    return "single_update" if response_has_update_fields(data) else "object"


def parser_mode_from_response(data: dict[str, Any], repairs: list[str]) -> str:
    joined = " | ".join(repairs)
    if "Wrapped top-level array as updates." in joined:
        return "raw_array"
    if "Wrapped a single update-shaped object as updates." in joined:
        return "single_update"
    if isinstance(data.get("findings"), list):
        return "findings_wrapper"
    if isinstance(data.get("updates"), list):
        return "updates_wrapper"
    if isinstance(data.get("items"), list):
        return "items_wrapper"
    return "json_object"


def normalize_response_value(value: Any) -> dict[str, Any] | None:
    return normalize_response_value_with_repairs(value)[0]


def normalize_response_value_with_repairs(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    repairs: list[str] = []
    if isinstance(value, list):
        return {"updates": value}, ["Wrapped top-level array as updates."]
    if not isinstance(value, dict):
        return None, repairs
    for key in ["updates", "findings", "items"]:
        if isinstance(value.get(key), dict):
            normalized = dict(value)
            normalized[key] = [value[key]]
            return normalized, [f"Wrapped object-valued {key} as a one-item array."]
    if response_has_update_fields(value):
        return {"updates": [value]}, ["Wrapped a single update-shaped object as updates."]
    return value, repairs


def best_response_value(values: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not values:
        return None
    for value in values:
        if coerce_findings(value):
            return value
    return values[0]


def best_response_value_with_repairs(values: list[tuple[dict[str, Any], list[str]]]) -> tuple[dict[str, Any], list[str]] | None:
    if not values:
        return None
    for value, repairs in values:
        if coerce_findings(value):
            return value, repairs
    return values[0]


def response_has_update_fields(value: dict[str, Any]) -> bool:
    return bool(
        any(key in value for key in ["page_number", "page", "sheet_page", "pdf_page", "page_no", "pageNumber"])
        and any(key in value for key in ["target_text", "required_update", "issue", "evidence_text", "comment_text"])
    )


def json_like_candidates(content: str) -> list[str]:
    text = normalize_chat_text(content)
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", text, flags=re.S):
        candidates.append(match.group(1).strip())
    candidates.append(text.strip())
    candidates.extend(balanced_objects(text))
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def balanced_objects(text: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start : index + 1])
                    start = None
    return objects


def _legacy_normalize_chat_text(content: str) -> str:
    return (
        str(content or "")
        .strip()
        .replace("\ufeff", "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


def normalize_chat_text(content: str) -> str:
    text = str(content or "").strip().replace("\ufeff", "")
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "â€œ": '"',
        "â€\u009d": '"',
        "â€˜": "'",
        "â€™": "'",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def repair_candidates(candidate: str) -> list[str]:
    text = candidate.strip()
    repaired = re.sub(r",\s*([}\]])", r"\1", text)
    return [item for item in [text, repaired] if item]


def first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    end = text.rfind("}")
    return text[start : end + 1] if end > start else None


def parse_loose_updates(content: str) -> list[dict[str, Any]]:
    text = normalize_chat_text(content)
    updates: list[dict[str, Any]] = []
    for obj in loose_update_objects(text):
        item: dict[str, Any] = {}
        for key in LOOSE_UPDATE_KEYS:
            match = re.search(rf'"?{key}"?\s*:\s*(.*?)(?=,\s*"?(?:{"|".join(LOOSE_UPDATE_KEYS)})"?\s*:|\s*$)', obj, flags=re.S)
            if not match:
                continue
            item[key] = clean_loose_value(match.group(1))
        if any(key in item for key in ["page_number", "page", "pdf_page", "page_no", "pageNumber"]) and (
            "target_text" in item or "required_update" in item or "issue" in item
        ):
            updates.append(item)
    return updates


def parse_loose_reviewed_pages(content: str) -> list[dict[str, Any]]:
    text = normalize_chat_text(content)
    array_match = re.search(r'"?reviewed_pages"?\s*:\s*\[', text, flags=re.S)
    if not array_match:
        return []
    start = array_match.end()
    end = matching_array_end(text, start - 1)
    section = text[start:end]
    reviewed: list[dict[str, Any]] = []
    for obj in loose_update_objects(section):
        item: dict[str, Any] = {}
        for key in ["page_number", "page", "pdf_page", "page_no", "pageNumber", "review_status", "status", "issue_count", "notes", "note"]:
            match = re.search(rf'"?{key}"?\s*:\s*(.*?)(?=,\s*"?(?:page_number|page|pdf_page|page_no|pageNumber|review_status|status|issue_count|notes|note)"?\s*:|\s*$)', obj, flags=re.S)
            if match:
                item[key] = clean_loose_value(match.group(1))
        if item:
            reviewed.append(item)
    return reviewed


LOOSE_UPDATE_KEYS = [
    "issue",
    "severity",
    "category",
    "page_number",
    "page",
    "sheet_page",
    "pdf_page",
    "page_no",
    "pageNumber",
    "target_text",
    "required_update",
    "recommended_update",
    "update_needed",
    "change_needed",
    "rationale",
    "confidence",
]


def loose_update_objects(text: str) -> list[str]:
    array_match = re.search(r'"?updates"?\s*:\s*\[', text, flags=re.S)
    start = array_match.end() if array_match else 0
    end = matching_array_end(text, start - 1) if array_match else len(text)
    section = text[start:end]
    objects: list[str] = []
    depth = 0
    obj_start: int | None = None
    for index, char in enumerate(section):
        if char == "{":
            if depth == 0:
                obj_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                objects.append(section[obj_start:index])
                obj_start = None
    if objects:
        return objects
    fallback = re.findall(r"\{([^{}]+)\}", section, flags=re.S)
    return fallback


def matching_array_end(text: str, open_bracket_index: int) -> int:
    depth = 0
    for index in range(open_bracket_index, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def clean_loose_value(value: str) -> str:
    text = value.strip().rstrip(",").strip()
    if text.endswith("}"):
        text = text[:-1].strip()
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        text = text[1:-1]
    return text.replace('\\"', '"').replace("\\n", " ").strip()


def error_snippet(text: str, position: int, radius: int = 80) -> str:
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return text[start:end].replace("\n", " ")


def coerce_findings(response: dict[str, Any]) -> list[Any]:
    updates = response.get("updates")
    if isinstance(updates, list):
        return updates
    if isinstance(updates, dict):
        return [updates]
    findings = response.get("findings")
    if isinstance(findings, list):
        return findings
    if isinstance(findings, dict):
        return [findings]
    items = response.get("items")
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return [items]
    return [response] if response_has_update_fields(response) else []


def _empty_placement_summary() -> dict[str, int]:
    return {
        "exact_target_found": 0,
        "fuzzy_target_found": 0,
        "page_level_fallback": 0,
        "manual_placement_needed": 0,
    }


def _placement_has_focus_rect(placement: dict[str, Any]) -> bool:
    rect_json = placement.get("rect_json")
    return isinstance(rect_json, list) and len(rect_json) >= 4


def _candidate_has_text(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    for key in ["target_text", "markup_text", "text_excerpt"]:
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def first_present(item: dict[str, Any], keys: list[str]) -> tuple[str | None, Any]:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return key, value
    return None, None


def first_string_present(item: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def coerce_page_number(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        text = str(value or "")
        match = re.search(r"\b(?:pdf\s*)?page(?:\s*(?:no\.?|number|#))?\s*[:#-]?\s*(\d+)\b", text, flags=re.I)
        if not match:
            match = re.search(r"\bp\.?\s*(\d+)\b", text, flags=re.I)
        if not match:
            match = re.search(r"\d+", text)
        if not match:
            return None
        page = int(match.group(1) if match.lastindex else match.group(0))
    return page if page >= 1 else None


def coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.65
    if confidence > 1:
        confidence /= 100
    return max(0.05, min(0.95, confidence))


def coerce_severity(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "critical": Severity.CRITICAL.value,
        "major": Severity.MAJOR.value,
        "minor": Severity.MINOR.value,
        "note": Severity.NOTE.value,
    }.get(normalized, Severity.MINOR.value)


def coerce_category(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    allowed = {item.value.lower(): item.value for item in FindingCategory}
    return allowed.get(normalized, FindingCategory.HUMAN_REVIEW_NEEDED.value)


def clean_text(value: Any, default: str, max_length: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return default
    return text[: max_length - 3].rstrip() + "..." if len(text) > max_length else text


def slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return out[:48] or "finding"


def trim_text(text: str, max_length: int) -> str:
    clean = text.strip()
    if len(clean) <= max_length:
        return clean
    half = max_length // 2
    return f"{clean[:half]}\n...[trimmed for AI review]...\n{clean[-half:]}"
