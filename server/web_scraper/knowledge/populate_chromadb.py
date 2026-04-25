#!/usr/bin/env python3
"""
populate_chromadb.py — Populate ChromaDB from knowledge_base.json
==================================================================

Reads json/knowledge_base.json, embeds every chunk via the embedding
service, and upserts them into the four ChromaDB collections:
  openings  |  tactics  |  endgames  |  beginner_principles

Prerequisites
-------------
  docker compose up chromadb embedding   # services must be healthy
  pip install requests                   # already in requirements.txt

Usage
-----
    # Populate all four collections (default URLs)
    python populate_chromadb.py

    # Target a specific collection only
    python populate_chromadb.py --collection openings

    # Override service URLs
    python populate_chromadb.py \\
        --chromadb-url http://localhost:8000 \\
        --embedding-url http://localhost:8100

    # Embed and validate without writing to ChromaDB
    python populate_chromadb.py --dry-run

    # Re-upsert everything (replaces existing vectors for the same IDs)
    python populate_chromadb.py --force

    # Wipe a collection then re-populate from scratch
    python populate_chromadb.py --reset --collection openings
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("populate")

_HERE = Path(__file__).resolve().parent
KNOWLEDGE_BASE = _HERE / "json" / "knowledge_base.json"
MANIFESTS_DIR = _HERE / "manifests"

COLLECTIONS = ["openings", "tactics", "endgames", "beginner_principles"]

DEFAULT_CHROMADB_URL = os.environ.get("CHROMADB_URL", "http://localhost:8000")
DEFAULT_EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8100")

BATCH_SIZE = 32
EMBED_TIMEOUT = 90
CHROMA_TIMEOUT = 30
CHROMA_TENANT = "default_tenant"
CHROMA_DB = "default_database"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _base(chromadb_url: str) -> str:
    return f"{chromadb_url}/api/v2/tenants/{CHROMA_TENANT}/databases/{CHROMA_DB}"


def check_health(chromadb_url: str, embedding_url: str, session: requests.Session) -> bool:
    ok = True
    for name, url in [("chromadb", f"{chromadb_url}/api/v2/heartbeat"),
                       ("embedding", f"{embedding_url}/health")]:
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                logger.info("[health] %s OK", name)
            else:
                logger.error("[health] %s returned HTTP %d", name, resp.status_code)
                ok = False
        except requests.RequestException as exc:
            logger.error("[health] %s unreachable: %s", name, exc)
            ok = False
    return ok


def get_or_create_collection(name: str, chromadb_url: str, session: requests.Session) -> str:
    """Return the collection UUID, creating it if necessary."""
    url = f"{_base(chromadb_url)}/collections/{name}"
    resp = session.get(url, timeout=CHROMA_TIMEOUT)
    if resp.status_code == 200:
        cid = resp.json()["id"]
        logger.info("[%s] collection exists (id=%s)", name, cid)
        return cid

    create_resp = session.post(
        f"{_base(chromadb_url)}/collections",
        json={"name": name, "metadata": {"hnsw:space": "cosine"}},
        timeout=CHROMA_TIMEOUT,
    )
    create_resp.raise_for_status()
    cid = create_resp.json()["id"]
    logger.info("[%s] collection created (id=%s)", name, cid)
    return cid


def delete_collection(name: str, chromadb_url: str, session: requests.Session) -> None:
    url = f"{_base(chromadb_url)}/collections/{name}"
    resp = session.delete(url, timeout=CHROMA_TIMEOUT)
    if resp.status_code in (200, 204):
        logger.info("[%s] collection deleted", name)
    elif resp.status_code == 404:
        logger.info("[%s] collection did not exist — nothing to delete", name)
    else:
        resp.raise_for_status()


def embed_texts(texts: list[str], embedding_url: str, session: requests.Session) -> list[list[float]]:
    resp = session.post(
        f"{embedding_url}/embed",
        json={"texts": texts},
        timeout=EMBED_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def upsert_batch(
    collection_id: str,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
    chromadb_url: str,
    session: requests.Session,
) -> None:
    url = f"{_base(chromadb_url)}/collections/{collection_id}/upsert"
    resp = session.post(
        url,
        json={"ids": ids, "embeddings": embeddings, "documents": documents, "metadatas": metadatas},
        timeout=CHROMA_TIMEOUT,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"ChromaDB upsert failed ({resp.status_code}): {resp.text[:300]}")


def _sanitize_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """ChromaDB metadata values must be str | int | float | bool — no lists or None."""
    keep = ("doc_id", "title", "phase", "topic", "url", "source_name", "chunk_index", "quality_score")
    meta: dict[str, Any] = {}
    for key in keep:
        val = chunk.get(key)
        if val is None:
            continue
        meta[key] = ", ".join(str(v) for v in val) if isinstance(val, list) else val
    tags = chunk.get("tags", [])
    if tags:
        meta["tags"] = ", ".join(str(t) for t in tags)
    meta["collection"] = chunk.get("collection", "")
    return meta


# ── Per-collection ingest ──────────────────────────────────────────────────────

def populate_collection(
    name: str,
    chunks: list[dict[str, Any]],
    chromadb_url: str,
    embedding_url: str,
    session: requests.Session,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    if not chunks:
        logger.warning("[%s] no chunks — skipping", name)
        return {"collection": name, "status": "empty", "inserted": 0, "errors": 0}

    logger.info("[%s] starting — %d chunks total", name, len(chunks))

    if not dry_run:
        collection_id = get_or_create_collection(name, chromadb_url, session)
    else:
        collection_id = "dry-run"

    inserted = 0
    errors = 0
    batches = range(0, len(chunks), BATCH_SIZE)

    for i, start in enumerate(batches):
        batch = chunks[start: start + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["chunk_id"] for c in batch]
        metas = [_sanitize_metadata(c) for c in batch]

        # Embed
        try:
            embeddings = embed_texts(texts, embedding_url, session)
        except requests.RequestException as exc:
            logger.error("[%s] embed failed for batch %d: %s", name, i, exc)
            errors += len(batch)
            continue

        if dry_run:
            logger.info("[DRY RUN][%s] batch %d/%d — %d chunks embedded OK",
                        name, i + 1, len(batches), len(batch))
            inserted += len(batch)
            continue

        # Upsert
        try:
            upsert_batch(collection_id, ids, embeddings, texts, metas, chromadb_url, session)
            inserted += len(batch)
            logger.info("[%s] batch %d/%d — upserted %d/%d",
                        name, i + 1, len(batches), inserted, len(chunks))
        except RuntimeError as exc:
            logger.error("[%s] upsert failed for batch %d: %s", name, i, exc)
            errors += len(batch)

        time.sleep(0.1)

    status = "dry_run" if dry_run else ("ok" if errors == 0 else "partial")
    logger.info("[%s] done — inserted=%d errors=%d", name, inserted, errors)
    return {
        "collection": name,
        "status": status,
        "total_chunks": len(chunks),
        "inserted": inserted,
        "errors": errors,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Populate ChromaDB from knowledge_base.json")
    parser.add_argument(
        "--collection",
        choices=COLLECTIONS,
        help="Populate only this collection (default: all four)",
    )
    parser.add_argument("--chromadb-url", default=DEFAULT_CHROMADB_URL,
                        help=f"ChromaDB base URL (default: {DEFAULT_CHROMADB_URL})")
    parser.add_argument("--embedding-url", default=DEFAULT_EMBEDDING_URL,
                        help=f"Embedding service URL (default: {DEFAULT_EMBEDDING_URL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Embed and validate but do NOT write to ChromaDB")
    parser.add_argument("--force", action="store_true",
                        help="Re-upsert even if chunk IDs already exist in ChromaDB")
    parser.add_argument("--reset", action="store_true",
                        help="Delete and recreate each target collection before populating")
    parser.add_argument("--input", default=str(KNOWLEDGE_BASE),
                        help="Path to knowledge_base.json (default: json/knowledge_base.json)")
    args = parser.parse_args()

    # Load knowledge base
    kb_path = Path(args.input)
    if not kb_path.exists():
        logger.error("knowledge_base.json not found at %s — run export_json.py first", kb_path)
        sys.exit(1)

    with open(kb_path, encoding="utf-8") as f:
        kb = json.load(f)

    targets = [args.collection] if args.collection else COLLECTIONS
    session = requests.Session()

    # Health check
    logger.info("=== Checking service health ===")
    if not check_health(args.chromadb_url, args.embedding_url, session):
        logger.error("One or more services are unreachable. Start them with: docker compose up chromadb embedding")
        sys.exit(1)

    # Reset if requested
    if args.reset and not args.dry_run:
        for col in targets:
            logger.info("[%s] --reset: deleting collection", col)
            delete_collection(col, args.chromadb_url, session)

    # Populate
    all_stats: list[dict] = []
    for col in targets:
        col_data = kb.get("collections", {}).get(col, {})
        chunks = col_data.get("chunks", [])
        logger.info("=== Populating [%s] — %d chunks ===", col, len(chunks))
        stats = populate_collection(
            name=col,
            chunks=chunks,
            chromadb_url=args.chromadb_url,
            embedding_url=args.embedding_url,
            session=session,
            dry_run=args.dry_run,
            force=args.force,
        )
        all_stats.append(stats)

    # Summary
    print()
    print("=" * 60)
    print(f"{'Collection':<25} {'Status':<12} {'Inserted':>10} {'Errors':>8}")
    print("-" * 60)
    for s in all_stats:
        print(f"{s['collection']:<25} {s['status']:<12} {s['inserted']:>10} {s['errors']:>8}")
    print("=" * 60)
    total_inserted = sum(s["inserted"] for s in all_stats)
    total_errors = sum(s["errors"] for s in all_stats)
    print(f"{'TOTAL':<25} {'':12} {total_inserted:>10} {total_errors:>8}")

    # Append to manifest
    if not args.dry_run:
        MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        manifest = MANIFESTS_DIR / "ingestion_runs.jsonl"
        with open(manifest, "a", encoding="utf-8") as f:
            for s in all_stats:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        logger.info("Manifest updated → %s", manifest)

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
