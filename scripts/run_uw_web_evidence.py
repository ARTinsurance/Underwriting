from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "evidence_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "site-evidence" / "traverse-singapore"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return clean[:90] or "blank"


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def site_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def has_manual_challenge(text: str) -> Optional[str]:
    folded = text.casefold()
    for token in ("captcha", "multi-factor", "verification code", "verify you are human", "access denied"):
        if token in folded:
            return token
    return None


@dataclass
class SearchTerm:
    key: str
    label: str
    value: str


@dataclass
class SourceDef:
    key: str
    name: str
    url: str
    mode: str


SOURCES = [
    SourceDef("ofac", "OFAC Sanctions Search", "https://sanctionssearch.ofac.treas.gov/", "search"),
    SourceDef("uk_reg", "UK Sanctions List Search", "https://search-uk-sanctions-list.service.gov.uk/", "search"),
    SourceDef(
        "eu_tracker",
        "EU Sanctions Tracker",
        "https://data.europa.eu/apps/eusanctionstracker/entities/%20",
        "search",
    ),
    SourceDef(
        "eu_vessel_designations",
        "EU Vessel Designations - DMA",
        "https://www.dma.dk/growth-and-framework-conditions/maritime-sanctions/sanctions-against-russia-and-belarus/eu-vessel-designations",
        "find",
    ),
]


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Equasis, HiFleet, and sanctions evidence screenshots for the UW workbench.")
    parser.add_argument("--quotation-ref", default="ART-2026070209-MW")
    parser.add_argument("--imo", default="9342865")
    parser.add_argument("--vessel-name", default="MV TRAVERSE SINGAPORE")
    parser.add_argument("--commercial-manager", default="GOLDENKING SHIP MANAGEMENT (GUANGZHOU) CO., LTD")
    parser.add_argument("--registered-owner", default="Traverse Shipping Co., Ltd")
    parser.add_argument("--listed-area", default="Gulf of Aden/Red Sea/Indian Ocean")
    parser.add_argument("--flag", default="Panama")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--headless", default="true")
    parser.add_argument("--slow-mo-ms", type=int, default=0)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--sources", default="equasis,hifleet,sanctions", help="Comma-separated: equasis,hifleet,sanctions")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    headless = str(args.headless).casefold() in {"1", "true", "yes", "y"}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_initial_manifest(args)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        write_manifest(args.manifest, manifest, error=f"Playwright unavailable: {exc}")
        print("Playwright is not installed. Run: pip install -r requirements-vm.txt && python -m playwright install chromium", file=sys.stderr)
        return 2

    selected_sources = {item.strip().casefold() for item in args.sources.split(",") if item.strip()}
    with sync_playwright() as playwright:
        if "equasis" in selected_sources:
            run_in_fresh_browser(playwright, args, headless, lambda context: capture_research_source(context, args, manifest, "equasis"))
        if "hifleet" in selected_sources:
            run_in_fresh_browser(playwright, args, headless, lambda context: capture_research_source(context, args, manifest, "hifleet"))
        if "sanctions" in selected_sources:
            for source in SOURCES:
                terms = eu_tracker_terms_from_manifest(manifest, args) if source.key == "eu_tracker" else search_terms_from_manifest(manifest, args)
                for term in terms:
                    run_in_fresh_browser(
                        playwright,
                        args,
                        headless,
                        lambda context, source=source, term=term: capture_sanctions_source(context, args, manifest, source, term, PlaywrightTimeoutError),
                    )

    summarize(manifest)
    write_manifest(args.manifest, manifest)
    print(f"Wrote {args.manifest}")
    return 0


def run_in_fresh_browser(playwright: Any, args: argparse.Namespace, headless: bool, callback: Any) -> None:
    browser = None
    context = None
    try:
        browser = playwright.chromium.launch(headless=headless, slow_mo=args.slow_mo_ms)
        context = browser.new_context(viewport={"width": 1440, "height": 950}, ignore_https_errors=True)
        callback(context)
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass


