#!/usr/bin/env python3
"""Research and review workflow for strategy glossary explanations.

This Phase 1 pipeline keeps the final dictionary minimal:
    [{"term": "...", "definition": "...", "source": "..."}]

It adds a review-oriented sidecar JSONL with candidate rewrites for weak
strategy definitions:
    {"term", "current_definition", "proposed_definition", "source",
     "evidence_urls", "evidence_snippets", "confidence", "status", "reason"}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from finetunning.build_dictionary import (
    BeautifulSoup,
    CURATED_DEFINITIONS,
    DEFAULT_CACHE_DIR,
    DEFAULT_DATASETS,
    DEFAULT_KNOWLEDGE_FILES,
    DEFAULT_WEB_SOURCES,
    compact_spaces,
    has_cjk,
    html_to_text,
    normalize_term,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DICTIONARY = REPO_ROOT / "finetunning/data/dictionary.json"
DEFAULT_CANDIDATES = REPO_ROOT / "finetunning/data/dictionary_candidates.strategy.jsonl"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; XiangqiStrategyDictionaryAgent/1.0; "
        "+https://github.com/GuchaIll/Capstone_Guided_Chinese_Chess)"
    ),
}
SEARCH_TIMEOUT_SECONDS = 8
FETCH_TIMEOUT_SECONDS = 8
CHECKPOINT_EVERY = 10
STRATEGY_HINTS = (
    "中炮",
    "屏風馬",
    "屏风马",
    "順炮",
    "顺炮",
    "過宮炮",
    "过宫炮",
    "飛相",
    "飞相",
    "反宮馬",
    "反宫马",
    "仙人指路",
    "士角炮",
    "三步虎",
    "單提馬",
    "单提马",
    "列炮",
    "兩頭蛇",
    "两头蛇",
    "巡河",
    "過河車",
    "过河车",
    "残局攻杀谱",
    "基本杀法",
    "梦入神机",
    "殺着",
    "杀着",
)
GENERIC_DEFINITION_PATTERNS = (
    re.compile(r"^A named Xiangqi opening or opening variation", re.I),
    re.compile(r"^A named basic kill pattern in Xiangqi\.?$", re.I),
    re.compile(r"^A named classical Xiangqi composition or study", re.I),
    re.compile(r"^An endgame attacking class in the .*taxonomy", re.I),
    re.compile(r"^A Xiangqi taxonomy", re.I),
)
SOURCE_QUALITY_HINTS = {
    "xqinenglish.com": 1.0,
    "xiangqi.com": 0.85,
    "wxf-xiangqi.org": 0.8,
    "chessdb.cn": 0.6,
}
FORUMISH_HINTS = ("forum", "reddit", "bbs", "贴吧", "stackexchange")


@dataclass(frozen=True)
class StrategyTerm:
    term: str
    kind: str
    taxonomy: str
    query_hint: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    provider_rank: int


@dataclass(frozen=True)
class PageDocument:
    url: str
    title: str
    text: str


@dataclass(frozen=True)
class Evidence:
    url: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True)
class WorkItem:
    strategy: StrategyTerm
    current_definition: str
    current_source: str
    action: str
    reason: str


class SearchProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str) -> list[SearchResult]:
        raise NotImplementedError


class DefinitionSynthesizer(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def summarize(self, term: str, strategy: StrategyTerm, evidence: list[Evidence]) -> str:
        raise NotImplementedError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draft/apply strategy dictionary explanation candidates")
    parser.add_argument("--mode", choices=("draft", "approve", "apply"), default="draft")
    parser.add_argument("--terms", choices=("strategy",), default="strategy")
    parser.add_argument("--dictionary", default=str(DEFAULT_DICTIONARY))
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--search-provider", default="auto")
    parser.add_argument("--max-terms", type=int, default=0, help="0 means no limit")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--approve-threshold", type=float, default=0.75)
    parser.add_argument("--approve-limit", type=int, default=0, help="0 means no limit")
    return parser.parse_args()


def load_dictionary(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Dictionary must be a JSON list: {path}")
    cleaned: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        term = compact_spaces(str(row.get("term", "")))
        definition = compact_spaces(str(row.get("definition", "")))
        source = compact_spaces(str(row.get("source", "")))
        if not term:
            continue
        cleaned.append({"term": term, "definition": definition, "source": source})
    return cleaned


def iter_jsonl(path: Path) -> Iterable[dict]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def to_halfwidth(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def clean_term(text: str) -> str:
    normalized, _ = normalize_term(text)
    return compact_spaces(to_halfwidth(normalized))


def guess_strategy_kind(raw_term: str, source_name: str) -> tuple[str, str, str]:
    term = clean_term(raw_term)
    _, meta = normalize_term(raw_term)
    taxonomy = meta.get("taxonomy", "")

    if source_name == "opening-repertoire" or any(hint in term for hint in STRATEGY_HINTS[:17]):
        return "opening", taxonomy, "opening variation strategy"
    if source_name == "basic-checkmates" or taxonomy == "基本杀法":
        return "basic_kill", "基本杀法", "basic kill mating pattern"
    if source_name == "advanced-checkmates" or term.endswith("类") or "杀着" in term:
        return "endgame_attack_class", "残局攻杀谱", "attacking endgame class"
    if source_name == "meng-ru-shen-ji" or taxonomy == "梦入神机":
        return "manual", "梦入神机", "classical composition strategy"
    return "strategy", taxonomy, "xiangqi strategy"


def is_strategy_term(term: str, kind: str = "") -> bool:
    if term in CURATED_DEFINITIONS:
        return True
    if kind in {"opening", "basic_kill", "endgame_attack_class", "manual"}:
        return True
    if not term or not has_cjk(term):
        return False
    if len(term) > 48:
        return False
    return any(hint in term for hint in STRATEGY_HINTS)


def load_strategy_terms() -> dict[str, StrategyTerm]:
    terms: dict[str, StrategyTerm] = {}

    for path in DEFAULT_KNOWLEDGE_FILES:
        if not path.exists():
            continue
        source_name = path.stem
        for row in read_json(path):
            raw_term = compact_spaces(str(row.get("name", "")))
            if not raw_term:
                continue
            term = clean_term(raw_term)
            kind, taxonomy, hint = guess_strategy_kind(raw_term, source_name)
            if is_strategy_term(term, kind):
                terms.setdefault(term, StrategyTerm(term=term, kind=kind, taxonomy=taxonomy, query_hint=hint))

    for dataset in DEFAULT_DATASETS:
        if not dataset.exists():
            continue
        for row in iter_jsonl(dataset):
            text = str(row.get("text", ""))
            if "<|assistant|>" not in text:
                continue
            assistant = text.split("<|assistant|>\n", 1)[-1].strip()
            if not assistant.startswith("This position demonstrates "):
                continue
            raw_term = assistant[len("This position demonstrates ") :].rstrip(".")
            term = clean_term(raw_term)
            kind, taxonomy, hint = guess_strategy_kind(raw_term, "dataset")
            if is_strategy_term(term, kind):
                terms.setdefault(term, StrategyTerm(term=term, kind=kind, taxonomy=taxonomy, query_hint=hint))

    for term, (_, source) in CURATED_DEFINITIONS.items():
        if term == "基本杀法":
            kind = "basic_kill"
            taxonomy = "基本杀法"
            hint = "basic kill mating pattern"
        elif term == "残局攻杀谱":
            kind = "endgame_attack_class"
            taxonomy = "残局攻杀谱"
            hint = "attacking endgame class"
        elif term == "梦入神机":
            kind = "manual"
            taxonomy = "梦入神机"
            hint = "classical composition strategy"
        else:
            kind = "strategy"
            taxonomy = ""
            hint = "xiangqi strategy"
        terms.setdefault(term, StrategyTerm(term=term, kind=kind, taxonomy=taxonomy, query_hint=hint))

    return dict(sorted(terms.items()))


def strategy_terms_from_dictionary(rows: list[dict[str, str]]) -> dict[str, StrategyTerm]:
    terms: dict[str, StrategyTerm] = {}
    for row in rows:
        term = clean_term(row["term"])
        kind, taxonomy, hint = guess_strategy_kind(term, "dictionary")
        if is_strategy_term(term, kind):
            terms.setdefault(term, StrategyTerm(term=term, kind=kind, taxonomy=taxonomy, query_hint=hint))
    return terms


def is_reference_noise(text: str) -> bool:
    lowered = text.lower()
    bad_markers = (
        "reference material",
        "works cited",
        "references",
        "isbn",
        "http://",
        "https://",
        "出版社",
        "self-explanatory",
    )
    return any(marker in lowered for marker in bad_markers)


def is_move_tree_only(text: str) -> bool:
    if not text:
        return True
    notation_hits = len(re.findall(r"[A-Z]?\d[=+\-]\d", text))
    word_hits = len(re.findall(r"[A-Za-z]{4,}", text))
    if notation_hits >= 2 and word_hits < 6:
        return True
    return False


def rewrite_reason(term: str, strategy: StrategyTerm, definition: str) -> str | None:
    definition = compact_spaces(definition)
    curated = CURATED_DEFINITIONS.get(term)
    if curated and definition == curated[0]:
        return None
    if not definition:
        return "missing definition"
    if is_reference_noise(definition):
        return "reference or glossary noise"
    if any(pattern.search(definition) for pattern in GENERIC_DEFINITION_PATTERNS):
        return "generic placeholder definition"
    if len(definition) > 180:
        return "definition is too long or excerpt-like"
    if strategy.kind in {"opening", "basic_kill", "endgame_attack_class", "manual"} and is_move_tree_only(definition):
        return "definition is mostly move notation without explanation"
    if strategy.kind == "opening" and "family" in definition.lower() and "variation" in definition.lower():
        return "family-level boilerplate without explanatory detail"
    return None


def collect_worklist(
    dictionary_rows: list[dict[str, str]],
    strategy_terms: dict[str, StrategyTerm],
) -> list[WorkItem]:
    by_term = {clean_term(row["term"]): row for row in dictionary_rows}
    worklist: list[WorkItem] = []

    for term, strategy in strategy_terms.items():
        current = by_term.get(term)
        current_definition = current["definition"] if current else ""
        current_source = current["source"] if current else ""
        reason = rewrite_reason(term, strategy, current_definition)
        action = "needs_rewrite" if reason else "keep"
        worklist.append(
            WorkItem(
                strategy=strategy,
                current_definition=current_definition,
                current_source=current_source,
                action=action,
                reason=reason or "definition is already acceptable",
            )
        )

    return worklist


def load_cached_documents() -> dict[str, PageDocument]:
    docs: dict[str, PageDocument] = {}
    cache_dir = DEFAULT_CACHE_DIR
    for source in DEFAULT_WEB_SOURCES:
        path = cache_dir / f"{source['source_id']}.html"
        if not path.exists():
            continue
        text = html_to_text(path.read_text(encoding="utf-8"))
        docs[source["url"]] = PageDocument(url=source["url"], title=source["title"], text=text)
    return docs


class PageFetcher:
    def __init__(self) -> None:
        self.cached_docs = load_cached_documents()

    def fetch(self, url: str) -> PageDocument | None:
        if url in self.cached_docs:
            return self.cached_docs[url]

        if url.startswith("file://"):
            path = Path(url[7:])
            if path.exists():
                return PageDocument(url=url, title=path.stem, text=html_to_text(path.read_text(encoding="utf-8")))
            return None

        request = Request(url, headers=HEADERS)
        try:
            with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError):
            return None

        title = url
        if "<title>" in html.lower():
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if m:
                title = compact_spaces(m.group(1))
        return PageDocument(url=url, title=title, text=html_to_text(html))


class LocalCacheSearchProvider(SearchProvider):
    def __init__(self) -> None:
        self.docs = list(load_cached_documents().values())

    def name(self) -> str:
        return "local_cache"

    def search(self, query: str) -> list[SearchResult]:
        term = query.split(" xiangqi", 1)[0].split(" 象棋", 1)[0].strip()
        results: list[SearchResult] = []
        for doc in self.docs:
            haystack = f"{doc.title}\n{doc.text}"
            if term not in haystack:
                continue
            snippet = extract_evidence_snippet(term, doc.text) or ""
            results.append(
                SearchResult(
                    title=doc.title,
                    url=doc.url,
                    snippet=snippet,
                    provider=self.name(),
                    provider_rank=len(results),
                )
            )
        return results


class CombinedSearchProvider(SearchProvider):
    def __init__(self, *providers: SearchProvider) -> None:
        self.providers = providers

    def name(self) -> str:
        return "+".join(provider.name() for provider in self.providers)

    def search(self, query: str) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for provider in self.providers:
            try:
                provider_results = provider.search(query)
            except Exception:
                provider_results = []
            for result in provider_results:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)
        return results


class BraveSearchProvider(SearchProvider):
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def name(self) -> str:
        return "brave"

    def search(self, query: str) -> list[SearchResult]:
        params = urlencode({"q": query, "count": 10})
        request = Request(
            f"{self.endpoint}?{params}",
            headers={
                **HEADERS,
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError):
            return []
        rows = payload.get("web", {}).get("results", [])
        return [
            SearchResult(
                title=compact_spaces(str(row.get("title", ""))),
                url=str(row.get("url", "")),
                snippet=compact_spaces(str(row.get("description", ""))),
                provider=self.name(),
                provider_rank=i,
            )
            for i, row in enumerate(rows)
            if row.get("url")
        ]


class SerpAPISearchProvider(SearchProvider):
    endpoint = "https://serpapi.com/search.json"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def name(self) -> str:
        return "serpapi"

    def search(self, query: str) -> list[SearchResult]:
        params = urlencode({"q": query, "api_key": self.api_key, "engine": "google", "num": 10})
        request = Request(f"{self.endpoint}?{params}", headers={**HEADERS, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError):
            return []
        rows = payload.get("organic_results", [])
        return [
            SearchResult(
                title=compact_spaces(str(row.get("title", ""))),
                url=str(row.get("link", "")),
                snippet=compact_spaces(str(row.get("snippet", ""))),
                provider=self.name(),
                provider_rank=i,
            )
            for i, row in enumerate(rows)
            if row.get("link")
        ]


class DuckDuckGoHTMLSearchProvider(SearchProvider):
    endpoint = "https://html.duckduckgo.com/html/"

    def name(self) -> str:
        return "duckduckgo_html"

    def search(self, query: str) -> list[SearchResult]:
        payload = urlencode({"q": query}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError):
            return []

        results: list[SearchResult] = []
        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "html.parser")
            for idx, anchor in enumerate(soup.select("a.result__a")):
                title = compact_spaces(anchor.get_text(" ", strip=True))
                raw_url = anchor.get("href", "")
                snippet_el = anchor.find_parent("div", class_="result")
                snippet = ""
                if snippet_el is not None:
                    snippet_node = snippet_el.select_one(".result__snippet")
                    if snippet_node is not None:
                        snippet = compact_spaces(snippet_node.get_text(" ", strip=True))
                url = compact_spaces(raw_url)
                if title and url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            provider=self.name(),
                            provider_rank=idx,
                        )
                    )
        else:
            for idx, match in enumerate(
                re.finditer(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                    html,
                    re.I | re.S,
                )
            ):
                title = compact_spaces(re.sub(r"<[^>]+>", " ", match.group(2)))
                url = compact_spaces(match.group(1))
                if title and url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet="",
                            provider=self.name(),
                            provider_rank=idx,
                        )
                    )
        return results


def build_search_provider(name: str) -> SearchProvider:
    if name == "auto":
        local_cache = LocalCacheSearchProvider()
        if os.environ.get("SERPAPI_API_KEY"):
            return CombinedSearchProvider(SerpAPISearchProvider(os.environ["SERPAPI_API_KEY"]), local_cache)
        if os.environ.get("BRAVE_SEARCH_API_KEY"):
            return CombinedSearchProvider(BraveSearchProvider(os.environ["BRAVE_SEARCH_API_KEY"]), local_cache)
        return CombinedSearchProvider(DuckDuckGoHTMLSearchProvider(), local_cache)
    if name == "serpapi":
        return SerpAPISearchProvider(os.environ["SERPAPI_API_KEY"])
    if name == "brave":
        return BraveSearchProvider(os.environ["BRAVE_SEARCH_API_KEY"])
    if name == "duckduckgo_html":
        return DuckDuckGoHTMLSearchProvider()
    if name == "local_cache":
        return LocalCacheSearchProvider()
    raise ValueError(f"Unknown search provider: {name}")


def domain_score(url: str) -> float:
    for hint, score in SOURCE_QUALITY_HINTS.items():
        if hint in url:
            return score
    return 0.4


def title_term_score(term: str, title: str) -> float:
    score = 0.0
    if term in title:
        score += 1.0
    if term.replace("-", "") in title.replace("-", ""):
        score += 0.3
    return score


def result_reject_reason(term: str, result: SearchResult) -> str | None:
    lowered = f"{result.title} {result.snippet} {result.url}".lower()
    if any(hint in lowered for hint in FORUMISH_HINTS):
        return "forum-like result"
    if "reference" in lowered or "works cited" in lowered:
        return "reference page"
    if term not in (result.title + " " + result.snippet):
        return "term not present in title/snippet"
    return None


def rank_search_results(term: str, strategy: StrategyTerm, results: list[SearchResult]) -> list[SearchResult]:
    ranked: list[tuple[float, SearchResult]] = []
    for result in results:
        if result_reject_reason(term, result):
            continue
        score = 0.0
        score += title_term_score(term, result.title) * 3.0
        score += domain_score(result.url) * 2.0
        score += max(0.0, 1.0 - (result.provider_rank * 0.08))
        if strategy.kind == "opening" and ("opening" in result.title.lower() or "opening" in result.snippet.lower()):
            score += 0.7
        if strategy.kind == "basic_kill" and ("kill" in result.title.lower() or "checkmate" in result.title.lower()):
            score += 0.7
        if strategy.kind == "manual" and ("manual" in result.title.lower() or "composition" in result.snippet.lower()):
            score += 0.7
        ranked.append((score, result))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in ranked]


def extract_evidence_snippet(term: str, text: str) -> str:
    lines = [compact_spaces(line) for line in text.splitlines() if compact_spaces(line)]
    for line in lines:
        if term in line and ":" in line:
            return line

    for line in lines:
        if term in line:
            line = re.split(r"References|Works Cited", line, maxsplit=1, flags=re.I)[0]
            if line:
                return line[:320]
    return ""


def evidence_reject_reason(term: str, snippet: str) -> str | None:
    if not snippet:
        return "no matching snippet"
    if is_reference_noise(snippet):
        return "reference-only snippet"
    if term not in snippet and term.replace("-", "") not in snippet.replace("-", ""):
        return "term missing from snippet"
    return None


class HeuristicSynthesizer(DefinitionSynthesizer):
    def name(self) -> str:
        return "heuristic"

    def summarize(self, term: str, strategy: StrategyTerm, evidence: list[Evidence]) -> str:
        if not evidence:
            return ""
        snippet = compact_spaces(evidence[0].snippet)
        snippet = snippet.replace(term, "", 1).strip(" ,:-")

        if ":" in snippet:
            head, tail = [compact_spaces(part) for part in snippet.split(":", 1)]
            head = head.strip(" ,:-")
            if tail:
                body = first_sentence(clean_candidate_text(tail))
                if body:
                    if head and strategy.kind == "opening" and not any(
                        token in body.lower() for token in ("opening", "defense", "variation")
                    ):
                        return ensure_one_sentence(f"{head} is a Xiangqi opening or defense in which {lowercase_first(body)}")
                    return ensure_one_sentence(body)
            if head:
                return ensure_one_sentence(clean_candidate_text(head))

        body = clean_candidate_text(snippet)
        if strategy.kind == "opening" and "opening" not in body.lower() and "defense" not in body.lower():
            body = f"{term} is a Xiangqi opening or opening variation. {body}"
        return ensure_one_sentence(first_sentence(body))


class OpenAISynthesizer(DefinitionSynthesizer):
    endpoint = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def name(self) -> str:
        return "openai"

    def summarize(self, term: str, strategy: StrategyTerm, evidence: list[Evidence]) -> str:
        snippets = "\n\n".join(f"- {ev.title}: {ev.snippet}" for ev in evidence[:3])
        prompt = (
            "Write exactly one plain-English sentence explaining the Xiangqi strategy term below.\n"
            "Start with the term or its family meaning, be definitional first, and avoid bibliography or move-tree noise.\n"
            "Only mention move notation if it is essential to the definition.\n\n"
            f"Term: {term}\n"
            f"Kind: {strategy.kind}\n"
            f"Evidence:\n{snippets}\n"
        )
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "You produce concise Xiangqi glossary definitions."},
                {"role": "user", "content": prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.endpoint,
            data=data,
            headers={
                **HEADERS,
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        return ensure_one_sentence(first_sentence(clean_candidate_text(content)))


def build_synthesizer() -> DefinitionSynthesizer:
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("STRATEGY_DICTIONARY_OPENAI_MODEL")
    if api_key and model:
        return OpenAISynthesizer(api_key=api_key, model=model)
    return HeuristicSynthesizer()


def first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", compact_spaces(text), maxsplit=1)
    return parts[0] if parts else ""


def lowercase_first(text: str) -> str:
    if not text:
        return ""
    return text[:1].lower() + text[1:]


def clean_candidate_text(text: str) -> str:
    text = compact_spaces(text)
    text = re.sub(r"AXF defn?:.*", "", text, flags=re.I)
    text = re.sub(r"For example,.*", "", text, flags=re.I)
    text = re.sub(r"More on this.*", "", text, flags=re.I)
    text = re.sub(r"Discussion required\..*", "", text, flags=re.I)
    text = re.sub(r"Much to be discussed\..*", "", text, flags=re.I)
    text = re.sub(r"HT Lau called it.*", "", text, flags=re.I)
    text = re.sub(r"\s*\|+\s*", " ", text)
    text = compact_spaces(text)
    return text.rstrip(" :;-")


def ensure_one_sentence(text: str) -> str:
    text = compact_spaces(text)
    if not text:
        return ""
    if len(text) > 220:
        text = text[:217].rstrip(" ,;:-") + "..."
    if text[-1] not in ".!?":
        text += "."
    return text


def build_query(strategy: StrategyTerm) -> str:
    parts = [strategy.term, "xiangqi", "象棋", strategy.query_hint]
    if strategy.taxonomy:
        parts.append(strategy.taxonomy)
    return " ".join(part for part in parts if part)


def summarize_reason(base_reason: str, evidence: list[Evidence], synthesizer: DefinitionSynthesizer) -> str:
    if not evidence:
        return f"{base_reason}; no acceptable evidence found"
    source_hint = evidence[0].title or evidence[0].url
    return f"{base_reason}; drafted from {synthesizer.name()} using {source_hint}"


def candidate_confidence(strategy: StrategyTerm, evidence: list[Evidence], definition: str) -> float:
    if not evidence or not definition:
        return 0.0
    base = min(1.0, evidence[0].score / 5.0)
    if strategy.kind == "opening" and ("opening" in definition.lower() or "defense" in definition.lower()):
        base += 0.1
    if strategy.kind == "basic_kill" and ("kill" in definition.lower() or "checkmate" in definition.lower()):
        base += 0.1
    return round(min(base, 0.99), 2)


def proposal_quality_reason(strategy: StrategyTerm, definition: str) -> str | None:
    definition = compact_spaces(definition)
    if not definition:
        return "missing proposed definition"
    if is_reference_noise(definition):
        return "reference-like proposed definition"
    if definition in {"1.", "1"}:
        return "degenerate move-tree proposal"
    if len(definition) < 18:
        return "proposal too short"
    if is_move_tree_only(definition):
        return "proposal is mostly move notation"
    if strategy.kind == "opening" and not any(
        token in definition.lower() for token in ("opening", "defense", "variation")
    ):
        return "opening proposal lacks explanatory framing"
    return None


def research_term(
    item: WorkItem,
    provider: SearchProvider,
    fetcher: PageFetcher,
    synthesizer: DefinitionSynthesizer,
) -> dict[str, object]:
    query = build_query(item.strategy)
    try:
        provider_results = provider.search(query)
    except Exception:
        provider_results = []
    ranked_results = rank_search_results(item.strategy.term, item.strategy, provider_results)

    evidence: list[Evidence] = []
    for result in ranked_results[:6]:
        page = fetcher.fetch(result.url)
        if not page:
            continue
        snippet = extract_evidence_snippet(item.strategy.term, page.text)
        reject = evidence_reject_reason(item.strategy.term, snippet)
        if reject:
            continue
        score = domain_score(result.url) * 2.5 + title_term_score(item.strategy.term, result.title) * 2.5
        if item.strategy.kind == "opening" and "opening" in (result.title + " " + snippet).lower():
            score += 0.8
        evidence.append(Evidence(url=result.url, title=result.title or page.title, snippet=snippet, score=score))
        if len(evidence) >= 3:
            break

    if evidence:
        proposed = synthesizer.summarize(item.strategy.term, item.strategy, evidence)
        quality_reason = proposal_quality_reason(item.strategy, proposed)
        status = "pending" if proposed and quality_reason is None else "rejected"
        source = evidence[0].url if proposed else ""
        confidence = candidate_confidence(item.strategy, evidence, proposed)
        reason = summarize_reason(
            quality_reason or item.reason,
            evidence,
            synthesizer,
        )
    else:
        proposed = ""
        status = "rejected"
        source = ""
        confidence = 0.0
        reason = summarize_reason(item.reason, evidence, synthesizer)

    return {
        "term": item.strategy.term,
        "current_definition": item.current_definition,
        "proposed_definition": proposed,
        "source": source,
        "evidence_urls": [ev.url for ev in evidence],
        "evidence_snippets": [ev.snippet for ev in evidence],
        "confidence": confidence,
        "status": status,
        "reason": reason,
    }


def write_candidates(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_candidates(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not path.exists():
        return rows
    for row in iter_jsonl(path):
        rows.append(row)
    return rows


def merge_candidate_rows(
    existing_rows: list[dict[str, object]],
    new_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for row in existing_rows:
        term = clean_term(str(row.get("term", "")))
        if term:
            merged[term] = dict(row)

    for row in new_rows:
        term = clean_term(str(row.get("term", "")))
        if not term:
            continue
        prior = merged.get(term)
        if prior and prior.get("status") == "approved":
            continue
        merged[term] = dict(row)

    return [merged[key] for key in sorted(merged)]


def apply_approved_candidates(
    dictionary_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    by_term = {clean_term(row["term"]): {"term": clean_term(row["term"]), "definition": row["definition"], "source": row["source"]} for row in dictionary_rows}

    for candidate in candidate_rows:
        if candidate.get("status") != "approved":
            continue
        term = clean_term(str(candidate.get("term", "")))
        definition = ensure_one_sentence(clean_candidate_text(str(candidate.get("proposed_definition", ""))))
        source = compact_spaces(str(candidate.get("source", "")))
        if not term or not definition or not source:
            continue
        by_term[term] = {"term": term, "definition": definition, "source": source}

    return [by_term[key] for key in sorted(by_term)]


def batch_approve_candidates(
    candidate_rows: list[dict[str, object]],
    threshold: float,
    limit: int,
) -> list[dict[str, object]]:
    approved = 0
    updated: list[dict[str, object]] = []
    for row in candidate_rows:
        candidate = dict(row)
        if candidate.get("status") == "pending":
            confidence = float(candidate.get("confidence", 0.0) or 0.0)
            if confidence >= threshold and (limit <= 0 or approved < limit):
                candidate["status"] = "approved"
                candidate["reason"] = f"{candidate.get('reason', '')}; auto-approved at threshold {threshold:.2f}".strip("; ")
                approved += 1
        updated.append(candidate)
    return updated


def write_dictionary(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run_draft(args: argparse.Namespace) -> None:
    dictionary_rows = load_dictionary(Path(args.dictionary))
    strategy_terms = load_strategy_terms()
    strategy_terms.update(strategy_terms_from_dictionary(dictionary_rows))
    worklist = collect_worklist(dictionary_rows, strategy_terms)
    targets = [item for item in worklist if item.action == "needs_rewrite"]
    if args.offset > 0:
        targets = targets[args.offset :]
    if args.max_terms > 0:
        targets = targets[: args.max_terms]

    provider = build_search_provider(args.search_provider)
    fetcher = PageFetcher()
    synthesizer = build_synthesizer()

    candidate_path = Path(args.candidates)
    existing_candidates = load_candidates(candidate_path) if args.merge_existing and candidate_path.exists() else []
    candidates: list[dict[str, object]] = []
    for index, item in enumerate(targets, start=1):
        candidates.append(research_term(item, provider, fetcher, synthesizer))
        if index % CHECKPOINT_EVERY == 0:
            snapshot = merge_candidate_rows(existing_candidates, candidates) if args.merge_existing else candidates
            write_candidates(candidate_path, snapshot)
            print(f"Checkpointed {index}/{len(targets)} candidates to: {args.candidates}", flush=True)

    if args.merge_existing:
        candidates = merge_candidate_rows(existing_candidates, candidates)
    write_candidates(candidate_path, candidates)

    kept = sum(1 for item in worklist if item.action == "keep")
    print(f"Wrote candidates to: {args.candidates}")
    print(f"Strategy terms in scope: {len(worklist)}")
    print(f"Kept: {kept}")
    print(f"Needs rewrite: {len(targets)}")
    print(f"Offset: {args.offset}")
    print(f"Search provider: {provider.name()}")
    print(f"Synthesizer: {synthesizer.name()}")


def run_apply(args: argparse.Namespace) -> None:
    dictionary_path = Path(args.dictionary)
    candidate_path = Path(args.candidates)
    dictionary_rows = load_dictionary(dictionary_path)
    candidate_rows = load_candidates(candidate_path)
    merged = apply_approved_candidates(dictionary_rows, candidate_rows)
    write_dictionary(dictionary_path, merged)

    approved = sum(1 for row in candidate_rows if row.get("status") == "approved")
    print(f"Applied approved candidates: {approved}")
    print(f"Updated dictionary: {dictionary_path}")


def run_approve(args: argparse.Namespace) -> None:
    candidate_path = Path(args.candidates)
    candidate_rows = load_candidates(candidate_path)
    updated = batch_approve_candidates(
        candidate_rows,
        threshold=args.approve_threshold,
        limit=args.approve_limit,
    )
    write_candidates(candidate_path, updated)
    approved = sum(1 for row in updated if row.get("status") == "approved")
    pending = sum(1 for row in updated if row.get("status") == "pending")
    print(f"Updated candidate statuses in: {candidate_path}")
    print(f"Approved: {approved}")
    print(f"Pending: {pending}")


def main() -> None:
    args = parse_args()
    if args.mode == "draft":
        run_draft(args)
        return
    if args.mode == "approve":
        run_approve(args)
        return
    if args.mode == "apply":
        run_apply(args)
        return
    raise ValueError(f"Unsupported mode: {args.mode}")


if __name__ == "__main__":
    main()
