# Marine Underwriting Sanctions Workbench

This repository contains a static/browser-based evidence workbench, a small persistent web service, sanctions-data refresh automation, an offline quotation-slip reviewer, and a VM-oriented browser workflow for marine war underwriting.

The components share the checked-in sanctions snapshot in `data/sanctions_snapshot.json`, but they do not all perform the same job. Read the workflow map and limitations below before using an output as underwriting or compliance evidence.

## Workflow map

| Component | Entry point | What it actually does | Primary output |
|---|---|---|---|
| Browser workbench | `index.html` | Builds source-search tasks for vessel/party terms, displays local snapshot hits and published evidence, captures or uploads screenshots, records a reviewer decision, and exports JSON/CSV | Browser state, screenshots, `marine-uw-review.json`, `marine-uw-source-results.csv` |
| Persistent web app | `web_app.py` | Serves the workbench and selected static assets, and stores browser review state in SQLite | `/data/underwriting.sqlite3` by default in containers |
| Sanctions data refresh | `scripts/update_sanctions_data.py` | Downloads and parses OFAC, UK, and EU source files into one local JSON snapshot; also re-screens entries in `data/vessels.json` | `data/raw/*`, `data/sanctions_snapshot.json`, updated `data/vessels.json` |
| Static evidence capture | `scripts/run_uw_web_evidence.py` | Uses Playwright to visit Equasis, HiFleet, and selected sanctions pages, save screenshots/text, and build the manifest displayed by the workbench | `data/evidence_manifest.json`, `site-evidence/<review>/*` |
| Offline quotation review | `underwriting_review.py` | Extracts parties from a JSON slip, fuzzy-matches them against the local snapshot, finds same-vessel quotes in the prior three calendar months, and summarizes listed areas and offered terms | Markdown and optional JSON report |
| VM browser agent | `python -m marine_uw_agent.run` | Retrieves or parses a quotation, attempts quotation history/Equasis/HiFleet research, runs local sanctions matching and cargo/listed-area checks, and populates a review workbook | JSON, Markdown, evidence folders, and `.xlsx` |
| Legacy audit-log runner | `sanctions_checker_improved.py` | Reads entity names and writes an audit CSV containing placeholder `NO_MATCH` values | `results/audit_log_*.csv` |
| Excel macro | `SanctionsCheck_VBA.bas` | Separate legacy VBA implementation; see the older deployment guides for its setup | Excel-managed results |

## Important limitations

- A local name hit is a candidate for human review, not a legal conclusion. False positives and false negatives are possible.
- `underwriting_review.py` and `marine_uw_agent` search the checked-in snapshot; they do not make live API calls to sanctions authorities during matching.
- The workbench's “Returned Sanctions Matches” are client-side normalized substring matches against the snapshot. Official-source screenshots and reviewer judgment remain separate evidence.
- `sanctions_checker_improved.py` does **not** currently query OFAC, UK, or EU data. Its loop explicitly simulates screening and records `NO_MATCH`; do not use those rows as proof of a completed sanctions search.
- The evidence runner operates third-party websites through browser selectors. CAPTCHA, MFA, access denial, timeouts, and page changes can require manual intervention. The code records such states instead of bypassing challenges.
- The web API has no authentication or authorization. Browser-generated review IDs separate records but are not access control. Put production deployments behind organizational SSO or an authenticated reverse proxy.
- No component implements a records-retention policy, automatic escalation, or compliance approval. Those are operational controls outside this repository.
- Review outputs support, but do not replace, an underwriter's or compliance officer's decision.

## 1. Browser sanctions evidence workbench

`index.html` is the main user-facing workbench. It accepts:

- quotation reference and listed area;
- ETA and flag;
- vessel name and IMO;
- commercial manager and registered owner;
- owner/manager address;
- reviewer, decision (`Pending`, `Clear`, `Review`, or `Match`), and notes.

For the populated IMO, vessel, manager, and owner terms, it creates tasks for:

- OFAC Sanctions Search;
- UK Sanctions List Search;
- EU Sanctions Tracker;
- EU vessel designations published by the Danish Maritime Authority;
- Equasis vessel/ownership/fleet research; and
- HiFleet position and port-history research.

The workbench loads `data/sanctions_snapshot.json` and `data/evidence_manifest.json`, displays local candidate hits and published automated evidence, and lets the reviewer open official sources, copy terms, capture a screen/window, or upload an image. Manual images are stored as data URLs with the review state. JSON export includes review data, evidence metadata/images, automated source results, the manifest, and returned local matches. CSV export gives one row per source/search-term pair with its result label and screenshot count.

### Static local run

Serve the repository over HTTP; opening `index.html` directly as a `file://` URL will prevent normal asset fetching.

```bash
python3 -m http.server 4173
```

