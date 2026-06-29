from __future__ import annotations

from typing import Any

from backend.app.database import Database


CHECKLIST_STATUSES = {
    "not_started",
    "checked",
    "issue_found",
    "not_applicable",
    "needs_human_review",
}


def _item(section: str, sheet_type: str, text: str, discipline: str = "engineering") -> dict[str, Any]:
    return {
        "section": section,
        "discipline": discipline,
        "sheet_type": sheet_type,
        "item_text": text,
        "applicability": "applicable",
        "source_template_reference": "Xcel Package / Comprehensive prompt checklist concept",
    }


DEFAULT_CHECKLIST_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "xcel-engineering-package-qc-r0",
        "name": "Xcel Engineering Package QC Checklist",
        "version": "R0 2026-06-15",
        "description": "Coverage tracker for Xcel-style natural gas engineering drawing packages. It tracks review coverage and links evidence/findings; it does not create findings.",
        "source_template_reference": "Xcel Package and Comprehensive prompt templates",
        "items": [
            _item("All Sheets", "general", "Verify revision block initials, revision labels, S/T/R, city, county, and division where visible."),
            _item("All Sheets", "general", "Check post-IFC revision clouds and triangle labels where the package visibly includes revisions."),
            _item("Cover Sheet", "cover", "Verify project name, city/state, maps, GPS/elevation, contacts, work orders, and functional locations."),
            _item("Index", "index", "Check drawing numbers, sheet titles, process areas, and index consistency against visible sheets."),
            _item("General Notes", "notes", "Verify current general notes, construction notes, and conflicting/duplicate note wording."),
            _item("Regulator Characteristics", "regulator", "Check regulator size, pressure class, outlet set point, spring/pilot ranges, end connections, OPP basis, and pilot heater status where shown."),
            _item("PFD", "pfd", "Check to/from tags, station blocks, equipment boundaries, flow arrows, reducers, tees, transition fittings, monolithic insulators, hot taps, and line types."),
            _item("P&ID", "p&id", "Check major/minor valves and fittings, instrumentation, sensing/power lines, temporary lines, AG/BG breaks, and demo hatches."),
            _item("Civil/Structural", "civil", "Check field verification notes, revision notes, municipality notes, elevations, structures, and support/foundation conflicts."),
            _item("Civil Site", "site", "Check layout, ingress/egress, parking/turnaround, emergency egress, north arrows, hatches, fences, gates, LOD, property lines, utilities, and site features."),
            _item("Environmental", "environmental", "Check inlet protection, silt fence, vehicle tracking pads, permitting callouts, and erosion/sediment control notes."),
            _item("Demo", "demo", "Check existing/proposed and AG/BG line types, demo hatches, flow arrows, field notes, and tie-in callouts."),
            _item("Mechanical Plan", "mechanical", "Check scale/dimensions, BOM callouts, station setbacks, fire valves, vehicle protection, blowdowns, taps, CP, operator access, and piping clearance."),
            _item("Piping Sections/Details", "piping_detail", "Check sensing/gauge/utility taps, regulator tap spacing, strainer drainage clearance, section references, soil-air interface notes, and buried/above-grade clearances."),
            _item("Isometric", "isometric", "Check model consistency, property features, dimensions, section references, bubbles, and tables."),
            _item("Heat Number/MTR", "mtr", "Check heat number, material traceability, MTR references, bubbles, and table consistency where present."),
            _item("Weld/NDE", "weld_nde", "Check weld/NDE identifiers, tables, acceptance notes, and drawing callouts where present."),
            _item("Bolt Torque", "bolt_torque", "Check flange rows, torque table descriptions, quantities, and references where present."),
            _item("BOM", "bom", "Check item descriptions/specs, item numbers, quantities, Xcel catalog IDs, and BOM callout consistency."),
        ],
    }
]


class ChecklistService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_templates(self) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in template.items() if key != "items"}
            | {"item_count": len(template.get("items") or [])}
            for template in DEFAULT_CHECKLIST_TEMPLATES
        ]

    def get_template(self, checklist_id: str) -> dict[str, Any]:
        for template in DEFAULT_CHECKLIST_TEMPLATES:
            if template["id"] == checklist_id:
                return template
        raise KeyError(checklist_id)

    def select_checklist(self, project_id: str, checklist_id: str) -> dict[str, Any]:
        template = self.get_template(checklist_id)
        return self.db.select_project_checklist(project_id, template)

    def get_project_checklist(self, project_id: str) -> dict[str, Any] | None:
        return self.db.get_project_checklist(project_id)

    def update_item(self, project_id: str, item_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        status = fields.get("status")
        if status is not None and status not in CHECKLIST_STATUSES:
            raise ValueError(f"Unsupported checklist status: {status}")
        mapped = fields.get("mapped_finding_ids")
        if mapped is not None and not isinstance(mapped, list):
            raise ValueError("mapped_finding_ids must be a list of existing finding IDs.")
        if mapped:
            existing_ids = {finding["id"] for finding in self.db.list_findings(project_id)}
            unknown = [finding_id for finding_id in mapped if finding_id not in existing_ids]
            if unknown:
                raise ValueError("Checklist items can only link existing project findings.")
        return self.db.update_project_checklist_item(project_id, item_id, fields)