def build_initial_manifest(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "review": {
            "quotationRef": args.quotation_ref,
            "listedArea": args.listed_area,
            "flag": args.flag,
            "vesselName": args.vessel_name,
            "imo": args.imo,
            "commercialManager": args.commercial_manager,
            "registeredOwner": args.registered_owner,
        },
        "summary": {
            "total_screenshots": 0,
            "completed_sources": 0,
            "manual_review_required": 0,
        },
        "screenshots": [],
        "fleet": {
            "manager": [],
            "owner": [],
        },
        "equasis": {
            "management_identified": False,
            "details": {},
            "missing_fields": [],
            "error": "",
        },
        "source_results": [],
    }


def search_terms(args: argparse.Namespace) -> List[SearchTerm]:
    terms = [
        SearchTerm("imo", "IMO", args.imo),
        SearchTerm("vessel", "Ship name", args.vessel_name),
        SearchTerm("manager", "Commercial manager", args.commercial_manager),
        SearchTerm("owner", "Registered owner", args.registered_owner),
    ]
    return [term for term in terms if term.value]


def search_terms_from_manifest(manifest: Dict[str, Any], args: argparse.Namespace) -> List[SearchTerm]:
    review = manifest.get("review") or {}
    terms = [
        SearchTerm("imo", "IMO", str(review.get("imo") or args.imo or "")),
        SearchTerm("vessel", "Ship name", str(review.get("vesselName") or args.vessel_name or "")),
        SearchTerm("manager", "Commercial manager", str(review.get("commercialManager") or args.commercial_manager or "")),
        SearchTerm("owner", "Registered owner", str(review.get("registeredOwner") or args.registered_owner or "")),
    ]
    return [term for term in terms if term.value]