Open `http://127.0.0.1:4173/index.html`.

In static mode, editable state is saved under `marineUwWorkbench` in browser `localStorage`; a generated `marineUwReviewId` identifies the browser's record if the API later becomes available. Clearing site data removes that local copy.

### Persistent local run

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-web.txt
APP_DATA_DIR=./runtime-data uvicorn web_app:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. FastAPI serves only the workbench, the sanctions snapshot, the evidence manifest, and files under `site-evidence/` and `screenshots/`; it does not mount the repository root.

The API is:

| Method and path | Behavior |
|---|---|
| `GET /api/health` | Opens/initializes SQLite and returns storage health |
| `GET /api/reviews/{review_id}` | Returns saved state and timestamps, or 404 |
| `PUT /api/reviews/{review_id}` | Creates or replaces a review state |
| `DELETE /api/reviews/{review_id}` | Deletes that review and returns 204 |

Review IDs may contain only letters, digits, hyphens, and underscores and are limited to 80 characters. A state must contain a `review` object and an `evidence` array. `MAX_STATE_BYTES` defaults to 25 MiB for the combined JSON payload, including embedded screenshots.

Relevant environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `APP_DATA_DIR` | `./runtime-data` | Directory used for application data |
| `DATABASE_PATH` | `$APP_DATA_DIR/underwriting.sqlite3` | Optional explicit SQLite path |
| `MAX_STATE_BYTES` | `26214400` | Maximum encoded review-state size |
| `PORT` | `8000` in the container command | Listening port for the Docker image |

### Docker and Render

```bash
docker compose up --build
```

`compose.yaml` maps port 8000 and mounts the named `underwriting-data` volume at `/data`. The container runs as UID 10001.

`render.yaml` defines a Docker web service, a 1 GiB persistent disk at `/data`, and `/api/health` as its health check. Persistent storage preserves SQLite across container replacement; it does not add user authentication.

## 2. Refreshing sanctions data

Run:

```bash
python3 scripts/update_sanctions_data.py
```

The script downloads these configured sources:

| Snapshot key | Dataset |
|---|---|
| `ofac_sdn` | OFAC SDN XML |
| `ofac_consolidated` | OFAC Consolidated non-SDN XML |
| `uk` | UK Sanctions List CSV |
| `eu` | EU consolidated financial sanctions XML, with an OpenSanctions-hosted source-file fallback |

For each source it records status, resolved URL, record count, SHA-256, byte size, selected response headers, duration, and any error. It writes all successfully parsed records to `data/sanctions_snapshot.json`. A run succeeds when at least one record exists, even if another source failed, so always inspect the per-source statuses before treating the snapshot as complete.

If `data/vessels.json` exists, the script also checks each vessel name and configured owner/manager/company fields using normalized exact or containment matching and writes source-grouped results back to that file.

The GitHub Actions workflow `.github/workflows/update-sanctions-data.yml` runs at minute 23 every six hours and on manual dispatch. It commits changes matching `data/sanctions_snapshot.json` and `data/raw/*`. The workflow's commit pattern does not currently include the enriched `data/vessels.json`.

## 3. Capturing website evidence

Install browser dependencies and create a local secret file:

```bash
cp .env.example .env
python3 -m pip install -r requirements-vm.txt
python3 -m playwright install chromium
```

Fill the required credentials in `.env`; it is ignored by Git. Then run, preferably headful when login or human confirmation may be needed:

```bash
python3 scripts/run_uw_web_evidence.py \
  --quotation-ref "ART-2026070209-MW" \
  --imo "9342865" \
  --vessel-name "MV TRAVERSE SINGAPORE" \
  --commercial-manager "GOLDENKING SHIP MANAGEMENT (GUANGZHOU) CO., LTD" \
  --registered-owner "Traverse Shipping Co., Ltd" \
  --headless false
```

Useful options include `--listed-area`, `--flag`, `--manifest`, `--output-dir`, `--timeout-ms`, `--slow-mo-ms`, and `--sources equasis,hifleet,sanctions`. Defaults currently describe the Traverse Singapore sample, including `data/evidence_manifest.json` and `site-evidence/traverse-singapore/`; override them for another review to avoid replacing or mixing sample evidence.

The runner launches fresh Chromium contexts, detects common CAPTCHA/MFA/access-denied states, records source-level status, and writes screenshots plus extracted text/HTML where available. Equasis runs first; the EU Tracker then receives separate search-bar submissions for the extracted IMO, vessel name, registered owner, commercial manager, their addresses, every additional Equasis management company, and each company's IMO and address. HiFleet receives the vessel IMO through its visible search bar before its result screenshot is taken. Review the generated manifest before publishing it because screenshots and extracted pages may contain commercial or personal information.

Validate the static deliverable with:

