# Natural Gas Engineering Copilot One-Shot Build Spec

## Current AutoQC Product Boundary

This document preserves the original build brief, including legacy deterministic reasoning language. The current AutoQC pilot boundary supersedes that early direction for user-facing findings:

- AutoQC is an AI-imported-update workflow.
- Upload/reprocess extracts sheets, page images, metadata, entities, OCR/text, review coverage, and prompt context, but it does not create reviewer-visible deterministic QC findings.
- User-facing findings/comments come from imported AI update JSON, optional configured Direct AI Review when clearly labeled, or reviewer/manual edits to those AI findings.
- Review coverage is tracked through imported AI `reviewed_pages` confirmations; no separate tracker workflow is part of the active product.
- Direct AI Review is currently experimental/text-context-only unless upgraded to true PDF/image-capable review and must pass the same coverage/import gates.
- Final export requires complete imported review coverage, accepted findings, signoff, and validation readiness.
- Raw pasted AI responses are preserved server-side for audit, while normal UI/API batch summaries expose only safe trace metadata.
- AI import batches record review modality; missed-issue audit imports record prior batch lineage and yield.
- Project packages validate before restore and strip local absolute paths from package JSON; restored paths are rebuilt from package contents.

## Purpose

Create a complete local-first application called Natural Gas Engineering Copilot. The app should act like an advanced AI engineering review assistant for natural gas regulator station drawing packages. The goal is to automate as much of a mechanical engineer's drawing QC workflow as possible by reviewing PDF drawing sets, reasoning about natural gas regulator station design, identifying likely issues, producing evidence-backed QC findings, and exporting a fully marked-up PDF that can be opened and reviewed in Bluebeam.

This app should not be a small prototype or a simple PDF viewer. It should be built as a serious working application with an advanced reasoning engine, drawing processing pipeline, structured finding model, editable review workflow, marked-up PDF export, QC log export, tests, sample data, and clear documentation. Codex should make reasonable technical decisions where implementation details are not specified, but it should preserve the core product goal: a real working engineering QC copilot.

The app should be optimized around one primary use case: a user uploads a natural gas regulator station drawing set PDF, the app analyzes the package, finds drawing and engineering QC issues, places comments onto the PDF, and exports a Bluebeam-compatible marked-up PDF plus supporting logs and reports.

## Core Product Behavior

The app begins with a project-based workflow. A user creates or opens a project, uploads a PDF drawing set, and starts an automated review. The system splits the drawing set into pages, renders each sheet, extracts embedded PDF text, performs OCR when necessary, classifies sheets, extracts title block information, detects tags and line numbers, builds a structured representation of the drawing package, reasons about the regulator station design, generates QC findings, places markups on the drawing, and exports a finished review package.

The review package should include a marked-up PDF, an Excel or CSV QC log, an internal JSON finding database, and a readable Markdown or HTML review summary. The marked-up PDF should use standard PDF annotations that open in common PDF viewers and Bluebeam. The output should feel similar to a first-pass Bluebeam review from an experienced engineer.

The app should support editing before export. The user should be able to inspect findings, edit comment text, change severity, change category, accept findings, reject findings, delete findings, and export only accepted findings. Even though the app is designed to automate as much as possible, final external use should remain controlled by the user.

## Scope

The first complete version should focus on natural gas regulator station drawing QC. It should support PDF drawing sets containing PFDs, P&IDs, general arrangements, layouts, legends, notes, details, and related sheets. The app should not include engineering calculation modules in the first version. The purpose is drawing review and design QC, not API 1102 calculation, regulator sizing, or pressure drop calculation.

The app should use the PDF drawing set as the source of truth. It may include architecture that allows future Excel, Plant 3D, Bluebeam, and specification imports, but the working one-shot app should function from PDF input alone. It should still be designed so those future inputs can be added cleanly.

The app should include advanced reasoning immediately. It should not defer the engineering review intelligence. The reasoning engine should be implemented as a real part of the app, with structured data models, evidence-backed findings, rule-based checks, AI-assisted review hooks, finding normalization, deduplication, severity assignment, and tests using sample scenarios.

## Recommended Architecture

Use a local-first architecture. Prefer a Python FastAPI backend, a React TypeScript frontend, and a SQLite local database. Use Python PDF-processing libraries such as PyMuPDF or equivalent for PDF rendering, text extraction, and annotation writing. Use OCR where practical. If OCR or AI dependencies are optional, provide graceful fallbacks so the app still runs locally.

The backend should own project storage, PDF ingestion, sheet processing, entity extraction, reasoning, finding storage, PDF markup, and export generation. The frontend should provide the project dashboard, PDF viewer, sheet list, issue list, issue inspector, and export workflow. The database should store projects, sheets, extracted entities, findings, review runs, and export records.

