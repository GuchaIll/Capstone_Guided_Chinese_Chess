#!/usr/bin/env python3
"""
export_json.py — Export chunks as a single organized JSON file
==============================================================

Reads the four collection JSONL files from knowledge/chunks/ and writes
knowledge/json/knowledge_base.json with all chunks separated by category.

Usage
-----
    python export_json.py
    python export_json.py --output knowledge/json/knowledge_base.json
    python export_json.py --pretty   # human-readable indentation
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_json")

_HERE = Path(__file__).resolve().parent
CHUNKS_DIR = _HERE / "chunks"
JSON_DIR = _HERE / "json"

COLLECTIONS = ["openings", "tactics", "endgames", "beginner_principles"]


def load_collection(name: str) -> list[dict]:
    path = CHUNKS_DIR / f"{name}.jsonl"
    if not path.exists():
        logger.warning("[%s] chunk file not found", name)
        return []
    chunks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning("Bad JSON line in %s: %s", name, exc)
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Export knowledge chunks to organized JSON")
    parser.add_argument("--output", default=str(JSON_DIR / "knowledge_base.json"))
    parser.add_argument("--pretty", action="store_true", help="Indent output for readability")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "schema_version": 1,
        "description": "Xiangqi RAG knowledge base — chunks separated by collection",
        "collections": {}
    }

    total = 0
    for col in COLLECTIONS:
        chunks = load_collection(col)
        result["collections"][col] = {
            "count": len(chunks),
            "chunks": chunks,
        }
        total += len(chunks)
        logger.info("[%s] %d chunks", col, len(chunks))

    result["total_chunks"] = total

    indent = 2 if args.pretty else None
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=indent)

    logger.info("Wrote %d total chunks → %s", total, out_path)


if __name__ == "__main__":
    main()
