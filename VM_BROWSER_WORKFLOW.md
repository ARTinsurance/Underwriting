# Marine War UW Review VM Browser Workflow

This workflow is browser-based only. It does not connect to Gmail and does not send email.

## Security

- Do not hardcode usernames, passwords, cookies, or session tokens.
- Put credentials in `.env`, environment variables, or the VM secret store.
- `.env`, browser profiles, run folders, evidence, and output folders are excluded from git.
- Workbook source rows use `Stored in VM secrets` instead of writing passwords.
- Logs and documentation must mask passwords and session tokens.

Copy `.env.example` to `.env` on the VM and fill in:

```bash
cp .env.example .env
```

## VM Setup

Use Python 3.11+:

```bash
python -m venv venv
. venv/bin/activate
pip install -r requirements-vm.txt
playwright install chromium
```

The browser profile is persistent at `./playwright-profile/` by default. On a shared VM, place this directory in an encrypted or access-controlled user folder and set:

```bash
export BROWSER_PROFILE_DIR=/secure/path/playwright-profile
```

## Run

```bash
python -m marine_uw_agent.run \
  --quotation-reference "ART-YYYYMMDDNN-MW" \
  --template-workbook "./input/UW Review - HK.xlsx" \
  --output-dir "./output" \
  --as-of-date "YYYY-MM-DD" \
  --headful true
```

Convenience script:

```bash
AS_OF_DATE=YYYY-MM-DD ./scripts/start_vm_browser.sh "ART-YYYYMMDDNN-MW"
```

For dry-run extraction tests without browser credentials:

```bash
python -m marine_uw_agent.run \
  --quotation-reference "ART-TEST" \
  --quotation-text "./sample_quote.txt" \
  --template-workbook "./input/UW Review - HK.xlsx" \
  --output-dir "./output" \
  --as-of-date "2026-06-17" \
  --offline
```

## Outputs

For each quotation reference, the workflow creates:

- `./runs/{quotation_reference}/evidence/`
- `./runs/{quotation_reference}/evidence/raw/`
- `./evidence/{quotation_reference}/`
- `./evidence/{quotation_reference}/raw/`
- `./runs/{quotation_reference}/downloads/`
- `./output/{quotation_reference}_extracted.json`
- `./output/{quotation_reference}_sanctions.json`
- `./output/{quotation_reference}_quote_history.json`
- `./output/{quotation_reference}_UW_Review.xlsx`
- `./output/{quotation_reference}_UW_Review.md`

## Manual Intervention

If Equasis, Hifleet, the quotation system, or an official sanctions source presents CAPTCHA, MFA, or a human verification challenge, the workflow stops that source and marks manual intervention required. It does not attempt bypasses.

If a website structure changes, the workflow saves available screenshot/HTML evidence and marks the source as failed/manual review required rather than fabricating results.

## Workbook

The agent uses `openpyxl` to preserve the supplied workbook where possible. It keeps sheet names and writes into:

- `Sources`
- `UW Info`
- `Fleet Info`
- `Search results`
- `Sanction Watchlist Countries` is left untouched unless the template later provides an explicit update map.

The uploaded `UW Review - HK.xlsx` must be present at the path passed with `--template-workbook`.
