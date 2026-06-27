# Sample Scenarios

Scenario data lives in `samples/scenarios/regulator_station_scenarios.json`.

The test suite currently covers:

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

Each scenario contains synthetic sheet text and expected finding title fragments. Tests construct sheet and entity records, run the same reasoning engine used by the app, and confirm expected findings are present.

To add a scenario:

1. Add a new object to the JSON array.
2. Include at least one PFD or P&ID sheet.
3. Include title block fields in `text` so extraction behavior is realistic.
4. Add `expected_findings` with title fragments that should appear.
5. Run `pytest`.

For full PDF workflow testing, use:

```powershell
python scripts/make_sample_pdf.py
python scripts/run_sample_review.py
```
