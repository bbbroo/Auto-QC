# Engineering Evaluation

AutoQC validation scripts prove workflow mechanics. They do not prove engineering correctness, review completeness, or usefulness of imported AI findings. Use a gold corpus before making pilot claims about review quality.

## Gold Corpus Goal

Build 3-5 human-reviewed drawing packages with:

- Expected findings accepted by a responsible reviewer.
- Known false positives that should not be reported.
- Missed issues found during second-pass review.
- Correct severity and category labels.
- Placement quality notes for exact, fuzzy, page-level, and manual-placement cases.

Keep private PDFs outside the repository. Store only redacted target text, page numbers, reviewer labels, and links to local controlled project artifacts.

## Corpus Format

Start from the v2 template:

```text
samples/evaluation/gold_corpus_template.json
```

Each case can embed `actual_findings` directly or point to an AutoQC export JSON using `actual_findings_path`. Use `missed_findings` for human-discovered misses and include reviewer disposition, placement status, source type, and audit lineage where available.

Run:

```powershell
python scripts/evaluate_gold_corpus.py samples/evaluation/gold_corpus_template.json
```

Optional report output:

```powershell
python scripts/evaluate_gold_corpus.py path\to\gold_corpus.json --output data\validation_reports\gold_corpus_metrics.json
```

## Metrics

- `recall`: expected human findings matched by AutoQC imported findings.
- `precision`: AutoQC imported findings that match expected human findings.
- `severity_accuracy`: matched findings with the expected severity.
- `category_accuracy`: matched findings with the expected category.
- `known_false_positive_count`: imported findings that match reviewer-designated false positives.
- `reviewer_disposition_totals`: accepted, rejected, edited, duplicate, deferred, and placement-needed outcomes.
- `placement_accuracy`: expected placement labels matched by AutoQC placement labels.
- `manual_placement_burden_total`: findings that required page-level/manual placement work.
- `second_pass_audit_yield_total`: findings imported from `missed_issue_audit` batches or batches with `audit_of_batch_id`.
- `declared_missed_issue_total`: known missed issues recorded by the human reviewer.

Matching is intentionally conservative: page number plus normalized target text. This keeps the first evaluation loop auditable and easy to challenge.

## Acceptance Use

For company pilot readiness, treat these as decision inputs, not automatic pass/fail gates. A useful pilot target is:

- high recall on drafting/titleblock/coordination issues,
- low known false-positive count,
- clear reviewer edits on every accepted final finding,
- no final export without human signoff,
- second-pass missed-issue audit yield tracked separately.
