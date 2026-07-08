from __future__ import annotations

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
FALLBACK = ROOT / "404.html"
SNAPSHOT = ROOT / "data" / "sanctions_snapshot.json"
EVIDENCE_MANIFEST = ROOT / "data" / "evidence_manifest.json"


class Parser(HTMLParser):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def extract_script(html: str) -> str:
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    check(match is not None, "index.html must contain an inline script")
    return match.group(1)


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    fallback = FALLBACK.read_text(encoding="utf-8")
    Parser().feed(html)
    Parser().feed(fallback)

    check("Marine UW Sanctions Evidence Workbench" in html, "workbench title missing")
    check("assetUrl(\"data/sanctions_snapshot.json\")" in html, "sanctions data must use project-path-aware assetUrl")
    check("assetUrl(\"data/evidence_manifest.json\")" in html, "evidence manifest must use project-path-aware assetUrl")
    check("run_uw_web_evidence.py" in html, "site must reference the automated evidence runner")
    check("/Underwriting/" in html, "GitHub Pages project path marker missing")
    check("window.location.replace" in fallback, "404 fallback must redirect to the workbench")
    check("/Underwriting/" in fallback, "404 fallback must preserve the GitHub Pages project path")

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    check(isinstance(snapshot.get("records"), list), "sanctions snapshot records must be a list")
    check(len(snapshot["records"]) > 0, "sanctions snapshot must contain records")
    evidence_manifest = json.loads(EVIDENCE_MANIFEST.read_text(encoding="utf-8"))
    check(isinstance(evidence_manifest.get("screenshots"), list), "evidence manifest screenshots must be a list")
    check(isinstance(evidence_manifest.get("source_results"), list), "evidence manifest source_results must be a list")

    script_path = Path("/tmp/underwriting-index-inline.js")
    script_path.write_text(extract_script(html), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(script_path)], text=True, capture_output=True)
    check(result.returncode == 0, result.stderr or result.stdout or "node --check failed")

    print("static site verification passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"static site verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
