# Company Pilot Operating Model

AutoQC is a local workflow aid for drawing markup review. It is not an engineering authority and does not replace responsible reviewer judgment.

## Roles

- **Reviewer:** uploads the package, generates the manual Chat Prompt, imports AI JSON, reviews each finding, edits wording, resolves placement, and signs final export.
- **Checker/Engineer:** reviews accepted findings for technical validity, code/company-standard interpretation, operability, safety, and construction feasibility.
- **Pilot owner:** maintains the gold corpus, records false positives/missed issues, and decides whether AutoQC is improving review throughput.

## Approved AI Workflow

Use the manual Chat Prompt workflow as the pilot path:

```text
Upload PDF -> Chat Prompt -> attach same PDF in ChatGPT/Copilot -> preview JSON -> import valid updates -> reviewer disposition -> draft/final export
```

The AI response must include `reviewed_pages` for the intended scope. AutoQC blocks incomplete coverage for final export.

## Direct AI Status

Direct AI Review is parked as experimental until it can inspect actual PDF/image content with the same coverage and import gates. Its current text-context-only mode may help with internal experiments, but it should not be used as a production-equivalent review.

Import batches now record explicit review modality:

- `manual_pdf_attached_external`: primary ChatGPT/Copilot workflow with the PDF attached externally.
- `text_context_only`: experimental Direct AI lab mode.
- `pdf_image_direct`: reserved for a future direct PDF/image-capable review path.

If Direct AI is upgraded later, promote it only when it can use `pdf_image_direct` or an equivalent PDF/image-inspection modality with the same coverage gates.

## Data Handling

- Keep client/company PDFs in controlled local storage.
- Do not commit private PDFs, raw AI responses, project packages, SQLite databases, validation reports, or generated exports.
- Treat project package zips as controlled project artifacts because they may include source PDFs, raw AI response history, findings, and exports.

## Final Export Rules

Final export is allowed only when:

- review coverage is complete,
- exported findings are accepted only,
- no accepted finding needs manual placement,
- generated PDF validation passes or warnings are acknowledged,
- reviewer signoff is recorded.

Draft exports are for internal working review and may include non-final statuses.

## Pilot Scorekeeping

Track these after every package:

- accepted findings,
- rejected findings,
- edited findings,
- duplicate/merged findings,
- known false positives,
- second-pass missed-issue audit yield,
- manual-placement burden,
- final export validation status,
- reviewer time spent before and after AutoQC.
