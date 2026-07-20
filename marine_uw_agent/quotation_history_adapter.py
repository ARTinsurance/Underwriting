from __future__ import annotations

import csv
import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .config import Settings
from .history import add_quote_comparison, filter_same_vessel_quotes
from .models import QuotationSlip, SourceResult
from .normalizers import normalize_imo, parse_date, search_variants
from .paths import RunPaths, evidence_path


HISTORY_FIELDS = (
    "quotation_reference",
    "broker",
    "vessel_imo",
    "listed_area",
    "coverage_type",
    "gross_rate",
    "discounts",
    "net_rate",
    "premium",
    "bound",
    "quotation_date",
)


FIELD_ALIASES = {
    "quotation_reference": ("quotation ref", "quotation reference", "quote ref", "ref no", "reference", "quote no", "quotationno", "quotation no"),
    "broker": ("broker", "producer", "intermediary", "brokername"),
    "vessel_imo": ("imo", "vessel imo", "imo number", "shipimo", "ship imo"),
    "listed_area": ("listed area", "area", "jwla area", "premium area", "voyage", "route"),
    "coverage_type": ("coverage", "type of coverage", "insurance type", "class", "risk type", "classtype", "class type"),
    "gross_rate": ("gross rate", "gross", "original rate", "grossrate"),
    "discounts": ("discount", "discounts", "ncb", "no claim bonus"),
    "net_rate": ("net rate", "net", "rate", "netrate"),
    "premium": ("premium", "net premium", "gross premium", "netpremium"),
    "bound": ("bound", "bound/not bound", "status", "bind status", "order status", "statusname"),
    "quotation_date": ("quotation date", "quote date", "date", "created date", "created at", "createtime", "create time"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def canonical_field(header: str) -> Optional[str]:
    normalized = normalize_header(header)
    compact = normalized.replace(" ", "")
    for field, aliases in FIELD_ALIASES.items():
        if normalized == field.replace("_", " ") or compact == field.replace("_", ""):
            return field
        if any(normalized == alias or compact == alias.replace(" ", "") for alias in aliases):
            return field
    for field, aliases in FIELD_ALIASES.items():
        if any(len(alias) > 3 and alias in normalized for alias in aliases):
            return field
    return None


class QuotationHistoryAdapter:
    """Retrieve and normalize historical quotation rows from the quotation system."""

    def __init__(self, settings: Settings, paths: RunPaths, max_pages: int = 8, retries: int = 2):
        self.settings = settings
        self.paths = paths
        self.max_pages = max_pages
        self.retries = retries
        self.audit_path = paths.root / "quotation_history_audit.jsonl"

    def retrieve(self, page: Any, slip: QuotationSlip, as_of_date: Any) -> Tuple[List[Dict[str, Any]], SourceResult]:
        evidence: List[str] = []
        raw_rows: List[Dict[str, Any]] = []
        errors: List[str] = []
        searched_terms: List[str] = []
        url = self.settings.quotation_system_url

        for attempt in range(1, self.retries + 2):
            try:
                self._log("attempt_started", {"attempt": attempt, "url": url})
                api_rows, api_evidence = self._retrieve_via_api(page, slip)
                if api_rows is not None:
                    evidence.extend(api_evidence)
                    normalized = self._dedupe([self._normalize_row(row) for row in api_rows])
                    filtered = filter_same_vessel_quotes(slip.__dict__, normalized, as_of_date)
                    compared = add_quote_comparison(slip.__dict__, filtered)
                    status = "ok" if compared else "no_history_found"
                    self._write_outputs(normalized, compared)
                    self._log("api_retrieval_completed", {"status": status, "raw_rows": len(api_rows), "matched_rows": len(compared)})
                    return compared, SourceResult(
                        "Quotation history",
                        status,
                        now_iso(),
                        self._api_origin() + "/api/swz/queryQuoteList",
                        evidence,
                        {
                            "method": "api",
                            "search_terms": [f"{kind}:{term}" for kind, term in self._search_terms(slip)],
                            "raw_rows": len(api_rows),
                            "matched_rows": len(compared),
                            "retrieved_at": now_iso(),
                        },
                    )
                self._ensure_authenticated(page)
                terms = self._search_terms(slip)
                for term_kind, term in terms:
                    searched_terms.append(f"{term_kind}:{term}")
                    self._ensure_authenticated(page)
                    self._search(page, term)
                    screenshot = evidence_path(self.paths, "quotation_history", f"{term_kind}_{term}")
                    page.screenshot(path=str(screenshot), full_page=True)
                    evidence.append(str(screenshot))
                    raw_path = self.paths.raw / f"quotation_history_{term_kind}_{self._safe(term)}.html"
                    raw_path.write_text(page.content(), encoding="utf-8")
                    evidence.append(str(raw_path))
                    rows = self._extract_paginated_rows(page, term_kind, term)
                    raw_rows.extend(rows)
                normalized = self._dedupe([self._normalize_row(row) for row in raw_rows])
                filtered = filter_same_vessel_quotes(slip.__dict__, normalized, as_of_date)
                compared = add_quote_comparison(slip.__dict__, filtered)
                status = "ok" if compared else "no_history_found"
                self._write_outputs(normalized, compared)
                self._log("retrieval_completed", {"status": status, "raw_rows": len(raw_rows), "matched_rows": len(compared)})
                return compared, SourceResult(
                    "Quotation history",
                    status,
                    now_iso(),
                    url,
                    evidence,
                    {
                        "search_terms": searched_terms,
                        "raw_rows": len(raw_rows),
                        "matched_rows": len(compared),
                        "retrieved_at": now_iso(),
                    },
                )
            except Exception as exc:
                errors.append(str(exc))
                self._log("attempt_failed", {"attempt": attempt, "error": str(exc)})
                if attempt > self.retries:
                    break
                try:
                    page.goto(url, wait_until="domcontentloaded")
                except Exception:
                    pass

        fallback_rows, fallback_source = self._fallback_history(slip, as_of_date)
        if fallback_rows:
            self._write_outputs(fallback_rows, fallback_rows)
            return fallback_rows, SourceResult(
                "Quotation history",
                "fallback_used",
                now_iso(),
                fallback_source,
                evidence,
                {"retrieved_at": now_iso(), "errors": errors},
            )
        return [], SourceResult(
            "Quotation history",
            "manual_entry_required",
            now_iso(),
            url,
            evidence,
            {"retrieved_at": now_iso(), "errors": errors, "fallback": "CSV/XLSX/manual entry required"},
            error="Automated quotation history retrieval failed; do not treat as no previous quotation.",
            manual_intervention_required=True,
        )

    def _retrieve_via_api(self, page: Any, slip: QuotationSlip) -> Tuple[Optional[List[Dict[str, Any]]], List[str]]:
        token = self._api_login(page)
        rows: List[Dict[str, Any]] = []
        evidence: List[str] = []
        for term_kind, term in self._search_terms(slip):
            for endpoint, params in self._api_query_variants(term_kind, term):
                page_rows, raw_payload = self._api_query(page, token, endpoint, params)
                raw_path = self.paths.raw / f"quotation_history_api_{self._safe(term_kind)}_{self._safe(term)}_{self._safe(endpoint)}_{params.get('page', 1)}.json"
                raw_path.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
                evidence.append(str(raw_path))
                rows.extend(dict(row, search_term=term, search_term_kind=term_kind, source_endpoint=endpoint) for row in page_rows)
                total = self._payload_total(raw_payload)
                page_num = int(params.get("page", 1))
                page_size = int(params.get("num", 20))
                while total and page_num * page_size < total and page_num < self.max_pages:
                    page_num += 1
                    next_params = dict(params, page=page_num)
                    page_rows, raw_payload = self._api_query(page, token, endpoint, next_params)
                    raw_path = self.paths.raw / f"quotation_history_api_{self._safe(term_kind)}_{self._safe(term)}_{self._safe(endpoint)}_{page_num}.json"
                    raw_path.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
                    evidence.append(str(raw_path))
                    rows.extend(dict(row, search_term=term, search_term_kind=term_kind, source_endpoint=endpoint) for row in page_rows)
        return rows, evidence

    def _api_origin(self) -> str:
        parsed = urlparse(self.settings.quotation_system_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _api_login(self, page: Any) -> str:
        if not self.settings.quotation_system_url:
            raise RuntimeError("QUOTATION_SYSTEM_URL is not configured")
        if not self.settings.quotation_system_username or not self.settings.quotation_system_password:
            raise RuntimeError("Quotation system credentials are not configured in backend environment variables")
        page.goto(self.settings.quotation_system_url, wait_until="domcontentloaded")
        encoded_password = base64.b64encode(self.settings.quotation_system_password.encode("utf-8")).decode("ascii")
        response = page.evaluate(
            """
            async ({username, password}) => {
              const resp = await fetch('/api/swz/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify({username, password})
              });
              const data = await resp.json().catch(() => ({}));
              return {status: resp.status, code: data.code, msg: data.msg || '', data};
            }
            """,
            {"username": self.settings.quotation_system_username, "password": encoded_password},
        )
        if response.get("status") != 200 or str(response.get("code")) != "200":
            message = response.get("msg") or "login rejected"
            raise RuntimeError(f"Quotation system API login failed: {message}")
        data = response.get("data", {}).get("data", {})
        token = data.get("token") or response.get("data", {}).get("token")
        if not token:
            raise RuntimeError("Quotation system API login did not return a token")
        return str(token)

    def _api_query_variants(self, term_kind: str, term: str) -> List[Tuple[str, Dict[str, Any]]]:
        base = {"num": 20, "page": 1}
        variants: List[Tuple[str, Dict[str, Any]]] = []
        if term_kind == "quotation_reference":
            variants.append(("queryQuoteList", dict(base, code=term, name="ALL", status="ALL", shipEname="")))
            variants.append(("queryBrokerQuoteList", dict(base, code=term, name="ALL", userName="", shipEname="")))
        else:
            variants.append(("queryQuoteList", dict(base, code="", name="ALL", status="ALL", shipEname=term)))
            variants.append(("queryQuoteList", dict(base, code=term, name="ALL", status="ALL", shipEname="")))
            variants.append(("queryBrokerQuoteList", dict(base, code="", name="ALL", userName="", shipEname=term)))
        return variants

    def _api_query(self, page: Any, token: str, endpoint: str, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        url = f"/api/swz/{endpoint}"
        payload = page.evaluate(
            """
            async ({url, params, token}) => {
              const query = new URLSearchParams();
              Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
              });
              const resp = await fetch(`${url}?${query.toString()}`, {
                method: 'GET',
                credentials: 'include',
                headers: {token}
              });
              const data = await resp.json().catch(() => ({}));
              return {status: resp.status, data};
            }
            """,
            {"url": url, "params": params, "token": token},
        )
        if payload.get("status") in {401, 403}:
            raise RuntimeError("Quotation system API session expired or was rejected")
        data = payload.get("data", {})
        if str(data.get("code", "200")) not in {"200", "0"} and "list" not in data:
            raise RuntimeError(f"Quotation system API query failed: {data.get('msg') or data.get('message') or 'unknown error'}")
        return self._payload_rows(data), payload

    def _payload_rows(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        for key in ("list", "rows", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in ("list", "rows", "records"):
                value = data.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
        return []

    def _payload_total(self, payload: Dict[str, Any]) -> int:
        data = payload.get("data")
        candidates = [payload.get("total"), payload.get("totalNum")]
        if isinstance(data, dict):
            candidates.extend([data.get("total"), data.get("totalNum")])
        for value in candidates:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    def _ensure_authenticated(self, page: Any) -> None:
        if not self.settings.quotation_system_url:
            raise RuntimeError("QUOTATION_SYSTEM_URL is not configured")
        if not self.settings.quotation_system_username or not self.settings.quotation_system_password:
            raise RuntimeError("Quotation system credentials are not configured in backend environment variables")
        try:
            current_url = page.url
        except Exception:
            current_url = ""
        if not current_url or current_url == "about:blank" or self._looks_like_login(page):
            page.goto(self.settings.quotation_system_url, wait_until="domcontentloaded")
        if not self._looks_like_login(page):
            return
        self._fill_login(page)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        if self._looks_like_login(page):
            raise RuntimeError("Quotation system login did not complete")

    def _fill_login(self, page: Any) -> None:
        user_selectors = (
            "#name",
            'input[name="username"]',
            'input[name="userName"]',
            'input[name="user"]',
            'input[name="account"]',
            'input[type="text"]',
            '#username',
            '#userName',
            '#login',
        )
        password_selectors = ("#word", 'input[name="password"]', 'input[type="password"]', '#password')
        if not self._fill_first(page, user_selectors, self.settings.quotation_system_username):
            raise RuntimeError("Quotation system username field was not found")
        if not self._fill_first(page, password_selectors, self.settings.quotation_system_password):
            raise RuntimeError("Quotation system password field was not found")
        if not self._click_first(page, ('button:has-text("登录")', 'button[type="submit"]', 'button[type="button"]', 'input[type="submit"]', 'button:has-text("Login")', 'button:has-text("Sign in")')):
            page.keyboard.press("Enter")

    def _looks_like_login(self, page: Any) -> bool:
        try:
            if page.locator('input[type="password"]').count() > 0:
                return True
            text = page.locator("body").inner_text(timeout=1000).casefold()
            return "login" in text and ("password" in text or "username" in text)
        except Exception:
            return True

    def _search_terms(self, slip: QuotationSlip) -> List[Tuple[str, str]]:
        terms: List[Tuple[str, str]] = []
        if slip.quotation_reference:
            terms.append(("quotation_reference", slip.quotation_reference))
        for term in search_variants(slip.vessel_name or "", slip.imo):
            if normalize_imo(term):
                terms.append(("vessel_imo", normalize_imo(term) or term))
        seen = set()
        output = []
        for item in terms:
            if item not in seen and item[1]:
                seen.add(item)
                output.append(item)
        return output

    def _search(self, page: Any, term: str) -> None:
        selectors = (
            'input[name*="quotation" i]',
            'input[name*="reference" i]',
            'input[name*="ref" i]',
            'input[name*="imo" i]',
            'input[type="search"]',
            'input[placeholder*="Search" i]',
            'input[placeholder*="quotation" i]',
            'input[placeholder*="IMO" i]',
            'input[type="text"]',
        )
        if not self._fill_first(page, selectors, term):
            raise RuntimeError("Quotation history search field was not found")
        if not self._click_first(page, ('button:has-text("Search")', 'button:has-text("Query")', 'button[type="submit"]', 'input[type="submit"]')):
            page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        if self._looks_like_login(page):
            self._ensure_authenticated(page)
            if not self._fill_first(page, selectors, term):
                raise RuntimeError("Quotation history search field was not found after reauthentication")
            if not self._click_first(page, ('button:has-text("Search")', 'button:has-text("Query")', 'button[type="submit"]', 'input[type="submit"]')):
                page.keyboard.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=15000)

    def _extract_paginated_rows(self, page: Any, term_kind: str, term: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for page_index in range(self.max_pages):
            rows.extend(self._extract_rows(page, term_kind, term))
            if not self._click_next(page):
                break
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        return rows

    def _extract_rows(self, page: Any, term_kind: str, term: str) -> List[Dict[str, Any]]:
        table_rows = self._extract_table_rows(page)
        if table_rows:
            return [dict(row, search_term=term, search_term_kind=term_kind) for row in table_rows]
        cards = self._extract_card_rows(page)
        return [dict(row, search_term=term, search_term_kind=term_kind) for row in cards]

    def _extract_table_rows(self, page: Any) -> List[Dict[str, Any]]:
        return page.evaluate(
            """
            () => {
              const tables = Array.from(document.querySelectorAll('table'));
              const out = [];
              for (const table of tables) {
                const headerCells = Array.from(table.querySelectorAll('thead th'));
                const fallbackHeader = Array.from(table.querySelectorAll('tr')).find(row => row.querySelectorAll('th,td').length > 1);
                const headers = (headerCells.length ? headerCells : Array.from(fallbackHeader?.querySelectorAll('th,td') || []))
                  .map(cell => (cell.innerText || '').trim());
                if (headers.length < 2) continue;
                const rows = Array.from(table.querySelectorAll('tbody tr')).length
                  ? Array.from(table.querySelectorAll('tbody tr'))
                  : Array.from(table.querySelectorAll('tr')).slice(1);
                for (const row of rows) {
                  const cells = Array.from(row.querySelectorAll('td'));
                  if (!cells.length) continue;
                  const item = {};
                  cells.forEach((cell, index) => { item[headers[index] || `column_${index + 1}`] = (cell.innerText || '').trim(); });
                  item.__row_text = (row.innerText || '').trim();
                  out.push(item);
                }
              }
              return out;
            }
            """
        )

    def _extract_card_rows(self, page: Any) -> List[Dict[str, Any]]:
        text = page.locator("body").inner_text(timeout=5000)
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        rows = []
        for block in blocks:
            if not re.search(r"(quotation|premium|broker|imo|rate)", block, re.IGNORECASE):
                continue
            item: Dict[str, str] = {"__row_text": block}
            for line in block.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    item[key.strip()] = value.strip()
            rows.append(item)
        return rows

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {field: "" for field in HISTORY_FIELDS}
        for key, value in row.items():
            field = canonical_field(str(key))
            if field:
                normalized[field] = clean(value)
        text = clean(row.get("__row_text") or " ".join(str(value) for value in row.values()))
        normalized["raw_text"] = text[:1500]
        self._fill_missing_from_text(normalized, text)
        normalized["vessel_imo"] = normalize_imo(normalized.get("vessel_imo") or text) or normalized.get("vessel_imo", "")
        parsed = parse_date(normalized.get("quotation_date"))
        normalized["quotation_date"] = parsed.isoformat() if parsed else normalized.get("quotation_date", "")
        normalized["retrieved_at"] = now_iso()
        return normalized

    def _fill_missing_from_text(self, row: Dict[str, Any], text: str) -> None:
        patterns = {
            "quotation_reference": r"\b(ART-\d{8,}-[A-Z]{1,4}|[A-Z]{2,}-\d{4,}[A-Z0-9-]*)\b",
            "premium": r"(?:premium)\s*[:\-]?\s*([A-Z]{3}|USD|HKD|CNY)?\s*([0-9,.]+)",
            "gross_rate": r"(?:gross rate)\s*[:\-]?\s*([0-9.]+%?)",
            "net_rate": r"(?:net rate|rate)\s*[:\-]?\s*([0-9.]+%?)",
            "quotation_date": r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}/\d{4})\b",
        }
        for field, pattern in patterns.items():
            if row.get(field):
                continue
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                row[field] = clean(" ".join(group for group in match.groups() if group))
        if not row.get("bound"):
            lowered = text.casefold()
            if "not bound" in lowered or "unbound" in lowered:
                row["bound"] = "Not bound"
            elif "bound" in lowered or "bind" in lowered:
                row["bound"] = "Bound"

    def _dedupe(self, rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for row in rows:
            key = (row.get("quotation_reference"), row.get("vessel_imo"), row.get("quotation_date"), row.get("premium"))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    def _click_next(self, page: Any) -> bool:
        for selector in ('button:has-text("Next")', 'a:has-text("Next")', '.pagination a:has-text(">")', 'button[aria-label*="next" i]'):
            locator = page.locator(selector)
            try:
                if locator.count() and locator.first.is_enabled() and locator.first.is_visible():
                    locator.first.click()
                    return True
            except Exception:
                continue
        return False

    def _fallback_history(self, slip: QuotationSlip, as_of_date: Any) -> Tuple[List[Dict[str, Any]], str]:
        for path_value in (getattr(self.settings, "quotation_history_fallback_csv", ""), getattr(self.settings, "quotation_history_fallback_xlsx", "")):
            if not path_value:
                continue
            path = Path(path_value)
            if not path.exists():
                continue
            rows = self._load_fallback_rows(path)
            normalized = self._dedupe([self._normalize_row(row) for row in rows])
            return add_quote_comparison(slip.__dict__, filter_same_vessel_quotes(slip.__dict__, normalized, as_of_date)), str(path)
        return [], "manual entry"

    def _load_fallback_rows(self, path: Path) -> List[Dict[str, Any]]:
        if path.suffix.casefold() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as handle:
                return list(csv.DictReader(handle))
        if path.suffix.casefold() in {".xlsx", ".xlsm"}:
            import openpyxl

            workbook = openpyxl.load_workbook(path, data_only=True)
            sheet = workbook.active
            headers = [clean(cell.value) for cell in sheet[1]]
            rows = []
            for row in sheet.iter_rows(min_row=2, values_only=True):
                item = {headers[index]: value for index, value in enumerate(row) if index < len(headers)}
                if any(clean(value) for value in item.values()):
                    rows.append(item)
            return rows
        return []

    def _write_outputs(self, normalized_rows: Sequence[Dict[str, Any]], matched_rows: Sequence[Dict[str, Any]]) -> None:
        raw_json = self.paths.output / "quotation_history_normalized.json"
        raw_json.write_text(json.dumps(list(normalized_rows), indent=2, ensure_ascii=False), encoding="utf-8")
        csv_path = self.paths.output / "quotation_history_matches.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(HISTORY_FIELDS) + ["matched_by", "retrieved_at"])
            writer.writeheader()
            for row in matched_rows:
                writer.writerow({field: row.get(field, "") for field in writer.fieldnames})

    def _fill_first(self, page: Any, selectors: Iterable[str], value: str) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if locator.count() and locator.first.is_visible():
                    locator.first.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _click_first(self, page: Any, selectors: Iterable[str]) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if locator.count() and locator.first.is_visible():
                    locator.first.click()
                    return True
            except Exception:
                continue
        return False

    def _log(self, event: str, payload: Dict[str, Any]) -> None:
        redacted = {key: value for key, value in payload.items() if "password" not in key.casefold()}
        redacted["event"] = event
        redacted["timestamp"] = now_iso()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redacted, ensure_ascii=False) + "\n")

    def _safe(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", value)[:80] or "blank"