def eu_tracker_terms_from_manifest(manifest: Dict[str, Any], args: argparse.Namespace) -> List[SearchTerm]:
    """Build EU Tracker searches from all useful Equasis vessel/management fields."""
    terms = search_terms_from_manifest(manifest, args)
    details = ((manifest.get("equasis") or {}).get("details") or {})
    for key, label, field in (
        ("imo", "IMO", "imo"),
        ("vessel", "Ship name", "vesselName"),
        ("manager", "Commercial manager", "commercialManager"),
        ("manager_address", "Commercial manager address", "managerAddress"),
        ("owner", "Registered owner", "registeredOwner"),
        ("owner_address", "Registered owner address", "ownerAddress"),
    ):
        value = str(details.get(field) or "").strip()
        if value:
            terms.append(SearchTerm(key, label, value))

    for fleet_group in ("manager", "owner"):
        rows = ((manifest.get("fleet") or {}).get(fleet_group) or [])
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or fleet_group).strip()
            company = str(row.get("company") or "").strip()
            company_imo = str(row.get("company_imo") or "").strip()
            address = str(row.get("address") or "").strip()
            if company:
                terms.append(SearchTerm(f"equasis_{fleet_group}_{index}", f"Equasis {role}", company))
            if company_imo:
                terms.append(SearchTerm(f"equasis_{fleet_group}_imo_{index}", f"Equasis {role} company IMO", company_imo))
            if address:
                terms.append(SearchTerm(f"equasis_{fleet_group}_address_{index}", f"Equasis {role} address", address))

    unique: List[SearchTerm] = []
    seen = set()
    for term in terms:
        normalized = normalize(term.value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(term)
    return unique


def capture_research_source(context: Any, args: argparse.Namespace, manifest: Dict[str, Any], source_key: str) -> None:
    if source_key == "equasis":
        source = {
            "key": "equasis",
            "name": "Equasis",
            "url": os.getenv("EQUASIS_URL", "https://www.equasis.org/EquasisWeb/public/HomePage"),
            "username": os.getenv("EQUASIS_USERNAME", ""),
            "password": os.getenv("EQUASIS_PASSWORD", ""),
        }
    else:
        source = {
            "key": "hifleet",
            "name": "HiFleet",
            "url": os.getenv("HIFLEET_URL", "https://hifleet.com/"),
            "username": os.getenv("HIFLEET_USERNAME", ""),
            "password": os.getenv("HIFLEET_PASSWORD", ""),
        }

    result = {
        "source_key": source["key"],
        "source_name": source["name"],
        "term_key": "imo",
        "term_label": "IMO",
        "term_value": args.imo,
        "status": "started",
        "url": source["url"],
        "captured_at": now_iso(),
        "screenshot": "",
        "raw_text_file": "",
        "manual_review_required": False,
        "error": "",
    }
    page = None
    try:
        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)
        page.goto(source["url"], wait_until="domcontentloaded")
        safe_wait(page, 1500)
        if source_key == "equasis":
            login_equasis(page, source["username"], source["password"])
        else:
            login_if_possible(page, source["username"], source["password"])
        safe_wait(page, 1500)
        if source_key == "equasis":
            search_equasis_imo(page, args.imo)
            expand_equasis_management_detail(page)
        else:
            search_hifleet_imo(page, args.imo)
        safe_wait(page, 3500)
        raw_text = body_text(page)
        challenge = has_manual_challenge(raw_text)
        if page:
            result["final_url"] = page.url
        if challenge:
            result["status"] = "manual_review_required"
            result["manual_review_required"] = True
            result["error"] = f"Manual challenge detected: {challenge}"
        elif source_key == "equasis" and not equasis_capture_has_ship_data(raw_text, args.imo):
            result["status"] = "manual_review_required"
            result["manual_review_required"] = True
            result["result_label"] = "Cannot identify Equasis management details"
            result["error"] = "Equasis rendered without accessible ship data after login/search/management-detail expansion."
        else:
            result["status"] = "captured"
            result["result_label"] = "Ship details captured" if source_key == "equasis" else "IMO search captured"
        if source_key == "equasis":
            merge_equasis_data(manifest, raw_text, args)
        save_result_files(page, args, manifest, result, source["key"], args.imo, raw_text)
    except Exception as exc:
        result["status"] = "failed"
        result["manual_review_required"] = True
        result["error"] = str(exc)
        if page:
            try:
                save_result_files(page, args, manifest, result, source["key"], args.imo, body_text(page))
            except Exception:
                pass
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
    manifest["source_results"].append(result)


