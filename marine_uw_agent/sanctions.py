from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List

from .models import Party, SanctionsMatch
from .normalizers import classify_match, normalize_company_name, normalize_imo, similarity


SOURCE_GROUPS = {
    "EU": {"eu"},
    "UK": {"uk"},
    "US": {"ofac", "ofac_sdn", "ofac_consolidated"},
}


class LocalSanctionsIndex:
    def __init__(self, snapshot_path: Path = Path("data/sanctions_snapshot.json")):
        self.snapshot_path = snapshot_path
        self.generated_at = ""
        self.records: List[Dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self.snapshot_path.exists():
            return
        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.generated_at = str(data.get("generated_at", ""))
        for record in data.get("records", []):
            source = str(record.get("source", ""))
            name = str(record.get("name", "")).strip()
            if source and name:
                self.records.append(
                    {
                        "source": source,
                        "name": name,
                        "normalized": normalize_company_name(name),
                        "program": str(record.get("program", "") or ""),
                        "reference": str(record.get("reference", "") or ""),
                    }
                )

    def search_party(self, party: Party, threshold: float = 82.0, limit: int = 5) -> List[SanctionsMatch]:
        if not party.name and not party.identifier:
            return []
        terms = [party.name]
        if party.identifier:
            terms.append(party.identifier)
        matches: List[SanctionsMatch] = []
        for term in [item for item in terms if item]:
            term_imo = normalize_imo(term)
            for record in self.records:
                record_imo = normalize_imo(record["name"])
                exact_identifier = bool(term_imo and record_imo and term_imo == record_imo)
                score = 100.0 if exact_identifier else similarity(term, record["name"])
                status = classify_match(term, record["name"], score=score, exact_identifier=exact_identifier)
                if status == "clear" or score < threshold:
                    continue
                matches.append(
                    SanctionsMatch(
                        source=record["source"],
                        search_term=term,
                        status=status,
                        matched_name=record["name"],
                        score=score,
                        program=record["program"],
                        unique_id=record["reference"],
                    )
                )
        return sorted(matches, key=lambda item: (item.status == "confirmed_match", item.score or 0), reverse=True)[:limit]


def group_sanctions_results(parties: Iterable[Party], index: LocalSanctionsIndex) -> Dict[str, List[SanctionsMatch]]:
    results: Dict[str, List[SanctionsMatch]] = {}
    for party in parties:
        party_key = f"{party.role}: {party.name or party.identifier or 'not provided'}"
        matches = index.search_party(party)
        if not matches:
            results[party_key] = [
                SanctionsMatch(source="EU/UK/US local snapshot", search_term=party.name or party.identifier or "", status="clear", notes="No relevant local sanctions snapshot match found.")
            ]
        else:
            results[party_key] = matches
    return results


def summarize_party_jurisdiction(matches: List[SanctionsMatch], jurisdiction: str) -> str:
    source_names = SOURCE_GROUPS.get(jurisdiction, set())
    scoped = [match for match in matches if match.source in source_names or match.source == "EU/UK/US local snapshot"]
    if not scoped:
        return "clear"
    if any(match.status == "confirmed_match" for match in scoped):
        return "confirmed match"
    if any(match.status == "likely_match" for match in scoped):
        return "manual review required"
    if any(match.status == "possible_match" for match in scoped):
        return "manual review required"
    return "clear"