The app should have a simple one-command development workflow. Include clear scripts and README instructions. A new user should be able to install dependencies, start the backend, start the frontend, upload a sample PDF, run a review, inspect findings, and export results.

## Data Model

The app should include structured models for projects, sheets, extracted entities, station components, findings, evidence, review runs, and exports.

A project represents one drawing review package. It should store the project name, source PDF, processing status, created date, updated date, output paths, and review summary.

A sheet represents one page in the drawing package. It should store page number, drawing number, sheet title, revision, detected sheet type, extraction status, OCR status, image path, text content, and review status.

Extracted entities represent drawing information found on each sheet. Entities should include line numbers, valve tags, equipment tags, instrument tags, notes, title block fields, revision information, drawing references, and possible symbols. Each entity should include text, normalized text, entity type, page number, sheet reference, bounding box when available, confidence, and extraction source.

A station graph should represent the inferred regulator station design. It should include components such as inlet isolation, outlet isolation, filter, worker regulator, monitor regulator, bypass, relief or overpressure protection, vents, drains, pressure gauges, transmitters, sensing lines, and associated lines. The graph does not need to be perfect, but it should provide a structured target for the reasoning engine.

A finding represents a QC issue. Each finding should include a stable finding ID, title, category, severity, confidence, sheet reference, page number, location, involved entities, evidence, reasoning summary, suggested correction, visible PDF comment text, status, source, and creation timestamp.

Evidence should be explicit. Each finding should list the observations that caused the finding. The app should avoid unsupported comments. If the app is uncertain, the finding should be marked as lower confidence or placed into a possible-issues status.

## Drawing Processing Pipeline

The app should ingest a PDF drawing set and create a project. It should split the PDF into sheet records and render each page as an image for display and OCR. It should extract embedded PDF text and preserve coordinates when possible. If embedded text is missing or weak, the app should use OCR or a fallback extraction path. The app should classify sheets using title block text, keywords, drawing numbers, and extracted content.

The sheet classifier should identify PFDs, P&IDs, layouts, legends, notes, details, cover sheets, drawing indexes, and unknown sheets. The app should prioritize PFD, P&ID, legend, notes, and layout sheets for advanced review.

The title block extractor should attempt to identify drawing number, sheet title, revision, project number, issue date, and sheet count. It should tolerate imperfect data and mark fields as unknown when extraction is not confident.

The entity extractor should identify likely equipment tags, valve tags, instrument tags, line numbers, drawing references, note references, revision callouts, and repeated or conflicting text. It should normalize common tag formats and store both raw and normalized forms.

## Advanced Reasoning Engine

The reasoning engine is the heart of the app. It should combine deterministic rules, structured engineering heuristics, and AI-assisted review hooks. It should not rely on one giant prompt or unstructured AI comments. The engine should create structured findings from evidence.

The regulator station configuration reviewer should look for expected regulator station components and flag missing or unclear items. It should review whether the drawings appear to show inlet isolation, outlet isolation, regulator run, bypass, filtering, overpressure protection, vents, drains, pressure instruments, and sensing lines. It should generate findings when important components are missing, unclear, or inconsistently shown.

The PFD/P&ID consistency reviewer should compare major equipment, valve tags, line numbers, flow direction references, and station components across PFD and P&ID sheets. It should flag tags or line numbers that appear on one drawing type but not the other, conflicting naming, inconsistent services, or unclear coordination between process and detailed drawings.

The operability reviewer should reason about whether the station can be isolated, bypassed, vented, drained, and maintained based on the visible arrangement. It should generate findings when drawings do not clearly show how the station is operated or maintained.

The overpressure protection reviewer should look for relief valves, monitor regulators, slam-shut devices, pressure control notes, setpoint references, or other overpressure protection indications. If no clear overpressure protection philosophy is visible, it should generate a finding asking the reviewer to confirm the OPP method.

The instrumentation reviewer should look for pressure gauges, transmitters, sensing lines, pilots, control references, and instrument tags. It should flag unclear or missing pressure sensing and control information.

The drafting quality reviewer should identify likely readability and coordination issues such as overlapping text, unclear leaders, duplicated tags, missing titles, missing revisions, unclear callouts, unmatched references, and title block issues.

The revision reviewer should identify possible revision problems, including missing revision data, duplicate drawing numbers, inconsistent title block information, revision references without corresponding revision information, and sheet index mismatches when detectable.

Every reasoning module should produce structured candidate findings. A finding normalizer should standardize titles, categories, severities, confidence, evidence, suggested correction, and visible comment text. A deduplication layer should merge overlapping findings and prevent repeated comments for the same issue.

## Finding Categories and Severity

The app should support categories including tag consistency, line number consistency, drawing coordination, missing information, regulator station design, safety and operability, overpressure protection, instrumentation, drafting quality, title block and revision, BOM or count issue, notes and specifications, and human review needed.

