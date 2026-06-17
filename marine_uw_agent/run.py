from __future__ import annotations

import argparse
import json
import getpass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .browser import BrowserSession, BrowserUnavailable, ManualInterventionRequired
from .config import Settings
from .listed_area import review_listed_area
from .models import QuotationSlip, ReviewState, RunInputs, SourceResult
from .normalizers import parse_date
from .party_builder import build_parties, missing_party_issues
from .paths import create_run_paths
from .quotation_extractor import extract_quotation_from_text
from .report import render_markdown
from .restrictions import cargo_restriction_review
from .sanctions import LocalSanctionsIndex, group_sanctions_results
from .source_adapters import EquasisClient, HifleetClient, QuotationSystemClient, now_iso
from .workbook import WorkbookPopulationError, populate_workbook


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VM browser workflow for marine war quotation underwriting review.")
    parser.add_argument("--quotation-reference", required=True)
    parser.add_argument("--template-workbook", default="UW Review - HK.xlsx")
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--output-workbook")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--quotation-pdf")
    parser.add_argument("--quotation-text")
    parser.add_argument("--cargo-json")
    parser.add_argument("--expected-listed-area")
    parser.add_argument("--headful", default="true")
    parser.add_argument("--offline", action="store_true", help="Skip browser automation and use supplied quotation text/PDF where available.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    as_of = parse_date(args.as_of_date)
    if not as_of:
        raise SystemExit("--as-of-date must be a valid date")
    headful = str(args.headful).casefold() in {"1", "true", "yes", "y"}
    output_dir = Path(args.output_dir)
    output_workbook = Path(args.output_workbook) if args.output_workbook else output_dir / f"{args.quotation_reference}_UW_Review.xlsx"
    cargo_details = json.loads(Path(args.cargo_json).read_text(encoding="utf-8")) if args.cargo_json else {}
    inputs = RunInputs(
        quotation_reference=args.quotation_reference,
        as_of_date=as_of,
        template_workbook_path=Path(args.template_workbook),
        output_dir=output_dir,
        output_workbook_path=output_workbook,
        quotation_pdf_path=Path(args.quotation_pdf) if args.quotation_pdf else None,
        cargo_details=cargo_details,
        expected_listed_area=args.expected_listed_area,
        headful=headful,
    )
    state = run_workflow(inputs, quotation_text_path=Path(args.quotation_text) if args.quotation_text else None, offline=args.offline)
    write_outputs(state)
    return 0


def run_workflow(inputs: RunInputs, quotation_text_path: Optional[Path] = None, offline: bool = False) -> ReviewState:
    settings = Settings.from_env()
    paths = create_run_paths(inputs.output_dir, inputs.quotation_reference)
    state = ReviewState(inputs=inputs, run_id=f"marine_uw_agent {__version__}", run_timestamp=now_iso())
    audit = {
        "run_timestamp": state.run_timestamp,
        "user": getpass.getuser(),
        "quotation_reference": inputs.quotation_reference,
        "code_version": state.run_id,
    }
    (paths.root / "run_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    if quotation_text_path:
        text = quotation_text_path.read_text(encoding="utf-8")
        state.quotation = extract_quotation_from_text(inputs.quotation_reference, text)
        state.source_results.append(SourceResult("Quotation text", "ok", now_iso(), str(quotation_text_path), [str(quotation_text_path)]))
    elif inputs.quotation_pdf_path:
        state.quotation = QuotationSlip(inputs.quotation_reference)
        state.open_issues.append("PDF extraction requires deployment parser/manual review")
        state.source_results.append(SourceResult("Quotation PDF", "manual_review_required", now_iso(), str(inputs.quotation_pdf_path), [str(inputs.quotation_pdf_path)], manual_intervention_required=True))

    if not offline:
        try:
            settings.validate_for_browser_run()
            with BrowserSession(settings.browser_profile_dir, paths.downloads, headful=inputs.headful) as browser:
                page = browser.page
                quotation_client = QuotationSystemClient(settings, paths)
                slip, source = quotation_client.retrieve(page, inputs.quotation_reference)
                state.source_results.append(source)
                if source.status == "ok":
                    state.quotation = slip
                if state.quotation and state.quotation.vessel_name and state.quotation.imo:
                    history, history_source = quotation_client.search_history(page, state.quotation, inputs.as_of_date)
                    state.quotation_history = history
                    state.source_results.append(history_source)
                    equasis_data, equasis_source = EquasisClient(settings, paths).research(page, state.quotation)
                    state.vessel_details = equasis_data
                    state.source_results.append(equasis_source)
                    hifleet_data, hifleet_source = HifleetClient(settings, paths).research(page, state.quotation)
                    state.hifleet = hifleet_data
                    state.source_results.append(hifleet_source)
        except (BrowserUnavailable, ManualInterventionRequired, ValueError) as exc:
            state.open_issues.append(str(exc))
            state.source_results.append(SourceResult("Browser workflow", "manual_review_required", now_iso(), "VM browser", error=str(exc), manual_intervention_required=True))

    if not state.quotation:
        state.quotation = QuotationSlip(inputs.quotation_reference)
        state.open_issues.append("quotation extraction failed")

    if inputs.cargo_details:
        state.quotation.cargo.update(inputs.cargo_details)
    validate_minimum_quotation(state)
    state.listed_area_review = review_listed_area(state.quotation, inputs.expected_listed_area)
    state.parties = build_parties(state.quotation, state.vessel_details, state.hifleet)
    state.open_issues.extend(issue for issue in missing_party_issues(state.parties, state.quotation) if issue not in state.open_issues)
    state.open_issues.extend(issue for issue in state.listed_area_review.get("ambiguities", []) if issue not in state.open_issues)
    urls = {
        "eu": settings.eu_russia_reg_833_url,
        "uk": settings.uk_russia_regs_url,
        "ofac": settings.ofac_url,
    }
    state.cargo_results = cargo_restriction_review(state.quotation.cargo, urls)
    for result in state.cargo_results:
        if result.status == "information_insufficient" and "missing cargo details" not in state.open_issues:
            state.open_issues.append("missing cargo details")
        if result.status == "manual_review_required" and "cargo restriction issue" not in state.open_issues:
            state.open_issues.append("cargo restriction issue")
    state.sanctions_results = group_sanctions_results(state.parties, LocalSanctionsIndex())
    if any(match.status in {"possible_match", "likely_match"} for matches in state.sanctions_results.values() for match in matches):
        state.open_issues.append("possible sanctions match")
    if not state.hifleet:
        state.open_issues.extend(issue for issue in ("missing port history", "missing AIS evidence") if issue not in state.open_issues)
    return state


def validate_minimum_quotation(state: ReviewState) -> None:
    if not state.quotation:
        return
    if not state.quotation.vessel_name:
        state.open_issues.append("missing vessel name - manual confirmation required before sanctions/history search")
    if not state.quotation.imo:
        state.open_issues.append("missing IMO - manual confirmation required before sanctions/history search")


def write_outputs(state: ReviewState) -> None:
    output_dir = state.inputs.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    reference = state.inputs.quotation_reference
    extracted_path = output_dir / f"{reference}_extracted.json"
    sanctions_path = output_dir / f"{reference}_sanctions.json"
    history_path = output_dir / f"{reference}_quote_history.json"
    report_path = output_dir / f"{reference}_UW_Review.md"
    extracted_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    sanctions_path.write_text(json.dumps({key: [item.__dict__ for item in value] for key, value in state.sanctions_results.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
    history_path.write_text(json.dumps(state.quotation_history, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(render_markdown(state), encoding="utf-8")
    if state.inputs.output_workbook_path:
        try:
            populate_workbook(state, state.inputs.output_workbook_path)
        except WorkbookPopulationError as exc:
            state.open_issues.append(str(exc))
            fallback = output_dir / f"{reference}_workbook_population_error.txt"
            fallback.write_text(str(exc), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
