from __future__ import annotations

import re
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, List, Optional


LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "llc",
    "plc",
    "pte",
    "sa",
    "sarl",
    "gmbh",
    "bv",
}


def normalize_company_name(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(word for word in value.split() if word not in LEGAL_SUFFIXES)


def normalize_vessel_name(value: str) -> str:
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


def normalize_imo(value: Any) -> Optional[str]:
    if value is None:
        return None
    match = re.search(r"\b(\d{7})\b", str(value))
    return match.group(1) if match else None


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def months_back(anchor: date, months: int) -> date:
    month = anchor.month - months
    year = anchor.year
    while month <= 0:
        month += 12
        year -= 1
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(anchor.day, days[month - 1]))


def search_variants(name: str, imo: Optional[str] = None) -> List[str]:
    variants = []
    for item in [
        name,
        name.upper(),
        re.sub(r"[^A-Za-z0-9]+", " ", name).strip(),
        re.sub(r"[^A-Za-z0-9]+", "", name).strip(),
        normalize_company_name(name),
        normalize_vessel_name(name),
        imo or "",
    ]:
        if item and item not in variants:
            variants.append(item)
    return variants


def similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, normalize_company_name(left), normalize_company_name(right)).ratio() * 100, 2)


def classify_match(search_term: str, matched_name: str, score: Optional[float] = None, exact_identifier: bool = False) -> str:
    if exact_identifier:
        return "confirmed_match"
    if normalize_imo(search_term) and normalize_imo(search_term) == normalize_imo(matched_name):
        return "confirmed_match"
    if normalize_company_name(search_term) == normalize_company_name(matched_name):
        return "likely_match"
    effective_score = score if score is not None else similarity(search_term, matched_name)
    if effective_score >= 92:
        return "likely_match"
    if effective_score >= 82:
        return "possible_match"
    return "clear"
