from __future__ import annotations

import io
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import fitz

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.services.classifier import TitleCandidate, classify_sheet, extract_title_block, normalize_space
from backend.app.services.extraction import extract_entities
from backend.app.services.storage import require_project_source_pdf_path


class PDFProcessor:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def project_dir(self, project_id: str) -> Path:
        return self.settings.data_dir / "projects" / project_id

    def save_uploaded_pdf(self, project_id: str, filename: str, content: bytes) -> Path:
        if not content:
            raise ValueError("Upload is empty. Select a PDF drawing set and try again.")
        if len(content) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"Upload exceeds {self.settings.max_upload_mb} MB limit")
        if not content.lstrip().startswith(b"%PDF"):
            raise ValueError("Uploaded file must be a PDF drawing set.")
        _validate_pdf_bytes(content)
        project_dir = self.project_dir(project_id)
        input_dir = project_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(filename or "drawing_set.pdf")
        target = input_dir / safe_name
        target.write_bytes(content)
        self.db.update_project(project_id, source_pdf_path=str(target), status="uploaded")
        return target

    def copy_sample_pdf(self, project_id: str, sample_pdf: Path) -> Path:
        project_dir = self.project_dir(project_id)
        input_dir = project_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target = input_dir / sample_pdf.name
        shutil.copyfile(sample_pdf, target)
        self.db.update_project(project_id, source_pdf_path=str(target), status="uploaded")
        return target

    def process_project(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        source_path = require_project_source_pdf_path(self.settings.data_dir, project_id, project.get("source_pdf_path"))

        self.db.update_project(project_id, status="processing")
        self.db.clear_project_analysis(project_id)
        sheets_dir = self.project_dir(project_id) / "sheets"
        sheets_dir.mkdir(parents=True, exist_ok=True)

        all_entities: list[dict[str, Any]] = []
        try:
            with fitz.open(source_path) as doc:
                doc_metadata = dict(doc.metadata or {})
                bookmark_titles = _bookmark_titles_by_page(doc)
                for page_index, page in enumerate(doc):
                    page_number = page_index + 1
                    text, blocks = _extract_page_text_and_blocks(page)
                    ocr_status = "not_required"

                    image_path = sheets_dir / f"page_{page_number:03d}.png"
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                    pix.save(image_path)

                    if _weak_text(text):
                        ocr_text = _ocr_image(image_path)
                        if ocr_text:
                            text = f"{text}\n{ocr_text}".strip()
                            ocr_status = "ocr_used"
                        else:
                            ocr_status = "ocr_unavailable"

                    title_candidates = _metadata_adjacent_title_candidates(
                        page=page,
                        page_number=page_number,
                        page_count=doc.page_count,
                        doc_metadata=doc_metadata,
                        bookmark_title=bookmark_titles.get(page_number),
                    )
                    title_block = extract_title_block(text, page_number, title_candidates)
                    sheet_type = classify_sheet(text, page_number, title_block.drawing_number, title_block.sheet_title)
                    sheet_id = str(uuid.uuid4())
                    sheet = {
                        "id": sheet_id,
                        "project_id": project_id,
                        "page_number": page_number,
                        "drawing_number": title_block.drawing_number,
                        "sheet_title": title_block.sheet_title,
                        "sheet_title_source": title_block.sheet_title_source,
                        "sheet_title_confidence": title_block.sheet_title_confidence,
                        "raw_extracted_title": title_block.raw_extracted_title,
                        "revision": title_block.revision,
                        "sheet_type": sheet_type,
                        "extraction_status": "text_extracted" if text.strip() else "no_text",
                        "ocr_status": ocr_status,
                        "image_path": str(image_path),
                        "text_content": text,
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                        "rotation": int(page.rotation or 0),
                        "source_width": float(page.cropbox.width),
                        "source_height": float(page.cropbox.height),
                        "review_status": "ready",
                    }
                    self.db.insert_sheet(sheet)
                    all_entities.extend(extract_entities(project_id, sheet_id, page_number, text, blocks))

            self.db.insert_entities(all_entities)
            sheets = self.db.list_sheets(project_id)
            stored_findings = self.db.list_findings(project_id, sources=["ai"])

            summary = _project_summary(sheets, stored_findings)
            self.db.update_project(project_id, status="ready", summary=summary)
            return {
                "project": self.db.get_project(project_id),
                "sheets": sheets,
                "findings": stored_findings,
                "summary": summary,
            }
        except Exception:
            self.db.update_project(project_id, status="failed")
            raise


def _safe_filename(filename: str) -> str:
    name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in filename).strip()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name or "drawing_set.pdf"


def _validate_pdf_bytes(content: bytes) -> None:
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            if doc.page_count < 1:
                raise ValueError("Uploaded PDF contains no pages.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Uploaded file could not be opened as a valid PDF drawing set.") from exc


