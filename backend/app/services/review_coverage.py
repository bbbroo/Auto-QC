from __future__ import annotations

from typing import Any


ReviewCoverageSummary = dict[str, Any]


def sheet_page_numbers(sheets: list[dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for sheet in sheets:
        try:
            page = int(sheet.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page > 0 and page not in pages:
            pages.append(page)
    return sorted(pages)


def expected_review_pages_for_scope(
    sheets: list[dict[str, Any]],
    *,
    review_scope: Any = "package",
    scope_pages: Any = None,
) -> list[int]:
    all_pages = sheet_page_numbers(sheets)
    scoped = [page for page in _coerce_page_list(scope_pages) if page in all_pages or not all_pages]
    scope = str(review_scope or "package").strip().lower().replace("_", "-")
    if scope in {"batch", "batches", "adaptive", "adaptive-batch", "sheet", "single", "single-sheet", "page"}:
        return sorted(dict.fromkeys(scoped))
    return all_pages


def build_review_coverage_summary(
    expected_pages: list[int],
    reviewed_pages: list[dict[str, Any]],
) -> ReviewCoverageSummary:
    expected = sorted(dict.fromkeys(int(page) for page in expected_pages if int(page) > 0))
    expected_set = set(expected)
    reviewed_by_page: dict[int, dict[str, Any]] = {}
    for item in reviewed_pages:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page <= 0 or (expected_set and page not in expected_set):
            continue
        reviewed_by_page[page] = item

    reviewed_pages_confirmed = sorted(
        page
        for page, item in reviewed_by_page.items()
        if str(item.get("review_status") or "").strip().lower() == "complete"
    )
    incomplete_review_pages = sorted(
        page
        for page, item in reviewed_by_page.items()
        if str(item.get("review_status") or "").strip().lower() == "incomplete"
    )
    not_readable_pages = sorted(
        page
        for page, item in reviewed_by_page.items()
        if str(item.get("review_status") or "").strip().lower() == "not_readable"
    )
    missing_review_pages = [page for page in expected if page not in reviewed_by_page]
    if expected and len(reviewed_pages_confirmed) == len(expected):
        status = "complete"
    elif not reviewed_by_page:
        status = "not_confirmed"
    else:
        status = "incomplete"
    percent = round((len(reviewed_pages_confirmed) / len(expected)) * 100, 1) if expected else 0.0
    return {
        "expected_review_pages": expected,
        "reviewed_pages_confirmed": reviewed_pages_confirmed,
        "missing_review_pages": missing_review_pages,
        "incomplete_review_pages": incomplete_review_pages,
        "not_readable_pages": not_readable_pages,
        "review_coverage_status": status,
        "review_coverage_percent": percent,
    }


def clean_pages_from_preview(preview: dict[str, Any]) -> list[int]:
    coverage = preview.get("review_coverage") if isinstance(preview.get("review_coverage"), dict) else preview
    confirmed = _coerce_page_list(coverage.get("reviewed_pages_confirmed") if isinstance(coverage, dict) else [])
    update_pages = {
        page
        for page in _coerce_page_list(
            [
                update.get("page_number")
                for update in preview.get("updates", [])
                if isinstance(update, dict) and update.get("page_number")
            ]
        )
    }
    return [page for page in confirmed if page not in update_pages]


def project_review_coverage_summary(
    sheets: list[dict[str, Any]],
    import_batches: list[dict[str, Any]],
) -> ReviewCoverageSummary:
    expected = sheet_page_numbers(sheets)
    reviewed: dict[int, dict[str, Any]] = {}
    incomplete: set[int] = set()
    not_readable: set[int] = set()
    for batch in import_batches:
        if batch.get("import_status") != "imported":
            continue
        preview = batch.get("preview") if isinstance(batch.get("preview"), dict) else {}
        metadata = batch.get("metadata") if isinstance(batch.get("metadata"), dict) else {}
        coverage = metadata.get("review_coverage") if isinstance(metadata.get("review_coverage"), dict) else {}
        confirmed = _coerce_page_list(coverage.get("reviewed_pages_confirmed"))
        if not confirmed:
            confirmed = [
                int(item.get("page_number"))
                for item in preview.get("reviewed_pages") or []
                if isinstance(item, dict)
                and str(item.get("review_status") or "").lower() == "complete"
                and _positive_int(item.get("page_number"))
            ]
        for page in confirmed:
            if page in expected:
                reviewed[page] = {"page_number": page, "review_status": "complete"}
        incomplete.update(page for page in _coerce_page_list(coverage.get("incomplete_review_pages")) if page in expected)
        not_readable.update(page for page in _coerce_page_list(coverage.get("not_readable_pages")) if page in expected)

    for page in sorted(incomplete - set(reviewed)):
        reviewed[page] = {"page_number": page, "review_status": "incomplete"}
    for page in sorted(not_readable - set(reviewed)):
        reviewed[page] = {"page_number": page, "review_status": "not_readable"}
    return build_review_coverage_summary(expected, [reviewed[page] for page in sorted(reviewed)])


def _coerce_page_list(value: Any) -> list[int]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    pages: list[int] = []
    for raw in raw_values:
        page = _positive_int(raw)
        if page and page not in pages:
            pages.append(page)
    return pages


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
