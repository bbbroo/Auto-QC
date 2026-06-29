from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REVIEWER_DISPOSITIONS = {
    "accepted",
    "rejected",
    "edited",
    "duplicate",
    "deferred",
    "needs_review",
    "needs_manual_placement",
    "needs_engineer_input",
}


def normalize_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def finding_signature(item: dict[str, Any]) -> tuple[int, str]:
    page = int(item.get("page_number") or 0)
    target = item.get("target_text") or item.get("markup_text") or item.get("text_excerpt")
    if not target and isinstance(item.get("evidence"), list):
        for evidence in item["evidence"]:
            if isinstance(evidence, dict):
                target = evidence.get("target_text") or evidence.get("markup_text") or evidence.get("text_excerpt")
                if target:
                    break
    return page, normalize_text(target)


def item_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def item_disposition(item: dict[str, Any]) -> str:
    value = item.get("reviewer_disposition") or item.get("disposition") or item.get("status") or "needs_review"
    normalized = normalize_text(value).replace(" ", "_")
    return normalized if normalized in REVIEWER_DISPOSITIONS else "needs_review"


def item_source_type(item: dict[str, Any]) -> str:
    metadata = item_metadata(item)
    value = item.get("source_type") or item.get("batch_source_type") or metadata.get("source_type") or ""
    return str(value or "").strip()


def is_second_pass_audit_item(item: dict[str, Any]) -> bool:
    metadata = item_metadata(item)
    return (
        item_source_type(item) == "missed_issue_audit"
        or bool(item.get("audit_of_batch_id"))
        or bool(metadata.get("audit_of_batch_id"))
    )


def placement_label(item: dict[str, Any]) -> str:
    value = (
        item.get("expected_placement_status")
        or item.get("placement_status")
        or item.get("placement_quality")
        or item.get("placement_label")
        or ""
    )
    return normalize_text(value).replace(" ", "_")