The app should use four severity levels: Critical, Major, Minor, and Note. Critical findings should be reserved for possible safety, compliance, or major operability issues. Major findings should include likely design coordination issues, missing important components, or high-value QC comments. Minor findings should include drafting clarity and non-critical coordination issues. Notes should be informational or low-risk observations.

Visible PDF comments should be concise and professional. They should not include long AI explanations. Internal finding records can include detailed reasoning and evidence.

Examples of comment style include: “Confirm overpressure protection philosophy. Relief, monitor, slam-shut, or other OPP method is not clearly shown.” Another example is: “Verify valve tag. Tag appears inconsistent between PFD and P&ID.” Another example is: “Clarify bypass arrangement. Regulator station bypass is not clearly shown on the current drawings.”

## PDF Markup Export

The app must export a fully marked-up PDF. The exported PDF should preserve the original drawing set and add standard PDF annotations for accepted findings. Each finding should place a sticky note, text annotation, highlight, rectangle, cloud-like box, or arrow/callout when coordinates are available. If exact coordinates are not available, the app should place a sheet-level comment in a consistent review area.

PDF annotations should include the visible QC comment text and optionally the finding ID. The app should include severity-based visual styling where practical. The output should open in common PDF viewers and Bluebeam. Do not require Bluebeam-specific APIs for the first version. Use standard PDF annotations.

The app should also export a QC log. The QC log should include finding ID, sheet number, page number, drawing title, category, severity, comment, evidence, suggested correction, confidence, status, source, and creation date. Export CSV at minimum and Excel if practical.

The app should export internal JSON findings for future backchecking, learning, and debugging.

## Frontend Requirements

The frontend should make the app usable end to end. It should include a project dashboard where users can create projects, upload PDFs, see processing status, and open reviews.

The review screen should show a sheet list or project tree on the left, the PDF page viewer in the center, and the issue list and issue inspector on the right. The user should be able to click a finding, jump to the related sheet, view its evidence, edit the comment, change severity or category, accept it, reject it, delete it, or mark it as needs review.

The export screen should allow the user to export a marked-up PDF, QC log, JSON finding file, and review summary. The app should clearly show what files were generated and where they are stored.

The UI does not need to be beautiful, but it should be professional and complete enough to use. It should not be a bare developer-only interface.

## AI Use

The app should include an AI review service abstraction. It should support a model provider configuration through environment variables or settings. The app should be able to run deterministic rules without AI so the app remains testable and usable when no API key is configured. When an AI key is configured, AI-assisted modules should add richer reasoning and review comments.

AI prompts should be specialized by task. Use separate prompts for sheet classification, title block extraction, entity extraction, regulator station reasoning, PFD/P&ID comparison, drafting quality review, finding normalization, and comment writing. Do not send the entire project to one prompt unless necessary.

AI outputs must be converted into structured findings. The app should reject or quarantine AI output that does not include evidence or cannot be normalized.

## Tests and Evaluation

The app should include tests. Tests should cover PDF ingestion, sheet classification, entity extraction, rule checks, finding normalization, deduplication, export generation, and PDF annotation creation.

The repository should include sample structured scenarios for reasoning tests. Scenarios should include a good regulator station, missing bypass, missing inlet isolation, missing outlet isolation, unclear overpressure protection, mismatched PFD/P&ID tags, missing vent or drain details, unclear pressure sensing line, duplicate tag, and revision/title block issue. Each scenario should include expected findings. The test runner should compare actual findings against expected findings.

The app should include sample data or generated placeholder PDFs so the workflow can be demonstrated without private project files. If a realistic sample drawing cannot be included, create synthetic sample data and a synthetic PDF that exercises the pipeline.

The README should explain how to run the app, how to run tests, how to run a sample review, how to configure AI, how to export markups, and how to add new rules.

## Repository Deliverables

The final repository should include the working backend, working frontend, local database setup, PDF processing services, reasoning engine, rule library, AI service abstraction, sample data, tests, documentation, and scripts.

The repository should include a README with complete setup and run instructions. It should include architecture documentation explaining the pipeline and reasoning engine. It should include documentation for adding rules and adding sample scenarios.

The app should include one-command or clearly documented startup scripts. The user should not have to reverse-engineer how to run the project.

## Acceptance Definition

The app is complete when a user can run it locally, upload a sample or real regulator station drawing set PDF, process the drawing package, see extracted sheets and findings, review/edit findings in the UI, export a marked-up PDF that opens in Bluebeam or a standard PDF viewer, export a QC log, export JSON findings, and run tests successfully.

The advanced reasoning engine must be present in the first version. It should not be left as a placeholder. It should include real structured checks for regulator station configuration, PFD/P&ID consistency, operability, overpressure protection, instrumentation, drafting quality, and revision/title block issues.

The final app should be designed as a serious foundation for an AI engineering associate that can automate a large portion of natural gas drawing QC work.
