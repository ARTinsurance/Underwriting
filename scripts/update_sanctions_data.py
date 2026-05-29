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
        "url": "https://www.treasury.gov/ofac/downloads/consolidated/cons_advanced.xml",
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
        "parser": "eu_xml",
        "raw": "eu_financial_sanctions.xml",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
                "type": clean(row.get("Individual, Entity, Ship")),
                "program": clean(row.get("Regime Name")),
                "reference": clean(row.get("Unique ID") or row.get("Group ID")),
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
            body, headers = download(source["url"])
            raw_path.write_bytes(body)
            parsed = parse_records(source, raw_path)
            records.extend(parsed)
            source_result.update({
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
    snapshot = {
        "generated_at": utc_now(),
        "status": "ok" if records else "empty",
        "sources": source_results,
        "records": records,
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH.relative_to(ROOT)} with {len(records)} records")
    for source in source_results:
        print(f"{source['key']}: {source['status']} ({source['records']} records)")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