```bash
python3 scripts/verify_static_site.py
```

This parses `index.html` and `404.html`, checks required project-path references and non-empty snapshot/manifest structures, and runs `node --check` on the inline JavaScript. Node.js is therefore required for this verification command.

## 4. Offline quotation-slip review

`underwriting_review.py` uses only the Python standard library and local files. Its input is a JSON object with permissive party fields. A representative input is:

```json
{
  "quotation_date": "2026-06-17",
  "vessel": {
    "name": "DUBAI TOWER",
    "imo": "9433066",
    "registered_owner": "Transfar Shipping Pte Ltd",
    "manager": "Bernhard Schulte"
  },
  "parties": [
    {"role": "assured", "name": "Example Assured Ltd"},
    {"role": "broker", "name": "Example Broker Ltd"}
  ],
  "trading_limits": "Worldwide excluding sanctioned trades. Black Sea calls require prior agreement.",
  "listed_areas": ["Black Sea"],
  "coverage": "marine war risks",
  "limit": "USD 10,000,000",
  "premium": "USD 25,000",
  "conditions": ["Subject to sanctions clause", "Subject to no known loss"]
}
```

Run:

```bash
python3 underwriting_review.py quote_slip.json \
  --history data/quotation_history.json \
  --output results/underwriting_review.md \
  --json-output results/underwriting_review.json
```

Options:

- `--history` accepts JSON (a list or an object containing a list) or CSV.
- `--snapshot` selects a different snapshot; default is `data/sanctions_snapshot.json`.
- `--as-of YYYY-MM-DD` overrides the slip/review date.
- `--threshold` sets the 0–1 fuzzy-name threshold; default is `0.94`.
- Without `--output`, the Markdown report is printed to stdout.

The reviewer extracts named parties from the `parties` array, common top-level roles, and vessel ownership/management fields. It normalizes names and legal suffixes, reports at most five matches per EU/UK/US group and party, and treats exact or subset-token names specially before applying `SequenceMatcher` similarity.

Quotation history is matched by IMO first or normalized vessel name, then restricted to the inclusive period from three calendar months before the review date through that date. The report also identifies explicit/inferred listed areas from configured keywords and summarizes coverage, limit, premium, deductible, period, conditions, and trading limits, flagging missing offering fields.

## 5. VM browser underwriting agent

This is the broadest workflow. Install `requirements-vm.txt` and Chromium as shown above, configure `.env`, and run:

```bash
python3 -m marine_uw_agent.run \
  --quotation-reference "ART-YYYYMMDDNN-MW" \
  --template-workbook "./input/UW Review - HK.xlsx" \
  --output-dir "./output" \
  --as-of-date "YYYY-MM-DD" \
  --headful true
```

The browser run requires `QUOTATION_SYSTEM_URL`, `QUOTATION_SYSTEM_USERNAME`, and `QUOTATION_SYSTEM_PASSWORD`. Equasis and HiFleet have their own optional URL/credential variables in `.env.example`. A persistent Playwright profile defaults to `./playwright-profile` and can be relocated with `BROWSER_PROFILE_DIR`.

Additional inputs:

- `--output-workbook` overrides the generated workbook path.
- `--quotation-text` parses a locally supplied text extraction.
- `--quotation-pdf` records the PDF as requiring deployment parsing/manual review; PDF text extraction is not implemented here.
- `--cargo-json` merges structured cargo details into the quotation.
- `--expected-listed-area` overrides the listed-area expectation.
- `--offline` skips all browser automation and works from supplied local input.

Offline example:

```bash
python3 -m marine_uw_agent.run \
  --quotation-reference "ART-TEST" \
  --quotation-text "./sample_quote.txt" \
  --template-workbook "./input/UW Review - HK.xlsx" \
  --output-dir "./output" \
  --as-of-date "2026-06-17" \
  --offline
```

The normal flow is:

1. Create run, download, and evidence paths and write `runs/<reference>/run_audit.json`.
2. Parse supplied text/PDF metadata or retrieve the quotation through the configured quotation system.
3. When vessel name and IMO are present, retrieve same-vessel quotation history and research Equasis and HiFleet.
4. Build parties from quotation and vessel sources.
5. Review listed-area wording and structured cargo information.
6. Match parties against the local sanctions snapshot and group results by jurisdiction/role.
7. Record missing data, possible matches, browser challenges, or source failures as open issues.
8. Write machine-readable output, Markdown, and the populated workbook.

Expected outputs include:

```text
runs/<reference>/run_audit.json
runs/<reference>/downloads/
runs/<reference>/evidence/
evidence/<reference>/
output/<reference>_extracted.json
output/<reference>_sanctions.json
output/<reference>_quote_history.json
output/<reference>_UW_Review.md
output/<reference>_UW_Review.xlsx
```

