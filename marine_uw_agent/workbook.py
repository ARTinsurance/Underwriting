from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .listed_area import client_offering_explanation
from .models import ReviewState, SanctionsMatch
from .sanctions import summarize_party_jurisdiction


SHEETS = ["Sources", "UW Info", "Fleet Info", "Search results", "Sanction Watchlist Countries"]


class WorkbookPopulationError(RuntimeError):
    pass


def populate_workbook(state: ReviewState, output_path: Path) -> Path:
    """Populate template workbook while preserving formatting when openpyxl is available.

    If the template is unavailable, a new workbook is created. This keeps the
    workflow testable while still preserving a real template in VM deployments.
    """
    try:
        import openpyxl
    except Exception as exc:
        raise WorkbookPopulationError("openpyxl is required to populate .xlsx workbooks in the VM deployment.") from exc

    template = state.inputs.template_workbook_path
    if template.exists():
        workbook = openpyxl.load_workbook(template)
    else:
        workbook = openpyxl.Workbook()
        workbook.active.title = SHEETS[0]
        for sheet in SHEETS[1:]:
            workbook.create_sheet(sheet)

    ensure_sheets(workbook)
    populate_sources(workbook["Sources"], state)
    populate_uw_info(workbook["UW Info"], state)
    populate_fleet_info(workbook["Fleet Info"], state)
    populate_search_results(workbook["Search results"], state)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return output_path


def ensure_sheets(workbook: Any) -> None:
    for sheet in SHEETS:
        if sheet not in workbook.sheetnames:
            workbook.create_sheet(sheet)


