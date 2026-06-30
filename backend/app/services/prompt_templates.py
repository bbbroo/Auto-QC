from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXHAUSTIVE_PROMPT_VERSION = "autoqc-chat-prompt-v4-exhaustive-manual"
EXHAUSTIVE_REVIEW_DEPTH = "Exhaustive Manual-Style Review"

BASE_EXHAUSTIVE_PRIORITIES = [
    "Default AutoQC drawing coordination checks: discrepancies between sheets, tags, notes, references, drawing callouts, section/detail references, legends, plans, details, PFDs, P&IDs, BOM callouts, and general notes.",
    "Drafting quality checks: misspellings, grammar issues, unclear notes, duplicate notes, conflicting requirements, ambiguous construction requirements, stale template notes, and copy-paste artifacts.",
    "Natural gas regulator station checks: worker/monitor regulators, control valves, OPP, relief, slam-shut, MAOP, setpoints, bypass/isolation, vents, drains, sensing/pilot lines, filters/strainers, instrumentation, SCADA tags, pressure class, flow direction, connection types, and construction notes.",
    "Title block/revision checks: drawing numbers, sheet titles, revisions, issue dates, sheet index consistency, revision block initials, revision clouds, and triangle labels, but only when visibly supported by the attached PDF.",
    "Xcel engineering package review requirements where applicable and visibly supported: All Sheets, Cover Sheet, Index, General Notes, Regulator Characteristics, PFD, P&ID, Civil/Structural, Civil Site, Demo, Mechanical Plan, Piping Sections/Details, Isometric, Heat Number/MTR, Weld/NDE, Bolt Torque, BOM, and Environmental sheets.",
    "Civil/site/environmental/permitting coordination: site layout, ingress/egress, parking/turnaround, emergency egress gates, north arrows, hatches, fences/gates, elevations, limits of disturbance, erosion and sediment controls, vehicle tracking pads, jurisdiction-specific callouts, property lines, utilities, and property features.",
    "Mechanical/demo/detail deliverables: line type conventions, AG/BG and new/existing breaks, scale/dimensions/snap points, flow arrows, station setbacks, fire valve location, vehicle protection, blowdowns/taps, cathodic protection, operator access, clearance/elevation, section references, pipe support/foundation conflicts, and required field notes.",
    "Fabrication/traceability deliverables where present: heat number/MTR, weld/NDE, bolt torque, bubbles, tables, flange rows, BOM descriptions/specs, item numbers, quantities, and catalog IDs.",
    "Use the attached PDF as the source of truth; only create updates with specific visible evidence and exact target_text. Use human review needed only when a visible issue appears uncertain.",
]

