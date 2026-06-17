from __future__ import annotations

import re
from typing import Any, Dict, List

from .models import QuotationSlip


JWLA_PATTERN = re.compile(r"\bJWLA[-\s]?\d{3}\b", re.IGNORECASE)


def review_listed_area(slip: QuotationSlip, override: str | None = None) -> Dict[str, Any]:
    source_text = " ".join(
        item
        for item in [
            override or "",
            slip.listed_area or "",
            slip.route or "",
            " ".join(slip.warranties),
            " ".join(slip.terms),
        ]
        if item
    )
    jwla_refs = sorted(set(match.group(0).upper().replace(" ", "-") for match in JWLA_PATTERN.finditer(source_text)))
    named_ports = extract_named_ports(source_text)
    prohibited_routes = []
    for phrase in ("not transiting through the Strait of Hormuz", "no strait of hormuz", "no israeli port", "no us port", "no uk port"):
        if phrase in source_text.casefold():
            prohibited_routes.append(phrase)

    ambiguity: List[str] = []
    if not source_text:
        ambiguity.append("route/listed-area ambiguity")
    if jwla_refs and not slip.listed_area:
        ambiguity.append("JWLA reference found outside Listed Area field; confirm intended listed area.")
    if jwla_refs:
        ambiguity.append("Exact coordinates not verified in source wording; confirm against current JWLA wording.")

    definition = "Information insufficient to define listed areas."
    if source_text:
        definition = "Listed Areas should be defined by the quotation's listed-area wording/JWLA reference and the specific route or transit clause, not as general worldwide cover."

    return {
        "listed_area": override or slip.listed_area,
        "route": slip.route,
        "jwla_references": jwla_refs,
        "named_ports": named_ports,
        "prohibited_routes": prohibited_routes,
        "definition": definition,
        "ambiguities": ambiguity,
        "source_text": source_text,
    }


def extract_named_ports(text: str) -> List[str]:
    candidates = []
    for label in ("from", "to", "via", "loading port", "discharge port"):
        pattern = rf"{label}\s+([A-Z][A-Za-z .'-]+)"
        for match in re.finditer(pattern, text):
            value = match.group(1).strip(" .;")
            if value and value not in candidates:
                candidates.append(value)
    return candidates[:20]


def client_offering_explanation(slip: QuotationSlip) -> str:
    coverage = slip.insurance_type or "Marine War cover"
    vessel = slip.vessel_name or "the declared vessel"
    route = slip.route or slip.listed_area or "the declared transit"
    parts = [
        f"We are offering short-period {coverage} for {vessel} for {route}",
        "subject to the quotation's route, period, warranties, exclusions, sanctions clauses, and final terms",
    ]
    if slip.sum_insured:
        parts.append(f"sum insured {slip.sum_insured}")
    if slip.net_rate:
        parts.append(f"net rate {slip.net_rate}")
    if slip.premium:
        parts.append(f"premium {slip.premium}")
    if slip.payment_terms:
        parts.append(f"payment terms {slip.payment_terms}")
    if slip.law_and_jurisdiction:
        parts.append(f"law and jurisdiction {slip.law_and_jurisdiction}")
    if slip.written_line:
        parts.append(f"written line {slip.written_line}")
    return ", ".join(parts) + ". Do not treat this as general worldwide cover unless the slip expressly states so."
