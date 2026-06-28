from __future__ import annotations

from pathlib import Path


def test_frontend_main_workflow_smoke_contract() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
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
        "Selected finding review card",
        "This finding is page-level only",
        "Edit in Inspector",
        "Recalculate Location",
        "Export placement",
        "Exact target found",
        "Fuzzy target found",
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
        "Management review dashboard",
        "Advanced Features",
        "Experimental / Power User Tools",
        "Markup Memory",
        "Include Markup Memory in generated prompts",
        "Rebuild Memory From Existing Findings",
        "Clear Markup Memory",
        "Memory examples that would be included in the next prompt",
    ]
    for text in workflow_text:
        assert text in app_source

    resilient_ui_hooks = [
        "global-status-banner",
        "inline-warning",
        "inline-helper",
        "source-pdf-button",
        "hasActiveFindingFilters",
        "exportDisabled",
        "saveDisabled",
        "viewer-mode-toggle",
        "viewer-finding-card",
        "viewer-page-level-note",
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
        "advanced-features-panel",
        "memory-preview-text",
        "memory-stats-grid",
    ]
    for hook in resilient_ui_hooks:
        assert hook in app_source or hook in styles_source

    responsive_accessibility_styles = [
        ":focus-visible",
        "@media (max-width: 760px)",
        "overflow-wrap: anywhere",
        "height: auto",
    ]
    for css_snippet in responsive_accessibility_styles:
        assert css_snippet in styles_source
