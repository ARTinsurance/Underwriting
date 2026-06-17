from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Sequence

from .normalizers import months_back, normalize_imo, normalize_vessel_name, parse_date


def filter_same_vessel_quotes(current: Dict[str, Any], quotes: Sequence[Dict[str, Any]], anchor: date) -> List[Dict[str, Any]]:
    imo = normalize_imo(current.get("imo"))
    vessel_name = str(current.get("vessel_name") or current.get("vessel") or "")
    normalized_vessel = normalize_vessel_name(vessel_name)
    cutoff = months_back(anchor, 3)
    matches = []
    for quote in quotes:
        quote_date = parse_date(quote.get("quotation_date") or quote.get("quote_date") or quote.get("date"))
        if not quote_date or quote_date < cutoff or quote_date > anchor:
            continue
        quote_imo = normalize_imo(quote.get("imo") or quote.get("vessel_imo"))
        quote_vessel = normalize_vessel_name(str(quote.get("vessel_name") or quote.get("vessel") or ""))
        matched_by = None
        if imo and quote_imo == imo:
            matched_by = "imo"
        elif normalized_vessel and quote_vessel == normalized_vessel:
            matched_by = "vessel_name"
        if matched_by:
            enriched = dict(quote)
            enriched["matched_by"] = matched_by
            enriched["parsed_quote_date"] = quote_date.isoformat()
            matches.append(enriched)
    return sorted(matches, key=lambda item: item["parsed_quote_date"], reverse=True)


def add_quote_comparison(current: Dict[str, Any], prior_quotes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    comparisons = []
    current_rate = current.get("net_rate")
    current_premium = current.get("premium")
    for quote in prior_quotes:
        item = dict(quote)
        item["current_net_rate"] = current_rate
        item["current_premium"] = current_premium
        item["route_changed"] = bool(current.get("route") and quote.get("route") and current.get("route") != quote.get("route"))
        item["listed_area_changed"] = bool(current.get("listed_area") and quote.get("listed_area") and current.get("listed_area") != quote.get("listed_area"))
        comparisons.append(item)
    return comparisons
