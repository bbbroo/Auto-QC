# Rule Engine

The first version uses deterministic, evidence-backed rules. Every finding is generated from observations stored in the finding evidence list.

## Review Modules

- Regulator station configuration: checks inlet isolation, outlet isolation, worker regulator, filter/strainer, and bypass visibility.
- PFD/P&ID consistency: compares extracted valve tags, equipment tags, instrument tags, and line numbers between PFD and P&ID sheets.
- Operability: checks whether bypass, vent/blowdown, and drain arrangements are visible enough to support isolation and maintenance review.
- Overpressure protection: checks for relief valves, monitor regulators, slam-shut devices, OPP references, and setpoint/MAOP basis.
- Instrumentation: checks pressure indication and regulator sensing, pilot, or control line visibility.
- Drafting quality: checks unresolved TBD/HOLD/VERIFY notes, unmatched drawing references, and excessive repeated tags.
- Revision/title block: checks missing drawing numbers, titles, revisions, and duplicate drawing numbers.

## Finding Lifecycle

Rules emit candidate findings. The normalizer then:

1. Creates a stable ID from rule, sheet, category, title, and involved entities.
2. Deduplicates overlapping findings.
3. Clamps confidence to a valid range.
4. Sets default status to `accepted` when confidence is at least `0.70`, otherwise `needs_review`.
5. Keeps visible PDF comments concise while preserving detailed reasoning internally.

## Adding Rules

Add a focused reviewer class in `backend/app/services/reasoning/engine.py` or split a new module under `backend/app/services/reasoning/`. A rule should return `CandidateFinding` records with:

- explicit `rule_id`
- category from the app category list
- severity
- confidence
- sheet/page if known
- evidence observations
- concise `comment_text`
- detailed `reasoning_summary`
- practical `suggested_correction`

Prefer narrow rules with clear evidence over broad comments. When a rule is uncertain, lower confidence so the UI marks the finding as needing review.
