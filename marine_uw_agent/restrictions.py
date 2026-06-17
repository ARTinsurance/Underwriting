from __future__ import annotations

from typing import Any, Dict, List

from .models import CargoRestrictionResult


RESTRICTED_CARGO_TERMS = {
    "oil": "Oil/petroleum cargo may require price-cap attestation and sanctions review.",
    "petroleum": "Oil/petroleum cargo may require price-cap attestation and sanctions review.",
    "coal": "Coal cargo can trigger Russia-related restrictions.",
    "iron": "Iron/steel cargo can trigger Russia-related restrictions.",
    "steel": "Iron/steel cargo can trigger Russia-related restrictions.",
    "luxury": "Luxury goods can trigger Russia-related restrictions.",
    "dual-use": "Dual-use goods require manual export-control review.",
    "military": "Military goods require manual export-control review.",
    "technology": "Restricted technology requires manual export-control review.",
}

RUSSIA_TERMS = ("russia", "russian", "ru origin", "crimea", "sevastopol")


def cargo_restriction_review(cargo: Dict[str, Any], urls: Dict[str, str]) -> List[CargoRestrictionResult]:
    values = " ".join(str(value) for value in cargo.values() if value).casefold()
    if not values:
        return [
            CargoRestrictionResult("EU", "information_insufficient", "Cargo details missing.", urls["eu"]),
            CargoRestrictionResult("UK", "information_insufficient", "Cargo details missing.", urls["uk"]),
            CargoRestrictionResult("US", "information_insufficient", "Cargo details missing.", urls["ofac"]),
        ]

    results: List[CargoRestrictionResult] = []
    restricted_reasons = [reason for term, reason in RESTRICTED_CARGO_TERMS.items() if term in values]
    russia_issue = any(term in values for term in RUSSIA_TERMS)
    if restricted_reasons or russia_issue:
        basis = "; ".join(restricted_reasons)
        if russia_issue:
            basis = (basis + "; " if basis else "") + "Russia-related origin/destination/ownership/voyage indicator found."
        status = "manual_review_required"
    else:
        basis = "No restricted cargo keyword or Russia-related indicator found in supplied cargo fields."
        status = "clear"

    results.append(CargoRestrictionResult("EU", status, basis, urls["eu"], "Council Regulation (EU) No 833/2014"))
    results.append(CargoRestrictionResult("UK", status, basis, urls["uk"], "Russia (Sanctions) (EU Exit) Regulations 2019"))
    results.append(CargoRestrictionResult("US", status, basis, urls["ofac"], "OFAC sanctions programs"))
    return results