DEFAULT_PROMPT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "default-deep-review",
        "name": "Exhaustive Manual Review (Default)",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Default production prompt for full manual-style sheet-by-sheet PDF review with no triage, sampling, skimming, or partial findings.",
        "category": "General",
        "intended_use": "General natural gas drawing package review when the attached PDF must be reviewed exhaustively across every visible sheet.",
        "review_depth": EXHAUSTIVE_REVIEW_DEPTH,
        "when_to_use": "Use for ordinary production drawing QC prompts where review completeness is required regardless of package length.",
        "when_not_to_use": "Do not use for quick parser smoke tests or intentionally narrow non-production checks.",
        "review_priorities": BASE_EXHAUSTIVE_PRIORITIES,
    },
    {
        "id": "natural-gas-regulator-station",
        "name": "Regulator Station Exhaustive Manual Review",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Full manual-style package review with extra emphasis on regulator station PFD/P&ID/plan/detail coordination.",
        "category": "Regulator station",
        "intended_use": "Exhaustive regulator station drawing coordination across process, mechanical, controls, title blocks, notes, plans, and details.",
        "review_depth": EXHAUSTIVE_REVIEW_DEPTH,
        "when_to_use": "Use when the package is primarily a regulator station or station modification and still needs every visible sheet reviewed.",
        "when_not_to_use": "Do not use as a shortcut for checking only PFDs, P&IDs, or high-risk station sheets.",
        "review_priorities": [
            *BASE_EXHAUSTIVE_PRIORITIES,
            "Regulator station emphasis: worker/monitor regulator or control valve coordination across PFD, P&ID, layout, schedules, and details.",
            "Regulator station emphasis: OPP, relief, slam-shut, MAOP, setpoint, bypass, isolation, vent, drain, and sensing-line notes.",
            "Regulator station emphasis: instrumentation, SCADA tags, pressure class, flow direction, connection types, filters/strainers, construction notes, and operator access coordination.",
        ],
    },
    {
        "id": "drawing-coordination",
        "name": "Drawing Coordination Exhaustive Manual Review",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Full manual-style package review with extra emphasis on cross-sheet references, tags, notes, and callout coordination.",
        "category": "Coordination",
        "intended_use": "Exhaustive sheet-to-sheet coordination of references, tags, callouts, notes, and deliverable consistency.",
        "review_depth": EXHAUSTIVE_REVIEW_DEPTH,
        "when_to_use": "Use when the main risk is inconsistency between drawings and every visible sheet still needs the baseline manual review method.",
        "when_not_to_use": "Do not use to check only likely coordination sheets or to skip low-risk sheets.",
        "review_priorities": [
            *BASE_EXHAUSTIVE_PRIORITIES,
            "Coordination emphasis: mismatched drawing references, sheet references, tags, line numbers, and note callouts.",
            "Coordination emphasis: conflicting requirements between plans, details, PFDs, P&IDs, legends, schedules, BOMs, title blocks, and general notes.",
            "Coordination emphasis: duplicate or ambiguous construction requirements that would confuse a drafter or field reviewer.",
        ],
    },
    {
        "id": "title-block-revision",
        "name": "Focused Title Block/Revision Review (Non-Production Shortcut)",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Narrow title block and revision prompt for intentional focused checks; production deep/comprehensive review should use the exhaustive manual default.",
        "category": "Focused/non-production",
        "intended_use": "Visible title block, drawing number, revision, issue date, and sheet index checks when a narrow review is intentionally selected.",
        "review_depth": "Focused Review (Non-Exhaustive)",
        "when_to_use": "Use only when you intentionally want a narrow title block/revision check, not a full production package review.",
        "when_not_to_use": "Do not use for broader process, civil, mechanical, regulator station, or full package review.",
        "review_priorities": [
            "Focused title block/revision emphasis: visible title block/revision conflicts in the attached PDF.",
            "Focused title block/revision emphasis: drawing number, title, revision, issue date, and sheet index inconsistencies visible in the PDF.",
            "Do not report UNKNOWN parser metadata as a drawing issue; use only visible PDF evidence.",
        ],
    },
    {
        "id": "minimal-smoke-test",
        "name": "Minimal Smoke-Test Prompt (Non-Production)",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Non-production prompt for validating the manual bridge and JSON parser with a tiny known package.",
        "category": "Testing/debug",
        "intended_use": "Quickly validate prompt generation, PDF attachment, JSON return, preview, and import in controlled tests only.",
        "review_depth": "Fast Smoke/Test Review (Non-Production)",
        "when_to_use": "Use during app smoke tests or onboarding checks with a tiny known package.",
        "when_not_to_use": "Do not use for production drawing review coverage or large drawing packages.",
        "review_priorities": [
            "Smoke-test emphasis: exercise page_number, target_text, required_update, rationale, and JSON import behavior using only clearly visible PDF evidence.",
            "Smoke-test emphasis: keep the app workflow validation simple; do not treat this as a production review template.",
        ],
    },
    {
        "id": "xcel-package",
        "name": "Xcel Package Exhaustive Manual Review",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Full manual-style package review with Xcel Engineering Package QC R0 2026-06-15 requirements where applicable and visibly supported.",
        "category": "Client-specific",
        "intended_use": "Xcel-style engineering package QC using applicable client/package requirements as review guidance while still reviewing every visible sheet.",
        "review_depth": EXHAUSTIVE_REVIEW_DEPTH,
        "when_to_use": "Use for Xcel packages or packages intentionally following the Xcel package-review structure when exhaustive manual review is required.",
        "when_not_to_use": "Do not use when client-specific Xcel requirements are not applicable or visible evidence is too limited.",
        "review_priorities": [
            *BASE_EXHAUSTIVE_PRIORITIES,
            "Apply the Xcel Engineering Package QC R0 2026-06-15 requirements where applicable and only when visible evidence exists in the attached PDF.",
            "All Sheets: verify revision block initials, title block S/T/R, city/county/division, revision, and post-IFC revision clouds/triangle labels.",
            "Cover Sheet and Index: verify project name, city/state, project maps, GPS/elevation, contacts, work orders, functional locations, drawing numbers, sheet titles, process areas, and index consistency.",
            "General Notes and Regulator Characteristics: verify current general notes template, regulator size versus P&ID/mechanical drawings, pressure class versus design pressure, outlet set point, spring and pilot ranges, end connections, OPP basis, and pilot heater status.",
            "PFD/P&ID: verify to/from tags, station blocks, equipment boundaries, flow arrows, major/minor valves and fittings, reducers/tees, transition fittings, monolithic insulators, hot tapping equipment, process line types, connection types, instrumentation/sensing/power lines, temporary lines, new/existing breaks, AG/BG breaks, and demo hatches.",
            "Civil/Structural/Site/Environmental: verify field verification/current revision/local municipality notes, site layout, ingress/egress, parking/turnaround, emergency egress gates, north arrows, hatches, fences/gates, elevations, limits of disturbance, inlet protection, silt fence, vehicle tracking pads, permitting callouts, property lines, utilities, and property features.",
            "Demo/Mechanical Plans and Piping Details: verify existing/proposed and AG/BG line types, scale/dimensions/snap points, flow arrows, BOM callouts, required field notes, station setbacks, fire valves, vehicle protection, blowdowns/taps, cathodic protection, operator access, ground/top piping clearance, sensing/gauge/utility taps, regulator tap spacing, strainer drainage clearance, section references, buried/above-grade pipe clearances, foundation/support conflicts, and soil-air interface notes.",
            "Isometric, heat number/MTR, weld/NDE, bolt torque, and BOM sheets: verify model consistency, property lines/features, dimensions, section references, bubbles/tables, flange rows, item descriptions/specs, item numbers, quantities, and Xcel catalog IDs.",
        ],
    },
    {
        "id": "comprehensive",
        "name": "Comprehensive Exhaustive Manual Review",
        "version": EXHAUSTIVE_PROMPT_VERSION,
        "description": "Exhaustive manual-style review combining AutoQC coordination, regulator-station, title block/revision, drafting-quality, civil/site/environmental/permitting, mechanical/demo/detail, fabrication/traceability, and applicable Xcel package-review requirements.",
        "category": "General",
        "intended_use": "Largest production prompt for broad package review where every visible sheet must receive the same baseline manual review method regardless of package length.",
        "review_depth": EXHAUSTIVE_REVIEW_DEPTH,
        "when_to_use": "Use when review completeness matters and partial findings are not acceptable.",
        "when_not_to_use": "Do not use for quick parser smoke tests or intentionally narrow non-production checks.",
        "review_priorities": BASE_EXHAUSTIVE_PRIORITIES,
    },
]


class PromptTemplateManager:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "prompt_templates.json"

    def list_templates(self) -> list[dict[str, Any]]:
        templates = self._load_templates()
        return sorted(templates, key=lambda item: str(item.get("name") or item.get("id") or ""))

    def get_template(self, template_id: str | None) -> dict[str, Any]:
        templates = self._load_templates()
        if template_id:
            for template in templates:
                if template.get("id") == template_id:
                    return template
        return templates[0]

    def _load_templates(self) -> list[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        canonical_by_id = {str(item.get("id")): dict(item) for item in DEFAULT_PROMPT_TEMPLATES}
        if not self.path.exists():
            templates = list(canonical_by_id.values())
            self.path.write_text(json.dumps(templates, indent=2, ensure_ascii=True), encoding="utf-8")
            return [dict(item) for item in templates]
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]
        if not isinstance(data, list):
            return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]

        templates_by_id = dict(canonical_by_id)
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            item_id = str(item["id"])
            if item_id not in canonical_by_id:
                templates_by_id[item_id] = dict(item)

        templates = list(templates_by_id.values())
        if data != templates:
            self.path.write_text(json.dumps(templates, indent=2, ensure_ascii=True), encoding="utf-8")
        return [dict(item) for item in templates]
