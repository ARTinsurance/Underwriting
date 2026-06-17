"""
Quotation slip underwriting review.

This module combines three checks that are normally completed together:

1. Sanctions screening for all slip parties across EU, UK, and US data.
2. Same-vessel quotation history review for the previous three months.
3. Quotation slip review covering listed areas and client offering terms.

Inputs are intentionally plain JSON/CSV so the review can run without external
packages or network access.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SOURCE_GROUPS = {
    "EU": {"eu"},
    "UK": {"uk"},
    "US": {"ofac", "ofac_sdn", "ofac_consolidated"},
}

LISTED_AREA_KEYWORDS = {
    "russia": "Russia",
    "russian": "Russia",
    "ukraine": "Ukraine",
    "crimea": "Crimea",
    "sevastopol": "Crimea",
    "black sea": "Black Sea",
    "sea of azov": "Sea of Azov",
    "belarus": "Belarus",
    "iran": "Iran",
    "syria": "Syria",
    "north korea": "North Korea",
    "dprk": "North Korea",
    "cuba": "Cuba",
    "venezuela": "Venezuela",
    "red sea": "Red Sea",
    "yemen": "Yemen",
    "gulf of aden": "Gulf of Aden",
    "somalia": "Somalia",
}

PARTY_FIELDS = (
    "assured",
    "insured",
    "client",
    "broker",
    "owner",
    "registered_owner",
    "beneficial_owner",
    "manager",
    "technical_manager",
    "commercial_manager",
    "operator",
    "charterer",
    "mortgagee",
    "loss_payee",
)


def normalize_name(value: str) -> str:
    """Normalize names for deterministic exact/fuzzy comparison."""
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    legal_suffixes = {
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
    words = [word for word in value.split() if word not in legal_suffixes]
    return " ".join(words)


def parse_date(value: Any) -> Optional[date]:
    """Parse common ISO and day/month/year dates."""
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
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def months_back(anchor: date, months: int) -> date:
    """Return the same day N calendar months back, clamped to month end."""
    month = anchor.month - months
    year = anchor.year
    while month <= 0:
        month += 12
        year -= 1

    days_in_month = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    day = min(anchor.day, days_in_month[month - 1])
    return date(year, month, day)


@dataclass
class Party:
    role: str
    name: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SanctionsMatch:
    source_group: str
    source: str
    listed_name: str
    score: float
    program: str = ""
    reference: str = ""


@dataclass
class PartySanctionsResult:
    party: Party
    checks: Dict[str, List[SanctionsMatch]]

    @property
    def has_match(self) -> bool:
        return any(self.checks.values())


class SanctionsSnapshot:
    """Searchable sanctions snapshot built from data/sanctions_snapshot.json."""

    def __init__(self, snapshot_path: Path):
        self.snapshot_path = snapshot_path
        self.generated_at = ""
        self.records: List[Dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.generated_at = str(data.get("generated_at", ""))
        for record in data.get("records", []):
            name = str(record.get("name", "")).strip()
            source = str(record.get("source", "")).strip()
            if not name or not source:
                continue
            self.records.append(
                {
                    "source": source,
                    "name": name,
                    "normalized_name": normalize_name(name),
                    "program": str(record.get("program", "") or ""),
                    "reference": str(record.get("reference", "") or ""),
                }
            )

    def search(self, party_name: str, threshold: float = 0.94, limit: int = 5) -> Dict[str, List[SanctionsMatch]]:
        normalized_party = normalize_name(party_name)
        results = {group: [] for group in SOURCE_GROUPS}
        if not normalized_party:
            return results

        party_tokens = set(normalized_party.split())
        for record in self.records:
            normalized_record = record["normalized_name"]
            if not normalized_record:
                continue

            score = self._score(normalized_party, normalized_record, party_tokens)
            if score < threshold:
                continue

            for group, sources in SOURCE_GROUPS.items():
                if record["source"] in sources:
                    results[group].append(
                        SanctionsMatch(
                            source_group=group,
                            source=record["source"],
                            listed_name=record["name"],
                            score=round(score, 4),
                            program=record["program"],
                            reference=record["reference"],
                        )
                    )
                    break

        for group in results:
            results[group] = sorted(results[group], key=lambda item: item.score, reverse=True)[:limit]
        return results

    @staticmethod
    def _score(normalized_party: str, normalized_record: str, party_tokens: set[str]) -> float:
        if normalized_party == normalized_record:
            return 1.0

        record_tokens = set(normalized_record.split())
        if len(party_tokens) >= 2 and party_tokens.issubset(record_tokens):
            return 0.98
        if len(record_tokens) >= 2 and record_tokens.issubset(party_tokens):
            return 0.98

        return SequenceMatcher(None, normalized_party, normalized_record).ratio()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_parties(slip: Dict[str, Any]) -> List[Party]:
    """Extract all named parties from a permissive quotation slip structure."""
    parties: List[Party] = []
    seen: set[Tuple[str, str]] = set()

    for item in slip.get("parties", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        role = str(item.get("role", "party")).strip() or "party"
        if name:
            key = (role.casefold(), normalize_name(name))
            if key not in seen:
                parties.append(Party(role=role, name=name, metadata=item))
                seen.add(key)

    for field_name in PARTY_FIELDS:
        value = slip.get(field_name)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                metadata = item
            else:
                name = str(item or "").strip()
                metadata = {}
            if not name:
                continue
            key = (field_name, normalize_name(name))
            if key not in seen:
                parties.append(Party(role=field_name.replace("_", " "), name=name, metadata=metadata))
                seen.add(key)

    vessel = slip.get("vessel", {}) or {}
    if isinstance(vessel, dict):
        for role in ("registered_owner", "beneficial_owner", "manager", "operator"):
            name = str(vessel.get(role, "")).strip()
            if not name:
                continue
            key = (role, normalize_name(name))
            if key not in seen:
                parties.append(Party(role=role.replace("_", " "), name=name, metadata={"source": "vessel"}))
                seen.add(key)

    return parties


def load_quotation_history(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("quotations", []))


def same_vessel_history(
    slip: Dict[str, Any],
    history: Sequence[Dict[str, Any]],
    as_of: Optional[date] = None,
    months: int = 3,
) -> List[Dict[str, Any]]:
    vessel = slip.get("vessel", {}) or {}
    vessel_name = str(vessel.get("name", slip.get("vessel_name", ""))).strip()
    vessel_imo = str(vessel.get("imo", slip.get("imo", ""))).strip()
    anchor = parse_date(slip.get("quotation_date") or slip.get("quote_date")) or as_of or date.today()
    cutoff = months_back(anchor, months)

    matches: List[Dict[str, Any]] = []
    for quote in history:
        quote_date = parse_date(quote.get("quotation_date") or quote.get("quote_date") or quote.get("date"))
        if not quote_date or quote_date < cutoff or quote_date > anchor:
            continue

        quote_imo = str(quote.get("imo") or quote.get("vessel_imo") or "").strip()
        quote_name = str(quote.get("vessel_name") or quote.get("vessel") or "").strip()
        imo_match = vessel_imo and quote_imo and vessel_imo == quote_imo
        name_match = vessel_name and normalize_name(vessel_name) == normalize_name(quote_name)
        if imo_match or name_match:
            enriched = dict(quote)
            enriched["matched_by"] = "imo" if imo_match else "vessel_name"
            enriched["parsed_quote_date"] = quote_date.isoformat()
            matches.append(enriched)

    return sorted(matches, key=lambda item: item.get("parsed_quote_date", ""), reverse=True)


def collect_text_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items: List[str] = []
        for nested in value.values():
            items.extend(collect_text_values(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(collect_text_values(nested))
        return items
    return [str(value)]


def review_listed_areas(slip: Dict[str, Any]) -> Dict[str, Any]:
    explicit = []
    for key in ("listed_areas", "listed_area", "breach_areas", "additional_premium_areas"):
        explicit.extend(collect_text_values(slip.get(key)))

    trading_text = []
    for key in ("areas", "trading_limits", "navigation_limits", "voyage", "route", "geographical_limits"):
        trading_text.extend(collect_text_values(slip.get(key)))

    haystack = " ".join(explicit + trading_text).casefold()
    inferred = sorted({label for keyword, label in LISTED_AREA_KEYWORDS.items() if keyword in haystack})

    if explicit:
        definition = "Use the slip's listed areas as the controlling definition, subject to policy wording and sanctions exclusions."
    elif inferred:
        definition = "No explicit listed-area schedule found; define listed areas from the trading/voyage references below and confirm with underwriter wording."
    else:
        definition = "No listed areas identified in the supplied slip fields; confirm whether standard excluded/breach areas apply."

    return {
        "explicit_listed_areas": [item for item in explicit if str(item).strip()],
        "inferred_listed_areas": inferred,
        "definition_guidance": definition,
        "source_text": [item for item in trading_text if str(item).strip()],
    }


def review_offering(slip: Dict[str, Any]) -> Dict[str, Any]:
    offering = slip.get("offering") or slip.get("coverage") or {}
    if isinstance(offering, str):
        offering = {"coverage": offering}

    fields = {
        "coverage": offering.get("coverage") or slip.get("coverage") or slip.get("product"),
        "limit": offering.get("limit") or slip.get("limit"),
        "deductible": offering.get("deductible") or slip.get("deductible"),
        "premium": offering.get("premium") or slip.get("premium"),
        "rate": offering.get("rate") or slip.get("rate"),
        "conditions": offering.get("conditions") or slip.get("conditions"),
        "exclusions": offering.get("exclusions") or slip.get("exclusions"),
        "subjectivities": offering.get("subjectivities") or slip.get("subjectivities"),
    }

    present = {key: value for key, value in fields.items() if value not in (None, "", [])}
    missing = [key for key in fields if key not in present]

    return {
        "summary": present,
        "missing_fields": missing,
        "client_wording": build_client_offering_sentence(present),
    }


def build_client_offering_sentence(fields: Dict[str, Any]) -> str:
    coverage = fields.get("coverage", "the requested marine insurance cover")
    parts = [f"We are offering {coverage}"]
    if fields.get("limit"):
        parts.append(f"with limit {fields['limit']}")
    if fields.get("deductible"):
        parts.append(f"deductible {fields['deductible']}")
    if fields.get("premium"):
        parts.append(f"premium {fields['premium']}")
    if fields.get("rate"):
        parts.append(f"rate {fields['rate']}")
    return ", ".join(parts) + "."


def review_quotation(
    slip: Dict[str, Any],
    sanctions_snapshot: SanctionsSnapshot,
    quotation_history: Sequence[Dict[str, Any]],
    as_of: Optional[date] = None,
    threshold: float = 0.94,
) -> Dict[str, Any]:
    parties = extract_parties(slip)
    sanctions_results = [
        PartySanctionsResult(party=party, checks=sanctions_snapshot.search(party.name, threshold=threshold))
        for party in parties
    ]

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sanctions_snapshot_generated_at": sanctions_snapshot.generated_at,
        "vessel": slip.get("vessel", {}),
        "parties": [party.__dict__ for party in parties],
        "sanctions_results": serialize_sanctions_results(sanctions_results),
        "quotation_history_matches": same_vessel_history(slip, quotation_history, as_of=as_of),
        "listed_area_review": review_listed_areas(slip),
        "offering_review": review_offering(slip),
    }


def serialize_sanctions_results(results: Sequence[PartySanctionsResult]) -> List[Dict[str, Any]]:
    serialized = []
    for result in results:
        serialized.append(
            {
                "party": result.party.__dict__,
                "status": "MATCH" if result.has_match else "NO_MATCH",
                "checks": {
                    group: [match.__dict__ for match in matches]
                    for group, matches in result.checks.items()
                },
            }
        )
    return serialized


def render_markdown(report: Dict[str, Any]) -> str:
    vessel = report.get("vessel") or {}
    vessel_name = vessel.get("name") or "Not specified"
    vessel_imo = vessel.get("imo") or "Not specified"
    lines = [
        "# Underwriting Quotation Review",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Sanctions snapshot: {report.get('sanctions_snapshot_generated_at') or 'Not specified'}",
        f"- Vessel: {vessel_name}",
        f"- IMO: {vessel_imo}",
        "",
        "## Sanctions Check Results",
        "",
    ]

    for result in report["sanctions_results"]:
        party = result["party"]
        lines.append(f"### {party['role']}: {party['name']}")
        lines.append(f"- Overall status: {result['status']}")
        for group in ("EU", "UK", "US"):
            matches = result["checks"].get(group, [])
            if not matches:
                lines.append(f"- {group}: No match")
                continue
            lines.append(f"- {group}: {len(matches)} possible match(es)")
            for match in matches:
                detail = f"  - {match['listed_name']} ({match['source']}, score {match['score']})"
                if match.get("reference"):
                    detail += f", ref {match['reference']}"
                lines.append(detail)
        lines.append("")

    lines.extend(["## Same-Vessel Quotation History", ""])
    history = report["quotation_history_matches"]
    if not history:
        lines.append("- No same-vessel quotations found in the previous 3 months from the quotation date.")
    else:
        for item in history:
            quote_id = item.get("quote_id") or item.get("id") or "No quote id"
            quote_date = item.get("parsed_quote_date") or item.get("quotation_date") or item.get("date")
            terms = item.get("terms") or item.get("premium") or item.get("rate") or ""
            lines.append(f"- {quote_date}: {quote_id}, matched by {item.get('matched_by')}, {terms}".rstrip(" ,"))

    listed = report["listed_area_review"]
    lines.extend(["", "## Listed Areas", "", f"- Guidance: {listed['definition_guidance']}"])
    if listed["explicit_listed_areas"]:
        lines.append(f"- Explicit listed areas: {', '.join(listed['explicit_listed_areas'])}")
    if listed["inferred_listed_areas"]:
        lines.append(f"- Inferred listed areas: {', '.join(listed['inferred_listed_areas'])}")
    if listed["source_text"]:
        lines.append(f"- Source wording reviewed: {'; '.join(listed['source_text'])}")

    offering = report["offering_review"]
    lines.extend(["", "## Client Offering", "", f"- {offering['client_wording']}"])
    for key, value in offering["summary"].items():
        lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    if offering["missing_fields"]:
        lines.append(f"- Missing/unclear fields: {', '.join(offering['missing_fields'])}")

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a quotation slip for sanctions, listed areas, and prior quotes.")
    parser.add_argument("slip", type=Path, help="Quotation slip JSON file")
    parser.add_argument("--history", type=Path, help="Quotation history JSON or CSV file")
    parser.add_argument("--snapshot", type=Path, default=Path("data/sanctions_snapshot.json"), help="Sanctions snapshot JSON")
    parser.add_argument("--output", type=Path, help="Markdown report path")
    parser.add_argument("--json-output", type=Path, help="JSON report path")
    parser.add_argument("--as-of", help="Override review date, YYYY-MM-DD")
    parser.add_argument("--threshold", type=float, default=0.94, help="Fuzzy match threshold")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    slip = load_json(args.slip)
    snapshot = SanctionsSnapshot(args.snapshot)
    history = load_quotation_history(args.history)
    as_of = parse_date(args.as_of) if args.as_of else None
    report = review_quotation(slip, snapshot, history, as_of=as_of, threshold=args.threshold)

    markdown = render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
