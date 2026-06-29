from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.sheet_evidence.cache import write_json


SOURCE_OF_TRUTH_WARNING = (
    "The attached PDF remains the source of truth. The evidence below is supporting navigation/context only and must not be treated as complete or authoritative."
)

DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_PROMPT_CHARS = 45_000

MANUAL_REVIEW_INSTRUCTIONS = """You are acting as the AI Deep Manual Review engine for AutoQC, a natural gas drawing QC tracker.

Review depth: Exhaustive Manual-Style Review. Review every visible sheet, note, callout, table, title block, revision block, plan, detail, section, diagram, PFD, P&ID, BOM, legend, symbol, and drawing reference in the attached PDF package. Do not triage, sample, skim, or only review high-risk sheets.

IMPORTANT: The actual drawing package PDF must be attached/uploaded to this chat. Review the attached PDF package itself. Do not rely on this prompt or extracted sheet evidence alone as the drawing source of truth.

SCOPED REVIEW MODE: Page batch. Review only the PDF pages listed in this batch. Use other pages only to verify references from the requested pages. Do not report issues found only on out-of-scope pages unless needed to explain a direct coordination issue from the in-scope pages.

Return ONLY valid JSON. Do not use markdown. Do not include commentary before or after the JSON.

Your job is to identify drawing updates needed. Do not write finished PDF markup comments. AutoQC will convert your updates into markups after the JSON is pasted back into the app.

Required response schema:
{
  "updates": [
    {
      "page_number": 1,
      "target_text": "exact visible text or concise visible target copied from the PDF",
      "issue": "clear description of the drawing issue",
      "recommended_update": "specific update needed",
      "reason": "why this update is needed based on visible PDF evidence",
      "confidence": "high|medium|low"
    }
  ]
}

Rules:
- Every update must have a page_number and target_text tied to visible PDF content.
- Verify every issue visually against the attached PDF.
- Do not assume extracted evidence is complete.
- Do not invent tags, notes, dimensions, references, or drawing requirements that are not visible in the PDF.
- If no visible actionable issues are found for this batch, return {"updates": []}.
"""


def page_prompt_context(packet: dict[str, Any], *, max_text_lines: int = 8, max_table_chars: int = 700) -> str:
    refs = packet.get("references") or {}
    tokens = packet.get("engineering_tokens") or {}
    quality = packet.get("quality") or {}
    text = packet.get("text") or {}
    title = packet.get("sheet_title") or "Unknown Sheet"
    drawing_number = packet.get("drawing_number") or "UNKNOWN"
    discipline = str(packet.get("discipline") or "unknown").replace("_", " ").upper()
    references = _take_unique(
        [
            *(refs.get("drawing_references") or []),
            *(refs.get("cross_references") or []),
        ],
        16,
    )
    tags = _take_unique(
        [
            *(tokens.get("equipment_tags") or []),
            *(tokens.get("instrument_tags") or []),
            *(tokens.get("valve_tags") or []),
        ],
        18,
    )
    pipe_sizes = _take_unique(tokens.get("pipe_size_tokens") or [], 12)
    important = _take_unique([*(text.get("important_text") or []), *(text.get("notes") or [])], max_text_lines)
    warnings = list(quality.get("warnings") or [])
    if packet.get("extraction_failed"):
        warnings.append("page evidence extraction failed; use the attached PDF page directly")
    if not text.get("title_block_text"):
        warnings.append("title block not confidently detected")
    if not packet.get("tables"):
        warnings.append("table extraction weak or no tables detected")

    lines = [
        f"PAGE {packet.get('page_number')} / SHEET {drawing_number} / {title}",
        SOURCE_OF_TRUTH_WARNING,
        f"Discipline: {discipline}",
        f"Extraction quality: {_quality_label(float(quality.get('overall_score') or 0))} ({float(quality.get('overall_score') or 0):.1f}/100)",
        f"Detected references: {', '.join(references) if references else 'none detected'}",
        f"Detected tags: {', '.join(tags) if tags else 'none detected'}",
        f"Detected pipe sizes: {', '.join(pipe_sizes) if pipe_sizes else 'none detected'}",
        "",
        "Important notes/text:",
    ]
    lines.extend([f"- {_clip(item, 220)}" for item in important] or ["- None detected in extracted support context."])
    lines.append("")
    lines.append("Tables:")
    table_lines = []
    for table in packet.get("tables") or []:
        content = _clip(str(table.get("content") or "").strip(), max_table_chars)
        if content:
            table_lines.append(f"- {table.get('type') or 'generic'} ({table.get('source') or 'unknown'}): {content}")
    lines.extend(table_lines or ["- None detected in extracted support context."])
    lines.append("")
    lines.append("Warnings:")
    lines.extend([f"- {_clip(item, 220)}" for item in _take_unique(warnings, 8)] or ["- None"])
    return "\n".join(lines).strip()