def write_table(sheet: Any, start_row: int, headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> int:
    for col, header in enumerate(headers, 1):
        sheet.cell(start_row, col).value = header
    row_index = start_row + 1
    for row in rows:
        for col, value in enumerate(row, 1):
            sheet.cell(row_index, col).value = value
        row_index += 1
    return row_index + 1


def populate_sources(sheet: Any, state: ReviewState) -> None:
    rows = [
        ("Quotation system", "QUOTATION_SYSTEM_URL", "Stored in VM secrets"),
        ("Equasis", "https://www.equasis.org/EquasisWeb/restricted/Search?fs=Search", "Stored in VM secrets"),
        ("Hifleet", "https://www.hifleet.com", "Stored in VM secrets"),
        ("UK Sanctions List", "https://search-uk-sanctions-list.service.gov.uk/", ""),
        ("UK Russia Regulations", "https://www.legislation.gov.uk/uksi/2019/855", ""),
        ("OFAC Sanctions Search", "https://sanctionssearch.ofac.treas.gov/", ""),
        ("EU Regulation 833/2014", "https://eur-lex.europa.eu/eli/reg/2014/833/oj/eng", ""),
    ]
    write_table(sheet, 1, ("Source", "URL / Reference", "Password"), rows)


def populate_uw_info(sheet: Any, state: ReviewState) -> None:
    slip = state.quotation
    if not slip:
        return
    sheet["A1"] = "Quotation Ref no."
    sheet["B1"] = slip.quotation_reference
    sheet["A2"] = "Listed Area"
    sheet["B2"] = state.listed_area_review.get("listed_area") or "Information insufficient"
    sheet["A3"] = "Estimated Date of Arrival"
    sheet["B3"] = state.hifleet.get("eta", "Information insufficient")

    vessel_rows = [
        (
            slip.vessel_name,
            slip.imo,
            "Vessel",
            slip.flag,
            israel_interest(state),
            jurisdiction_summary(state, "vessel name", "EU"),
            jurisdiction_summary(state, "vessel name", "UK"),
            "Not checked",
            jurisdiction_summary(state, "vessel name", "US"),
            port_history_summary(state),
        )
    ]
    row = write_table(
        sheet,
        5,
        ("Vessel Name", "IMO", "Role", "Flag", "Israeli Interest Y/N", "EU result", "UK result", "UN result", "US result", "Call port history"),
        vessel_rows,
    )

    party_rows = []
    for party in state.parties:
        matches = state.sanctions_results.get(f"{party.role}: {party.name or party.identifier}", [])
        party_rows.append(
            (
                party.name,
                party.identifier,
                party.role,
                party.country,
                "Information insufficient",
                summarize_party_jurisdiction(matches, "EU"),
                summarize_party_jurisdiction(matches, "UK"),
                "Not checked",
                summarize_party_jurisdiction(matches, "US"),
                party.address,
            )
        )
    row = write_table(sheet, row, ("Name", "Identifier", "Role", "Country origin", "Israeli Interest Y/N", "EU result", "UK result", "UN result", "US result", "Address"), party_rows)

    history_rows = [
        (
            item.get("quotation_reference") or item.get("quote_id"),
            item.get("broker"),
            item.get("listed_area"),
            item.get("type_of_coverage") or item.get("insurance_type"),
            item.get("net_rate"),
            item.get("premium"),
            item.get("bound") or item.get("status"),
        )
        for item in state.quotation_history
    ]
    row = write_table(sheet, row, ("Quotation Ref no.", "Broker", "Listed Area", "Type of Coverage", "Net rate", "Premium", "Bound or not"), history_rows)

    cargo = slip.cargo or {}
    cargo_rows = [
        (
            cargo.get("description"),
            cargo.get("hs_code"),
            cargo.get("loading_port"),
            cargo.get("discharge_port"),
            cargo.get("intermediate_port"),
            cargo_status(state, "EU"),
            cargo_status(state, "UK"),
            "Not checked",
            cargo_status(state, "US"),
            cargo.get("nexus") or "Information insufficient",
        )
    ]
    write_table(sheet, row, ("Cargo carried on board", "HS code", "Loading port", "Discharge port", "Intermediate port", "EU result", "UK result", "UN result", "US result", "Any EU/UK/US nexus"), cargo_rows)


def populate_fleet_info(sheet: Any, state: ReviewState) -> None:
    rows = []
    fleet = state.vessel_details.get("associated_fleet", [])
    for item in fleet if isinstance(fleet, list) else []:
        rows.append((item.get("vessel_name"), item.get("imo"), item.get("role"), item.get("flag"), item.get("manager") or item.get("owner"), "Information insufficient", "Information insufficient", item.get("source", "Equasis/Hifleet")))
    if not rows:
        rows.append((state.quotation.vessel_name if state.quotation else "", state.quotation.imo if state.quotation else "", "Current vessel", state.quotation.flag if state.quotation else "", state.quotation.registered_owner if state.quotation else "", "See UW Info", port_history_summary(state), "Quotation/Equasis/Hifleet"))
    write_table(sheet, 1, ("Vessel name", "IMO", "Role/relationship", "Flag", "Manager/owner", "Sanctions result", "Port call exposure", "Source"), rows)


def populate_search_results(sheet: Any, state: ReviewState) -> None:
    summary = evidence_summary(state)
    rows = [(section, text) for section, text in summary.items()]
    write_table(sheet, 1, ("Section", "Result"), rows)


def jurisdiction_summary(state: ReviewState, role_contains: str, jurisdiction: str) -> str:
    for key, matches in state.sanctions_results.items():
        if role_contains in key:
            return summarize_party_jurisdiction(matches, jurisdiction)
    return "Information insufficient"


def cargo_status(state: ReviewState, jurisdiction: str) -> str:
    for result in state.cargo_results:
        if result.jurisdiction == jurisdiction:
            return result.status.replace("_", " ")
    return "Information insufficient"


def israel_interest(state: ReviewState) -> str:
    text = " ".join([str(state.hifleet), str(state.quotation.cargo if state.quotation else "")]).casefold()
    if "israel" in text or "israeli" in text:
        return "Manual review required"
    return "Information insufficient"


def port_history_summary(state: ReviewState) -> str:
    if not state.hifleet:
        return "missing port history"
    text = str(state.hifleet).casefold()
    exposures = [label for label in ("israel", "united states", "usa", "united kingdom", "uk") if label in text]
    return "Manual review required: " + ", ".join(exposures) if exposures else "No relevant exposure identified in available evidence"


def evidence_summary(state: ReviewState) -> Dict[str, str]:
    all_matches = [match for matches in state.sanctions_results.values() for match in matches]
    has_risk = any(match.status in {"possible_match", "likely_match", "confirmed_match"} for match in all_matches)
    insufficient = state.open_issues or any(result.status == "information_insufficient" for result in state.cargo_results)
    if has_risk:
        headline = "Manual review required due to possible/likely/confirmed sanctions result."
    elif insufficient:
        headline = "No confirmed sanctions match identified based on available information; however, review remains information-insufficient pending " + ", ".join(state.open_issues or ["missing cargo/source data"]) + "."
    else:
        headline = "No sanction concerns identified from completed EU/UK/US checks."

    return {
        "Executive result": headline,
        "Vessel search result": str(state.vessel_details)[:3000],
        "Owner search result": party_result_text(state, "owner"),
        "Manager search result": party_result_text(state, "manager"),
        "Charterer search result": party_result_text(state, "charterer"),
        "Cargo search result": "; ".join(f"{item.jurisdiction}: {item.status} - {item.basis}" for item in state.cargo_results),
        "Port history result": port_history_summary(state),
        "Prior quotation comparison": str(state.quotation_history)[:3000] or "No same-vessel quotation records found from available search.",
        "Listed area and offer": client_offering_explanation(state.quotation) if state.quotation else "Information insufficient",
        "Evidence": "; ".join(path for source in state.source_results for path in source.evidence_paths),
    }


def party_result_text(state: ReviewState, role: str) -> str:
    rows = []
    for key, matches in state.sanctions_results.items():
        if role in key:
            rows.append(key + ": " + ", ".join(f"{match.source} {match.status}" for match in matches))
    return "; ".join(rows) or "not provided / not found"
