from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROMPT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "default-deep-review",
        "name": "Default AutoQC Deep Review prompt",
        "version": "autoqc-chat-prompt-v1",
        "description": "Broad drawing update review for the standard AutoQC manual ChatGPT/Copilot bridge.",
        "review_priorities": [
            "Discrepancies between sheets, tags, notes, references, and drawing callouts.",
            "Misspellings, grammar issues, unclear notes, duplicate notes, and conflicting requirements.",
            "Natural gas regulator station review items only when visible evidence exists in the attached PDF.",
        ],
    },
    {
        "id": "natural-gas-regulator-station",
        "name": "Natural gas regulator station prompt",
        "version": "autoqc-chat-prompt-v2-regulator-station",
        "description": "Focused station review for PFD/P&ID/plan/detail coordination.",
        "review_priorities": [
            "Worker/monitor regulator or control valve coordination across PFD, P&ID, layout, and details.",
            "OPP, relief, slam-shut, MAOP, setpoint, bypass, isolation, vent, drain, and sensing-line notes.",
            "Instrumentation, SCADA tag, pressure class, flow direction, and construction note coordination.",
        ],
    },
    {
        "id": "drawing-coordination",
        "name": "Drawing coordination prompt",
        "version": "autoqc-chat-prompt-v2-coordination",
        "description": "Cross-sheet drawing reference, tag, note, and callout coordination.",
        "review_priorities": [
            "Mismatched drawing references, sheet references, tags, line numbers, and note callouts.",
            "Conflicting required updates between plans, details, PFDs, P&IDs, legends, and general notes.",
            "Duplicate or ambiguous construction requirements that would confuse a drafter or field reviewer.",
        ],
    },
    {
        "id": "title-block-revision",
        "name": "Title block/revision prompt",
        "version": "autoqc-chat-prompt-v2-title-block",
        "description": "Focused title block, revision, drawing number, and issue-history review.",
        "review_priorities": [
            "Visible title block/revision conflicts in the attached PDF.",
            "Drawing number, title, revision, issue date, and sheet index inconsistencies visible in the PDF.",
            "Do not report UNKNOWN parser metadata as a drawing issue; use only visible PDF evidence.",
        ],
    },
    {
        "id": "minimal-smoke-test",
        "name": "Minimal smoke-test prompt",
        "version": "autoqc-chat-prompt-v2-smoke",
        "description": "Short prompt for validating the manual bridge and JSON parser with a tiny response.",
        "review_priorities": [
            "Return one or two obvious drawing updates only if clearly visible in the attached PDF.",
            "Prefer concise output that exercises page_number, target_text, required_update, and rationale.",
        ],
    },
    {
        "id": "xcel-package",
        "name": "Xcel Package",
        "version": "autoqc-chat-prompt-v3-xcel-package",
        "description": "Focused Xcel engineering package review based on the Xcel Engineering Package QC Checklist R0 2026-06-15.",
        "review_priorities": [
            "Apply the Xcel Engineering Package QC Checklist R0 2026-06-15 where applicable and only when visible evidence exists in the attached PDF.",
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
        "name": "Comprehensive",
        "version": "autoqc-chat-prompt-v3-comprehensive",
        "description": "Exhaustive drawing-package review combining AutoQC coordination, regulator-station, title block/revision, drafting-quality, and applicable Xcel checklist coverage.",
        "review_priorities": [
            "Perform a comprehensive review intended to catch every visible, actionable drawing mistake across the attached package while still avoiding unsupported assumptions.",
            "Combine the Default AutoQC, Natural Gas Regulator Station, Drawing Coordination, Title Block/Revision, and applicable Xcel Engineering Package QC Checklist priorities.",
            "Cross-check sheet-to-sheet coordination: drawing references, sheet references, tags, line numbers, note callouts, section/detail callouts, BOM callouts, legends, plans, details, PFDs, P&IDs, and general notes.",
            "Check drafting quality: misspellings, grammar, unclear notes, duplicate notes, conflicting requirements, ambiguous construction requirements, stale template notes, and copy-paste artifacts.",
            "Check visible title block and revision information: drawing numbers, titles, revisions, issue dates, sheet index consistency, revision block initials, revision clouds, and triangle labels; do not report parser UNKNOWN metadata.",
            "Check natural gas regulator station design coordination: worker/monitor regulators, control valves, OPP, relief, slam-shut, MAOP, setpoints, bypass/isolation, vents, drains, sensing/pilot lines, filters/strainers, instrumentation, SCADA tags, pressure class, flow direction, connection types, and construction notes.",
            "Apply applicable Xcel package checklist items for All Sheets, Cover Sheet, Index, General Notes, Regulator Characteristics, PFD, P&ID, Civil/Structural, Civil Site, Demo, Mechanical Plan, Piping Sections/Details, Isometric, Heat Number/MTR, Weld/NDE, Bolt Torque, BOM, and Environmental sheets.",
            "Check civil/site/environmental/permitting coordination: site layout, ingress/egress, parking/turnaround, emergency egress gates, north arrows, hatches, fences/gates, elevations, limits of disturbance, erosion and sediment controls, vehicle tracking pads, jurisdiction-specific callouts, property lines, utilities, and property features.",
            "Check mechanical/demo/detail deliverables: line type conventions, AG/BG and new/existing breaks, scale/dimensions/snap points, flow arrows, station setbacks, fire valve location, vehicle protection, blowdowns/taps, cathodic protection, operator access, clearance/elevation, section references, pipe support/foundation conflicts, and required field notes.",
            "Check fabrication/traceability deliverables where present: heat number/MTR, weld/NDE, bolt torque, bubbles, tables, flange rows, BOM descriptions/specs, item numbers, quantities, and catalog IDs.",
            "Use the attached PDF as the source of truth; only create updates with specific visible evidence and exact target_text. Use human review needed only when a visible issue appears uncertain.",
        ],
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
        if not self.path.exists():
            self.path.write_text(json.dumps(DEFAULT_PROMPT_TEMPLATES, indent=2, ensure_ascii=True), encoding="utf-8")
            return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]
        if not isinstance(data, list):
            return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]
        by_id = {str(item.get("id")): dict(item) for item in DEFAULT_PROMPT_TEMPLATES}
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                merged = {**by_id.get(str(item["id"]), {}), **item}
                by_id[str(item["id"])] = merged
        return list(by_id.values())
