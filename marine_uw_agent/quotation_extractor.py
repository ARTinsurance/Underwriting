from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

from .models import QuotationSlip
from .normalizers import normalize_imo


FIELD_PATTERNS = {
    "quotation_date": r"(?:quotation date|quote date)\s*[:\-]\s*(.+)",
    "validity": r"(?:validity|valid until)\s*[:\-]\s*(.+)",
    "insurance_type": r"(?:insurance type|type of coverage|coverage)\s*[:\-]\s*(.+)",
    "assured": r"(?:assured|insured|client)\s*[:\-]\s*(.+)",
    "broker": r"(?:broker)\s*[:\-]\s*(.+)",
    "registered_owner": r"(?:registered owner|owner)\s*[:\-]\s*(.+)",
    "vessel_name": r"(?:vessel name|vessel)\s*[:\-]\s*(.+)",
    "imo": r"(?:imo|imo number)\s*[:\-]?\s*(\d{7})",
    "built_year": r"(?:built|build year|year built)\s*[:\-]\s*(.+)",
    "vessel_type": r"(?:vessel type|type of ship)\s*[:\-]\s*(.+)",
    "flag": r"(?:flag)\s*[:\-]\s*(.+)",
    "grt": r"(?:grt|gross tonnage)\s*[:\-]\s*(.+)",
    "vessel_class": r"(?:class|classification)\s*[:\-]\s*(.+)",
    "period": r"(?:period of insurance|period|cover period)\s*[:\-]\s*(.+)",
    "route": r"(?:route|transit route|voyage)\s*[:\-]\s*(.+)",
    "listed_area": r"(?:listed area|premium area)\s*[:\-]\s*(.+)",
    "sum_insured": r"(?:sum insured|hull value|insured value)\s*[:\-]\s*(.+)",
    "gross_rate": r"(?:gross rate)\s*[:\-]\s*(.+)",
    "discounts": r"(?:discounts?|discount)\s*[:\-]\s*(.+)",
    "no_claim_bonus": r"(?:no claim bonus|ncb)\s*[:\-]\s*(.+)",
    "net_rate": r"(?:net rate)\s*[:\-]\s*(.+)",
    "premium": r"(?:premium|net premium)\s*[:\-]\s*(.+)",
    "payment_terms": r"(?:payment terms?)\s*[:\-]\s*(.+)",
    "law_and_jurisdiction": r"(?:law and jurisdiction|jurisdiction)\s*[:\-]\s*(.+)",
    "written_line": r"(?:written line|line)\s*[:\-]\s*(.+)",
}


def _first_match(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip(";")


def _lines_after_heading(text: str, headings: Iterable[str]) -> list[str]:
    results = []
    lines = text.splitlines()
    heading_pattern = re.compile("|".join(re.escape(item) for item in headings), re.IGNORECASE)
    for index, line in enumerate(lines):
        if heading_pattern.search(line):
            for nested in lines[index + 1 : index + 6]:
                clean = nested.strip(" -\t")
                if clean:
                    results.append(clean)
    return results[:10]


def extract_quotation_from_text(quotation_reference: str, text: str) -> QuotationSlip:
    data: Dict[str, Optional[str]] = {}
    for field_name, pattern in FIELD_PATTERNS.items():
        data[field_name] = _first_match(pattern, text)
    if data.get("imo"):
        data["imo"] = normalize_imo(data["imo"])

    slip = QuotationSlip(quotation_reference=quotation_reference, raw_text=text, **data)
    slip.terms = _lines_after_heading(text, ("terms", "terms and conditions"))
    slip.warranties = _lines_after_heading(text, ("warranties", "express warranties", "warranty"))
    slip.clauses = _lines_after_heading(text, ("clauses", "subject to"))
    slip.cargo = {
        "description": _first_match(r"(?:cargo|cargo carried on board)\s*[:\-]\s*(.+)", text),
        "hs_code": _first_match(r"(?:hs code|commodity code)\s*[:\-]\s*(.+)", text),
        "loading_port": _first_match(r"(?:loading port|load port)\s*[:\-]\s*(.+)", text),
        "discharge_port": _first_match(r"(?:discharge port|disport)\s*[:\-]\s*(.+)", text),
        "intermediate_port": _first_match(r"(?:intermediate port|via port)\s*[:\-]\s*(.+)", text),
    }
    slip.cargo = {key: value for key, value in slip.cargo.items() if value}
    return slip
