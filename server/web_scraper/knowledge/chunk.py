#!/usr/bin/env python3
"""
chunk.py — Document → Retrieval Chunk Splitter
===============================================

Reads knowledge/normalized/documents.jsonl and splits each document
into retrieval-sized chunks, routing them into collection-specific
JSONL files under knowledge/chunks/.

Chunking strategy (per rag_migration.md):
  - Articles: split on headings (h1–h4) with 400–800 token windows
  - Proverb lists (html_list): one chunk per proverb item
  - Puzzles (html_table): one chunk per puzzle row
  - Default: sliding window with 15% overlap

Output files:
  knowledge/chunks/openings.jsonl
  knowledge/chunks/tactics.jsonl
  knowledge/chunks/endgames.jsonl
  knowledge/chunks/beginner_principles.jsonl

Usage
-----
    # Chunk all normalized documents
    python chunk.py

    # Chunk a specific source
    python chunk.py --source-id xqinenglish_opening_basics_05

    # Override target window size (in words; ~1 word ≈ 1.3 tokens)
    python chunk.py --max-words 500

    # Re-chunk, overwriting existing output files
    python chunk.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chunk")

_HERE = Path(__file__).resolve().parent
NORMALIZED_DIR = _HERE / "normalized"
CHUNKS_DIR = _HERE / "chunks"

VALID_COLLECTIONS = {"openings", "tactics", "endgames", "beginner_principles"}

# Target chunk size in words (400–800 tokens ≈ 300–600 words at 1.3 tok/word)
DEFAULT_MAX_WORDS = 450
OVERLAP_RATIO = 0.12   # ~12% overlap between adjacent window chunks

# Heading line pattern (Markdown-style, as produced by normalize.py)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


# ── Text splitting helpers ───────────────────────────────────────────────────

def split_by_headings(text: str) -> list[tuple[str, str]]:
    """
    Split text on Markdown headings.
    Returns list of (heading_text, section_body) pairs.
    The first pair may have an empty heading if the text starts with body.
    """
    sections: list[tuple[str, str]] = []
    last_end = 0
    last_heading = ""

    for m in _HEADING_RE.finditer(text):
        body = text[last_end:m.start()].strip()
        if body or last_heading:
            sections.append((last_heading, body))
        last_heading = m.group(2).strip()
        last_end = m.end()

    # Final section
    tail = text[last_end:].strip()
    if tail or last_heading:
        sections.append((last_heading, tail))

    return sections


def split_proverb_list(text: str) -> list[str]:
    """Return one chunk per bullet/numbered list item."""
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif re.match(r"^\d+\.", stripped):
            items.append(re.sub(r"^\d+\.\s*", "", stripped).strip())
    return [i for i in items if len(i) > 10]


def sliding_window(text: str, max_words: int, overlap: float) -> list[str]:
    """Fallback: sliding window over words."""
    words = text.split()
    if len(words) <= max_words:
        return [text.strip()] if text.strip() else []

    step = max(1, int(max_words * (1 - overlap)))
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return chunks


def word_count(text: str) -> int:
    return len(text.split())


# ── Chunk a single document ──────────────────────────────────────────────────

def make_chunk(
    doc: dict[str, Any],
    text: str,
    collection: str,
    chunk_index: int,
    title_override: str | None = None,
) -> dict[str, Any]:
    title = title_override or doc["title"]
    chunk_id = f"{doc['doc_id']}#{collection}#chunk-{chunk_index:03d}"
    return {
        "chunk_id": chunk_id,
        "doc_id": doc["doc_id"],
        "collection": collection,
        "text": text.strip(),
        "title": title,
        "phase": doc.get("phase", "general"),
        "topic": doc.get("topic", ""),
        "tags": doc.get("tags", []),
        "url": doc.get("url", ""),
        "source_name": doc.get("source_name", ""),
        "quality_score": _quality_score(text),
        "chunk_index": chunk_index,
    }


def _quality_score(text: str) -> float:
    """Heuristic quality score [0.0–1.0] for a chunk."""
    wc = word_count(text)
    if wc < 20:
        return 0.1
    if wc < 50:
        return 0.4
    if wc < 100:
        return 0.6
    # Penalize chunks with excessive bullet points (might be nav/menu leakage)
    bullet_ratio = text.count("\n- ") / max(wc, 1)
    if bullet_ratio > 0.15:
        return 0.5
    return min(0.95, 0.7 + (wc / 600) * 0.25)


def chunk_document(
    doc: dict[str, Any],
    max_words: int,
    extraction_method: str,
) -> dict[str, list[dict[str, Any]]]:
    """
    Return a dict mapping collection name → list of chunks for that collection.
    """
    collections: list[str] = [c for c in doc.get("retrieval_collections", []) if c in VALID_COLLECTIONS]
    if not collections:
        logger.warning("No valid collections for %s — skipping", doc["doc_id"])
        return {}

    content = doc.get("content", "")
    results: dict[str, list[dict[str, Any]]] = {c: [] for c in collections}

    # ── Strategy selection ───────────────────────────────────────────────────
    if extraction_method == "proverb_list_parser":
        items = split_proverb_list(content)
        if not items:
            items = sliding_window(content, max_words, OVERLAP_RATIO)

        for col in collections:
            for idx, item in enumerate(items):
                if word_count(item) < 5:
                    continue
                results[col].append(make_chunk(doc, item, col, idx))

    elif extraction_method == "puzzle_table_parser":
        # Each row is already a separate proverb-style chunk after normalize
        rows = [line.strip() for line in content.splitlines() if " | " in line]
        for col in collections:
            for idx, row in enumerate(rows):
                if row:
                    results[col].append(make_chunk(doc, row, col, idx))

    else:
        # Heading-based article split (default for html_content_div, etc.)
        sections = split_by_headings(content)

        # If no meaningful sections found, fall back to sliding window
        useful_sections = [(h, b) for h, b in sections if word_count(b) >= 30]

        if not useful_sections:
            windows = sliding_window(content, max_words, OVERLAP_RATIO)
            for col in collections:
                for idx, win in enumerate(windows):
                    results[col].append(make_chunk(doc, win, col, idx))
        else:
            global_idx = 0
            for heading, body in useful_sections:
                section_text = f"{heading}\n\n{body}".strip() if heading else body

                if word_count(section_text) <= max_words:
                    for col in collections:
                        results[col].append(make_chunk(doc, section_text, col, global_idx, heading or None))
                    global_idx += 1
                else:
                    # Section too long: apply sliding window within it
                    windows = sliding_window(section_text, max_words, OVERLAP_RATIO)
                    for win in windows:
                        for col in collections:
                            results[col].append(make_chunk(doc, win, col, global_idx, heading or None))
                        global_idx += 1

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Split normalized documents into retrieval chunks")
    parser.add_argument("--source-id", help="Chunk only documents from this source_id")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS, help="Max words per chunk")
    parser.add_argument("--force", action="store_true", help="Overwrite existing chunk files")
    args = parser.parse_args()

    docs_path = NORMALIZED_DIR / "documents.jsonl"
    if not docs_path.exists():
        logger.error("documents.jsonl not found — run normalize.py first")
        return

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing chunk IDs per collection (for incremental mode)
    existing: dict[str, set[str]] = {col: set() for col in VALID_COLLECTIONS}
    if not args.force:
        for col in VALID_COLLECTIONS:
            path = CHUNKS_DIR / f"{col}.jsonl"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            ch = json.loads(line)
                            existing[col].add(ch["chunk_id"])
                        except json.JSONDecodeError:
                            pass

    # Accumulate new chunks per collection
    new_chunks: dict[str, list[dict[str, Any]]] = {col: [] for col in VALID_COLLECTIONS}

    total_docs = 0
    with open(docs_path, encoding="utf-8") as f:
        for line in f:
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Filter by source_id if requested
            if args.source_id and not doc.get("doc_id", "").endswith(args.source_id):
                continue

            extraction_method = doc.get("extraction_method", "html_content_div")
            col_chunks = chunk_document(doc, args.max_words, extraction_method)

            for col, chunks in col_chunks.items():
                for chunk in chunks:
                    if chunk["chunk_id"] in existing[col]:
                        continue
                    if word_count(chunk["text"]) < 15:
                        continue
                    if chunk["quality_score"] < 0.3:
                        continue
                    new_chunks[col].append(chunk)

            total_docs += 1

    # Write chunk files
    for col in VALID_COLLECTIONS:
        chunks = new_chunks[col]
        if not chunks:
            continue
        path = CHUNKS_DIR / f"{col}.jsonl"
        mode = "w" if args.force else "a"
        with open(path, mode, encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        logger.info("[%s] wrote %d chunks → %s", col, len(chunks), path)

    total_chunks = sum(len(v) for v in new_chunks.values())
    logger.info("Done. docs_processed=%d  new_chunks=%d", total_docs, total_chunks)


if __name__ == "__main__":
    main()