def _extract_page_text_and_blocks(page: fitz.Page) -> tuple[str, list[tuple[float, float, float, float, str]]]:
    plain_text = page.get_text("text", sort=True) or ""
    blocks = _page_blocks(page)
    block_text = "\n".join(block[4].strip() for block in blocks if block[4].strip())
    words = page.get_text("words", sort=True) or []
    word_text = _words_to_text(words)

    candidates = [plain_text, block_text, word_text]
    text = max(candidates, key=_text_quality_score).strip()
    if block_text and block_text not in text and _text_quality_score(block_text) > 20:
        text = f"{text}\n{block_text}".strip()
    return text, blocks


def _page_blocks(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    blocks: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("blocks", sort=True) or []:
        if len(block) >= 5 and isinstance(block[4], str) and block[4].strip():
            blocks.append((float(block[0]), float(block[1]), float(block[2]), float(block[3]), block[4]))
    return blocks


def _words_to_text(words: list[Any]) -> str:
    if not words:
        return ""
    rows: list[list[Any]] = []
    for word in sorted(words, key=lambda item: (round(float(item[1]) / 3) * 3, float(item[0]))):
        if len(word) < 5 or not str(word[4]).strip():
            continue
        y0 = float(word[1])
        for row in rows:
            if abs(float(row[0][1]) - y0) <= 3:
                row.append(word)
                break
        else:
            rows.append([word])
    lines = []
    for row in rows:
        row.sort(key=lambda item: float(item[0]))
        lines.append(" ".join(str(item[4]) for item in row))
    return "\n".join(lines)


def _metadata_adjacent_title_candidates(
    *,
    page: fitz.Page,
    page_number: int,
    page_count: int,
    doc_metadata: dict[str, Any],
    bookmark_title: str | None,
) -> list[TitleCandidate]:
    candidates: list[TitleCandidate] = []
    if bookmark_title:
        candidates.append(TitleCandidate(bookmark_title, "bookmark", 0.82))
    page_label = _page_label(page)
    if page_label and page_label != str(page_number):
        candidates.append(TitleCandidate(page_label, "page_label", 0.56))
    metadata_title = normalize_space(str(doc_metadata.get("title") or ""))
    if metadata_title and metadata_title.lower() != "untitled":
        confidence = 0.66 if page_count == 1 else 0.42
        candidates.append(TitleCandidate(metadata_title, "pdf_metadata", confidence))
    return candidates


def _bookmark_titles_by_page(doc: fitz.Document) -> dict[int, str]:
    try:
        toc = doc.get_toc(simple=True) or []
    except Exception:
        return {}
    titles = {}
    for item in toc:
        if len(item) >= 3:
            level, title, page_number = item[:3]
            try:
                page = int(page_number)
                depth = int(level)
            except (TypeError, ValueError):
                continue
            title_text = normalize_space(str(title))
            current = titles.get(page)
            if page >= 1 and title_text and (current is None or depth >= current[0]):
                titles[page] = (depth, title_text)
    return {page: value[1] for page, value in titles.items()}


def _page_label(page: fitz.Page) -> str | None:
    get_label = getattr(page, "get_label", None)
    if not callable(get_label):
        return None
    try:
        label = normalize_space(str(get_label() or ""))
    except Exception:
        return None
    return label or None


def _text_quality_score(text: str) -> int:
    clean = (text or "").strip()
    if not clean:
        return 0
    words = re.findall(r"[A-Za-z0-9]{2,}", clean)
    return len(clean) + 8 * len(words)


def _weak_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    words = re.findall(r"[A-Za-z0-9]{2,}", stripped)
    titleblock_or_notes_tokens = re.findall(r"\b(?:drawing|sheet|revision|rev|date|note|notes|detail|section|plan|profile|scale|project)\b", stripped, flags=re.I)
    if len(words) >= 20 or len(stripped) >= 180:
        return False
    if len(words) >= 10 and len(titleblock_or_notes_tokens) >= 2:
        return False
    return len(stripped) < 80 or len(words) < 10


def _ocr_image(image_path: Path) -> str:
    try:
        from PIL import Image
        import pytesseract

        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image)
    except Exception:
        return ""


def _project_summary(sheets: list[dict[str, Any]], findings: list[dict[str, Any]]) -> str:
    severity_counts: dict[str, int] = {}
    for finding in findings:
        severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1
    sheet_counts: dict[str, int] = {}
    for sheet in sheets:
        sheet_counts[sheet["sheet_type"]] = sheet_counts.get(sheet["sheet_type"], 0) + 1
    return (
        f"Processed {len(sheets)} sheets. "
        f"Detected sheet types: {sheet_counts}. "
        f"AI findings currently available: {len(findings)} by severity: {severity_counts}."
    )
