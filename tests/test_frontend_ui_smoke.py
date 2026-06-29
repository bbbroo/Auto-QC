from __future__ import annotations

from pathlib import Path


def test_frontend_main_workflow_smoke_contract() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/api.ts").read_text(encoding="utf-8")
    styles_source = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    workflow_text = [
        "Upload / sample package",
        "Chat Prompt",
        "Paste AI update JSON",
        "Preview AI Updates",
        "Import Valid Updates",
        "AI QC Log",
        "Inspector",
        "Review Package",
        "Open Source PDF",
        "No AI findings imported yet",
        "Finding Focus",
        "Full Sheet",
        "Marked PDF",
        "Manual markup placement",
        "Place on drawing",
        "Finding Quality and Placement dashboard",
        "Import Quality Report",
        "Checklist",
        "Coverage Tracker",
        "Select checklist for project",
        "Checklist items track review coverage and link evidence/findings",
        "Export placement",
        "Exact target found",
        "Fuzzy target found",
        "Manual placement saved",
        "Manual placement needed",
        "Auto-advance",
        "left to review",
        "All placement",
        "Located",
        "Reviewer keyboard shortcuts",
        "Export Project Package",
        "Import Project Package",
        "Prompt template",
        "System Check",
        "Audit Log",
        "How to use AutoQC",
        "Duplicate / merge",
        "Mark as duplicate",
        "Hide duplicate from export",
        "Validation",
        "Prompt template comparison preview",
        "Review depth",
        "Exhaustive Deep Review",
        "Large package review: hybrid mode reviews every page in adaptive batches, then queues text-heavy sheets for single-sheet deep dives.",
        "Large Package Review",
        "Hybrid adaptive review",
        "Whole package prompt",
        "Batch Coverage",
        "Sheet Deep Dives",
        "Generate Next Batch Prompt",
        "Deep Dive This Sheet",
        "Mark Reviewed / No Updates",
        "Pages confirmed reviewed",
        "Scoped review complete",
        "AI response coverage",
        "This is response coverage only; it does not prove those pages are clean.",
        "Management review dashboard",
        "What should I do next?",
        "Recovery Center",
        "No active recovery items. Keep reviewing normally.",
        "Why blocked?",
        "Advanced Features",
        "Experimental / Power User Tools",
        "Markup Memory",
        "Include Markup Memory in generated prompts",
        "Rebuild Memory From Existing Findings",
        "Clear Markup Memory",
        "Memory examples that would be included in the next prompt",
        "Memory is local",
        "Include current project examples",
        "Open experimental power-user settings",
    ]
    for text in workflow_text:
        assert text in app_source
    assert 'aria-label="Advanced Features"' in app_source
    assert 'role="tab"\n            aria-selected={leftRailCard === "advanced"' not in app_source
    assert 'coordinate_space: "image_pixel"' in api_source
    assert 'coordinate_space: "display_rotated"' not in api_source
    assert "clientPointToImagePixelPoint" in app_source
    assert "imageElement.getBoundingClientRect()" in app_source
    assert "imageElement.naturalWidth" in app_source
    assert "imageElement.naturalHeight" in app_source
    assert "imagePixelRectToOverlayPercent" in app_source
    assert 'data-coordinate-space="image_pixel"' in app_source

    resilient_ui_hooks = [
        "global-status-banner",
        "inline-warning",
        "inline-helper",
        "source-pdf-button",
        "hasActiveFindingFilters",
        "exportDisabled",
        "saveDisabled",
        "viewer-mode-toggle",
        "manual-placement-draft",
        "manual-placement-tools",
        "finding-overlay.selected",
        "viewer-placement-summary",
        "export-placement-summary",
        "placementSummaryText",
        "review-queue-card",
        "shortcut-hints",
        "placement-filter",
        "matchesPlacementFilter",
        "nextUnreviewedFinding",
        "dashboard-summary",
        "readiness-panel",
        "audit-log-panel",
        "export-validation",
        "modal-backdrop",
        "dedupe-tools",
        "checklist-panel",
        "checklist-progress",
        "advanced-features-panel",
        "memory-preview-text",
        "memory-stats-grid",
        "large-package-review",
        "review-scope-row",
        "workflow-guide",
        "workflow-stepper",
        "recovery-center",
        "operation-progress",
        "why-blocked-details",
        "success-helper",
        "warning-helper",
    ]
    for hook in resilient_ui_hooks:
        assert hook in app_source or hook in styles_source
    assert "viewer-finding-card" not in app_source

    responsive_accessibility_styles = [
        ":focus-visible",
        "@media (max-width: 760px)",
        "overflow-wrap: anywhere",
        "height: auto",
    ]
    for css_snippet in responsive_accessibility_styles:
        assert css_snippet in styles_source


def test_launcher_opens_detected_frontend_port() -> None:
    launcher = Path("Run AutoQC.bat").read_text(encoding="utf-8")

    assert "FRONTEND_BASE_PORT=5173" in launcher
    assert "FRONTEND_MAX_PORT=5199" in launcher
    assert 'set "FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%"' in launcher
    assert "npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT% --strictPort" in launcher
    assert 'start "" "%FRONTEND_URL%"' in launcher
