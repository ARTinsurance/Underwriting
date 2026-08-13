from __future__ import annotations

import json
import base64
import mimetypes
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", ROOT / "runtime-data"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "underwriting.sqlite3"))
MAX_STATE_BYTES = int(os.getenv("MAX_STATE_BYTES", str(25 * 1024 * 1024)))

app = FastAPI(title="Marine UW Sanctions Workbench", version="1.0.0")


def run_equasis_lookup(imo: str) -> dict[str, Any]:
    if len(imo) != 7 or not imo.isdigit():
        raise HTTPException(status_code=400, detail="IMO must contain exactly seven digits")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="equasis-lookup-", dir=DATA_DIR) as temporary:
        temp = Path(temporary)
        manifest = temp / "manifest.json"
        output = temp / "evidence"
        command = [
            sys.executable, str(ROOT / "scripts" / "run_uw_web_evidence.py"),
            "--imo", imo, "--vessel-name", "", "--commercial-manager", "",
            "--registered-owner", "", "--sources", "equasis,sanctions", "--headless", "true",
            "--manifest", str(manifest), "--output-dir", str(output),
        ]
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600, check=False)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="Equasis lookup timed out") from exc
        if not manifest.exists():
            detail = (completed.stderr or completed.stdout or "Equasis lookup failed")[-1000:]
            raise HTTPException(status_code=502, detail=detail)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        result = next((item for item in payload.get("source_results", []) if item.get("source_key") == "equasis"), {})
        if result.get("status") != "captured":
            raise HTTPException(status_code=502, detail=result.get("error") or "Equasis did not return accessible ship details")
        equasis = payload.get("equasis") or {}
        screenshots = []
        for item in payload.get("screenshots", []):
            relative = str(item.get("image") or "")
            image_path = (ROOT / relative).resolve()
            if relative and image_path.is_relative_to(output.resolve()) and image_path.is_file():
                encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
                item = {**item, "image": f"data:image/png;base64,{encoded}", "raw_text_file": ""}
            screenshots.append(item)
        return {
            "imo": imo,
            "details": equasis.get("details") or {},
            "shipFields": equasis.get("ship_fields") or {},
            "management": equasis.get("management") or [],
            "generatedAt": payload.get("generated_at"),
            "summary": payload.get("summary") or {},
            "sourceResults": payload.get("source_results") or [],
            "screenshots": screenshots,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        yield connection
        connection.commit()
    finally:
        connection.close()


def validate_review_id(review_id: str) -> str:
    if not review_id or len(review_id) > 80 or not all(character.isalnum() or character in "-_" for character in review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")
    return review_id


def validate_state(payload: Any) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("review"), dict) or not isinstance(payload.get("evidence", []), list):
        raise HTTPException(status_code=422, detail="State must contain a review object and evidence array")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="Review and screenshots exceed the storage limit")
    return encoded


@app.get("/api/health")
async def health() -> dict[str, str]:
    with database() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "storage": "sqlite"}


@app.post("/api/equasis/{imo}")
async def equasis_lookup(imo: str) -> dict[str, Any]:
    return await run_in_threadpool(run_equasis_lookup, imo)


@app.get("/api/reviews/{review_id}")
async def get_review(review_id: str) -> dict[str, Any]:
    review_id = validate_review_id(review_id)
    with database() as connection:
        row = connection.execute(
            "SELECT state_json, created_at, updated_at FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return {
        "id": review_id,
        "state": json.loads(row["state_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@app.put("/api/reviews/{review_id}")
async def put_review(review_id: str, request: Request) -> dict[str, str]:
    review_id = validate_review_id(review_id)
    if request.headers.get("content-length") and int(request.headers["content-length"]) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="Review and screenshots exceed the storage limit")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from None
    encoded = validate_state(payload)
    now = utc_now()
    with database() as connection:
        connection.execute(
            """
            INSERT INTO reviews (id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
            """,
            (review_id, encoded, now, now),
        )
    return {"id": review_id, "updatedAt": now}


@app.delete("/api/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(review_id: str) -> Response:
    review_id = validate_review_id(review_id)
    with database() as connection:
        connection.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse((ROOT / "index.html").read_text(encoding="utf-8"))


@app.get("/index.html", include_in_schema=False)
async def index_html() -> HTMLResponse:
    return await index()


@app.get("/data/sanctions_snapshot.json", include_in_schema=False)
async def sanctions_snapshot() -> Response:
    return Response((ROOT / "data" / "sanctions_snapshot.json").read_bytes(), media_type="application/json")


@app.get("/data/evidence_manifest.json", include_in_schema=False)
async def evidence_manifest() -> Response:
    return Response((ROOT / "data" / "evidence_manifest.json").read_bytes(), media_type="application/json")


# Only explicitly publish generated evidence directories. Never mount the repository
# root: it contains .env, source workbooks, runtime data, and other private files.
def published_asset(directory: str, relative_path: str) -> Response:
    base = (ROOT / directory).resolve()
    path = (base / relative_path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(path.read_bytes(), media_type=media_type)


@app.get("/site-evidence/{relative_path:path}", include_in_schema=False)
async def site_evidence_asset(relative_path: str) -> Response:
    return published_asset("site-evidence", relative_path)


@app.get("/screenshots/{relative_path:path}", include_in_schema=False)
async def screenshot_asset(relative_path: str) -> Response:
    return published_asset("screenshots", relative_path)
