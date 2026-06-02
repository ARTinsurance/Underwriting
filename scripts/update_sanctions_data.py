#!/usr/bin/env python3
"""
Download official sanctions datasets and build a compact JSON snapshot for the
static sanctions dashboard.

This replaces screenshot-only Selenium checks with repeatable data ingestion:
- OFAC SDN XML
- OFAC Consolidated non-SDN XML
- UK Sanctions List CSV
- EU Consolidated Financial Sanctions XML

The script stores raw source files under data/raw/ and writes a searchable
data/sanctions_snapshot.json file for the website.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SNAPSHOT_PATH = DATA_DIR / "sanctions_snapshot.json"
VESSELS_PATH = DATA_DIR / "vessels.json"
LOCAL_EU_PDF = ROOT / "制裁自动化" / "20250708-European UnionConsolidated Financial Sanctions List.pdf"

SOURCES = [
    {
        "key": "ofac_sdn",
        "name": "OFAC SDN List",
        "url": "https://www.treasury.gov/ofac/downloads/sdn.xml",
        "parser": "ofac_xml",
        "raw": "ofac_sdn.xml",
    },
    {
        "key": "ofac_consolidated",
        "name": "OFAC Consolidated non-SDN List",
        "url": "https://sanctionslistservice.ofac.treas.gov/api/download/CONS_ADVANCED.XML",
        "parser": "ofac_xml",
        "raw": "ofac_consolidated.xml",
    },
    {
        "key": "uk",
        "name": "UK Sanctions List",
        "url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",
        "parser": "uk_csv",
        "raw": "uk_sanctions_list.csv",
    },
    {
        "key": "eu",
        "name": "EU Consolidated Financial Sanctions List",
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content",
        "fallback_urls": [
            "https://data.opensanctions.org/datasets/latest/eu_fsf/source.xml",
        ],
        "parser": "eu_xml",
        "raw": "eu_financial_sanctions.xml",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "UnderwritingSanctionsChecker/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), {
            "http_status": str(response.status),
            "content_type": response.headers.get("content-type", ""),
            "last_modified": response.headers.get("last-modified", ""),
            "etag": response.headers.get("etag", ""),
        }


def download_with_fallbacks(source: dict[str, object]) -> tuple[bytes, dict[str, str], str]:
    urls = [str(source["url"]), *[str(url) for url in source.get("fallback_urls", [])]]
    errors = []
    for url in urls:
        try:
            body, headers = download(url)
            return body, headers, url
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def xml_text(node: ET.Element, names: Iterable[str]) -> str:
    wanted = set(names)
    for child in node.iter():
        if child.tag.split("}", 1)[-1] in wanted and child.text:
            return clean(child.text)
    return ""


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def parse_ofac_xml(path: Path, source_key: str, source_name: str) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    records: list[dict[str, str]] = []

    party_subtypes = {
        item.attrib.get("ID", ""): clean(item.text)
        for item in root.iter()
        if local_name(item.tag) == "PartySubType"
    }
    distinct_parties = [item for item in root.iter() if local_name(item.tag) == "DistinctParty"]
    if distinct_parties:
        for party in distinct_parties:
            profile = next((item for item in party if local_name(item.tag) == "Profile"), None)
            party_type = party_subtypes.get(profile.attrib.get("PartySubTypeID", "") if profile is not None else "", "")
            names = []
            for alias in party.iter():
                if local_name(alias.tag) != "Alias":
                    continue
                name_parts = [
                    clean(part.text)
                    for part in alias.iter()
                    if local_name(part.tag) == "NamePartValue" and clean(part.text)
                ]
                if name_parts:
                    names.append(" ".join(name_parts))

            for name in sorted(set(names)):
                records.append({
                    "source": source_key,
                    "source_name": source_name,
                    "name": name,
                    "type": party_type,
                    "program": "",
                    "reference": clean(party.attrib.get("FixedRef")),
                })
        return records

    for entry in root.iter():
        if local_name(entry.tag) not in {"sdnEntry", "sanctionEntry"}:
            continue

        names = []
        primary = " ".join(
            part for part in [
                xml_text(entry, ["firstName"]),
                xml_text(entry, ["lastName", "name"]),
            ] if part
        )
        if primary:
            names.append(primary)

        for alias in entry.iter():
            if local_name(alias.tag) in {"aka", "nameAlias"}:
                alias_name = xml_text(alias, ["wholeName", "lastName"])
                if alias_name:
                    names.append(alias_name)

        program_values = [
            clean(child.text)
            for child in entry.iter()
            if local_name(child.tag) in {"program", "programList"} and child.text
        ]

        for name in sorted(set(names)):
            records.append({
                "source": source_key,
                "source_name": source_name,
                "name": name,
                "type": xml_text(entry, ["sdnType", "type"]),
                "program": "; ".join(sorted(set(program_values)))[:240],
                "reference": xml_text(entry, ["uid", "entNum"]),
            })

    return records


def parse_uk_csv(path: Path, source_key: str, source_name: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        first_line = csv_file.readline()
        if not first_line.startswith("Last Updated,"):
            pass
        else:
            csv_file.seek(0)
        reader = csv.DictReader(csv_file)
        for row in reader:
            names = [
                row.get("Name 6"),
                row.get("Name 1"),
                row.get("Name 2"),
                row.get("Name"),
                row.get("Alias"),
                row.get("Organisation Name"),
            ]
            name = clean(" ".join(part for part in names if clean(part)))
            if not name:
                continue
            records.append({
                "source": source_key,
                "source_name": source_name,
                "name": name,
                "type": clean(row.get("Designation Type")),
                "program": clean(row.get("Regime Name")),
                "reference": clean(row.get("Unique ID") or row.get("OFSI Group ID")),
            })
    return records


def parse_eu_xml(path: Path, source_key: str, source_name: str) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    records: list[dict[str, str]] = []

    for entity in root.iter():
        if local_name(entity.tag) != "sanctionEntity":
            continue

        program = xml_text(entity, ["programme", "regulationType", "remark"])
        reference = entity.attrib.get("logicalId", "") or entity.attrib.get("euReferenceNumber", "")
        for alias in entity.iter():
            if local_name(alias.tag) != "nameAlias":
                continue
            name = clean(alias.attrib.get("wholeName") or alias.attrib.get("nameAliasWholeName"))
            if not name:
                name = xml_text(alias, ["wholeName"])
            if name:
                records.append({
                    "source": source_key,
                    "source_name": source_name,
                    "name": name,
                    "type": clean(entity.attrib.get("subjectType") or entity.attrib.get("subjectTypeClassificationCode")),
                    "program": program[:240],
                    "reference": clean(reference),
                })
    return records


def parse_records(source: dict[str, str], raw_path: Path) -> list[dict[str, str]]:
    parser = source["parser"]
    if parser == "ofac_xml":
        return parse_ofac_xml(raw_path, source["key"], source["name"])
    if parser == "uk_csv":
        return parse_uk_csv(raw_path, source["key"], source["name"])
    if parser == "eu_xml":
        return parse_eu_xml(raw_path, source["key"], source["name"])
    raise ValueError(f"Unknown parser: {parser}")


def source_bucket(source_key: str) -> str:
    if source_key.startswith("ofac"):
        return "ofac"
    if source_key == "uk":
        return "uk"
    if source_key == "eu":
        return "eu"
    return source_key


def match_records(name: str, records: list[dict[str, str]]) -> list[dict[str, str]]:
    target = normalize_name(name)
    if not target:
        return []

    matches: list[dict[str, str]] = []
    for record in records:
        candidate = normalize_name(record.get("name", ""))
        if not candidate:
            continue
        candidate_tokens = candidate.split()
        candidate_is_specific = len(candidate) >= 8 and len(candidate_tokens) >= 2
        target_is_specific = len(target) >= 8 and len(target.split()) >= 2
        if (
            candidate == target
            or (candidate_is_specific and candidate in target)
            or (target_is_specific and target in candidate)
        ):
            matches.append(record)
    return matches


def subject_names(vessel: dict[str, object]) -> list[dict[str, str]]:
    subjects: list[dict[str, str]] = []
    vessel_name = clean(vessel.get("name"))
    if vessel_name:
        subjects.append({"role": "vessel", "name": vessel_name})

    owner_fields = [
        "owner",
        "registered_owner",
        "beneficial_owner",
        "operator",
        "manager",
        "ism_manager",
    ]
    for field in owner_fields:
        value = vessel.get(field)
        if isinstance(value, list):
            values = value
        else:
            values = [value]
        for item in values:
            name = clean(item)
            if name:
                subjects.append({"role": field, "name": name})

    for item in vessel.get("company_entities", []) or []:
        if isinstance(item, dict):
            name = clean(item.get("name"))
            role = clean(item.get("role")) or "company_entity"
        else:
            name = clean(item)
            role = "company_entity"
        if name:
            subjects.append({"role": role, "name": name})

    seen = set()
    unique_subjects = []
    for subject in subjects:
        key = (subject["role"], normalize_name(subject["name"]))
        if key in seen:
            continue
        seen.add(key)
        unique_subjects.append(subject)
    return unique_subjects


def summarize_matches(subject: dict[str, str], matches: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "checked_name": subject["name"],
            "checked_role": subject["role"],
            "matched_name": clean(record.get("name")),
            "source": source_bucket(clean(record.get("source"))),
            "source_name": clean(record.get("source_name")),
            "type": clean(record.get("type")),
            "program": clean(record.get("program")),
            "reference": clean(record.get("reference")),
        }
        for record in matches[:10]
    ]


def empty_source_result() -> dict[str, object]:
    return {"sanctioned": False, "matches": []}


def enrich_vessels(records: list[dict[str, str]], generated_at: str) -> None:
    if not VESSELS_PATH.exists():
        return

    vessel_data = json.loads(VESSELS_PATH.read_text(encoding="utf-8"))
    vessels = vessel_data.get("vessels", [])
    if not isinstance(vessels, list):
        return

    for vessel in vessels:
        if not isinstance(vessel, dict):
            continue

        source_results = {
            "ofac": empty_source_result(),
            "uk": empty_source_result(),
            "eu": empty_source_result(),
        }
        subject_results = []

        for subject in subject_names(vessel):
            matches = match_records(subject["name"], records)
            if not matches:
                subject_results.append({
                    **subject,
                    "status": "clear",
                    "matches": [],
                })
                continue

            summarized = summarize_matches(subject, matches)
            subject_results.append({
                **subject,
                "status": "match",
                "matches": summarized,
            })

            for match in summarized:
                bucket = match["source"]
                if bucket not in source_results:
                    continue
                source_results[bucket]["sanctioned"] = True
                source_results[bucket]["matches"].append(match)

        vessel["sanctions"] = {
            "checked_at": generated_at,
            "status": "match" if any(item["sanctioned"] for item in source_results.values()) else "clear",
            "sources": source_results,
            "subjects": subject_results,
        }

    vessel_data["sanctions_checked_at"] = generated_at
    VESSELS_PATH.write_text(json.dumps(vessel_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)

    records: list[dict[str, str]] = []
    source_results: list[dict[str, object]] = []

    for source in SOURCES:
        raw_path = RAW_DIR / source["raw"]
        started = time.time()
        source_result: dict[str, object] = {
            "key": source["key"],
            "name": source["name"],
            "url": source["url"],
            "raw_file": str(raw_path.relative_to(ROOT)),
            "records": 0,
            "status": "error",
        }

        try:
            body, headers, resolved_url = download_with_fallbacks(source)
            raw_path.write_bytes(body)
            parsed = parse_records(source, raw_path)
            records.extend(parsed)
            source_result.update({
                "url": resolved_url,
                "records": len(parsed),
                "status": "ok",
                "sha256": fingerprint(body),
                "bytes": len(body),
                "duration_seconds": round(time.time() - started, 2),
                **headers,
            })
        except Exception as exc:
            source_result.update({
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(time.time() - started, 2),
            })

        source_results.append(source_result)

    if LOCAL_EU_PDF.exists():
        source_results.append({
            "key": "eu_local_pdf",
            "name": "Local EU PDF reference",
            "url": str(LOCAL_EU_PDF.relative_to(ROOT)),
            "records": 0,
            "status": "reference_only",
            "bytes": LOCAL_EU_PDF.stat().st_size,
            "sha256": fingerprint(LOCAL_EU_PDF.read_bytes()),
        })

    records = sorted(records, key=lambda item: (item["source"], item["name"].casefold()))
    generated_at = utc_now()
    snapshot = {
        "generated_at": generated_at,
        "status": "ok" if records else "empty",
        "sources": source_results,
        "records": records,
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    enrich_vessels(records, generated_at)
    print(f"Wrote {SNAPSHOT_PATH.relative_to(ROOT)} with {len(records)} records")
    for source in source_results:
        print(f"{source['key']}: {source['status']} ({source['records']} records)")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
