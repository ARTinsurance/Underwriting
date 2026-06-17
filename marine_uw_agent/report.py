from __future__ import annotations

from .listed_area import client_offering_explanation
from .models import ReviewState
from .workbook import evidence_summary


def render_markdown(state: ReviewState) -> str:
    slip = state.quotation
    summary = evidence_summary(state)
    lines = [
        "# UW Sanctions and Quotation Review",
        "",
        "## 1. Executive Summary",
        "",
        f"- Overall result: {overall_result(state)}",
        f"- Key findings: {summary['Executive result']}",
        f"- Required follow-up: {', '.join(state.open_issues) if state.open_issues else 'None identified from available information'}",
        "",
        "## 2. Quotation Extract",
        "",
    ]
    if slip:
        for key in ("quotation_reference", "quotation_date", "insurance_type", "assured", "broker", "vessel_name", "imo", "route", "listed_area", "sum_insured", "net_rate", "premium", "payment_terms", "law_and_jurisdiction", "written_line"):
            lines.append(f"- {key.replace('_', ' ').title()}: {getattr(slip, key)}")
    else:
        lines.append("- Quotation was not extracted.")

    lines.extend(["", "## 3. Vessel Details", "", str(state.vessel_details or "Information insufficient")])

    lines.extend(["", "## 4. Parties Screened", "", "| Role | Name | Identifier | Source |", "|---|---|---|---|"])
    for party in state.parties:
        lines.append(f"| {party.role} | {party.name} | {party.identifier or ''} | {party.source or ''} |")

    lines.extend(["", "## 5. EU/UK/US Sanctions Results", ""])
    for key, matches in state.sanctions_results.items():
        lines.append(f"### {key}")
        for match in matches:
            lines.append(f"- {match.source}: {match.status}; term `{match.search_term}`; match `{match.matched_name or 'none'}`; score {match.score}; evidence {', '.join(match.evidence_paths) or 'local snapshot/no screenshot'}")

    lines.extend(["", "## 6. Cargo Restriction Review", ""])
    for result in state.cargo_results:
        lines.append(f"- {result.jurisdiction}: {result.status} - {result.basis} ({result.regulation}{', ' + result.article_or_annex if result.article_or_annex else ''})")

    lines.extend(["", "## 7. Hifleet Position and Port-Call Review", "", str(state.hifleet or "Information insufficient")])

    lines.extend(["", "## 8. Same-Vessel Quotations in Past 3 Months", ""])
    if state.quotation_history:
        lines.extend(["| Quote | Date | Broker | Listed Area | Net Rate | Premium | Status |", "|---|---|---|---|---|---|---|"])
        for item in state.quotation_history:
            lines.append(f"| {item.get('quotation_reference') or item.get('quote_id') or ''} | {item.get('parsed_quote_date') or item.get('quotation_date') or ''} | {item.get('broker') or ''} | {item.get('listed_area') or ''} | {item.get('net_rate') or ''} | {item.get('premium') or ''} | {item.get('bound') or item.get('status') or ''} |")
    else:
        lines.append("- No same-vessel quotations found from available search. See audit trail for search terms/date window.")

    lines.extend(["", "## 9. Listed Area and Coverage Offered", "", f"- Definition: {state.listed_area_review.get('definition', 'Information insufficient')}", f"- Client explanation: {client_offering_explanation(slip) if slip else 'Information insufficient'}"])
    for item in state.listed_area_review.get("ambiguities", []):
        lines.append(f"- Ambiguity: {item}")

    lines.extend(["", "## 10. Open Issues", ""])
    checklist = [
        "missing beneficial owner",
        "missing operator/manager",
        "missing charterer",
        "missing cargo details",
        "missing HS code",
        "missing port history",
        "missing AIS evidence",
        "possible sanctions match",
        "cargo restriction issue",
        "route/listed-area ambiguity",
        "need order revalidation 48 hours before HRA entry",
        "need final wording confirmation",
    ]
    for item in checklist:
        checked = "x" if item in state.open_issues else " "
        lines.append(f"- [{checked}] {item}")

    lines.extend(["", "## 11. Audit Trail", "", f"- Quotation reference: {state.inputs.quotation_reference}", f"- Run timestamp: {state.run_timestamp}", f"- Code version: {state.run_id}"])
    for source in state.source_results:
        lines.append(f"- {source.source}: {source.status}; {source.url}; evidence: {', '.join(source.evidence_paths)}; error: {source.error or ''}")
    return "\n".join(lines) + "\n"


def overall_result(state: ReviewState) -> str:
    statuses = [match.status for matches in state.sanctions_results.values() for match in matches]
    if "confirmed_match" in statuses:
        return "Confirmed match"
    if "likely_match" in statuses or "possible_match" in statuses:
        return "Possible match"
    if state.open_issues or any(item.status == "information_insufficient" for item in state.cargo_results):
        return "Information insufficient"
    return "Clear"
