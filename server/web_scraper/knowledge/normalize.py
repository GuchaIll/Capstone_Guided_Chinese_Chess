#!/usr/bin/env python3
"""
normalize.py — HTML → Document JSONL Normalizer
=================================================

Reads raw HTML files referenced in sources.yaml (acquired by acquire.py),
cleans them into structured documents, and writes one JSONL line per
document to knowledge/normalized/documents.jsonl.

Each output document follows the standard schema from rag_migration.md:
  doc_id, source_name, source_type, title, url, phase, topic, language,
  content, summary, tags, difficulty, license_note, extraction_method,
  retrieval_collections, metadata, content_hash, captured_at

Usage
-----
    # Normalize all acquired sources
    python normalize.py

    # Normalize a specific source
    python normalize.py --source-id xqinenglish_opening_basics_05

    # Normalize only wave 1
    python normalize.py --wave 1

    # Re-normalize even if output already exists
    python normalize.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup, Tag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("normalize")

_HERE = Path(__file__).resolve().parent
SOURCES_YAML = _HERE / "sources.yaml"
RAW_DIR = _HERE / "raw"
NORMALIZED_DIR = _HERE / "normalized"
MANIFESTS_DIR = _HERE / "manifests"

# ── Tags to strip entirely (content + tag removed) ──────────────────────────
_STRIP_TAGS = {
    "script", "style", "noscript", "iframe", "form",
    "nav", "header", "footer",
}

# ── CSS class / id fragments that indicate boilerplate ──────────────────────
_BOILERPLATE_PATTERNS = re.compile(
    r"(cookie|banner|popup|sidebar|breadcrumb|pagination|share|social|"
    r"advertisement|advert|module|widget|related|comment|login|signup|"
    r"newsletter|toolbar|topbar|menu|navbar)",
    re.IGNORECASE,
)

# ── Selectors tried in order to locate the main content block ───────────────
_CONTENT_SELECTORS = [
    "div#content",
    "div.article-content",
    "div.item-page",          # Joomla CMS (xqinenglish)
    "div.blog",               # Joomla blog layout
    "article",
    "main",
    "div#main",
    "div.main-content",
    "div.entry-content",
    "div.post-content",
    "div.td-post-content",
    "div.mw-parser-output",   # MediaWiki
    "div#mw-content-text",
    "div.content",
    "div#article",
    "div.article",
]


def load_sources() -> list[dict[str, Any]]:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


# ── Boilerplate removal ──────────────────────────────────────────────────────

def _is_boilerplate_tag(tag: Tag) -> bool:
    """Return True if a tag looks like navigation/ads/widgets."""
    tag_name = tag.name or ""
    if tag_name in _STRIP_TAGS:
        return True
    classes = " ".join(tag.get("class", []))
    tag_id = tag.get("id", "")
    combined = f"{classes} {tag_id}"
    return bool(_BOILERPLATE_PATTERNS.search(combined))


def remove_boilerplate(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        if _is_boilerplate_tag(tag):
            tag.decompose()


# ── Content extraction ───────────────────────────────────────────────────────

def find_content_element(soup: BeautifulSoup) -> Tag | None:
    """Try each selector in order and return the first match."""
    for selector in _CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el:
            return el
    return None


def element_to_text(el: Tag) -> str:
    """Convert a BeautifulSoup element to clean plain text, preserving structure."""
    lines: list[str] = []

    for child in el.descendants:
        if not isinstance(child, Tag):
            continue
        tag_name = child.name

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            heading_text = child.get_text(separator=" ", strip=True)
            if heading_text:
                lines.append(f"\n{'#' * level} {heading_text}\n")

        elif tag_name == "p":
            para = child.get_text(separator=" ", strip=True)
            if para:
                lines.append(para + "\n")

        elif tag_name in ("li",):
            item = child.get_text(separator=" ", strip=True)
            if item:
                lines.append(f"- {item}")

        elif tag_name in ("ol",):
            # Numbered list items are handled via <li> above
            pass

        elif tag_name == "tr":
            cells = [td.get_text(separator=" ", strip=True) for td in child.find_all(["td", "th"])]
            if any(cells):
                lines.append(" | ".join(cells))

    full_text = "\n".join(lines)
    # Collapse 3+ consecutive newlines into two
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)
    return full_text.strip()


def extract_title(soup: BeautifulSoup, fallback: str) -> str:
    # Try <h1> inside content first, then <title>, then fallback
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        # Strip site name suffix (e.g. "Article - xqinenglish.com")
        parts = re.split(r"\s*[-|–—]\s*", raw)
        return parts[0].strip() if parts else raw
    return fallback


def estimate_difficulty(tags: list[str], title: str) -> str:
    combined = " ".join(tags + [title]).lower()
    if any(w in combined for w in ("beginner", "basics", "introduction", "intro", "how to play", "proverb")):
        return "beginner"
    if any(w in combined for w in ("advanced", "expert", "master", "deep", "complex")):
        return "advanced"
    return "intermediate"


# ── Per-source normalizer ────────────────────────────────────────────────────

def normalize_html_source(source: dict[str, Any], html_bytes: bytes) -> dict[str, Any] | None:
    """Parse raw HTML and return a normalized document dict."""
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
    except Exception as exc:
        logger.error("Failed to parse HTML for %s: %s", source["source_id"], exc)
        return None

    remove_boilerplate(soup)

    content_el = find_content_element(soup)
    if content_el is None:
        # Fall back to <body>
        content_el = soup.find("body") or soup

    raw_text = element_to_text(content_el)

    if len(raw_text.strip()) < 80:
        logger.warning("[SKIP] Extracted text too short for %s (%d chars)", source["source_id"], len(raw_text.strip()))
        return None

    title = extract_title(soup, fallback=source.get("title", source["source_id"]))
    tags: list[str] = source.get("tags", [])
    phase = source.get("phase", "general")
    collections: list[str] = source.get("expected_collections", [])

    # Build topic from tags and phase
    topic_parts = [phase] + [t for t in tags[:3] if t != phase]
    topic = ", ".join(topic_parts)

    doc_id = f"{source['site_name']}/{phase}/{source['source_id']}"

    return {
        "doc_id": doc_id,
        "source_name": source.get("site_name", source["source_id"]),
        "source_type": "html",
        "title": title,
        "url": source.get("canonical_url", ""),
        "phase": phase,
        "topic": topic,
        "language": "en",
        "content": raw_text,
        "summary": None,
        "tags": tags,
        "difficulty": estimate_difficulty(tags, title),
        "license_note": "public web content, attributed",
        "extraction_method": source.get("extraction_method", "html_content_div"),
        "retrieval_collections": collections,
        "metadata": {
            "site_section": source.get("notes", ""),
            "author": None,
            "published_at": None,
            "board_fen": None,
            "solution": None,
        },
        "content_hash": sha256_text(raw_text),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize raw HTML into document JSONL")
    parser.add_argument("--source-id", help="Normalize only this source_id")
    parser.add_argument("--wave", type=int, help="Normalize only sources from this wave")
    parser.add_argument("--force", action="store_true", help="Re-normalize all (overwrite existing)")
    args = parser.parse_args()

    sources_data = load_sources()

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NORMALIZED_DIR / "documents.jsonl"

    # Load existing doc_ids to support incremental updates
    existing_ids: set[str] = set()
    if out_path.exists() and not args.force:
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    doc = json.loads(line)
                    existing_ids.add(doc["doc_id"])
                except json.JSONDecodeError:
                    pass

    new_docs: list[dict[str, Any]] = []

    for source in sources_data:
        sid = source["source_id"]

        if args.source_id and sid != args.source_id:
            continue
        if args.wave and source.get("wave") != args.wave:
            continue
        if source.get("url_status") != "resolved":
            logger.info("[SKIP unresolved] %s", sid)
            continue
        if source.get("status") == "deferred":
            continue

        fmt = source.get("format", "")
        if fmt not in (
            "html", "html_content_div", "html_main_content",
            "html_list", "html_table", "html_hub",
            "html_forum", "html_and_pdf",
        ):
            logger.info("[SKIP non-HTML] %s (%s)", sid, fmt)
            continue

        raw_file = RAW_DIR / source.get("raw_subdir", source["site_name"]) / f"{sid}.html"
        if not raw_file.exists():
            logger.warning("[MISSING RAW] %s — run acquire.py first", sid)
            continue

        phase = source.get("phase", "general")
        doc_id = f"{source['site_name']}/{phase}/{sid}"
        if doc_id in existing_ids and not args.force:
            logger.info("[SKIP existing] %s", doc_id)
            continue

        logger.info("[NORMALIZE] %s", sid)
        html_bytes = raw_file.read_bytes()
        doc = normalize_html_source(source, html_bytes)

        if doc is not None:
            new_docs.append(doc)
            logger.info("[OK] %s — %d chars", doc["doc_id"], len(doc["content"]))
        else:
            logger.warning("[FAILED] %s", sid)

    if new_docs:
        with open(out_path, "a" if not args.force else "w", encoding="utf-8") as f:
            for doc in new_docs:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")
        logger.info("Wrote %d documents → %s", len(new_docs), out_path)
    else:
        logger.info("No new documents to write.")


if __name__ == "__main__":
    main()
