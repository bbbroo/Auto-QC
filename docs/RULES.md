# Legacy Rule Engine

The active UI review workflow is AI-only. Uploading a drawing package and running the standard project review prepares sheets, text, entities, and images, but it does not create deterministic rule findings for the reviewer.

AI review items come from `backend/app/services/ai_review.py`. The primary workflow is the manual prompt bridge: generate a Chat Prompt, attach the drawing package in ChatGPT or Copilot Chat, preview the returned JSON, then import valid updates. The optional configured AI provider path is separate. Imported updates are normalized into `source="ai"` findings, default to `needs_review`, and are the only findings listed, edited, deleted, or exported by the active UI/API.

Manual imports record `review_modality: manual_pdf_attached_external`. Second-pass missed-issue audit imports are still AI-imported findings, but their import batches also record `audit_of_batch_id`, `audit_round`, and `audit_yield_count` so recall-audit yield can be measured separately from first-pass review.

The deterministic rule engine remains in the repository as internal/testable legacy code. It is useful for regression coverage of extraction, station-graph reasoning, stable IDs, evidence records, deduplication, confidence handling, and legacy rule behavior. It should not be described as the source of active user-facing review items.

## Legacy Review Modules

- Regulator station configuration: checks inlet isolation, outlet isolation, worker regulator, filter/strainer, and bypass visibility.
- PFD/P&ID consistency: compares extracted valve tags, equipment tags, instrument tags, and line numbers between PFD and P&ID sheets.
- Operability: checks whether bypass, vent/blowdown, and drain arrangements are visible enough to support isolation and maintenance review.
- Overpressure protection: checks for relief valves, monitor regulators, slam-shut devices, OPP references, and setpoint/MAOP basis.
- Instrumentation: checks pressure indication and regulator sensing, pilot, or control line visibility.
- Drafting quality: checks unresolved TBD/HOLD/VERIFY notes, unmatched drawing references, and excessive repeated tags.
- Revision/title block: checks missing drawing numbers, titles, revisions, and duplicate drawing numbers.

## Active AI Finding Lifecycle

AI provider responses or manually imported AI JSON updates are previewed before they become candidate findings. The active workflow then:

1. Parses strict JSON or common ChatGPT/Copilot malformed JSON into a preview.
2. Reports parser repairs, warnings, missing/weak fields, duplicate stable IDs, coverage status, and create/update actions.
3. Computes expected review pages from the prompt scope: whole package, batch, or single sheet.
4. Blocks import unless every expected page is confirmed in `reviewed_pages` with `review_status: "complete"`.
5. Requires a valid page number, usable `target_text`, and update/comment text for each imported finding.
6. Maps the update to the matching sheet.
7. Creates a stable AI rule ID primarily from page and normalized target text.
8. Converts the update into a `CandidateFinding` with `source="ai"`.
9. Preserves original AI fields, AI import batch ID, and prompt version for audit/debugging.
10. Normalizes and deduplicates candidates.
11. Sets status to `needs_review` so a human reviewer confirms, edits, rejects, defers, or escalates the item before export.

Updates with missing or blank `target_text` are skipped during preview with a visible reason. Pages with updates do not automatically count as reviewed; clean pages count only when imported `reviewed_pages` confirms them complete and there are no returned update candidates for that page. Preview IDs can only be imported while their batch is still `previewed`; stale or already imported previews must be regenerated so old pasted JSON cannot silently overwrite a newer import.

The active API returns only these AI findings through `/projects/{project_id}/findings`.

## Editable AI Findings

Reviewers can edit AI findings without changing their `source="ai"` boundary. Editable export-facing fields include final PDF comment, required update, rationale, category, severity, page number, target text/evidence, confidence, reviewer note, and reviewer status. The original AI payload remains available on the finding for audit/debugging.

Expanded reviewer statuses are:

- `needs_review`
- `accepted`
- `rejected`
- `needs_manual_placement`
- `needs_engineer_input`
- `duplicate`
- `deferred`

Draft exports include selected statuses, use draft-labeled filenames/summaries, and always filter to `source="ai"`. Final exports are stricter: accepted findings only, complete review coverage required, reviewer signoff required, no manual-placement blockers, and generated PDF validation must pass or have warnings explicitly acknowledged. The pilot workflow does not support a final-export coverage override.

Direct AI Review is optional and experimental. It is text-context-only unless upgraded to true PDF/image review, and records `review_modality: text_context_only`. If the direct path is capped by `AUTOQC_AI_MAX_SHEETS`, imported coverage is scoped to only the sent pages and cannot complete a whole-package review by itself.

## Placement Statuses

Marked PDF export records placement status for each exported AI finding:

- `exact_target_found`: existing location or exact target text search succeeded.
- `fuzzy_target_found`: a reasonable shortened/normalized target search succeeded.
- `page_level_fallback`: target text was not found, so a page-level note was added.
- `manual_placement_needed`: no valid page/target placement was available.

The QA register CSV records placement status, whether target text was found, whether the finding was exported, and whether manual placement is needed.

## Legacy Deterministic Lifecycle

When tests call the deterministic engine directly, rules emit candidate findings. The normalizer then:

1. Creates a stable ID from rule, sheet, category, title, and involved entities.
2. Deduplicates overlapping findings.
3. Clamps confidence to a valid range.
4. Sets default status to `accepted` when confidence is at least `0.70`, otherwise `needs_review`.
5. Keeps visible PDF comments concise while preserving detailed reasoning internally.

## Adding Legacy Rules

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

Prefer narrow rules with clear evidence over broad comments. When a rule is uncertain, lower confidence so deterministic tests can assert the expected status. New deterministic rules should be treated as internal coverage unless the product direction explicitly changes; they should not be wired into the active UI as reviewer findings.

## Adding Active Review Guidance

For user-facing review behavior, update the AI workflow instead of adding deterministic UI rules. Relevant places are:

- `backend/app/services/ai_review.py`: prompt, payload, response parsing, category/severity coercion, and AI finding normalization.
- Manual prompt guidance: require the actual drawing package PDF to be attached in the external AI chat and require JSON updates with `page_number`, `target_text`, and `required_update`.
- Tests around AI import/provider behavior: verify the AI response becomes `source="ai"` findings and remains editable/exportable through the active API.
