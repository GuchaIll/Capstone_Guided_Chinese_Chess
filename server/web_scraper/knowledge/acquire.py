#!/usr/bin/env python3
"""
acquire.py — Wave 1 RAG Knowledge Acquisition
==============================================

Fetches raw HTML artifacts from sources listed in sources.yaml,
saves them under knowledge/raw/<site>/<source_id>.html, and appends
one manifest line per acquisition to knowledge/manifests/acquisition_runs.jsonl.

Usage
-----
    # Acquire all planned, resolved Wave 1 sources
    python acquire.py

    # Acquire a specific source only
    python acquire.py --source-id xqinenglish_opening_basics_05

    # Dry run (print what would be fetched)
    python acquire.py --dry-run

    # Acquire specific wave
    python acquire.py --wave 1

    # Force re-fetch even if raw file already exists
    python acquire.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("acquire")

_HERE = Path(__file__).resolve().parent
SOURCES_YAML = _HERE / "sources.yaml"
RAW_DIR = _HERE / "raw"
MANIFESTS_DIR = _HERE / "manifests"

# Polite rate limit between requests (seconds)
DEFAULT_RATE_LIMIT = 2.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; XiangqiRAGBot/1.0; "
        "+https://github.com/GuchaIll/Capstone_Guided_Chinese_Chess)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def load_sources() -> list[dict[str, Any]]:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def filter_sources(
    sources: list[dict[str, Any]],
    wave: int | None,
    source_id: str | None,
    resolved_only: bool = True,
) -> list[dict[str, Any]]:
    out = []
    for s in sources:
        if source_id and s["source_id"] != source_id:
            continue
        if wave and s.get("wave") != wave:
            continue
        if resolved_only and s.get("url_status") != "resolved":
            logger.info("Skipping unresolved source: %s", s["source_id"])
            continue
        if s.get("status") == "deferred":
            logger.info("Skipping deferred source: %s", s["source_id"])
            continue
        # Only handle HTML-based sources in this script
        fmt = s.get("format", "")
        if fmt not in (
            "html", "html_content_div", "html_main_content",
            "html_list", "html_table", "html_hub",
            "html_forum", "html_and_pdf", "dynamic_web",
        ):
            logger.info("Skipping non-HTML source (%s): %s", fmt, s["source_id"])
            continue
        out.append(s)
    return out


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def fetch_html(url: str, session: requests.Session) -> tuple[bytes, str, int]:
    """Return (content_bytes, final_url, http_status)."""
    resp = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    return resp.content, resp.url, resp.status_code


def raw_path(source: dict[str, Any]) -> Path:
    subdir = source.get("raw_subdir", source["site_name"])
    dest = RAW_DIR / subdir / f"{source['source_id']}.html"
    return dest


def acquire_source(
    source: dict[str, Any],
    session: requests.Session,
    force: bool,
) -> dict[str, Any] | None:
    """Fetch one source and save raw HTML. Returns manifest entry or None on skip."""
    sid = source["source_id"]
    url = source["canonical_url"]
    dest = raw_path(source)

    if dest.exists() and not force:
        logger.info("[SKIP] Already acquired: %s → %s", sid, dest)
        return None

    logger.info("[FETCH] %s  %s", sid, url)
    try:
        content, final_url, status = fetch_html(url, session)
    except requests.RequestException as exc:
        logger.error("[ERROR] %s — %s", sid, exc)
        return {
            "source_id": sid,
            "url": url,
            "final_url": None,
            "status": "error",
            "http_status": None,
            "content_hash": None,
            "content_length": None,
            "error": str(exc),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }

    if status >= 400:
        logger.warning("[HTTP %d] %s — %s", status, sid, url)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    logger.info("[SAVED] %s (%d bytes)", dest, len(content))

    return {
        "source_id": sid,
        "url": url,
        "final_url": final_url,
        "status": "ok" if status < 400 else "http_error",
        "http_status": status,
        "content_hash": sha256_bytes(content),
        "content_length": len(content),
        "raw_path": str(dest.relative_to(_HERE)),
        "error": None,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }


def append_manifest(entries: list[dict[str, Any]]) -> None:
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = MANIFESTS_DIR / "acquisition_runs.jsonl"
    with open(manifest, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("Manifest updated: %s (%d entries)", manifest, len(entries))


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire raw HTML for RAG knowledge sources")
    parser.add_argument("--source-id", help="Acquire only this source_id")
    parser.add_argument("--wave", type=int, help="Acquire only sources from this wave number")
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_RATE_LIMIT,
        help="Seconds between requests (default: 2.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if raw file already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sources that would be fetched without actually fetching",
    )
    args = parser.parse_args()

    sources = load_sources()
    targets = filter_sources(
        sources,
        wave=args.wave,
        source_id=args.source_id,
    )

    if not targets:
        logger.warning("No sources matched the given filters.")
        return

    logger.info("Sources to acquire: %d", len(targets))

    if args.dry_run:
        for s in targets:
            print(f"  {s['source_id']:60s}  {s['canonical_url']}")
        return

    session = requests.Session()
    manifest_entries: list[dict[str, Any]] = []

    for i, source in enumerate(targets):
        entry = acquire_source(source, session, force=args.force)
        if entry is not None:
            manifest_entries.append(entry)

        # Rate limit between requests (not after last one)
        if i < len(targets) - 1:
            time.sleep(args.rate_limit)

    if manifest_entries:
        append_manifest(manifest_entries)

    ok = sum(1 for e in manifest_entries if e["status"] == "ok")
    skip = len(targets) - len(manifest_entries)
    err = sum(1 for e in manifest_entries if e["status"] != "ok")
    logger.info("Done. ok=%d  skipped=%d  errors=%d", ok, skip, err)


if __name__ == "__main__":
    main()
