#!/usr/bin/env python3
"""
validate_chromadb_collections.py — ChromaDB collection migration validator
=========================================================================

Validates the four Xiangqi RAG collections after population:
  openings, tactics, endgames, beginner_principles

Checks performed per collection:
  - collection exists
  - count matches knowledge_base.json input
  - documents / metadatas / embeddings are retrievable
  - metadata["collection"] matches the collection name
  - canonical semantic query ranks the intended collection best
  - cross-collection query isolation
  - duplicate document leakage across collections

Outputs:
  - manifests/chromadb_validation_<timestamp>.json
  - manifests/chromadb_validation_<timestamp>.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_HERE = Path(__file__).resolve().parent
KNOWLEDGE_BASE = _HERE / "json" / "knowledge_base.json"
MANIFESTS_DIR = _HERE / "manifests"

COLLECTIONS = ["openings", "tactics", "endgames", "beginner_principles"]
CHROMA_TENANT = "default_tenant"
CHROMA_DB = "default_database"

DEFAULT_CHROMADB_URL = os.environ.get("CHROMADB_URL", "http://localhost:8000")
DEFAULT_EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8100")

HTTP_TIMEOUT = 30
PAGE_SIZE = 128

CANONICAL_QUERIES = {
    "openings": "central cannon opening strategy control the center early develop pieces in the opening",
    "tactics": "fork attack pin piece clearance tactic dislodge tactical motif",
    "endgames": "king opposition zugzwang practical endgame king and pawn technique",
    "beginner_principles": "develop pieces early protect the king avoid moving the same piece twice beginner fundamentals",
}

ISOLATION_TESTS = [
    {
        "query": "develop pieces early and control the center",
        "expected_best": "openings",
        "expected_weak": "tactics",
        "label": "opening concept in tactics",
    },
    {
        "query": "fork attack with tactical motif",
        "expected_best": "tactics",
        "expected_weak": "openings",
        "label": "tactical concept in openings",
    },
    {
        "query": "king opposition and zugzwang in practical endgames",
        "expected_best": "endgames",
        "expected_weak": "openings",
        "label": "endgame concept in openings",
    },
    {
        "query": "basic opening fundamentals for beginners",
        "expected_best": "beginner_principles",
        "expected_weak": "tactics",
        "label": "beginner concept in tactics",
    },
]


@dataclass
class QueryResult:
    collection: str
    top_distance: float | None
    top_id: str | None
    top_document: str | None
    result_count: int


def _base(chromadb_url: str) -> str:
    return f"{chromadb_url}/api/v2/tenants/{CHROMA_TENANT}/databases/{CHROMA_DB}"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _preview(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _safe_get(mapping: dict[str, Any], key: str, default: Any) -> Any:
    value = mapping.get(key, default)
    return default if value is None else value


class Validator:
    def __init__(self, chromadb_url: str, embedding_url: str, knowledge_base_path: Path) -> None:
        self.chromadb_url = chromadb_url.rstrip("/")
        self.embedding_url = embedding_url.rstrip("/")
        self.knowledge_base_path = knowledge_base_path
        self.session = requests.Session()
        self.kb = self._load_knowledge_base()
        self.collection_ids: dict[str, str] = {}

    def _load_knowledge_base(self) -> dict[str, Any]:
        with open(self.knowledge_base_path, encoding="utf-8") as handle:
            return json.load(handle)

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        expected: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> Any:
        response = self.session.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {url} failed ({response.status_code}): {response.text[:500]}")
        if not response.content:
            return None
        return response.json()

    def check_health(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for name, url in {
            "chromadb": f"{self.chromadb_url}/api/v2/heartbeat",
            "embedding": f"{self.embedding_url}/health",
        }.items():
            try:
                response = self.session.get(url, timeout=10)
                results[name] = {
                    "ok": response.status_code == 200,
                    "status_code": response.status_code,
                }
            except requests.RequestException as exc:
                results[name] = {"ok": False, "error": str(exc)}
        return results

    def expected_counts(self) -> dict[str, int]:
        collections = self.kb.get("collections", {})
        return {
            name: len(_safe_get(_safe_get(collections, name, {}), "chunks", []))
            for name in COLLECTIONS
        }

    def resolve_collection_id(self, collection: str) -> str:
        if collection in self.collection_ids:
            return self.collection_ids[collection]
        payload = self._request_json(
            "GET",
            f"{_base(self.chromadb_url)}/collections/{collection}",
        )
        collection_id = payload["id"]
        self.collection_ids[collection] = collection_id
        return collection_id

    def collection_count(self, collection: str) -> int:
        collection_id = self.resolve_collection_id(collection)
        for ref in (collection, collection_id):
            try:
                payload = self._request_json("GET", f"{_base(self.chromadb_url)}/collections/{ref}/count")
                if isinstance(payload, int):
                    return payload
                if isinstance(payload, dict) and "count" in payload:
                    return int(payload["count"])
            except RuntimeError:
                continue
        raise RuntimeError(f"Unable to retrieve count for collection {collection}")

    def embed_query(self, text: str) -> list[float]:
        payload = self._request_json(
            "POST",
            f"{self.embedding_url}/embed",
            json={"texts": [text]},
        )
        embeddings = payload.get("embeddings", [])
        if not embeddings:
            raise RuntimeError("Embedding service returned no embeddings")
        return embeddings[0]

    def query_collection(self, collection: str, text: str, n_results: int = 3) -> QueryResult:
        collection_id = self.resolve_collection_id(collection)
        embedding = self.embed_query(text)
        payload = self._request_json(
            "POST",
            f"{_base(self.chromadb_url)}/collections/{collection_id}/query",
            json={
                "query_embeddings": [embedding],
                "n_results": n_results,
                "include": ["documents", "distances", "metadatas"],
            },
        )
        ids = payload.get("ids", [[]])
        docs = payload.get("documents", [[]])
        distances = payload.get("distances", [[]])
        flat_ids = ids[0] if ids else []
        flat_docs = docs[0] if docs else []
        flat_distances = distances[0] if distances else []
        return QueryResult(
            collection=collection,
            top_distance=flat_distances[0] if flat_distances else None,
            top_id=flat_ids[0] if flat_ids else None,
            top_document=flat_docs[0] if flat_docs else None,
            result_count=len(flat_ids),
        )

    def get_page(self, collection: str, offset: int, limit: int) -> dict[str, Any]:
        collection_id = self.resolve_collection_id(collection)
        return self._request_json(
            "POST",
            f"{_base(self.chromadb_url)}/collections/{collection_id}/get",
            json={
                "limit": limit,
                "offset": offset,
                "include": ["documents", "metadatas", "embeddings"],
            },
        )

    def get_all_rows(self, collection: str, expected_total: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while offset < expected_total:
            page = self.get_page(collection, offset, min(PAGE_SIZE, expected_total - offset))
            ids = page.get("ids") or []
            docs = page.get("documents") or []
            metas = page.get("metadatas") or []
            embeddings = page.get("embeddings") or []
            if not ids:
                break
            for index, chunk_id in enumerate(ids):
                rows.append(
                    {
                        "id": chunk_id,
                        "document": docs[index] if index < len(docs) else None,
                        "metadata": metas[index] if index < len(metas) else None,
                        "embedding": embeddings[index] if index < len(embeddings) else None,
                    }
                )
            offset += len(ids)
        return rows

    def evaluate(self) -> dict[str, Any]:
        health = self.check_health()
        if not all(item.get("ok") for item in health.values()):
            return {
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "status": "blocked",
                "health": health,
                "error": "ChromaDB or embedding service is unavailable",
            }

        expected_counts = self.expected_counts()
        collections_report: dict[str, Any] = {}
        all_doc_hashes: dict[str, list[dict[str, str]]] = defaultdict(list)

        for collection in COLLECTIONS:
            expected = expected_counts[collection]
            collection_id = self.resolve_collection_id(collection)
            actual = self.collection_count(collection)
            rows = self.get_all_rows(collection, actual)

            metadata_mismatches: list[dict[str, Any]] = []
            missing_documents = 0
            missing_metadatas = 0
            missing_embeddings = 0

            for row in rows:
                document = row.get("document")
                metadata = row.get("metadata") or {}
                embedding = row.get("embedding")

                if not document:
                    missing_documents += 1
                if not metadata:
                    missing_metadatas += 1
                if not embedding:
                    missing_embeddings += 1

                if metadata and metadata.get("collection") != collection:
                    metadata_mismatches.append(
                        {
                            "id": row["id"],
                            "collection": metadata.get("collection"),
                        }
                    )

                if document:
                    all_doc_hashes[_sha(_normalize_text(document))].append(
                        {"collection": collection, "id": row["id"], "preview": _preview(document, 120)}
                    )

            structure_sample = self.get_page(collection, 0, 1) if actual else {}
            collections_report[collection] = {
                "collection_id": collection_id,
                "expected_count": expected,
                "actual_count": actual,
                "count_matches_input": actual == expected,
                "exists": True,
                "retrieved_rows": len(rows),
                "structural_keys": sorted(structure_sample.keys()),
                "has_ids": bool(structure_sample.get("ids") or actual == 0),
                "has_documents": bool(structure_sample.get("documents") or actual == 0),
                "has_metadatas": bool(structure_sample.get("metadatas") or actual == 0),
                "has_embeddings": bool(structure_sample.get("embeddings") or actual == 0),
                "missing_documents": missing_documents,
                "missing_metadatas": missing_metadatas,
                "missing_embeddings": missing_embeddings,
                "metadata_collection_mismatches": metadata_mismatches,
                "sample_collection_metadata": [
                    (row.get("metadata") or {}).get("collection") for row in rows[:5]
                ],
                "sample_ids": [row["id"] for row in rows[:5]],
                "sample_previews": [_preview(row.get("document") or "") for row in rows[:3]],
            }

        semantic_matrix: dict[str, dict[str, Any]] = {}
        for expected_collection, query in CANONICAL_QUERIES.items():
            per_collection: dict[str, Any] = {}
            ranked: list[QueryResult] = []
            for collection in COLLECTIONS:
                result = self.query_collection(collection, query)
                ranked.append(result)
                per_collection[collection] = {
                    "top_distance": result.top_distance,
                    "top_id": result.top_id,
                    "top_preview": _preview(result.top_document or ""),
                    "result_count": result.result_count,
                }

            ranked.sort(key=lambda item: math.inf if item.top_distance is None else item.top_distance)
            best = ranked[0] if ranked else None
            semantic_matrix[expected_collection] = {
                "query": query,
                "expected_best": expected_collection,
                "actual_best": best.collection if best else None,
                "pass": best is not None and best.collection == expected_collection,
                "results": per_collection,
            }

        isolation_results: list[dict[str, Any]] = []
        for test in ISOLATION_TESTS:
            ranked: list[QueryResult] = []
            for collection in COLLECTIONS:
                ranked.append(self.query_collection(collection, test["query"]))
            ranked.sort(key=lambda item: math.inf if item.top_distance is None else item.top_distance)

            best = ranked[0] if ranked else None
            weak = next((item for item in ranked if item.collection == test["expected_weak"]), None)
            expected = next((item for item in ranked if item.collection == test["expected_best"]), None)
            passed = bool(
                best is not None
                and best.collection == test["expected_best"]
                and expected is not None
                and weak is not None
                and expected.top_distance is not None
                and weak.top_distance is not None
                and expected.top_distance < weak.top_distance
            )

            isolation_results.append(
                {
                    **test,
                    "actual_best": best.collection if best else None,
                    "pass": passed,
                    "ranking": [
                        {
                            "collection": item.collection,
                            "top_distance": item.top_distance,
                            "top_id": item.top_id,
                            "top_preview": _preview(item.top_document or ""),
                        }
                        for item in ranked
                    ],
                }
            )

        duplicate_leakage = []
        for digest, refs in all_doc_hashes.items():
            involved = sorted({item["collection"] for item in refs})
            if len(involved) > 1:
                duplicate_leakage.append(
                    {
                        "hash": digest,
                        "collections": involved,
                        "occurrences": refs,
                    }
                )

        summary = {
            "count_checks_passed": all(item["count_matches_input"] for item in collections_report.values()),
            "structure_checks_passed": all(
                item["has_ids"] and item["has_documents"] and item["has_metadatas"] and item["has_embeddings"]
                for item in collections_report.values()
            ),
            "metadata_checks_passed": all(
                not item["metadata_collection_mismatches"] for item in collections_report.values()
            ),
            "semantic_checks_passed": all(item["pass"] for item in semantic_matrix.values()),
            "isolation_checks_passed": all(item["pass"] for item in isolation_results),
            "duplicate_leakage_detected": bool(duplicate_leakage),
        }
        summary["overall_pass"] = all(
            [
                summary["count_checks_passed"],
                summary["structure_checks_passed"],
                summary["metadata_checks_passed"],
                summary["semantic_checks_passed"],
                summary["isolation_checks_passed"],
                not summary["duplicate_leakage_detected"],
            ]
        )

        return {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if summary["overall_pass"] else "failed",
            "health": health,
            "summary": summary,
            "collections": collections_report,
            "semantic_matrix": semantic_matrix,
            "isolation_tests": isolation_results,
            "duplicate_leakage": duplicate_leakage,
        }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# ChromaDB Collection Validation Report")
    lines.append("")
    lines.append(f"- Run at: {report.get('ran_at', 'unknown')}")
    lines.append(f"- Status: {report.get('status', 'unknown')}")
    lines.append("")

    health = report.get("health", {})
    lines.append("## Service Health")
    lines.append("")
    for name, result in health.items():
        if result.get("ok"):
            lines.append(f"- {name}: OK (HTTP {result.get('status_code')})")
        else:
            detail = result.get("error") or f"HTTP {result.get('status_code')}"
            lines.append(f"- {name}: FAIL ({detail})")
    lines.append("")

    summary = report.get("summary", {})
    lines.append("## Executive Summary")
    lines.append("")
    for key in [
        "count_checks_passed",
        "structure_checks_passed",
        "metadata_checks_passed",
        "semantic_checks_passed",
        "isolation_checks_passed",
        "duplicate_leakage_detected",
        "overall_pass",
    ]:
        lines.append(f"- {key}: {summary.get(key)}")
    lines.append("")

    lines.append("## Collection Counts")
    lines.append("")
    lines.append("| Collection | Expected | Actual | Match | Metadata label sample |")
    lines.append("|---|---:|---:|---|---|")
    for collection, details in report.get("collections", {}).items():
        sample = ", ".join(str(item) for item in details.get("sample_collection_metadata", []))
        lines.append(
            f"| {collection} | {details.get('expected_count', 0)} | {details.get('actual_count', 0)} | {details.get('count_matches_input')} | {sample} |"
        )
    lines.append("")

    lines.append("## Structural Integrity")
    lines.append("")
    for collection, details in report.get("collections", {}).items():
        lines.append(f"### {collection}")
        lines.append("")
        lines.append(f"- collection_id: {details.get('collection_id')}")
        lines.append(f"- structural_keys: {details.get('structural_keys')}")
        lines.append(f"- has_ids: {details.get('has_ids')}")
        lines.append(f"- has_documents: {details.get('has_documents')}")
        lines.append(f"- has_metadatas: {details.get('has_metadatas')}")
        lines.append(f"- has_embeddings: {details.get('has_embeddings')}")
        lines.append(f"- missing_documents: {details.get('missing_documents')}")
        lines.append(f"- missing_metadatas: {details.get('missing_metadatas')}")
        lines.append(f"- missing_embeddings: {details.get('missing_embeddings')}")
        mismatches = details.get("metadata_collection_mismatches", [])
        if mismatches:
            lines.append(f"- metadata mismatches: {len(mismatches)}")
            for mismatch in mismatches[:5]:
                lines.append(f"- mismatch sample: id={mismatch.get('id')} metadata.collection={mismatch.get('collection')}")
        else:
            lines.append("- metadata mismatches: 0")
        for preview in details.get("sample_previews", []):
            lines.append(f"- sample: {preview}")
        lines.append("")

    lines.append("## Canonical Semantic Queries")
    lines.append("")
    for expected, details in report.get("semantic_matrix", {}).items():
        lines.append(f"### {expected}")
        lines.append("")
        lines.append(f"- query: {details.get('query')}")
        lines.append(f"- expected_best: {details.get('expected_best')}")
        lines.append(f"- actual_best: {details.get('actual_best')}")
        lines.append(f"- pass: {details.get('pass')}")
        lines.append("")
        lines.append("| Collection | Top distance | Top id | Preview |")
        lines.append("|---|---:|---|---|")
        for collection, result in details.get("results", {}).items():
            lines.append(
                f"| {collection} | {result.get('top_distance')} | {result.get('top_id') or ''} | {result.get('top_preview') or ''} |"
            )
        lines.append("")

    lines.append("## Cross-Collection Isolation Tests")
    lines.append("")
    for test in report.get("isolation_tests", []):
        lines.append(f"### {test.get('label')}")
        lines.append("")
        lines.append(f"- query: {test.get('query')}")
        lines.append(f"- expected_best: {test.get('expected_best')}")
        lines.append(f"- expected_weak: {test.get('expected_weak')}")
        lines.append(f"- actual_best: {test.get('actual_best')}")
        lines.append(f"- pass: {test.get('pass')}")
        lines.append("")
        lines.append("| Rank | Collection | Top distance | Top id | Preview |")
        lines.append("|---:|---|---:|---|---|")
        for index, item in enumerate(test.get("ranking", []), start=1):
            lines.append(
                f"| {index} | {item.get('collection')} | {item.get('top_distance')} | {item.get('top_id') or ''} | {item.get('top_preview') or ''} |"
            )
        lines.append("")

    lines.append("## Duplicate Leakage")
    lines.append("")
    duplicates = report.get("duplicate_leakage", [])
    if not duplicates:
        lines.append("- No duplicate documents detected across collections.")
    else:
        lines.append(f"- Duplicate groups detected: {len(duplicates)}")
        for duplicate in duplicates[:10]:
            lines.append(f"- Collections: {', '.join(duplicate.get('collections', []))}")
            for occurrence in duplicate.get("occurrences", [])[:6]:
                lines.append(
                    f"- occurrence: {occurrence.get('collection')} {occurrence.get('id')} {occurrence.get('preview')}"
                )
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_prefix: str | None) -> tuple[Path, Path]:
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = output_prefix or f"chromadb_validation_{timestamp}"
    json_path = MANIFESTS_DIR / f"{stem}.json"
    md_path = MANIFESTS_DIR / f"{stem}.md"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
        handle.write("\n")

    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ChromaDB collection migration and separation")
    parser.add_argument("--chromadb-url", default=DEFAULT_CHROMADB_URL)
    parser.add_argument("--embedding-url", default=DEFAULT_EMBEDDING_URL)
    parser.add_argument("--input", default=str(KNOWLEDGE_BASE), help="Path to knowledge_base.json")
    parser.add_argument("--output-prefix", help="Output filename stem written under manifests/")
    args = parser.parse_args()

    validator = Validator(
        chromadb_url=args.chromadb_url,
        embedding_url=args.embedding_url,
        knowledge_base_path=Path(args.input),
    )
    report = validator.evaluate()
    json_path, md_path = write_outputs(report, args.output_prefix)

    print(json.dumps(
        {
            "status": report.get("status"),
            "overall_pass": report.get("summary", {}).get("overall_pass"),
            "json_report": str(json_path),
            "markdown_report": str(md_path),
        },
        ensure_ascii=False,
        indent=2,
    ))

    if report.get("status") == "blocked" or not report.get("summary", {}).get("overall_pass", False):
        sys.exit(1)


if __name__ == "__main__":
    main()