def package_prompt_context(packets: list[dict[str, Any]], *, max_pages: int | None = None) -> str:
    selected = packets[:max_pages] if max_pages else packets
    lines = [
        "AUTOQC SHEET EVIDENCE SUPPORT CONTEXT",
        SOURCE_OF_TRUTH_WARNING,
        "Use this context to navigate the attached PDF and focus review attention. Verify every issue visually in the PDF before reporting it.",
        "",
    ]
    for packet in selected:
        lines.append(page_prompt_context(packet))
        lines.append("")
        lines.append("---")
        lines.append("")
    if max_pages and len(packets) > max_pages:
        lines.append(f"{len(packets) - max_pages} additional page evidence packets were omitted from this prompt context for size.")
    return "\n".join(lines).strip()


def enhanced_prompt_preview(packets: list[dict[str, Any]], *, max_pages: int | None = None) -> str:
    return (
        "AutoQC Enhanced Prompt Context Preview\n\n"
        f"{SOURCE_OF_TRUTH_WARNING}\n\n"
        "Attach the drawing package PDF when using this context. The evidence is not a replacement for visual review.\n\n"
        f"{package_prompt_context(packets, max_pages=max_pages)}\n"
    )


def generate_enhanced_prompt_batches(
    packets: list[dict[str, Any]],
    output_dir: Path,
    *,
    pages_per_batch: int = DEFAULT_BATCH_SIZE,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> dict[str, Any]:
    """Write ChatGPT/Copilot-safe page-batched enhanced prompts and an index."""
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_batch_size = max(1, int(pages_per_batch or DEFAULT_BATCH_SIZE))
    normalized_limit = max(5_000, int(max_prompt_chars or DEFAULT_MAX_PROMPT_CHARS))
    ordered = sorted(packets, key=lambda item: (str(item.get("pdf_name") or item.get("pdf_path") or ""), int(item.get("page_number") or 0)))
    batches = []
    for batch_number, start in enumerate(range(0, len(ordered), normalized_batch_size), start=1):
        batch_packets = ordered[start : start + normalized_batch_size]
        prompt, clipped = enhanced_prompt_batch(batch_packets, batch_number=batch_number, max_prompt_chars=normalized_limit)
        page_label = _batch_page_label(batch_packets)
        path = output_dir / f"batch_{batch_number:03d}_pages_{page_label}.md"
        path.write_text(prompt + "\n", encoding="utf-8")
        batches.append(
            {
                "batch_number": batch_number,
                "path": str(path),
                "pdf_pages": _batch_pdf_pages(batch_packets),
                "packet_count": len(batch_packets),
                "char_count": len(prompt),
                "max_prompt_chars": normalized_limit,
                "clipped_to_limit": clipped,
                "source_of_truth_warning_present": SOURCE_OF_TRUTH_WARNING in prompt,
            }
        )
    index_text = batch_index_markdown(batches, pages_per_batch=normalized_batch_size, max_prompt_chars=normalized_limit)
    index_path = output_dir / "batch_index.md"
    index_path.write_text(index_text, encoding="utf-8")
    payload = {
        "output_dir": str(output_dir),
        "batch_index": str(index_path),
        "batch_count": len(batches),
        "pages_per_batch": normalized_batch_size,
        "max_prompt_chars": normalized_limit,
        "batches": batches,
    }
    write_json(output_dir / "batch_index.json", payload)
    return payload


def enhanced_prompt_batch(batch_packets: list[dict[str, Any]], *, batch_number: int, max_prompt_chars: int) -> tuple[str, bool]:
    scope_lines = _scope_lines(batch_packets)
    evidence = _batch_evidence_context(batch_packets, max_text_lines=8, max_table_chars=700)
    prompt = _compose_batch_prompt(batch_number, scope_lines, evidence)
    if len(prompt) <= max_prompt_chars:
        return prompt, False

    evidence = _batch_evidence_context(batch_packets, max_text_lines=4, max_table_chars=300)
    prompt = _compose_batch_prompt(batch_number, scope_lines, evidence)
    if len(prompt) <= max_prompt_chars:
        return prompt, False

    clipped_evidence = evidence[: max(0, max_prompt_chars - len(_compose_batch_prompt(batch_number, scope_lines, "")) - 450)].rstrip()
    clipped_evidence += "\n\n[Evidence context trimmed to stay within the configured prompt size limit. The attached PDF remains the source of truth.]"
    return _compose_batch_prompt(batch_number, scope_lines, clipped_evidence), True


def batch_index_markdown(batches: list[dict[str, Any]], *, pages_per_batch: int, max_prompt_chars: int) -> str:
    lines = [
        "# AutoQC Enhanced Prompt Batch Index",
        "",
        SOURCE_OF_TRUTH_WARNING,
        "",
        f"- Pages per batch: {pages_per_batch}",
        f"- Max prompt chars per batch: {max_prompt_chars}",
        f"- Batch count: {len(batches)}",
        "",
        "## Batches",
        "",
    ]
    for batch in batches:
        scopes = "; ".join(f"{pdf}: pages {', '.join(str(page) for page in pages)}" for pdf, pages in batch.get("pdf_pages", {}).items())
        clipped = " yes" if batch.get("clipped_to_limit") else " no"
        lines.append(f"- Batch {int(batch.get('batch_number') or 0):03d}: `{Path(str(batch.get('path'))).name}`")
        lines.append(f"  - Scope: {scopes or 'none'}")
        lines.append(f"  - Prompt chars: {batch.get('char_count')} / {batch.get('max_prompt_chars')}")
        lines.append(f"  - Trimmed to limit:{clipped}")
    return "\n".join(lines).strip() + "\n"


def _compose_batch_prompt(batch_number: int, scope_lines: list[str], evidence: str) -> str:
    return "\n".join(
        [
            f"# AutoQC Enhanced Manual Review Prompt Batch {batch_number:03d}",
            "",
            SOURCE_OF_TRUTH_WARNING,
            "The sheet evidence below is not complete extraction. It is only support context to help navigate the attached PDF.",
            "",
            "## Pages in scope",
            "",
            *[f"- {line}" for line in scope_lines],
            "",
            "## Manual review instructions",
            "",
            MANUAL_REVIEW_INSTRUCTIONS.strip(),
            "",
            "## Sheet evidence support context for this batch",
            "",
            evidence.strip() if evidence.strip() else "No sheet evidence packets were available for this batch. Review the attached PDF pages directly.",
        ]
    ).strip()


def _batch_evidence_context(batch_packets: list[dict[str, Any]], *, max_text_lines: int, max_table_chars: int) -> str:
    lines = []
    for packet in batch_packets:
        lines.append(page_prompt_context(packet, max_text_lines=max_text_lines, max_table_chars=max_table_chars))
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).strip()


def _scope_lines(batch_packets: list[dict[str, Any]]) -> list[str]:
    lines = []
    for pdf_name, pages in _batch_pdf_pages(batch_packets).items():
        lines.append(f"{pdf_name}: pages {', '.join(str(page) for page in pages)}")
    return lines


def _batch_pdf_pages(batch_packets: list[dict[str, Any]]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for packet in batch_packets:
        pdf_name = str(packet.get("pdf_name") or Path(str(packet.get("pdf_path") or "PDF")).name)
        grouped.setdefault(pdf_name, []).append(int(packet.get("page_number") or 0))
    return grouped


def _batch_page_label(batch_packets: list[dict[str, Any]]) -> str:
    pages = [int(packet.get("page_number") or 0) for packet in batch_packets]
    if not pages:
        return "none"
    return f"{min(pages):03d}_{max(pages):03d}"


def _quality_label(score: float) -> str:
    if score >= 75:
        return "Good"
    if score >= 50:
        return "Usable with caution"
    if score > 0:
        return "Weak"
    return "Unavailable"


def _take_unique(values: object, limit: int) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
        if len(ordered) >= limit:
            break
    return ordered


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)].rstrip() + " ...[trimmed]"
