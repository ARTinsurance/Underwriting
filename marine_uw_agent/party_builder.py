from __future__ import annotations

from typing import Any, Dict, List

from .models import Party, QuotationSlip


def add_party(parties: List[Party], name: Any, role: str, identifier: Any = None, country: Any = None, address: Any = None, source: str = "quotation") -> None:
    clean_name = str(name or "").strip()
    clean_identifier = str(identifier or "").strip() or None
    if not clean_name and not clean_identifier:
        return
    key = (clean_name.casefold(), role.casefold(), clean_identifier)
    existing = {(party.name.casefold(), party.role.casefold(), party.identifier) for party in parties}
    if key not in existing:
        parties.append(Party(clean_name, role, clean_identifier, str(country or "") or None, str(address or "") or None, source))


def build_parties(quotation: QuotationSlip, vessel_details: Dict[str, Any], hifleet: Dict[str, Any]) -> List[Party]:
    parties: List[Party] = []
    add_party(parties, quotation.vessel_name, "vessel name", quotation.imo)
    add_party(parties, quotation.flag, "flag state")
    add_party(parties, quotation.registered_owner, "registered owner")
    add_party(parties, quotation.assured, "assured")
    add_party(parties, quotation.broker, "broker")

    for role in ("beneficial_owner", "operator", "ism_manager", "technical_manager", "commercial_manager", "ship_manager", "registered_owner"):
        add_party(parties, vessel_details.get(role), role.replace("_", " "), source="Equasis/Hifleet")

    for role in ("charterer", "sub_charterer", "cargo_owner", "consignee"):
        add_party(parties, quotation.cargo.get(role), role.replace("_", " "), source="quotation cargo")

    for role in ("loading_port", "discharge_port", "intermediate_port"):
        add_party(parties, quotation.cargo.get(role), role.replace("_", " "), source="quotation cargo")

    for role in ("last_port", "next_port", "ais_destination"):
        add_party(parties, hifleet.get(role), role.replace("_", " "), source="Hifleet")

    return parties


def missing_party_issues(parties: List[Party], quotation: QuotationSlip) -> List[str]:
    issues = []
    required_roles = {
        "beneficial owner": "missing beneficial owner",
        "operator": "missing operator/manager",
        "charterer": "missing charterer",
    }
    present_roles = {party.role for party in parties if party.name or party.identifier}
    for role, issue in required_roles.items():
        if role not in present_roles:
            issues.append(issue)
    if not quotation.cargo:
        issues.append("missing cargo details")
    elif not quotation.cargo.get("hs_code"):
        issues.append("missing HS code")
    return issues
