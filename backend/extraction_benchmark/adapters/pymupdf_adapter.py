from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.extraction_benchmark.adapters.base import ExtractorAdapter, NormalizedResult, safe_name


class PyMuPDFAdapter(ExtractorAdapter):
    tool_name = "pymupdf"
    package_names = ("PyMuPDF",)
    module_names = ("fitz",)

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import fitz  # noqa: F401
        except Exception as exc:
            return False, f"PyMuPDF import failed: {exc}"
        return True, None

    def _extract_page(
        self,
        pdf_path: Path,
        page_number: int,
        output_dir: Path,
        timeout_seconds: int,
    ) -> NormalizedResult:
        import fitz

        with fitz.open(pdf_path) as doc:
            if page_number < 1 or page_number > doc.page_count:
                raise ValueError(f"page {page_number} is outside PDF page range 1-{doc.page_count}")
            page = doc.load_page(page_number - 1)
            text = page.get_text("text", sort=True) or ""
            blocks = _page_blocks(page)
            images = _page_images(page)
            thumbnail_path = _write_thumbnail(page, pdf_path, page_number, output_dir)
            if thumbnail_path:
                images.append({"bbox": None, "description": "debug page thumbnail", "path": str(thumbnail_path)})
            return {
                "text": text,
                "blocks": blocks,
                "images": images,
                "metadata": {
                    "page_width": float(page.rect.width),
                    "page_height": float(page.rect.height),
                    "rotation": int(page.rotation or 0),
                    "cropbox_width": float(page.cropbox.width),
                    "cropbox_height": float(page.cropbox.height),
                    "page_count": int(doc.page_count),
                },
            }


def _page_blocks(page: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(page.get_text("blocks", sort=True) or []):
        if len(block) < 5:
            continue
        text = str(block[4] or "").strip()
        if not text:
            continue
        block_type = int(block[6]) if len(block) > 6 and isinstance(block[6], int) else 0
        blocks.append(
            {
                "type": "text" if block_type == 0 else "image",
                "text": text,
                "bbox": [float(block[0]), float(block[1]), float(block[2]), float(block[3])],
                "confidence": None,
                "metadata": {"block_index": index, "pymupdf_block_type": block_type},
            }
        )
    return blocks


def _page_images(page: Any) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    try:
        page_images = page.get_images(full=True) or []
    except Exception:
        return images
    for image_index, image in enumerate(page_images):
        xref = image[0]
        try:
            rects = page.get_image_rects(xref) or []
        except Exception:
            rects = []
        if not rects:
            images.append({"bbox": None, "description": f"embedded image {xref}", "path": None})
            continue
        for rect in rects:
            images.append(
                {
                    "bbox": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    "description": f"embedded image {xref}",
                    "path": None,
                    "metadata": {"image_index": image_index},
                }
            )
    return images


def _write_thumbnail(page: Any, pdf_path: Path, page_number: int, output_dir: Path) -> Path | None:
    try:
        import fitz

        target_dir = output_dir / "pymupdf" / safe_name(pdf_path.stem)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"page_{page_number:03d}_thumb.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(0.35, 0.35), alpha=False)
        pix.save(target)
        return target
    except Exception:
        return None

