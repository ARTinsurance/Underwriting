from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .browser import ManualInterventionRequired, pause_for_manual_if_needed
from .config import Settings
from .history import add_quote_comparison, filter_same_vessel_quotes
from .models import QuotationSlip, SourceResult
from .normalizers import parse_date, search_variants
from .paths import RunPaths, evidence_path
from .quotation_extractor import extract_quotation_from_text


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class QuotationSystemClient:
    def __init__(self, settings: Settings, paths: RunPaths):
        self.settings = settings
        self.paths = paths

    def retrieve(self, page: Any, quotation_reference: str) -> tuple[QuotationSlip, SourceResult]:
        url = self.settings.quotation_system_url
        evidence: List[str] = []
        try:
            page.goto(url, wait_until="domcontentloaded")
            pause_for_manual_if_needed(page, "Quotation system")
            self._fill_login_if_present(page)
            pause_for_manual_if_needed(page, "Quotation system")
            self._search_reference(page, quotation_reference)
            screenshot = evidence_path(self.paths, "quotation_system", quotation_reference)
            page.screenshot(path=str(screenshot), full_page=True)
            evidence.append(str(screenshot))
            html_path = self.paths.raw / f"quotation_{quotation_reference}.html"
            html_path.write_text(page.content(), encoding="utf-8")
            evidence.append(str(html_path))
            text = page.locator("body").inner_text(timeout=10000)
            slip = extract_quotation_from_text(quotation_reference, text)
            return slip, SourceResult("Quotation system", "ok", now_iso(), url, evidence, {"quotation_reference": quotation_reference})
        except ManualInterventionRequired:
            raise
        except Exception as exc:
            return QuotationSlip(quotation_reference=quotation_reference), SourceResult("Quotation system", "failed", now_iso(), url, evidence, error=str(exc), manual_intervention_required=True)

    def _fill_login_if_present(self, page: Any) -> None:
        username = self.settings.quotation_system_username
        password = self.settings.quotation_system_password
        for selector in ('input[name="username"]', 'input[type="email"]', '#username', '#UserName'):
            if page.locator(selector).count():
                page.locator(selector).first.fill(username)
                break
        for selector in ('input[name="password"]', 'input[type="password"]', '#password', '#Password'):
            if page.locator(selector).count():
                page.locator(selector).first.fill(password)
                break
        for selector in ('button[type="submit"]', 'input[type="submit"]', 'button:has-text("Login")', 'button:has-text("Sign in")'):
            if page.locator(selector).count():
                page.locator(selector).first.click()
                page.wait_for_load_state("domcontentloaded")
                break

    def _search_reference(self, page: Any, quotation_reference: str) -> None:
        for selector in ('input[name="quotation_reference"]', 'input[type="search"]', '#quotationReference', 'input[placeholder*="Search"]'):
            if page.locator(selector).count():
                page.locator(selector).first.fill(quotation_reference)
                page.keyboard.press("Enter")
                page.wait_for_load_state("domcontentloaded")
                return
        page.get_by_text(quotation_reference, exact=False).first.click(timeout=3000)

    def search_history(self, page: Any, slip: QuotationSlip, as_of_date: Any) -> tuple[List[Dict[str, Any]], SourceResult]:
        evidence: List[str] = []
        try:
            current = slip.__dict__
            anchor = parse_date(slip.quotation_date) or as_of_date
            raw_quotes: List[Dict[str, Any]] = []
            for term in search_variants(slip.vessel_name or "", slip.imo):
                page.goto(self.settings.quotation_system_url, wait_until="domcontentloaded")
                self._search_reference(page, term)
                screenshot = evidence_path(self.paths, "quotation_history", term)
                page.screenshot(path=str(screenshot), full_page=True)
                evidence.append(str(screenshot))
                raw_quotes.extend(self._extract_history_rows(page))
            matches = filter_same_vessel_quotes(current, raw_quotes, anchor)
            return add_quote_comparison(current, matches), SourceResult("Quotation history", "ok", now_iso(), self.settings.quotation_system_url, evidence, {"search_terms": search_variants(slip.vessel_name or "", slip.imo)})
        except Exception as exc:
            return [], SourceResult("Quotation history", "failed", now_iso(), self.settings.quotation_system_url, evidence, error=str(exc), manual_intervention_required=True)

    def _extract_history_rows(self, page: Any) -> List[Dict[str, Any]]:
        rows = []
        try:
            table_rows = page.locator("table tr")
            for index in range(1, min(table_rows.count(), 200)):
                cells = table_rows.nth(index).locator("td")
                values = [cells.nth(cell).inner_text().strip() for cell in range(cells.count())]
                if values:
                    rows.append({"quotation_reference": values[0], "quotation_date": values[1] if len(values) > 1 else "", "raw": values})
        except Exception:
            pass
        return rows