def count_by(items: list[dict[str, Any]], key_fn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = key_fn(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_actual_findings(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ["findings", "updates", "actual_findings"]:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"{path} does not contain a findings array.")


def evaluate_case(case: dict[str, Any], corpus_dir: Path) -> dict[str, Any]:
    expected = [item for item in case.get("expected_findings") or [] if isinstance(item, dict)]
    rejected = [item for item in case.get("known_false_positives") or [] if isinstance(item, dict)]
    declared_missed = [
        item
        for item in [*(case.get("missed_findings") or []), *(case.get("missed_issues") or [])]
        if isinstance(item, dict)
    ]
    actual_ref = case.get("actual_findings_path")
    actual = load_actual_findings((corpus_dir / actual_ref).resolve()) if actual_ref else [
        item for item in case.get("actual_findings") or [] if isinstance(item, dict)
    ]

    expected_by_signature = {finding_signature(item): item for item in expected}
    rejected_signatures = {finding_signature(item) for item in rejected}
    actual_by_signature = {finding_signature(item): item for item in actual}

    matched_signatures = sorted(set(expected_by_signature) & set(actual_by_signature))
    missed_signatures = sorted(set(expected_by_signature) - set(actual_by_signature))
    extra_signatures = sorted(set(actual_by_signature) - set(expected_by_signature))
    false_positive_signatures = sorted(set(actual_by_signature) & rejected_signatures)

    severity_matches = 0
    category_matches = 0
    placement_expected = 0
    placement_matches = 0
    for signature in matched_signatures:
        expected_item = expected_by_signature[signature]
        actual_item = actual_by_signature[signature]
        if str(expected_item.get("severity") or "").lower() == str(actual_item.get("severity") or "").lower():
            severity_matches += 1
        if str(expected_item.get("category") or "").lower() == str(actual_item.get("category") or "").lower():
            category_matches += 1
        expected_placement = placement_label(expected_item)
        if expected_placement:
            placement_expected += 1
            if placement_label(actual_item) == expected_placement:
                placement_matches += 1

    expected_count = len(expected_by_signature)
    actual_count = len(actual_by_signature)
    matched_count = len(matched_signatures)
    recall = matched_count / expected_count if expected_count else 1.0
    precision = matched_count / actual_count if actual_count else (1.0 if expected_count == 0 else 0.0)
    dispositions = count_by(actual, item_disposition)
    second_pass_yield_count = sum(1 for item in actual if is_second_pass_audit_item(item))
    manual_placement_burden_count = sum(
        1
        for item in actual
        if placement_label(item) in {"manual_placement_needed", "page_level_fallback"}
        or item_disposition(item) == "needs_manual_placement"
    )

    return {
        "case_id": case.get("case_id") or case.get("name") or "unnamed_case",
        "package_name": case.get("package_name"),
        "expected_count": expected_count,
        "actual_count": actual_count,
        "matched_count": matched_count,
        "missed_count": len(missed_signatures),
        "declared_missed_issue_count": len({finding_signature(item) for item in declared_missed}),
        "extra_count": len(extra_signatures),
        "known_false_positive_count": len(false_positive_signatures),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "severity_accuracy": round(severity_matches / matched_count, 4) if matched_count else 0.0,
        "category_accuracy": round(category_matches / matched_count, 4) if matched_count else 0.0,
        "placement_expected_count": placement_expected,
        "placement_matched_count": placement_matches,
        "placement_accuracy": round(placement_matches / placement_expected, 4) if placement_expected else 0.0,
        "reviewer_dispositions": dispositions,
        "accepted_count": dispositions.get("accepted", 0),
        "rejected_count": dispositions.get("rejected", 0),
        "edited_count": dispositions.get("edited", 0),
        "duplicate_count": dispositions.get("duplicate", 0),
        "manual_placement_burden_count": manual_placement_burden_count,
        "second_pass_audit_yield_count": second_pass_yield_count,
        "missed_signatures": missed_signatures,
        "extra_signatures": extra_signatures,
        "known_false_positive_signatures": false_positive_signatures,
    }


def evaluate_corpus(corpus_path: Path) -> dict[str, Any]:
    corpus = load_json(corpus_path)
    cases = corpus.get("cases") if isinstance(corpus, dict) else None
    if not isinstance(cases, list):
        raise ValueError("Gold corpus must contain a cases array.")
    case_results = [evaluate_case(case, corpus_path.parent) for case in cases if isinstance(case, dict)]
    expected_total = sum(item["expected_count"] for item in case_results)
    actual_total = sum(item["actual_count"] for item in case_results)
    matched_total = sum(item["matched_count"] for item in case_results)
    placement_expected_total = sum(item["placement_expected_count"] for item in case_results)
    placement_matched_total = sum(item["placement_matched_count"] for item in case_results)
    disposition_totals: dict[str, int] = {}
    for item in case_results:
        for disposition, count in item["reviewer_dispositions"].items():
            disposition_totals[disposition] = disposition_totals.get(disposition, 0) + count
    return {
        "corpus_path": str(corpus_path),
        "schema_version": corpus.get("schema_version") if isinstance(corpus, dict) else None,
        "case_count": len(case_results),
        "expected_total": expected_total,
        "actual_total": actual_total,
        "matched_total": matched_total,
        "missed_total": sum(item["missed_count"] for item in case_results),
        "declared_missed_issue_total": sum(item["declared_missed_issue_count"] for item in case_results),
        "extra_total": sum(item["extra_count"] for item in case_results),
        "known_false_positive_total": sum(item["known_false_positive_count"] for item in case_results),
        "recall": round(matched_total / expected_total, 4) if expected_total else 1.0,
        "precision": round(matched_total / actual_total, 4) if actual_total else (1.0 if expected_total == 0 else 0.0),
        "placement_accuracy": round(placement_matched_total / placement_expected_total, 4) if placement_expected_total else 0.0,
        "placement_expected_total": placement_expected_total,
        "placement_matched_total": placement_matched_total,
        "reviewer_disposition_totals": disposition_totals,
        "second_pass_audit_yield_total": sum(item["second_pass_audit_yield_count"] for item in case_results),
        "manual_placement_burden_total": sum(item["manual_placement_burden_count"] for item in case_results),
        "cases": case_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AutoQC findings against a human-reviewed gold corpus.")
    parser.add_argument("corpus", type=Path, help="Path to a gold corpus JSON file.")
    parser.add_argument("--output", type=Path, help="Optional path for a JSON metrics report.")
    args = parser.parse_args()

    report = evaluate_corpus(args.corpus)
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
