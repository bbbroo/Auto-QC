from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.app.models import (
    Evidence,
    FindingCategory,
    FindingStatus,
    Severity,
    SheetType,
    StationComponent,
    StationGraph,
    utc_now_iso,
)


@dataclass
class CandidateFinding:
    rule_id: str
    title: str
    category: str
    severity: str
    confidence: float
    sheet_id: str | None
    page_number: int | None
    evidence: list[dict[str, Any]]
    reasoning_summary: str
    suggested_correction: str
    comment_text: str
    location: dict[str, float] | None = None
    involved_entities: list[str] = field(default_factory=list)
    source: str = "rules"


class PackageContext:
    def __init__(self, project_id: str, sheets: list[dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        self.project_id = project_id
        self.sheets = sheets
        self.entities = entities
        self.sheet_by_id = {sheet["id"]: sheet for sheet in sheets}
        self.entities_by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in entities:
            self.entities_by_sheet[entity["sheet_id"]].append(entity)
        self.pfd_sheets = [sheet for sheet in sheets if sheet.get("sheet_type") == SheetType.PFD.value]
        self.pid_sheets = [sheet for sheet in sheets if sheet.get("sheet_type") == SheetType.PID.value]
        self.review_sheets = self.pid_sheets or self.pfd_sheets or [
            sheet for sheet in sheets if sheet.get("sheet_type") not in {SheetType.COVER.value, SheetType.INDEX.value}
        ]
        self.graph = self._build_station_graph()

    def sheet_label(self, sheet: dict[str, Any] | None) -> str:
        if not sheet:
            return "drawing package"
        number = sheet.get("drawing_number") or "UNKNOWN"
        title = sheet.get("sheet_title") or "Unknown Sheet"
        return f"{number} p. {sheet.get('page_number')}: {title}"

    def first_review_sheet(self) -> dict[str, Any] | None:
        if self.pid_sheets:
            return self.pid_sheets[0]
        if self.pfd_sheets:
            return self.pfd_sheets[0]
        return self.review_sheets[0] if self.review_sheets else (self.sheets[0] if self.sheets else None)

    def _build_station_graph(self) -> StationGraph:
        graph = StationGraph(project_id=self.project_id)
        graph.pfd_sheet_ids = [sheet["id"] for sheet in self.pfd_sheets]
        graph.pid_sheet_ids = [sheet["id"] for sheet in self.pid_sheets]
        graph.tags = sorted({entity["normalized_text"] for entity in self.entities if entity["entity_type"].endswith("_tag")})
        graph.line_numbers = sorted({entity["normalized_text"] for entity in self.entities if entity["entity_type"] == "line_number"})

        patterns: dict[str, list[str]] = {
            "inlet_isolation": [r"inlet\s+(?:isolation|block|valve)", r"\binlet\b.{0,60}\b(?:V|HV|MOV|XV|BV)-?\d+"],
            "outlet_isolation": [r"outlet\s+(?:isolation|block|valve)", r"\boutlet\b.{0,60}\b(?:V|HV|MOV|XV|BV)-?\d+"],
            "filter": [r"\bfilter\b", r"\bstrainer\b", r"\bFLT-?\d+"],
            "worker_regulator": [r"worker\s+regulator", r"\bREG-?\d+", r"\bPCV-?\d+"],
            "monitor_regulator": [r"monitor\s+regulator", r"\bMON-?\d+", r"\bmonitor\b"],
            "bypass": [r"\bbypass\b"],
            "relief": [r"\b(?:PSV|PRV|RV)-?\d+", r"\brelief\b", r"slam[- ]?shut"],
            "overpressure_note": [r"\bOPP\b", r"overpressure", r"MAOP", r"set\s*point", r"setpoint"],
            "vent": [r"\bvent\b", r"\bBDV-?\d+", r"\bblowdown\b"],
            "drain": [r"\bdrain\b"],
            "pressure_gauge": [r"pressure\s+gauge", r"\b(?:PI|PG)-?\d+"],
            "pressure_transmitter": [r"pressure\s+transmitter", r"\b(?:PT|PIT)-?\d+"],
            "sensing_line": [r"sensing\s+line", r"control\s+line", r"pilot\s+(?:line|supply)", r"\bpilot\b"],
        }

        for component_type, component_patterns in patterns.items():
            evidence: list[Evidence] = []
            for sheet in self.review_sheets:
                text = sheet.get("text_content") or ""
                for pattern in component_patterns:
                    match = re.search(pattern, text, flags=re.I | re.S)
                    if match:
                        evidence.append(
                            Evidence(
                                observation=f"Detected {component_type.replace('_', ' ')} indicator on {self.sheet_label(sheet)}.",
                                sheet_id=sheet["id"],
                                page_number=sheet.get("page_number"),
                                text_excerpt=_excerpt(text, match.start(), match.end()),
                                confidence=0.82,
                            )
                        )
                        break
            graph.components[component_type] = StationComponent(
                component_type=component_type,
                present=bool(evidence),
                sheet_ids=sorted({item.sheet_id for item in evidence if item.sheet_id}),
                evidence=evidence,
                confidence=min(0.95, 0.55 + 0.1 * len(evidence)) if evidence else 0.0,
            )
        return graph


class ReasoningEngine:
    """Deterministic evidence-backed reviewer for regulator station drawing sets."""

    def review_project(self, project_id: str, sheets: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        context = PackageContext(project_id, sheets, entities)
        candidates: list[CandidateFinding] = []
        candidates.extend(self._review_package_completeness(context))
        candidates.extend(self._review_regulator_configuration(context))
        candidates.extend(self._review_pfd_pid_consistency(context))
        candidates.extend(self._review_operability(context))
        candidates.extend(self._review_overpressure_protection(context))
        candidates.extend(self._review_instrumentation(context))
        candidates.extend(self._review_drafting_quality(context))
        candidates.extend(self._review_revision_titleblocks(context))
        candidates = [candidate for candidate in candidates if candidate.evidence]
        return self._normalize_and_dedupe(project_id, candidates)

    def _review_package_completeness(self, context: PackageContext) -> list[CandidateFinding]:
        findings: list[CandidateFinding] = []
        if not context.pfd_sheets:
            findings.append(
                self._missing(
                    context,
                    "PFD sheet not detected",
                    FindingCategory.MISSING_INFORMATION.value,
                    Severity.MAJOR.value,
                    "Confirm the drawing package includes a process flow diagram or equivalent process schematic.",
                    "PFD sheet was not detected from drawing titles, numbers, or extracted text.",
                    "Confirm PFD or equivalent process schematic is included in the package.",
                    "package_completeness.pfd",
                    confidence=0.76,
                )
            )
        if not context.pid_sheets:
            findings.append(
                self._missing(
                    context,
                    "P&ID sheet not detected",
                    FindingCategory.MISSING_INFORMATION.value,
                    Severity.MAJOR.value,
                    "Confirm the drawing package includes a P&ID for regulator station controls and instrumentation.",
                    "P&ID sheet was not detected from drawing titles, numbers, or extracted text.",
                    "Add or identify the P&ID used for detailed station review.",
                    "package_completeness.pid",
                    confidence=0.78,
                )
            )
        return findings

    def _review_regulator_configuration(self, context: PackageContext) -> list[CandidateFinding]:
        checks = [
            (
                "inlet_isolation",
                "Inlet isolation not clearly shown",
                FindingCategory.SAFETY_OPERABILITY.value,
                Severity.CRITICAL.value,
                "Confirm inlet isolation valve. Inlet isolation is not clearly shown.",
                "Regulator station drawings should clearly show how the station is isolated from upstream gas.",
                "Show or label inlet isolation on the PFD/P&ID/layout.",
                0.82,
            ),
            (
                "outlet_isolation",
                "Outlet isolation not clearly shown",
                FindingCategory.SAFETY_OPERABILITY.value,
                Severity.CRITICAL.value,
                "Confirm outlet isolation valve. Outlet isolation is not clearly shown.",
                "Regulator station drawings should clearly show how the station is isolated from downstream piping.",
                "Show or label outlet isolation on the PFD/P&ID/layout.",
                0.82,
            ),
            (
                "worker_regulator",
                "Worker regulator not clearly identified",
                FindingCategory.REGULATOR_STATION_DESIGN.value,
                Severity.MAJOR.value,
                "Identify worker regulator. Primary regulation device is not clearly shown.",
                "A regulator station drawing package should identify the active worker regulator or control valve.",
                "Label the worker regulator/control valve and coordinate the tag across PFD and P&ID.",
                0.8,
            ),
            (
                "filter",
                "Filter or strainer not clearly shown",
                FindingCategory.REGULATOR_STATION_DESIGN.value,
                Severity.MINOR.value,
                "Confirm filter/strainer requirement. Upstream filtration is not clearly shown.",
                "No filter or strainer indicator was found on prioritized regulator station sheets.",
                "Confirm whether filtration is required and show it when applicable.",
                0.63,
            ),
        ]
        findings = []
        for key, title, category, severity, comment, reasoning, correction, confidence in checks:
            if not self._present(context, key):
                findings.append(
                    self._missing(context, title, category, severity, comment, reasoning, correction, f"configuration.{key}", confidence)
                )
        return findings

    def _review_pfd_pid_consistency(self, context: PackageContext) -> list[CandidateFinding]:
        if not context.pfd_sheets or not context.pid_sheets:
            return []

        findings: list[CandidateFinding] = []
        pfd_ids = {sheet["id"] for sheet in context.pfd_sheets}
        pid_ids = {sheet["id"] for sheet in context.pid_sheets}
        entity_types = {
            "valve_tag": (FindingCategory.TAG_CONSISTENCY.value, Severity.MAJOR.value),
            "equipment_tag": (FindingCategory.TAG_CONSISTENCY.value, Severity.MAJOR.value),
            "instrument_tag": (FindingCategory.TAG_CONSISTENCY.value, Severity.MINOR.value),
            "line_number": (FindingCategory.LINE_NUMBER_CONSISTENCY.value, Severity.MAJOR.value),
        }

        for entity_type, (category, severity) in entity_types.items():
            pfd = self._entities_by_text(context, pfd_ids, entity_type)
            pid = self._entities_by_text(context, pid_ids, entity_type)
            if not pfd or not pid:
                continue
            only_pfd = sorted(set(pfd) - set(pid))[:8]
            only_pid = sorted(set(pid) - set(pfd))[:8]
            for value in only_pfd:
                entity = pfd[value][0]
                sheet = context.sheet_by_id.get(entity["sheet_id"])
                findings.append(
                    CandidateFinding(
                        rule_id=f"pfd_pid.{entity_type}.pfd_only",
                        title=f"{_display_entity_type(entity_type)} appears on PFD but not P&ID",
                        category=category,
                        severity=severity,
                        confidence=0.72,
                        sheet_id=entity["sheet_id"],
                        page_number=entity.get("page_number"),
                        location=entity.get("bbox"),
                        involved_entities=[entity["id"]],
                        evidence=[
                            _evidence(
                                f"{value} was extracted from {context.sheet_label(sheet)} but not from detected P&ID sheets.",
                                sheet,
                                entity.get("text"),
                                [entity["id"]],
                                0.78,
                            )
                        ],
                        reasoning_summary="Major tags and line numbers should be coordinated between process and detailed instrumentation drawings.",
                        suggested_correction=f"Verify whether {value} should be shown or renamed on the P&ID.",
                        comment_text=f"Verify {value}. It appears on the PFD but not on the P&ID.",
                    )
                )
            for value in only_pid:
                entity = pid[value][0]
                sheet = context.sheet_by_id.get(entity["sheet_id"])
                findings.append(
                    CandidateFinding(
                        rule_id=f"pfd_pid.{entity_type}.pid_only",
                        title=f"{_display_entity_type(entity_type)} appears on P&ID but not PFD",
                        category=category,
                        severity=severity,
                        confidence=0.68,
                        sheet_id=entity["sheet_id"],
                        page_number=entity.get("page_number"),
                        location=entity.get("bbox"),
                        involved_entities=[entity["id"]],
                        evidence=[
                            _evidence(
                                f"{value} was extracted from {context.sheet_label(sheet)} but not from detected PFD sheets.",
                                sheet,
                                entity.get("text"),
                                [entity["id"]],
                                0.74,
                            )
                        ],
                        reasoning_summary="Major tags and line numbers should be coordinated between process and detailed instrumentation drawings.",
                        suggested_correction=f"Verify whether {value} should be shown or renamed on the PFD.",
                        comment_text=f"Verify {value}. It appears on the P&ID but not on the PFD.",
                    )
                )
        return findings

    def _review_operability(self, context: PackageContext) -> list[CandidateFinding]:
        findings = []
        if not self._present(context, "bypass"):
            findings.append(
                self._missing(
                    context,
                    "Bypass arrangement not clearly shown",
                    FindingCategory.SAFETY_OPERABILITY.value,
                    Severity.MAJOR.value,
                    "Clarify bypass arrangement. Regulator station bypass is not clearly shown.",
                    "No bypass indicator was detected on PFD, P&ID, or layout sheets. This may affect maintenance or temporary operation planning.",
                    "Show the bypass or add a note stating that no bypass is provided by design.",
                    "operability.bypass",
                    0.78,
                )
            )
        if not self._present(context, "vent"):
            findings.append(
                self._missing(
                    context,
                    "Vent or drain detail not clearly shown",
                    FindingCategory.SAFETY_OPERABILITY.value,
                    Severity.MAJOR.value,
                    "Clarify vent/blowdown arrangement. Venting path is not clearly shown.",
                    "No vent or blowdown indicator was detected on prioritized regulator station drawings.",
                    "Show vent/blowdown valves, discharge destination, or a design note describing the arrangement.",
                    "operability.vent",
                    0.74,
                )
            )
        if not self._present(context, "drain"):
            findings.append(
                self._missing(
                    context,
                    "Drain detail not clearly shown",
                    FindingCategory.SAFETY_OPERABILITY.value,
                    Severity.MINOR.value,
                    "Confirm drain details. Drain arrangement is not clearly shown.",
                    "No drain indicator was detected. This may be acceptable for some dry gas installations, but should be confirmed.",
                    "Show low-point drains or add a note if drains are not required.",
                    "operability.drain",
                    0.64,
                )
            )
        return findings

    def _review_overpressure_protection(self, context: PackageContext) -> list[CandidateFinding]:
        has_monitor = self._present(context, "monitor_regulator")
        has_relief = self._present(context, "relief")
        has_opp_note = self._present(context, "overpressure_note")
        findings: list[CandidateFinding] = []

        if not has_monitor and not has_relief and not has_opp_note:
            findings.append(
                self._missing(
                    context,
                    "Overpressure protection philosophy not clearly shown",
                    FindingCategory.OVERPRESSURE_PROTECTION.value,
                    Severity.CRITICAL.value,
                    "Confirm overpressure protection philosophy. Relief, monitor, slam-shut, or other OPP method is not clearly shown.",
                    "No relief valve, monitor regulator, slam-shut, OPP note, MAOP note, or setpoint reference was detected.",
                    "Identify the overpressure protection method and coordinate setpoints or governing notes.",
                    "opp.missing",
                    0.84,
                )
            )
            return findings

        opp_text = "\n".join(sheet.get("text_content") or "" for sheet in context.review_sheets)
        setpoint_present = bool(re.search(r"\b\d{1,4}\s*(?:psig|psi|kpa|bar)\b", opp_text, flags=re.I))
        if (has_monitor or has_relief or has_opp_note) and not setpoint_present:
            first = self._first_component_sheet(context, "monitor_regulator") or self._first_component_sheet(context, "relief") or context.first_review_sheet()
            findings.append(
                CandidateFinding(
                    rule_id="opp.setpoint",
                    title="Overpressure protection setpoint basis not clearly shown",
                    category=FindingCategory.OVERPRESSURE_PROTECTION.value,
                    severity=Severity.MAJOR.value,
                    confidence=0.7,
                    sheet_id=first["id"] if first else None,
                    page_number=first.get("page_number") if first else None,
                    evidence=[
                        _evidence(
                            "An overpressure protection indicator was detected, but no pressure setpoint or basis was found in extracted text.",
                            first,
                            None,
                            [],
                            0.7,
                        )
                    ],
                    reasoning_summary="The drawings indicate an OPP method but do not clearly expose setpoint or basis text.",
                    suggested_correction="Add or reference OPP setpoint/basis information, or confirm it is controlled by a separate design document.",
                    comment_text="Confirm OPP setpoint/basis. OPP method is indicated, but setpoint information is not clearly shown.",
                )
            )
        return findings

    def _review_instrumentation(self, context: PackageContext) -> list[CandidateFinding]:
        findings: list[CandidateFinding] = []
        has_pressure = self._present(context, "pressure_gauge") or self._present(context, "pressure_transmitter")
        if not has_pressure:
            findings.append(
                self._missing(
                    context,
                    "Pressure indication not clearly shown",
                    FindingCategory.INSTRUMENTATION.value,
                    Severity.MAJOR.value,
                    "Show pressure indication. Pressure gauge/transmitter information is not clearly shown.",
                    "No pressure gauge or pressure transmitter indicator was found in prioritized station drawings.",
                    "Show upstream/downstream pressure indication and coordinate tags across drawings.",
                    "instrumentation.pressure_indication",
                    0.78,
                )
            )
        if not self._present(context, "sensing_line"):
            findings.append(
                self._missing(
                    context,
                    "Pressure sensing or pilot line not clearly shown",
                    FindingCategory.INSTRUMENTATION.value,
                    Severity.MAJOR.value,
                    "Clarify pressure sensing/control line. Sensing connection is not clearly shown.",
                    "No sensing line, control line, or pilot line indicator was detected near the regulation package.",
                    "Show regulator sensing/pilot connections and downstream takeoff location.",
                    "instrumentation.sensing_line",
                    0.76,
                )
            )
        return findings

    def _review_drafting_quality(self, context: PackageContext) -> list[CandidateFinding]:
        findings: list[CandidateFinding] = []

        for sheet in context.review_sheets:
            text = sheet.get("text_content") or ""
            unclear = re.search(r"\b(?:TBD|HOLD|VERIFY|ILLEGIBLE|OVERLAP|UNCLEAR)\b", text, flags=re.I)
            if unclear:
                findings.append(
                    CandidateFinding(
                        rule_id="drafting.unclear_text",
                        title="Unresolved drafting note or unclear text",
                        category=FindingCategory.DRAFTING_QUALITY.value,
                        severity=Severity.MINOR.value,
                        confidence=0.72,
                        sheet_id=sheet["id"],
                        page_number=sheet.get("page_number"),
                        evidence=[
                            _evidence(
                                "Extracted text contains a drafting uncertainty marker such as TBD, HOLD, VERIFY, ILLEGIBLE, OVERLAP, or UNCLEAR.",
                                sheet,
                                _excerpt(text, unclear.start(), unclear.end()),
                                [],
                                0.76,
                            )
                        ],
                        reasoning_summary="Unresolved drafting markers should be cleared before issue.",
                        suggested_correction="Resolve or remove the drafting marker and update the drawing note.",
                        comment_text="Resolve unclear/TBD drafting note before issue.",
                    )
                )

        by_sheet_tag: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for entity in context.entities:
            if entity["entity_type"] in {"valve_tag", "equipment_tag", "instrument_tag"}:
                by_sheet_tag[(entity["sheet_id"], entity["normalized_text"])].append(entity)
        for (sheet_id, tag), matches in by_sheet_tag.items():
            unique_locations = {
                (round((item.get("bbox") or {}).get("x0", -1)), round((item.get("bbox") or {}).get("y0", -1))) for item in matches
            }
            has_coordinate_spread = len(unique_locations) >= 2 and (-1, -1) not in unique_locations
            has_text_only_repetition = len(matches) >= 4 and unique_locations == {(-1, -1)}
            if len(matches) >= 3 and (has_coordinate_spread or has_text_only_repetition):
                sheet = context.sheet_by_id.get(sheet_id)
                findings.append(
                    CandidateFinding(
                        rule_id="drafting.duplicate_tag",
                        title="Repeated tag appears on sheet",
                        category=FindingCategory.DRAFTING_QUALITY.value,
                        severity=Severity.MINOR.value,
                        confidence=0.66,
                        sheet_id=sheet_id,
                        page_number=sheet.get("page_number") if sheet else None,
                        location=matches[0].get("bbox"),
                        involved_entities=[item["id"] for item in matches],
                        evidence=[
                            _evidence(
                                f"{tag} appears {len(matches)} times on {context.sheet_label(sheet)}.",
                                sheet,
                                tag,
                                [item["id"] for item in matches],
                                0.7,
                            )
                        ],
                        reasoning_summary="Repeated tags may be intentional, but clustered duplicates often indicate copied callouts or ambiguous labels.",
                        suggested_correction=f"Confirm whether repeated {tag} labels are intentional and unambiguous.",
                        comment_text=f"Verify duplicate tag {tag}. Repeated labels may be ambiguous.",
                    )
                )
        return findings

    def _review_revision_titleblocks(self, context: PackageContext) -> list[CandidateFinding]:
        findings: list[CandidateFinding] = []

        for sheet in context.sheets:
            if not sheet.get("drawing_number") or sheet.get("drawing_number") == "UNKNOWN":
                findings.append(
                    self._sheet_finding(
                        sheet,
                        "Drawing number not identified",
                        FindingCategory.TITLE_BLOCK_REVISION.value,
                        Severity.MAJOR.value,
                        "Complete title block. Drawing number was not identified.",
                        "Title block extraction did not find a drawing number.",
                        "Add or clarify the drawing number in the title block.",
                        "titleblock.drawing_number",
                        0.75,
                    )
                )
            if not sheet.get("revision") or sheet.get("revision") == "UNKNOWN":
                findings.append(
                    self._sheet_finding(
                        sheet,
                        "Revision missing or not identified",
                        FindingCategory.TITLE_BLOCK_REVISION.value,
                        Severity.MINOR.value,
                        "Complete title block. Revision was not identified.",
                        "Title block extraction did not find a revision.",
                        "Add or clarify the current revision in the title block.",
                        "titleblock.revision",
                        0.68,
                    )
                )

        numbers = [sheet.get("drawing_number") for sheet in context.sheets if sheet.get("drawing_number") and sheet.get("drawing_number") != "UNKNOWN"]
        duplicate_numbers = [number for number, count in Counter(numbers).items() if count > 1]
        for number in duplicate_numbers:
            duplicate_sheets = [sheet for sheet in context.sheets if sheet.get("drawing_number") == number]
            first = duplicate_sheets[0]
            findings.append(
                CandidateFinding(
                    rule_id="titleblock.duplicate_drawing_number",
                    title="Duplicate drawing number detected",
                    category=FindingCategory.TITLE_BLOCK_REVISION.value,
                    severity=Severity.MAJOR.value,
                    confidence=0.82,
                    sheet_id=first["id"],
                    page_number=first.get("page_number"),
                    evidence=[
                        _evidence(
                            f"Drawing number {number} appears on pages {', '.join(str(sheet.get('page_number')) for sheet in duplicate_sheets)}.",
                            first,
                            number,
                            [],
                            0.82,
                        )
                    ],
                    reasoning_summary="Duplicate drawing numbers can break drawing index and revision control.",
                    suggested_correction=f"Verify whether {number} is duplicated or one title block is incorrect.",
                    comment_text=f"Verify duplicate drawing number {number}.",
                )
            )

        drawing_numbers = {number.replace("&", "") for number in numbers}
        references = [entity for entity in context.entities if entity["entity_type"] == "drawing_reference"]
        for ref in references:
            normalized = ref["normalized_text"].replace("&", "")
            if normalized.startswith(("REV", "NOTE")):
                continue
            if normalized not in drawing_numbers and not _is_self_label_noise(normalized):
                sheet = context.sheet_by_id.get(ref["sheet_id"])
                findings.append(
                    CandidateFinding(
                        rule_id="titleblock.unmatched_reference",
                        title="Referenced drawing not found in package",
                        category=FindingCategory.DRAWING_COORDINATION.value,
                        severity=Severity.MINOR.value,
                        confidence=0.62,
                        sheet_id=ref["sheet_id"],
                        page_number=ref.get("page_number"),
                        location=ref.get("bbox"),
                        involved_entities=[ref["id"]],
                        evidence=[
                            _evidence(
                                f"Reference {ref['normalized_text']} was extracted but no matching drawing number was found in the package.",
                                sheet,
                                ref.get("text"),
                                [ref["id"]],
                                0.66,
                            )
                        ],
                        reasoning_summary="Unmatched drawing references may indicate a missing sheet or stale callout.",
                        suggested_correction=f"Verify reference {ref['normalized_text']} against the drawing index.",
                        comment_text=f"Verify drawing reference {ref['normalized_text']}. Matching sheet was not found.",
                    )
                )
        return findings

    def _missing(
        self,
        context: PackageContext,
        title: str,
        category: str,
        severity: str,
        comment: str,
        reasoning: str,
        correction: str,
        rule_id: str,
        confidence: float,
    ) -> CandidateFinding:
        first = context.first_review_sheet()
        reviewed = [context.sheet_label(sheet) for sheet in context.review_sheets] or ["no reviewable sheets"]
        return CandidateFinding(
            rule_id=rule_id,
            title=title,
            category=category,
            severity=severity,
            confidence=confidence,
            sheet_id=first["id"] if first else None,
            page_number=first.get("page_number") if first else None,
            evidence=[
                {
                    "observation": f"Reviewed prioritized sheets without detecting the required item: {'; '.join(reviewed[:8])}.",
                    "sheet_id": first["id"] if first else None,
                    "page_number": first.get("page_number") if first else None,
                    "text_excerpt": None,
                    "entity_ids": [],
                    "confidence": confidence,
                }
            ],
            reasoning_summary=reasoning,
            suggested_correction=correction,
            comment_text=comment,
        )

    def _sheet_finding(
        self,
        sheet: dict[str, Any],
        title: str,
        category: str,
        severity: str,
        comment: str,
        reasoning: str,
        correction: str,
        rule_id: str,
        confidence: float,
    ) -> CandidateFinding:
        return CandidateFinding(
            rule_id=rule_id,
            title=title,
            category=category,
            severity=severity,
            confidence=confidence,
            sheet_id=sheet["id"],
            page_number=sheet.get("page_number"),
            evidence=[
                {
                    "observation": f"Title block field is missing or unclear on {sheet.get('drawing_number', 'UNKNOWN')} page {sheet.get('page_number')}.",
                    "sheet_id": sheet["id"],
                    "page_number": sheet.get("page_number"),
                    "text_excerpt": (sheet.get("text_content") or "")[:240],
                    "entity_ids": [],
                    "confidence": confidence,
                }
            ],
            reasoning_summary=reasoning,
            suggested_correction=correction,
            comment_text=comment,
        )

    def _present(self, context: PackageContext, component_type: str) -> bool:
        component = context.graph.components.get(component_type)
        return bool(component and component.present)

    def _first_component_sheet(self, context: PackageContext, component_type: str) -> dict[str, Any] | None:
        component = context.graph.components.get(component_type)
        if not component or not component.sheet_ids:
            return None
        return context.sheet_by_id.get(component.sheet_ids[0])

    def _entities_by_text(
        self,
        context: PackageContext,
        sheet_ids: set[str],
        entity_type: str,
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in context.entities:
            if entity["sheet_id"] in sheet_ids and entity["entity_type"] == entity_type:
                out[entity["normalized_text"]].append(entity)
        return out

    def _normalize_and_dedupe(self, project_id: str, candidates: list[CandidateFinding]) -> list[dict[str, Any]]:
        merged: dict[str, CandidateFinding] = {}
        for candidate in candidates:
            candidate.confidence = max(0.05, min(0.98, candidate.confidence))
            candidate.severity = _severity_value(candidate.severity)
            candidate.comment_text = _normalize_comment(candidate.comment_text)
            candidate.status = FindingStatus.ACCEPTED.value if candidate.confidence >= 0.72 else FindingStatus.NEEDS_REVIEW.value  # type: ignore[attr-defined]
            key = self._dedupe_key(candidate)
            existing = merged.get(key)
            if not existing:
                merged[key] = candidate
                continue
            if _severity_rank(candidate.severity) < _severity_rank(existing.severity):
                existing.severity = candidate.severity
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.evidence.extend(candidate.evidence)
            existing.involved_entities = sorted(set(existing.involved_entities + candidate.involved_entities))
            existing.location = existing.location or candidate.location
            if candidate.rule_id not in existing.rule_id:
                existing.rule_id = f"{existing.rule_id},{candidate.rule_id}"

        findings: list[dict[str, Any]] = []
        now = utc_now_iso()
        for candidate in merged.values():
            stable_id = self._stable_id(project_id, candidate)
            status = FindingStatus.ACCEPTED.value if candidate.confidence >= 0.72 else FindingStatus.NEEDS_REVIEW.value
            findings.append(
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "sheet_id": candidate.sheet_id,
                    "stable_id": stable_id,
                    "title": candidate.title,
                    "category": candidate.category,
                    "severity": candidate.severity,
                    "confidence": round(candidate.confidence, 2),
                    "page_number": candidate.page_number,
                    "location": candidate.location,
                    "involved_entities": sorted(set(candidate.involved_entities)),
                    "evidence": _dedupe_evidence(candidate.evidence),
                    "reasoning_summary": candidate.reasoning_summary,
                    "suggested_correction": candidate.suggested_correction,
                    "comment_text": candidate.comment_text,
                    "status": status,
                    "source": candidate.source,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return sorted(findings, key=lambda item: (_severity_rank(item["severity"]), item.get("page_number") or 9999, item["title"]))

    def _dedupe_key(self, candidate: CandidateFinding) -> str:
        if candidate.rule_id.startswith(("configuration.", "operability.", "instrumentation.", "opp.", "package_completeness.")):
            return candidate.rule_id
        entity_part = ",".join(sorted(candidate.involved_entities)) if candidate.involved_entities else ""
        return "|".join(
            [
                candidate.category.lower(),
                candidate.title.lower(),
                candidate.sheet_id or "project",
                entity_part or re.sub(r"\W+", "", candidate.comment_text.lower())[:48],
            ]
        )

    def _stable_id(self, project_id: str, candidate: CandidateFinding) -> str:
        raw = "|".join(
            [
                project_id,
                candidate.rule_id,
                candidate.sheet_id or "project",
                candidate.title,
                ",".join(sorted(candidate.involved_entities)),
            ]
        )
        return f"QC-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10].upper()}"


def _severity_rank(severity: str) -> int:
    return {
        Severity.CRITICAL.value: 0,
        Severity.MAJOR.value: 1,
        Severity.MINOR.value: 2,
        Severity.NOTE.value: 3,
    }.get(_severity_value(severity), 4)


def _severity_value(severity: str | Severity) -> str:
    return severity.value if isinstance(severity, Severity) else str(severity)


def _normalize_comment(text: str, max_length: int = 360) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) > max_length:
        return clean[: max_length - 3].rstrip() + "..."
    return clean


def _display_entity_type(entity_type: str) -> str:
    return {
        "valve_tag": "Valve tag",
        "equipment_tag": "Equipment tag",
        "instrument_tag": "Instrument tag",
        "line_number": "Line number",
    }.get(entity_type, "Entity")


def _excerpt(text: str, start: int, end: int, radius: int = 80) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _evidence(
    observation: str,
    sheet: dict[str, Any] | None,
    text_excerpt: str | None,
    entity_ids: list[str],
    confidence: float,
) -> dict[str, Any]:
    return {
        "observation": observation,
        "sheet_id": sheet["id"] if sheet else None,
        "page_number": sheet.get("page_number") if sheet else None,
        "text_excerpt": text_excerpt,
        "entity_ids": entity_ids,
        "confidence": confidence,
    }


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("observation"), item.get("sheet_id"), item.get("text_excerpt"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:12]


def _is_self_label_noise(value: str) -> bool:
    return value in {"PID", "PFD", "PANDID"} or bool(re.fullmatch(r"[MLNDGA]-?\d", value))
