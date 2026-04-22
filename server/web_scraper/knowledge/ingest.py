#!/usr/bin/env python3
"""
ingest.py — Chunk JSONL → ChromaDB Ingestion
=============================================

Reads per-collection chunk JSONL files from knowledge/chunks/,
embeds each chunk via the embedding service, and upserts into
the corresponding ChromaDB collection.

Also appends one run-summary line to knowledge/manifests/ingestion_runs.jsonl.

Usage
-----
    # Ingest all chunk files (with ChromaDB + embedding running)
    python ingest.py

    # Ingest one collection only
    python ingest.py --collection openings

    # Override service URLs
    python ingest.py --chromadb-url http://localhost:8000 --embedding-url http://localhost:8100

    # Dry run (embed + validate, but do not insert into ChromaDB)
    python ingest.py --dry-run

    # Re-ingest everything (skip duplicate check)
    python ingest.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest")

_HERE = Path(__file__).resolve().parent
CHUNKS_DIR = _HERE / "chunks"
MANIFESTS_DIR = _HERE / "manifests"

VALID_COLLECTIONS = ["openings", "tactics", "endgames", "beginner_principles"]

DEFAULT_CHROMADB_URL = os.environ.get("CHROMADB_URL", "http://localhost:8000")
DEFAULT_EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8100")

BATCH_SIZE = 32          # chunks per embedding + upsert call
EMBED_TIMEOUT = 60       # seconds
CHROMA_TIMEOUT = 30      # seconds

CHROMA_TENANT = "default_tenant"
CHROMA_DB = "default_database"


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def embed_texts(
    texts: list[str],
    embedding_url: str,
    session: requests.Session,
) -> list[list[float]]:
    resp = session.post(
        f"{embedding_url}/embed",
        json={"texts": texts},
        timeout=EMBED_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def ensure_collection(collection: str, chromadb_url: str, session: requests.Session) -> str:
    """Get or create collection; return its UUID."""
    url = (
        f"{chromadb_url}/api/v2/tenants/{CHROMA_TENANT}"
        f"/databases/{CHROMA_DB}/collections/{collection}"
    )
    resp = session.get(url, timeout=CHROMA_TIMEOUT)
    if resp.status_code == 200:
        return resp.json()["id"]

    # Create it
    create_url = (
        f"{chromadb_url}/api/v2/tenants/{CHROMA_TENANT}"
        f"/databases/{CHROMA_DB}/collections"
    )
    create_resp = session.post(
        create_url,
        json={"name": collection, "metadata": {"hnsw:space": "cosine"}},
        timeout=CHROMA_TIMEOUT,
    )
    create_resp.raise_for_status()
    logger.info("Created collection: %s", collection)
    return create_resp.json()["id"]


def upsert_chunks(
    collection_id: str,
    chunk_ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    chromadb_url: str,
    session: requests.Session,
) -> None:
    url = (
        f"{chromadb_url}/api/v2/tenants/{CHROMA_TENANT}"
        f"/databases/{CHROMA_DB}/collections/{collection_id}/upsert"
    )
    payload = {
        "ids": chunk_ids,
        "embeddings": embeddings,
        "documents": documents,
        "metadatas": metadatas,
    }
    resp = session.post(url, json=payload, timeout=CHROMA_TIMEOUT)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"ChromaDB upsert failed ({resp.status_code}): {resp.text[:400]}")


# ── Metadata sanitizer ───────────────────────────────────────────────────────

def _sanitize_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """
    ChromaDB metadata values must be str, int, float, or bool.
    Convert lists to comma-joined strings and drop None.
    """
    meta: dict[str, Any] = {}
    for key in ("doc_id", "title", "phase", "topic", "url", "source_name", "chunk_index", "quality_score"):
        val = chunk.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            meta[key] = ", ".join(str(v) for v in val)
        else:
            meta[key] = val
    tags = chunk.get("tags", [])
    if tags:
        meta["tags"] = ", ".join(tags)
    return meta


# ── Main ingest loop ──────────────────────────────────────────────────────────

def ingest_collection(
    collection: str,
    chromadb_url: str,
    embedding_url: str,
    session: requests.Session,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    """Ingest one collection. Return stats dict."""
    chunk_path = CHUNKS_DIR / f"{collection}.jsonl"
    if not chunk_path.exists():
        logger.warning("[%s] No chunk file found at %s", collection, chunk_path)
        return {"collection": collection, "status": "skipped", "inserted": 0, "errors": 0}

    chunks: list[dict[str, Any]] = []
    with open(chunk_path, encoding="utf-8") as f:
        for line in f:
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not chunks:
        logger.info("[%s] No chunks to ingest.", collection)
        return {"collection": collection, "status": "empty", "inserted": 0, "errors": 0}

    if not dry_run:
        collection_id = ensure_collection(collection, chromadb_url, session)
    else:
        collection_id = "dry-run"

    inserted = 0
    errors = 0

    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[batch_start: batch_start + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["chunk_id"] for c in batch]
        metas = [_sanitize_metadata(c) for c in batch]

        try:
            embeddings = embed_texts(texts, embedding_url, session)
        except requests.RequestException as exc:
            logger.error("[%s] Embedding failed for batch %d–%d: %s",
                         collection, batch_start, batch_start + len(batch), exc)
            errors += len(batch)
            continue

        if dry_run:
            logger.info("[DRY RUN][%s] batch %d chunks embedded OK", collection, len(batch))
            inserted += len(batch)
            continue

        try:
            upsert_chunks(collection_id, ids, embeddings, texts, metas, chromadb_url, session)
            inserted += len(batch)
            logger.info("[%s] upserted %d / %d", collection, batch_start + len(batch), len(chunks))
        except RuntimeError as exc:
            logger.error("[%s] Upsert failed: %s", collection, exc)
            errors += len(batch)

        # Brief pause between batches to avoid overloading services
        time.sleep(0.2)

    return {
        "collection": collection,
        "status": "dry_run" if dry_run else "ok",
        "total_chunks": len(chunks),
        "inserted": inserted,
        "errors": errors,
        "embedding_model": "chromadb-default",
        "run_at": datetime.now(timezone.utc).isoformat(),
    }


def append_ingestion_manifest(run_stats: list[dict[str, Any]]) -> None:
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = MANIFESTS_DIR / "ingestion_runs.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for stat in run_stats:
            f.write(json.dumps(stat, ensure_ascii=False) + "\n")
    logger.info("Ingestion manifest updated: %s", path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest chunk JSONL files into ChromaDB")
    parser.add_argument(
        "--collection",
        choices=VALID_COLLECTIONS,
        help="Ingest only this collection (default: all)",
    )
    parser.add_argument("--chromadb-url", default=DEFAULT_CHROMADB_URL)
    parser.add_argument("--embedding-url", default=DEFAULT_EMBEDDING_URL)
    parser.add_argument("--dry-run", action="store_true", help="Embed but do not insert")
    parser.add_argument("--force", action="store_true", help="Re-upsert even existing IDs")
    args = parser.parse_args()

    targets = [args.collection] if args.collection else VALID_COLLECTIONS

    session = requests.Session()
    all_stats: list[dict[str, Any]] = []

    for collection in targets:
        logger.info("=== Ingesting collection: %s ===", collection)
        stats = ingest_collection(
            collection=collection,
            chromadb_url=args.chromadb_url,
            embedding_url=args.embedding_url,
            session=session,
            dry_run=args.dry_run,
            force=args.force,
        )
        all_stats.append(stats)
        logger.info(
            "[%s] total=%s  inserted=%d  errors=%d",
            collection,
            stats.get("total_chunks", 0),
            stats["inserted"],
            stats["errors"],
        )

    if not args.dry_run:
        append_ingestion_manifest(all_stats)

    total_inserted = sum(s["inserted"] for s in all_stats)
    total_errors = sum(s["errors"] for s in all_stats)
    logger.info("=== Done. inserted=%d  errors=%d ===", total_inserted, total_errors)


if __name__ == "__main__":
    main()
