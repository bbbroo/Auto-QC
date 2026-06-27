from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path
from typing import Any

import fitz

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.services.classifier import classify_sheet, extract_title_block
from backend.app.services.extraction import extract_entities
from backend.app.services.reasoning import ReasoningEngine


class PDFProcessor:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.reasoning = ReasoningEngine()

    def project_dir(self, project_id: str) -> Path:
        return self.settings.data_dir / "projects" / project_id

    def save_uploaded_pdf(self, project_id: str, filename: str, content: bytes) -> Path:
        if len(content) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"Upload exceeds {self.settings.max_upload_mb} MB limit")
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
        source_pdf = project.get("source_pdf_path")
        if not source_pdf:
            raise ValueError("Project has no source PDF")
        source_path = Path(source_pdf)
        if not source_path.exists():
            raise FileNotFoundError(source_path)

        self.db.update_project(project_id, status="processing")
        self.db.clear_project_analysis(project_id)
        sheets_dir = self.project_dir(project_id) / "sheets"
        sheets_dir.mkdir(parents=True, exist_ok=True)

        all_entities: list[dict[str, Any]] = []
        try:
            with fitz.open(source_path) as doc:
                for page_index, page in enumerate(doc):
                    page_number = page_index + 1
                    text = page.get_text("text") or ""
                    blocks = _page_blocks(page)
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

                    title_block = extract_title_block(text, page_number)
                    sheet_type = classify_sheet(text, page_number, title_block.drawing_number, title_block.sheet_title)
                    sheet_id = str(uuid.uuid4())
                    sheet = {
                        "id": sheet_id,
                        "project_id": project_id,
                        "page_number": page_number,
                        "drawing_number": title_block.drawing_number,
                        "sheet_title": title_block.sheet_title,
                        "revision": title_block.revision,
                        "sheet_type": sheet_type,
                        "extraction_status": "text_extracted" if text.strip() else "no_text",
                        "ocr_status": ocr_status,
                        "image_path": str(image_path),
                        "text_content": text,
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                        "review_status": "ready",
                    }
                    self.db.insert_sheet(sheet)
                    all_entities.extend(extract_entities(project_id, sheet_id, page_number, text, blocks))

            self.db.insert_entities(all_entities)
            sheets = self.db.list_sheets(project_id)
            entities = self.db.list_entities(project_id)
            findings = self.reasoning.review_project(project_id, sheets, entities)
            self.db.replace_findings(project_id, findings)

            summary = _project_summary(sheets, findings)
            self.db.update_project(project_id, status="ready", summary=summary)
            return {
                "project": self.db.get_project(project_id),
                "sheets": sheets,
                "findings": findings,
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


def _page_blocks(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    blocks: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("blocks") or []:
        if len(block) >= 5 and isinstance(block[4], str) and block[4].strip():
            blocks.append((float(block[0]), float(block[1]), float(block[2]), float(block[3]), block[4]))
    return blocks


def _weak_text(text: str) -> bool:
    stripped = (text or "").strip()
    return len(stripped) < 40 or len(stripped.split()) < 8


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
        f"Generated {len(findings)} findings by severity: {severity_counts}."
    )

