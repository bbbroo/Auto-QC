# Sheet Evidence Builder Hardening

## Goal
Finish Sheet Evidence Builder hardening - per-page isolation, resumable processing, improved validation, enhanced prompt batch generation.

## Scope
1. builder.py: per-page try/except isolation, fallback packets, resumable processing
2. validate_pdf_output: comprehensive checks
3. Enhanced prompt batch generation wiring
4. Tests for all new functionality
5. Run compileall, tests, autopilot E2E

## Non-goals
- Expose benchmark UI
- Require heavy optional extractors (camelot, pdfplumber)
- Remove old prompt path
- Send PDFs externally

## Success Criteria
- [ ] Per-page isolation: one failing page doesn't abort the whole PDF
- [ ] Fallback packets have extraction_failed=true, page_number, page_count, pdf_name, warnings
- [ ] Resumable processing: reuses existing page_###.json unless --force
- [ ] validate_pdf_output checks page count, JSON files, summary, prompt context, source-of-truth warning
- [ ] Enhanced prompt batches generated with correct structure
- [ ] All tests pass
- [ ] autopilot E2E run succeeds
