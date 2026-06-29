# Sample Scenarios

Scenario data lives in `samples/scenarios/regulator_station_scenarios.json`.

These scenarios are legacy deterministic reasoning fixtures. They do not describe the active UI review workflow, and they are not expected to create reviewer-visible findings when a project is uploaded or reprocessed.

Active reviewer coverage is now tracked through imported AI `reviewed_pages` confirmations, not through these deterministic scenarios.

The active UI review workflow is AI-only: users generate a manual prompt, attach the PDF in ChatGPT or Copilot Chat, preview the returned JSON, and import valid updates. Imported updates become `source="ai"` review items. The configured direct AI path is optional and not required for the local no-key workflow.

The legacy scenario test suite currently covers:

- good regulator station
- missing bypass
- missing inlet isolation
- missing outlet isolation
- unclear overpressure protection
- mismatched PFD/P&ID tags
- missing vent or drain details
- unclear pressure sensing line
- duplicate tag
- revision/title block issue

Each scenario contains synthetic sheet text and expected finding title fragments. Tests construct sheet and entity records, run the legacy deterministic reasoning engine directly, and confirm expected internal findings are present. This preserves coverage for the station-graph/rule code without implying that the active UI creates deterministic rule findings.

To add a scenario:

1. Add a new object to the JSON array.
2. Include at least one PFD or P&ID sheet.
3. Include title block fields in `text` so extraction behavior is realistic.
4. Add `expected_findings` with title fragments that should appear.
5. Run `pytest`.

For PDF ingestion and export-shell testing, use:

```powershell
python scripts/make_sample_pdf.py
python scripts/run_sample_review.py
```

That script processes the sample PDF and exports the project shell. It should report zero findings unless AI updates have been imported or an AI provider review has created `source="ai"` findings.