def capture_sanctions_source(context: Any, args: argparse.Namespace, manifest: Dict[str, Any], source: SourceDef, term: SearchTerm, timeout_error: Any) -> None:
    result = {
        "source_key": source.key,
        "source_name": source.name,
        "term_key": term.key,
        "term_label": term.label,
        "term_value": term.value,
        "status": "started",
        "url": source.url,
        "captured_at": now_iso(),
        "screenshot": "",
        "raw_text_file": "",
        "manual_review_required": False,
        "error": "",
    }
    page = None
    try:
        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)
        page.goto(source.url, wait_until="domcontentloaded")
        safe_wait(page, 1200)
        accept_cookie_banner(page)
        if source.key == "ofac":
            search_ofac(page, term)
            safe_wait(page, 3500)
        elif source.key == "eu_tracker":
            search_eu_tracker(page, term)
            safe_wait(page, 3500)
        elif source.mode == "search":
            search_in_page(page, term.value)
            safe_wait(page, 3500)
        else:
            try:
                highlight_page_term(page, term.value)
            except Exception:
                pass
            safe_wait(page, 700)
        raw_text = body_text(page)
        challenge = has_manual_challenge(raw_text)
        if challenge:
            result["status"] = "manual_review_required"
            result["manual_review_required"] = True
            result["result_label"] = "Cannot complete source check"
            result["error"] = f"Manual challenge detected: {challenge}"
        elif source_requires_accessible_text(source.key) and len(normalize(raw_text)) < 20:
            result["status"] = "manual_review_required"
            result["manual_review_required"] = True
            result["result_label"] = "Cannot read source result"
            result["error"] = "The source page rendered without accessible text or visible result data."
        elif sanctions_match_found(source, term, raw_text):
            result["status"] = "match_found"
            result["match_found"] = True
            result["result_label"] = "Match returned"
        else:
            result["status"] = "no_match"
            result["match_found"] = False
            result["result_label"] = "No match returned"
        save_result_files(page, args, manifest, result, source.key, f"{term.key}-{term.value}", raw_text, full_page=source.mode != "find")
    except timeout_error as exc:
        result["status"] = "timeout"
        result["manual_review_required"] = True
        result["result_label"] = "Cannot complete source check"
        result["error"] = str(exc)
        if page:
            try:
                save_result_files(page, args, manifest, result, source.key, f"{term.key}-{term.value}", body_text(page), full_page=source.mode != "find")
            except Exception:
                pass
    except Exception as exc:
        result["status"] = "failed"
        result["manual_review_required"] = True
        result["result_label"] = "Cannot complete source check"
        result["error"] = str(exc)
        if page:
            try:
                save_result_files(page, args, manifest, result, source.key, f"{term.key}-{term.value}", body_text(page), full_page=source.mode != "find")
            except Exception:
                pass
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
    manifest["source_results"].append(result)


def safe_wait(page: Any, ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=min(max(ms, 1000), 5000))
    except Exception:
        time.sleep(ms / 1000)


def visible(locator: Any) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def fill_first_visible(page: Any, selectors: Iterable[str], value: str) -> bool:
    if not value:
        return False
    for selector in selectors:
        locator = page.locator(selector)
        if visible(locator):
            try:
                locator.first.fill(value)
                return True
            except Exception:
                continue
    return False


