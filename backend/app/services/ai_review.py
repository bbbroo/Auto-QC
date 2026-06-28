from __future__ import annotations

import ast
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
from backend.app.services.storage import require_project_source_pdf_path


CHAT_PROMPT_VERSION = "autoqc-chat-prompt-v1"
DEFAULT_IMPORT_SOURCE = "manual_chat_prompt"


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

    def generate_manual_prompt(self, project_id: str, template_id: str | None = None) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        sheets = self.db.list_sheets(project_id)
        entities = self.db.list_entities(project_id)
        existing = self.db.list_findings(project_id, sources=["ai"])
        template = self.templates.get_template(template_id)
        payload = build_ai_payload(project, sheets, entities, existing, self.settings.ai_max_sheets)
        context = manual_prompt_context(payload)
        prompt_version = str(template.get("version") or CHAT_PROMPT_VERSION)
        memory_context = self.markup_memory.build_markup_memory_prompt_context(project_id)
        prompt_metadata = {
            "included_full_extracted_text": False,
            "sheet_index_count": len(context.get("sheet_index", [])),
            "source_of_truth": "attached_pdf",
            "prompt_template_id": template.get("id"),
            "prompt_template_name": template.get("name"),
            "prompt_template_version": prompt_version,
            "markup_memory_enabled": bool(memory_context.get("enabled")),
            "markup_memory_positive_examples": len(memory_context.get("positive_examples") or []),
            "markup_memory_avoid_examples": len(memory_context.get("avoid_examples") or []),
        }
        prompt_run = self.db.insert_ai_prompt_run(
            project_id,
            prompt_version,
            context.get("sheet_index", []),
            prompt_metadata,
        )
        prompt = build_manual_prompt(payload, prompt_run, template, markup_memory_context=memory_context)
        return {
            "project_id": project_id,
            "prompt_id": prompt_run["id"],
            "prompt_version": prompt_version,
            "generated_at": prompt_run["generated_at"],
            "prompt": prompt,
            "payload_sheet_count": len(payload.get("sheets", [])),
            "instructions": "Copy this prompt into ChatGPT or Copilot Chat. Paste the returned JSON into AutoQC using Import AI Response.",
            "prompt_metadata": prompt_metadata,
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
                "import_status": "previewed" if preview["valid_recoverable_updates"] else "failed",
                "preview": preview,
                "metadata": parser_metadata,
            },
        )
        batch_summary = dict(batch)
        batch_summary.pop("preview", None)
        preview["batch"] = batch_summary
        preview["batch_id"] = batch["id"]
        if preview["valid_recoverable_updates"] == 0:
            reason = preview["warnings"][0] if preview["warnings"] else "No importable AI updates were found."
            raise ValueError(
                f"AI response did not contain any updates to import. AI import preview found zero importable updates. {reason} Check that the response has an updates array with valid page numbers and drawing update fields."
            )
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
        ai_findings = [
            item.get("finding")
            for item in preview.get("updates", [])
            if isinstance(item, dict) and item.get("will_import") and isinstance(item.get("finding"), dict)
        ]
        ai_findings = [finding for finding in ai_findings if finding]
        ai_findings = self._enrich_imported_finding_locations(project_id, ai_findings)
        if not ai_findings:
            raise ValueError("AI import preview contains zero valid updates to import. Run preview again and review the warnings.")
        existing = self.db.list_findings(project_id, sources=["ai"])
        existing_by_stable = {finding.get("stable_id"): finding for finding in existing}
        created_count = sum(1 for finding in ai_findings if finding.get("stable_id") not in existing_by_stable)
        updated_count = sum(1 for finding in ai_findings if finding.get("stable_id") in existing_by_stable)
        self.db.replace_findings(project_id, merge_existing_ai_findings(existing, ai_findings), sources=["ai"])
        stored_imported = _find_by_stable_ids(self.db.list_findings(project_id, sources=["ai"]), ai_findings)
        batch = self.db.update_ai_import_batch(
            preview_id,
            {
                "created_count": created_count,
                "updated_count": updated_count,
                "duplicate_count": int(preview.get("duplicate_updates") or 0),
                "import_status": "imported",
                "imported_at": utc_now_iso_safe(),
            },
        )
        return {
            "project": self.db.get_project(project_id),
            "ai_findings_created": len(ai_findings),
            "ai_updates_imported": len(ai_findings),
            "raw_ai_count": int(preview.get("total_candidate_updates") or len(ai_findings)),
            "imported_stable_ids": [finding["stable_id"] for finding in ai_findings],
            "imported_finding_ids": [finding["id"] for finding in stored_imported],
            "batch": batch,
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
        preview = build_import_preview(
            project_id=project_id,
            sheets=sheets,
            response=ai_response,
            existing_findings=existing,
            parser_repairs=[],
            parser_warnings=[],
            batch_id=batch_id,
            prompt_version="direct_ai_review",
            source_type="direct_ai",
            prompt_id=None,
        )
        ai_findings = [
            item["finding"]
            for item in preview.get("updates", [])
            if isinstance(item, dict) and item.get("will_import") and isinstance(item.get("finding"), dict)
        ]
        batch = self.db.create_ai_import_batch(
            project_id,
            {
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
            },
        )
        self.db.replace_findings(project_id, merge_existing_ai_findings(existing, ai_findings), sources=["ai"])
        stored_imported = _find_by_stable_ids(self.db.list_findings(project_id, sources=["ai"]), ai_findings)
        return {
            "project": self.db.get_project(project_id),
            "ai_findings_created": len(ai_findings),
            "ai_updates_imported": len(ai_findings),
            "raw_ai_count": len(coerce_findings(ai_response)),
            "imported_stable_ids": [finding["stable_id"] for finding in ai_findings],
            "imported_finding_ids": [finding["id"] for finding in stored_imported],
            "batch": batch,
            "findings": self.db.list_findings(project_id, sources=["ai"]),
        }


def _find_by_stable_ids(stored_findings: list[dict[str, Any]], imported_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    imported_stable_ids = {finding["stable_id"] for finding in imported_findings}
    return [finding for finding in stored_findings if finding.get("stable_id") in imported_stable_ids]


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
        for key in ["prompt_template_id", "prompt_template_name", "prompt_template_version"]
        if metadata.get(key)
    }


def merge_existing_ai_findings(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    incoming_stable_ids = {finding["stable_id"] for finding in incoming}
    return [finding for finding in existing if finding.get("stable_id") not in incoming_stable_ids] + incoming


SYSTEM_PROMPT = """You are an expert natural gas drawing QC reviewer. Return only valid JSON with a top-level updates array. Identify drawing updates needed; do not write finished markup comments. Create specific, evidence-backed updates only. Avoid repeated title-block, parser, or OCR noise. Every update must include issue, severity, category, page_number, target_text, required_update, rationale, and confidence."""


def build_ai_payload(
    project: dict[str, Any],
    sheets: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    existing_findings: list[dict[str, Any]],
    max_sheets: int,
) -> dict[str, Any]:
    sheet_payload = []
    for sheet in sheets[:max_sheets]:
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
            for item in entities[:250]
        ],
        "existing_findings_summary": [
            {"title": item.get("title"), "page_number": item.get("page_number"), "comment_text": item.get("comment_text")}
            for item in existing_findings[:80]
        ],
    }