class EquasisClient:
    def __init__(self, settings: Settings, paths: RunPaths):
        self.settings = settings
        self.paths = paths

    def research(self, page: Any, slip: QuotationSlip) -> tuple[Dict[str, Any], SourceResult]:
        evidence: List[str] = []
        try:
            page.goto(self.settings.equasis_url, wait_until="domcontentloaded")
            pause_for_manual_if_needed(page, "Equasis")
            term = slip.imo or slip.vessel_name or ""
            for selector in ('input[name="P_IMO"]', 'input[name="search"]', 'input[type="text"]'):
                if page.locator(selector).count():
                    page.locator(selector).first.fill(term)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("domcontentloaded")
                    break
            pause_for_manual_if_needed(page, "Equasis")
            screenshot = evidence_path(self.paths, "equasis", term)
            page.screenshot(path=str(screenshot), full_page=True)
            evidence.append(str(screenshot))
            html_path = self.paths.raw / f"equasis_{term}.html"
            html_path.write_text(page.content(), encoding="utf-8")
            evidence.append(str(html_path))
            data = {"search_term": term, "raw_text": page.locator("body").inner_text(timeout=10000)[:20000]}
            return data, SourceResult("Equasis", "ok", now_iso(), self.settings.equasis_url, evidence, data)
        except ManualInterventionRequired:
            raise
        except Exception as exc:
            return {}, SourceResult("Equasis", "failed", now_iso(), self.settings.equasis_url, evidence, error=str(exc), manual_intervention_required=True)


class HifleetClient:
    def __init__(self, settings: Settings, paths: RunPaths):
        self.settings = settings
        self.paths = paths

    def research(self, page: Any, slip: QuotationSlip) -> tuple[Dict[str, Any], SourceResult]:
        evidence: List[str] = []
        try:
            page.goto(self.settings.hifleet_url, wait_until="domcontentloaded")
            pause_for_manual_if_needed(page, "Hifleet")
            self._login_if_present(page)
            term = slip.imo or slip.vessel_name or ""
            for selector in ('input[type="search"]', 'input[name="keyword"]', 'input[type="text"]'):
                if page.locator(selector).count():
                    page.locator(selector).first.fill(term)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("domcontentloaded")
                    break
            pause_for_manual_if_needed(page, "Hifleet")
            screenshot = evidence_path(self.paths, "hifleet", term)
            page.screenshot(path=str(screenshot), full_page=True)
            evidence.append(str(screenshot))
            html_path = self.paths.raw / f"hifleet_{term}.html"
            html_path.write_text(page.content(), encoding="utf-8")
            evidence.append(str(html_path))
            data = {"search_term": term, "raw_text": page.locator("body").inner_text(timeout=10000)[:20000]}
            return data, SourceResult("Hifleet", "ok", now_iso(), self.settings.hifleet_url, evidence, data)
        except ManualInterventionRequired:
            raise
        except Exception as exc:
            return {}, SourceResult("Hifleet", "failed", now_iso(), self.settings.hifleet_url, evidence, error=str(exc), manual_intervention_required=True)

    def _login_if_present(self, page: Any) -> None:
        for selector in ('input[name="username"]', 'input[type="email"]', '#username'):
            if page.locator(selector).count():
                page.locator(selector).first.fill(self.settings.hifleet_username)
                break
        for selector in ('input[name="password"]', 'input[type="password"]', '#password'):
            if page.locator(selector).count():
                page.locator(selector).first.fill(self.settings.hifleet_password)
                break
        for selector in ('button[type="submit"]', 'button:has-text("Login")', 'button:has-text("Sign in")'):
            if page.locator(selector).count():
                page.locator(selector).first.click()
                page.wait_for_load_state("domcontentloaded")
                break
