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
    SourceDef("uk_reg", "UK Russia Regulations 2019/855", "https://www.legislation.gov.uk/uksi/2019/855", "find"),
    SourceDef("eu_reg", "EU Regulation 833/2014", "https://eur-lex.europa.eu/eli/reg/2014/833/oj/eng", "find"),
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

    with sync_playwright() as playwright:
        run_in_fresh_browser(playwright, args, headless, lambda context: capture_research_source(context, args, manifest, "equasis"))
        run_in_fresh_browser(playwright, args, headless, lambda context: capture_research_source(context, args, manifest, "hifleet"))
        for source in SOURCES:
            for term in search_terms(args):
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
        "source_results": [],
    }


def search_terms(args: argparse.Namespace) -> List[SearchTerm]:
    return [
        SearchTerm("imo", "IMO", args.imo),
        SearchTerm("vessel", "Ship name", args.vessel_name),
        SearchTerm("manager", "Commercial manager", args.commercial_manager),
        SearchTerm("owner", "Registered owner", args.registered_owner),
    ]


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
        login_if_possible(page, source["username"], source["password"])
        safe_wait(page, 1500)
        search_in_page(page, args.imo)
        safe_wait(page, 3500)
        raw_text = body_text(page)
        challenge = has_manual_challenge(raw_text)
        if challenge:
            result["status"] = "manual_review_required"
            result["manual_review_required"] = True
            result["error"] = f"Manual challenge detected: {challenge}"
        else:
            result["status"] = "captured"
        if source_key == "equasis":
            merge_equasis_data(manifest, raw_text)
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
            result["error"] = f"Manual challenge detected: {challenge}"
        elif normalize(term.value) in normalize(raw_text):
            result["status"] = "visible_result_or_page_match"
        else:
            result["status"] = "captured_no_visible_match"
        save_result_files(page, args, manifest, result, source.key, f"{term.key}-{term.value}", raw_text, full_page=source.mode != "find")
    except timeout_error as exc:
        result["status"] = "timeout"
        result["manual_review_required"] = True
        result["error"] = str(exc)
        if page:
            try:
                save_result_files(page, args, manifest, result, source.key, f"{term.key}-{term.value}", body_text(page), full_page=source.mode != "find")
            except Exception:
                pass
    except Exception as exc:
        result["status"] = "failed"
        result["manual_review_required"] = True
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
    try:
        page.screenshot(path=str(screenshot), full_page=full_page, timeout=15000)
    except Exception:
        page.screenshot(path=str(screenshot), full_page=False, timeout=15000)
    raw.write_text(raw_text[:20000], encoding="utf-8")
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
            "captured_at": result["captured_at"],
            "image": result["screenshot"],
            "raw_text_file": result["raw_text_file"],
            "manual_review_required": result["manual_review_required"],
            "error": result["error"],
        }
    )


def merge_equasis_data(manifest: Dict[str, Any], raw_text: str) -> None:
    rows = extract_fleet_rows(raw_text)
    if rows:
        manifest["fleet"]["manager"] = rows
        manifest["fleet"]["owner"] = rows


def extract_fleet_rows(raw_text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in raw_text.splitlines():
        text = " ".join(line.split())
        match = re.search(r"\(?\s*(\d{7})\s*\)?\s+([A-Z0-9][A-Z0-9 .'-]{2,})", text)
        if not match:
            continue
        if len(rows) >= 80:
            break
        rows.append(
            {
                "ship": f"({match.group(1)}) {match.group(2).strip()}",
                "gross_tonnage": "",
                "type": "",
                "flag": "",
                "acting_as": text[:240],
            }
        )
    return rows


def summarize(manifest: Dict[str, Any]) -> None:
    source_results = manifest["source_results"]
    manifest["summary"] = {
        "total_screenshots": len(manifest["screenshots"]),
        "completed_sources": sum(1 for item in source_results if item.get("status") not in {"started", "failed", "timeout"}),
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
