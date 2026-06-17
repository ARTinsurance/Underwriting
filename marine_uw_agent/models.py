from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


MatchStatus = str


@dataclass
class RunInputs:
    quotation_reference: str
    as_of_date: date
    template_workbook_path: Path
    output_dir: Path
    output_workbook_path: Optional[Path] = None
    quotation_pdf_path: Optional[Path] = None
    cargo_details: Dict[str, Any] = field(default_factory=dict)
    expected_listed_area: Optional[str] = None
    headful: bool = True


@dataclass
class SourceResult:
    source: str
    status: str
    timestamp: str
    url: str
    evidence_paths: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    manual_intervention_required: bool = False


@dataclass
class QuotationSlip:
    quotation_reference: str
    quotation_date: Optional[str] = None
    validity: Optional[str] = None
    insurance_type: Optional[str] = None
    assured: Optional[str] = None
    broker: Optional[str] = None
    registered_owner: Optional[str] = None
    vessel_name: Optional[str] = None
    imo: Optional[str] = None
    built_year: Optional[str] = None
    vessel_type: Optional[str] = None
    flag: Optional[str] = None
    grt: Optional[str] = None
    vessel_class: Optional[str] = None
    period: Optional[str] = None
    route: Optional[str] = None
    listed_area: Optional[str] = None
    sum_insured: Optional[str] = None
    gross_rate: Optional[str] = None
    discounts: Optional[str] = None
    no_claim_bonus: Optional[str] = None
    net_rate: Optional[str] = None
    premium: Optional[str] = None
    terms: List[str] = field(default_factory=list)
    warranties: List[str] = field(default_factory=list)
    clauses: List[str] = field(default_factory=list)
    payment_terms: Optional[str] = None
    law_and_jurisdiction: Optional[str] = None
    written_line: Optional[str] = None
    cargo: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class Party:
    name: str
    role: str
    identifier: Optional[str] = None
    country: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None


@dataclass
class SanctionsMatch:
    source: str
    search_term: str
    status: MatchStatus
    matched_name: Optional[str] = None
    score: Optional[float] = None
    program: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    address: Optional[str] = None
    unique_id: Optional[str] = None
    evidence_paths: List[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class CargoRestrictionResult:
    jurisdiction: str
    status: str
    basis: str
    regulation: str
    article_or_annex: Optional[str] = None
    evidence_paths: List[str] = field(default_factory=list)


@dataclass
class ReviewState:
    inputs: RunInputs
    run_id: str
    run_timestamp: str
    quotation: Optional[QuotationSlip] = None
    quotation_history: List[Dict[str, Any]] = field(default_factory=list)
    vessel_details: Dict[str, Any] = field(default_factory=dict)
    hifleet: Dict[str, Any] = field(default_factory=dict)
    parties: List[Party] = field(default_factory=list)
    sanctions_results: Dict[str, List[SanctionsMatch]] = field(default_factory=dict)
    cargo_results: List[CargoRestrictionResult] = field(default_factory=list)
    listed_area_review: Dict[str, Any] = field(default_factory=dict)
    open_issues: List[str] = field(default_factory=list)
    source_results: List[SourceResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if hasattr(value, "__dataclass_fields__"):
                return {key: convert(getattr(value, key)) for key in value.__dataclass_fields__}
            if isinstance(value, list):
                return [convert(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            return value

        return convert(self)