def build_manual_prompt(
    payload: dict[str, Any],
    prompt_run: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
    markup_memory_context: dict[str, Any] | None = None,
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
    memory_section = ""
    if markup_memory_context and markup_memory_context.get("enabled") and markup_memory_context.get("prompt_section"):
        memory_section = f"\n\n{markup_memory_context['prompt_section']}\n"
    return (
        "You are acting as the AI Deep Review engine for AutoQC, a natural gas drawing QC tracker. This prompt is intended to be pasted into ChatGPT or Copilot Chat.\n"
        f"Prompt version: {context.get('prompt', {}).get('prompt_version', CHAT_PROMPT_VERSION)}.\n\n"
        f"Prompt template: {template.get('name', 'Default AutoQC Deep Review prompt')} ({template.get('id', 'default-deep-review')}).\n\n"
        "IMPORTANT: The actual drawing package PDF must be attached/uploaded to this chat. Review the attached PDF package itself. Do not rely on this prompt alone as the drawing source of truth.\n\n"
        "Return ONLY valid JSON. Do not use markdown. Do not include commentary before or after the JSON.\n\n"
        "Your job is to identify drawing updates needed. Do not write finished PDF markup comments. AutoQC will convert your updates into markups after I paste your JSON back into the app.\n\n"
        "Review priorities:\n"
        f"{priority_lines}\n"
        "- Title block/revision issues only when visible in the actual attached PDF, not merely because metadata says UNKNOWN.\n\n"
        "Rules:\n"
        "- Every update must have a page_number and target_text copied from the attached PDF.\n"
        "- target_text should be the exact note/callout/word AutoQC can search for when creating markups.\n"
        "- Only report updates supported by visible evidence in the attached PDF. Do not invent code requirements, company standards, missing equipment, missing sheets, design defects, or title-block problems from general expectations, metadata, sheet titles, OCR status, or UNKNOWN values.\n"
        "- If evidence is uncertain, either skip the item or use category \"human review needed\" with a clear uncertainty rationale.\n"
        "- Do not report OCR, parser, extraction-quality, or UNKNOWN metadata issues as drawing updates. Treat AutoQC context as navigation only.\n"
        "- Create title-block/revision updates only when the attached PDF visibly shows a real missing, conflicting, or incorrect title-block value.\n"
        "- If the PDF package is not attached or not readable in this chat, return {\"updates\": [], \"error\": \"Attach the actual drawing package PDF before review.\"}.\n"
        "- If there are no good updates, return {\"updates\": []}.\n\n"
        f"{memory_section}"
        "Required response schema:\n"
        "{\n"
        "  \"schema_version\": \"autoqc-ai-updates-v1\",\n"
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
        "Minimal AutoQC project context only, not the drawing source of truth:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Final reminder: use the attached PDF, not this sheet index, as evidence. Return only the JSON object with the updates array."
    )


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
    }


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
    if not items and response.get("error"):
        warnings.append(f"AI response error: {clean_text(response.get('error'), 'Unknown AI response error.')}")
    if not items:
        warnings.append("No updates array or update-shaped objects were found in the AI response.")

    parser_metadata = parser_metadata or {}
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
    return {
        "project_id": project_id,
        "source_type": source_type,
        "prompt_version": prompt_version,
        "prompt_id": prompt_id,
        "schema_version": parser_metadata.get("schema_version") or response.get("schema_version") or "autoqc-ai-updates-v1",
        "parser_mode": parser_metadata.get("parser_mode") or "unknown",
        "response_shape": parser_metadata.get("response_shape") or "unknown",
        "total_candidate_updates": len(items),
        "valid_recoverable_updates": valid_count,
        "skipped_updates": skipped_count,
        "duplicate_updates": duplicate_updates,
        "parser_repairs_applied": list(dict.fromkeys(parser_repairs)),
        "warnings": warnings,
        "updates": updates,
    }


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