Workbook population uses `openpyxl`, preserves the supplied workbook where possible, and writes `Sources`, `UW Info`, `Fleet Info`, and `Search results`. `Sanction Watchlist Countries` is intentionally left untouched. If population fails, the workflow writes `<reference>_workbook_population_error.txt`.

See `VM_BROWSER_WORKFLOW.md` for the VM-specific runbook. The helper `scripts/start_vm_browser.sh` accepts the quotation reference as its first argument and reads `TEMPLATE_WORKBOOK_PATH`, `OUTPUT_DIR`, and `AS_OF_DATE` from the environment.

## 6. Legacy audit-log runner

The default `company_names.csv` allows this command to run without Excel dependencies:

```bash
python3 sanctions_checker_improved.py
```

It reads the first column of CSV, one name per line from TXT/`.list`, or the first Excel column when `pandas`/`openpyxl` are installed. Settings are normalized from `sanctions_config.json`, and the output columns are timestamp, entity name, search result, status, and OS type.

Again, the present implementation records simulated `NO_MATCH` values. The Windows/macOS/Linux helper scripts install historical dependencies and invoke this runner, but they do not change that limitation. Outlook COM sending exists only when enabled in configuration and `pywin32` is available on Windows; the non-Windows “SMTP” method is a logging stub, not a mail transport.

## Automated deployment

`.github/workflows/pages.yml` deploys the repository root as a Pages artifact on pushes to `main` or `github-pages-sanctions-site`, and on manual dispatch. Pages must be configured to use **GitHub Actions** as its source. The configured project URL is:

```text
https://artinsurance.github.io/Underwriting/
```

Because the workflow uploads `path: .`, every tracked, non-excluded file in the checkout is part of the artifact. Do not commit credentials, browser profiles, private workbooks, sensitive raw evidence, or runtime databases. The FastAPI/SQLite service is not part of GitHub Pages; Pages always runs the static/local-storage mode.

## Tests

After installing VM requirements, run the unit tests and static check:

```bash
python3 -m unittest -v
python3 scripts/verify_static_site.py
```

The tests cover quotation parsing, normalization, sanctions classification, three-month history filtering, cargo and missing-information handling, evidence paths, history-row normalization, workbook population, offline workflow behavior, quotation-review rendering, and SQLite validation/upsert behavior. They mock or avoid live third-party browser sessions; passing tests do not prove those sites are currently reachable or unchanged.

## Repository layout

```text
.
├── index.html / 404.html             Static workbench and Pages fallback
├── web_app.py                        FastAPI + SQLite persistence
├── data/
│   ├── sanctions_snapshot.json       Generated local sanctions index
│   ├── evidence_manifest.json        Published browser-evidence metadata
│   ├── vessels.json                  Vessel dashboard data
│   └── raw/                          Downloaded source datasets and other inputs
├── site-evidence/                    Publishable generated evidence
├── scripts/
│   ├── update_sanctions_data.py      Dataset refresh/parser
│   ├── run_uw_web_evidence.py        Static-site Playwright evidence capture
│   ├── verify_static_site.py         HTML/data/JavaScript validation
│   └── start_vm_browser.sh           VM-agent convenience wrapper
├── underwriting_review.py            Offline JSON quotation reviewer
├── marine_uw_agent/                  Browser-oriented underwriting package
├── sanctions_checker_improved.py     Legacy placeholder audit runner
├── SanctionsCheck_VBA.bas            Legacy Excel macro
├── requirements-web.txt              FastAPI runtime dependencies
├── requirements-vm.txt               Browser/Excel/test dependencies
├── Dockerfile / compose.yaml         Container deployment
├── render.yaml                       Render Blueprint
├── .github/workflows/                Pages and sanctions-refresh automation
└── test_*.py                         Unit tests
```

## Security and handling notes

- Keep `.env`, runtime databases, browser profiles, output, run, and evidence working directories out of Git. The current `.gitignore` covers the standard local paths.
- Treat quotation documents, ownership data, screenshots, and browser storage as potentially sensitive.
- Do not place credentials in workbooks, screenshots, logs, manifests, command history, or committed configuration.
- Review any captured HTML/text and the Pages artifact before publication.
- Protect SQLite backups and define retention/deletion rules appropriate to your organization.
- Independently confirm candidate sanctions matches and unresolved source checks before binding, clearing, or escalating a risk.

## Additional documents

- `VM_BROWSER_WORKFLOW.md` — focused VM setup, security, outputs, and manual-intervention behavior.
- `QUICK_START.md`, `DEPLOYMENT_GUIDE.md`, `CODE_REVIEW.md`, and `FINAL_DELIVERABLES.md` — historical documentation for the earlier VBA/Python deployment. Where those documents conflict with this README or current source, the current source code is authoritative.