def click_first_visible(page: Any, selectors: Iterable[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        if visible(locator):
            try:
                locator.first.click()
                return True
            except Exception:
                continue
    return False


def login_if_possible(page: Any, username: str, password: str) -> None:
    if not username or not password:
        return
    filled_user = fill_first_visible(
        page,
        (
            'input[name="username"]',
            'input[name="user"]',
            'input[name="email"]',
            'input[type="email"]',
            '#username',
            '#userName',
            '#login',
            'input[placeholder*="mail" i]',
            'input[placeholder*="user" i]',
        ),
        username,
    )
    filled_password = fill_first_visible(
        page,
        (
            'input[name="password"]',
            'input[type="password"]',
            '#password',
            '#Password',
            'input[placeholder*="password" i]',
        ),
        password,
    )
    if filled_user or filled_password:
        click_first_visible(
            page,
            (
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'a:has-text("Login")',
                'a:has-text("Log in")',
            ),
        )


def login_equasis(page: Any, username: str, password: str) -> None:
    if not username or not password:
        return
    accept_cookie_banner(page)
    if fill_first_visible(page, ("#home-login",), username) and fill_first_visible(page, ("#home-password",), password):
        if not click_first_visible(page, ('form:has(#home-login) input[type="submit"]', 'form:has(#home-login) button[type="submit"]')):
            page.locator("#home-password").press("Enter")
        safe_wait(page, 3500)
        return
    click_first_visible(
        page,
        (
            'a:has-text("Login")',
            'a:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("Log in")',
            'input[value*="Login" i]',
        ),
    )
    safe_wait(page, 900)
    filled_user = fill_first_visible(
        page,
        (
            'input[name="j_email"]',
            'input[name="j_username"]',
            'input[name="username"]',
            'input[name="login"]',
            'input[name*="user" i]',
            'input[name*="email" i]',
            'input[type="email"]',
            '#j_username',
            '#username',
            '#login',
            'input[placeholder*="mail" i]',
            'input[placeholder*="user" i]',
        ),
        username,
    )
    filled_password = fill_first_visible(
        page,
        (
            'input[name="j_password"]',
            'input[name="password"]',
            'input[type="password"]',
            '#j_password',
            '#password',
            'input[placeholder*="password" i]',
        ),
        password,
    )
    if filled_user or filled_password:
        click_first_visible(
            page,
            (
                'button[type="submit"]',
                'input[type="submit"]',
                'input[name="submit"][value="Login"]',
                'button:has-text("Login")',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'input[value*="Login" i]',
                'input[value*="Sign in" i]',
            ),
        )
        safe_wait(page, 1600)
    click_first_visible(
        page,
        (
            'a:has-text("Go to My Equasis")',
            'button:has-text("Go to My Equasis")',
            'input[value*="Go to My Equasis" i]',
        ),
    )
    safe_wait(page, 1200)


def accept_cookie_banner(page: Any) -> None:
    for selector in (
        'button:has-text("No, I want to reject all cookies")',
        'button:has-text("Reject all cookies")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Yes, these cookies are OK")',
        'button:has-text("Close")',
    ):
        locator = page.locator(selector)
        if visible(locator):
            try:
                locator.first.click()
                safe_wait(page, 500)
                return
            except Exception:
                continue


def search_ofac(page: Any, term: SearchTerm) -> bool:
    if term.key == "imo":
        filled = fill_first_visible(page, ("#ctl00_MainContent_txtID", 'input[name="ctl00$MainContent$txtID"]'), term.value)
    else:
        filled = fill_first_visible(page, ("#ctl00_MainContent_txtLastName", 'input[name="ctl00$MainContent$txtLastName"]'), term.value)
    if not filled:
        return search_in_page(page, term.value)
    if click_first_visible(page, ("#ctl00_MainContent_btnSearch", 'input[name="ctl00$MainContent$btnSearch"]')):
        return True
    page.keyboard.press("Enter")
    return True


def search_equasis_imo(page: Any, imo: str) -> bool:
    try:
        page.locator("#checkbox-ship").set_checked(True)
    except Exception:
        pass
    try:
        page.locator("#checkbox-company").set_checked(False)
    except Exception:
        pass
    safe_wait(page, 600)
    selectors = (
        'input[name="P_IMO"]',
        'input[name="P_IMO_NUMBER"]',
        'input[name*="imo" i]',
        'input[id*="imo" i]',
        'input[placeholder*="IMO" i]',
        'input[name="search"]',
        'input[type="search"]',
        'input[type="text"]',
    )
    if not fill_first_visible(page, selectors, imo):
        return search_in_page(page, imo)
    submitted = click_first_visible(
        page,
        (
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Go")',
            'input[value*="Go" i]',
            'button:has-text("Search")',
            'input[value*="Search" i]',
            'a:has-text("Search")',
        ),
    )
    if not submitted:
        page.keyboard.press("Enter")
    safe_wait(page, 1800)
    click_first_visible(
        page,
        (
            f'a:has-text("{imo}")',
            f'text="{imo}"',
            'table a',
        ),
    )
    safe_wait(page, 1800)
    return True


def search_hifleet_imo(page: Any, imo: str) -> bool:
    """Type an IMO into HiFleet's visible search control and submit it."""
    selectors = (
        'input[placeholder*="IMO" i]',
        'input[placeholder*="ship" i]',
        'input[placeholder*="vessel" i]',
        'input[placeholder*="search" i]',
        'input[name*="imo" i]',
        'input[name*="search" i]',
        'input[id*="imo" i]',
        'input[id*="search" i]',
        'input[type="search"]',
        'input[type="text"]',
    )
    if not fill_first_visible(page, selectors, imo):
        raise RuntimeError("Could not find a visible HiFleet IMO search bar")
    if not click_first_visible(
        page,
        (
            'button:has-text("Search")',
            'button[aria-label*="search" i]',
            'button[type="submit"]',
            'input[type="submit"]',
        ),
    ):
        page.keyboard.press("Enter")
    return True


def expand_equasis_management_detail(page: Any) -> None:
    for selector in (
        'text=/Management detail/i',
        'text=/Management details/i',
        'text=/Management/i',
        'a:has-text("Management detail")',
        'button:has-text("Management detail")',
        '[aria-label*="Management" i]',
    ):
        locator = page.locator(selector)
        if not visible(locator):
            continue
        try:
            locator.first.click()
            safe_wait(page, 1200)
            break
        except Exception:
            continue
    for selector in (
        'text=/Registered owner/i',
        'text=/Commercial manager/i',
        'text=/Ship manager/i',
    ):
        try:
            page.locator(selector).first.scroll_into_view_if_needed(timeout=1500)
            break
        except Exception:
            continue


def search_eu_tracker(page: Any, term: SearchTerm) -> bool:
    """Type one Equasis-derived value into the EU Tracker search bar."""
    selectors = (
        'input[type="search"]',
        'input[placeholder*="search" i]',
        'input[placeholder*="entity" i]',
        'input[name*="search" i]',
        'input[name*="query" i]',
        'input[id*="search" i]',
        'input[id*="query" i]',
        'input[type="text"]',
    )
    if not fill_first_visible(page, selectors, term.value):
        raise RuntimeError("Could not find a visible EU Sanctions Tracker search bar")
    if not click_first_visible(
        page,
        (
            'button:has-text("Search")',
            'button[aria-label*="search" i]',
            'button[type="submit"]',
            'input[type="submit"]',
        ),
    ):
        page.keyboard.press("Enter")
    return True


def source_requires_accessible_text(source_key: str) -> bool:
    return source_key in {"equasis", "eu_tracker", "eu_vessel_designations", "uk_reg", "ofac"}


def sanctions_match_found(source: SourceDef, term: SearchTerm, raw_text: str) -> bool:
    normalized_text = normalize(raw_text)
    normalized_term = normalize(term.value)
    if not normalized_text or not normalized_term:
        return False
    if source.key == "ofac":
        no_result_markers = (
            "no results",
            "returned no results",
            "no records found",
            "your search did not return",
        )
        if any(marker in normalized_text for marker in no_result_markers):
            return False
        result_markers = ("search results", "program", "list", "score", "name")
        return normalized_term in normalized_text and any(marker in normalized_text for marker in result_markers)
    if source.key == "eu_tracker":
        no_result_markers = ("no results", "no entities", "not found")
        if any(marker in normalized_text for marker in no_result_markers):
            return False
        return normalized_term in normalized_text and any(marker in normalized_text for marker in ("entity", "designation", "programme", "regulation"))
    if source.key == "eu_vessel_designations":
        return normalized_term in normalized_text
    if source.key == "uk_reg":
        return normalized_term in normalized_text
    return normalized_term in normalized_text


def search_in_page(page: Any, term: str) -> bool:
    selectors = (
        'input[type="search"]',
        'input[name*="search" i]',
        'input[name*="keyword" i]',
        'input[name*="imo" i]',
        'input[id*="search" i]',
        'input[id*="keyword" i]',
        'input[id*="imo" i]',
        'input[placeholder*="search" i]',
        'input[placeholder*="imo" i]',
        'input[type="text"]',
        'textarea',
    )
    if fill_first_visible(page, selectors, term):
        page.keyboard.press("Enter")
        return True
    highlight_page_term(page, term)
    return False


def highlight_page_term(page: Any, term: str) -> None:
    page.evaluate(
        """
        (term) => {
          const old = document.querySelectorAll('[data-uw-highlight="1"]');
          old.forEach((node) => {
            const parent = node.parentNode;
            if (!parent) return;
            parent.replaceChild(document.createTextNode(node.textContent), node);
            parent.normalize();
          });
          if (!term) return;
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const nodes = [];
          while (walker.nextNode()) nodes.push(walker.currentNode);
          const lower = term.toLowerCase();
          let first = null;
          nodes.forEach((textNode) => {
            const text = textNode.nodeValue || '';
            const index = text.toLowerCase().indexOf(lower);
            if (index === -1) return;
            const range = document.createRange();
            range.setStart(textNode, index);
            range.setEnd(textNode, index + term.length);
            const mark = document.createElement('mark');
            mark.dataset.uwHighlight = '1';
            mark.style.background = '#ffe066';
            mark.style.color = '#111827';
            mark.style.padding = '0 2px';
            range.surroundContents(mark);
            if (!first) first = mark;
          });
          if (first) first.scrollIntoView({block: 'center', inline: 'nearest'});
        }
        """,
        term,
    )


def body_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""


def save_result_files(page: Any, args: argparse.Namespace, manifest: Dict[str, Any], result: Dict[str, Any], source_key: str, term: str, raw_text: str, full_page: bool = True) -> None:
    base = f"{source_key}-{slug(term)}"
    screenshot = args.output_dir / f"{base}.png"
    raw = args.output_dir / f"{base}.txt"
    html = args.output_dir / f"{base}.html"
    try:
        page.screenshot(path=str(screenshot), full_page=full_page, timeout=15000)
    except Exception:
        page.screenshot(path=str(screenshot), full_page=False, timeout=15000)
    raw.write_text(raw_text[:20000], encoding="utf-8")
    if source_key == "equasis":
        try:
            html.write_text(page.content()[:200000], encoding="utf-8")
            result["html_file"] = site_path(html)
        except Exception:
            pass
    result["screenshot"] = site_path(screenshot)
    result["raw_text_file"] = site_path(raw)
    result["captured_at"] = now_iso()
    manifest["screenshots"].append(
        {
            "id": base,
            "source_key": result["source_key"],
            "source_name": result["source_name"],
            "term_key": result["term_key"],
            "term_label": result["term_label"],
            "term_value": result["term_value"],
            "status": result["status"],
            "result_label": result.get("result_label", ""),
            "match_found": bool(result.get("match_found", False)),
            "captured_at": result["captured_at"],
            "image": result["screenshot"],
            "raw_text_file": result["raw_text_file"],
            "manual_review_required": result["manual_review_required"],
            "error": result["error"],
        }
    )


def merge_equasis_data(manifest: Dict[str, Any], raw_text: str, args: argparse.Namespace) -> None:
    details = extract_equasis_details(raw_text)
    missing_fields = [field for field in ("registeredOwner", "commercialManager") if not details.get(field)]
    manifest["equasis"] = {
        "management_identified": not missing_fields,
        "details": details,
        "missing_fields": missing_fields,
        "error": "" if not missing_fields else f"Could not identify: {', '.join(missing_fields)}",
    }
    review = manifest.setdefault("review", {})
    if details.get("vesselName"):
        review["vesselName"] = details["vesselName"]
    if details.get("imo"):
        review["imo"] = details["imo"]
    if details.get("flag"):
        review["flag"] = details["flag"]
    if details.get("registeredOwner"):
        review["registeredOwner"] = details["registeredOwner"]
    if details.get("commercialManager"):
        review["commercialManager"] = details["commercialManager"]
    if details.get("ownerAddress"):
        review["ownerAddress"] = details["ownerAddress"]
    management_rows = extract_equasis_management_rows(raw_text, details, args)
    if management_rows:
        manifest["fleet"]["manager"] = [row for row in management_rows if "manager" in row.get("role", "").casefold()]
        manifest["fleet"]["owner"] = [row for row in management_rows if "owner" in row.get("role", "").casefold()]


def equasis_capture_has_ship_data(raw_text: str, imo: str) -> bool:
    if imo and imo in raw_text:
        return True
    details = extract_equasis_details(raw_text)
    return any(details.get(key) for key in ("vesselName", "registeredOwner", "commercialManager"))


def extract_equasis_details(raw_text: str) -> Dict[str, str]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    text = "\n".join(" ".join(line.split()) for line in lines)
    details: Dict[str, str] = {}
    header_match = re.search(r"([A-Z0-9][A-Z0-9 .'\-&/]{2,})\s+-\s+IMO\s*n[°o]\s*(\d{7})", text, re.IGNORECASE)
    if header_match:
        details["vesselName"] = clean_equasis_value(header_match.group(1))
        details["imo"] = header_match.group(2)
    flag_index = next((index for index, line in enumerate(lines) if line.casefold() == "flag"), -1)
    if flag_index != -1:
        for candidate in lines[flag_index + 1 : flag_index + 4]:
            flag_match = re.search(r"\(([A-Za-z .'-]+)\)", candidate)
            if flag_match:
                details["flag"] = clean_equasis_value(flag_match.group(1))
                break
    for row in extract_management_table_lines(raw_text):
        cells = split_management_row(row)
        if len(cells) < 5:
            continue
        role = cells[1].casefold()
        if "commercial manager" in role or "ship manager" in role:
            details["commercialManager"] = clean_equasis_value(cells[2])
            details.setdefault("managerAddress", clean_equasis_value(cells[3]))
        if "registered owner" in role:
            details["registeredOwner"] = clean_equasis_value(cells[2])
            details["ownerAddress"] = clean_equasis_value(cells[3])
    return details


def clean_equasis_value(value: str) -> str:
    return " ".join(value.strip(" :-").split())[:180]


def extract_management_table_lines(raw_text: str) -> List[str]:
    return [line for line in raw_text.splitlines() if re.match(r"^\s*\d{7}\s+", line)]


def split_management_row(row: str) -> List[str]:
    if "\t" in row:
        return [cell.strip() for cell in row.split("\t") if cell.strip()]
    return [cell.strip() for cell in re.split(r"\s{2,}", row) if cell.strip()]


def extract_equasis_management_rows(raw_text: str, details: Dict[str, str], args: argparse.Namespace) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    vessel = details.get("vesselName") or args.vessel_name or args.imo
    for line in extract_management_table_lines(raw_text):
        cells = split_management_row(line)
        if len(cells) < 5:
            continue
        company_imo, role, company, address, effect = cells[:5]
        rows.append(
            {
                "ship": f"({args.imo}) {vessel}",
                "gross_tonnage": "",
                "type": "Management detail",
                "flag": details.get("flag", args.flag),
                "role": role,
                "company_imo": company_imo,
                "company": company,
                "address": address,
                "date_of_effect": effect,
                "acting_as": f"{role}: {company}; {address}; {effect}",
            }
        )
    return rows


def prioritize_fleet_rows(rows: List[Dict[str, str]], imo: str) -> List[Dict[str, str]]:
    if not imo:
        return rows
    return sorted(rows, key=lambda row: (imo not in row.get("ship", ""), row.get("ship", "")))


def summarize(manifest: Dict[str, Any]) -> None:
    source_results = manifest["source_results"]
    manifest["summary"] = {
        "total_screenshots": len(manifest["screenshots"]),
        "completed_sources": sum(1 for item in source_results if item.get("status") not in {"started", "failed", "timeout"}),
        "matches_found": sum(1 for item in source_results if item.get("match_found")),
        "manual_review_required": sum(1 for item in source_results if item.get("manual_review_required")),
    }
    manifest["generated_at"] = now_iso()


def write_manifest(path: Path, manifest: Dict[str, Any], error: str = "") -> None:
    if error:
        manifest.setdefault("source_results", []).append(
            {
                "source_key": "runner",
                "source_name": "Evidence runner",
                "status": "failed",
                "manual_review_required": True,
                "error": error,
                "captured_at": now_iso(),
            }
        )
    summarize(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
