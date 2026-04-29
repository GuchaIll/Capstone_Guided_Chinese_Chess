#!/usr/bin/env python3
"""Build a clean Xiangqi terminology dictionary for RAG.

The script does three things:
1. Extract candidate Xiangqi terms from the fine-tuning datasets and knowledge JSON.
2. Normalize raw labels such as "双车马炮类(31) - 残局攻杀谱" into headwords like "双车马炮类".
3. Produce a minimal dictionary containing only `term`, `definition`, and `source`.

Usage
-----
    python finetunning/build_dictionary.py

    python finetunning/build_dictionary.py --fetch-web

    python finetunning/build_dictionary.py \
        --output finetunning/data/dictionary.json \
        --fetch-web
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "finetunning/data/dictionary.json"
DEFAULT_DATASETS = [
    REPO_ROOT / "finetunning/data/dataset.train.jsonl",
    REPO_ROOT / "finetunning/data/dataset.val.jsonl",
]
DEFAULT_KNOWLEDGE_FILES = [
    REPO_ROOT / "server/web_scraper/knowledge/json/basic-checkmates.json",
    REPO_ROOT / "server/web_scraper/knowledge/json/advanced-checkmates.json",
    REPO_ROOT / "server/web_scraper/knowledge/json/opening-repertoire.json",
    REPO_ROOT / "server/web_scraper/knowledge/json/meng-ru-shen-ji.json",
]
DEFAULT_CACHE_DIR = REPO_ROOT / "finetunning/data/term_cache"
DEFAULT_WEB_SOURCES = [
    {
        "source_id": "xqinenglish_simple_glossary",
        "title": "Basics of Xiangqi (Chinese Chess) Simple Glossary",
        "url": (
            "https://www.xqinenglish.com/index.php?option=com_content&view=article"
            "&id=110&catid=110&Itemid=504&lang=en"
        ),
    },
    {
        "source_id": "xqinenglish_intro_opening",
        "title": "Introduction to the Xiangqi (Chinese Chess) Opening",
        "url": (
            "https://www.xqinenglish.com/index.php?option=com_content&view=article"
            "&id=105&catid=226&Itemid=511&lang=en"
        ),
    },
    {
        "source_id": "xqinenglish_basic_checkmate_methods",
        "title": "What is a Basic Kill?",
        "url": (
            "https://www.xqinenglish.com/index.php?option=com_content&view=article"
            "&id=100&catid=207&Itemid=522&lang=en"
        ),
    },
]

KNOWN_SUFFIXES = (
    "残局攻杀谱",
    "基本杀法",
    "梦入神机",
    "常見開局",
    "常见开局",
    "冷門開局",
    "冷门开局",
)
OPENING_HINTS = (
    "炮",
    "馬",
    "马",
    "局",
    "屏風",
    "屏风",
    "飛相",
    "飞相",
    "順炮",
    "顺炮",
    "反宮",
    "反宫",
    "過宮",
    "过宫",
    "中炮",
    "仙人指路",
    "士角炮",
    "三步虎",
    "龜背炮",
    "龟背炮",
)
PIECE_TERM_TOKENS = [
    ("雙車", "two chariots"),
    ("双车", "two chariots"),
    ("單車", "single chariot"),
    ("单车", "single chariot"),
    ("雙馬", "two horses"),
    ("双马", "two horses"),
    ("單馬", "single horse"),
    ("单马", "single horse"),
    ("雙炮", "two cannons"),
    ("双炮", "two cannons"),
    ("單炮", "single cannon"),
    ("单炮", "single cannon"),
    ("雙兵", "two pawns"),
    ("双兵", "two pawns"),
    ("單兵", "single pawn"),
    ("单兵", "single pawn"),
    ("車", "chariot"),
    ("车", "chariot"),
    ("馬", "horse"),
    ("马", "horse"),
    ("炮", "cannon"),
    ("兵", "pawn"),
]
OPENING_TRANSLATIONS = {
    "中炮": "Central Cannon",
    "過宮炮": "Cross-Palace Cannon",
    "过宫炮": "Cross-Palace Cannon",
    "屏風馬": "Screen Horse",
    "屏风马": "Screen Horse",
    "飛相": "Flying Elephant",
    "飞相": "Flying Elephant",
    "順炮": "Same Direction Cannons",
    "顺炮": "Same Direction Cannons",
    "反宮馬": "Reversed Palace Horse",
    "反宫马": "Reversed Palace Horse",
    "三步虎": "Three-Step Tiger",
    "仙人指路": "Immortal Pointing the Way",
    "士角炮": "Palace-Corner Cannon",
    "龜背炮": "Turtle-Back Cannons",
    "龟背炮": "Turtle-Back Cannons",
    "巡河炮": "Riverbank Cannon",
    "巡河車": "Riverbank Chariot",
    "巡河车": "Riverbank Chariot",
    "過河車": "Cross-River Chariot",
    "过河车": "Cross-River Chariot",
    "兩頭蛇": "Two-Headed Snake",
    "两头蛇": "Two-Headed Snake",
    "橫車": "Ranked Chariot",
    "横车": "Ranked Chariot",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; XiangqiDictionaryBuilder/1.0; "
        "+https://github.com/GuchaIll/Capstone_Guided_Chinese_Chess)"
    ),
}
ALWAYS_KEEP_TERMS = {"基本杀法", "残局攻杀谱", "梦入神机", "偷步"}
CURATED_DEFINITIONS = {
    "基本杀法": (
        "A Xiangqi taxonomy of named basic mating techniques and standard kill patterns.",
        "https://www.xqinenglish.com/index.php?option=com_content&view=article&id=100&catid=207&Itemid=522&lang=en",
    ),
    "残局攻杀谱": (
        "A Xiangqi taxonomy and manual tradition for named attacking endgame classes and mating patterns.",
        str(REPO_ROOT / "server/web_scraper/knowledge/json/advanced-checkmates.json"),
    ),
    "梦入神机": (
        "A classical Xiangqi composition collection and taxonomy of named studies.",
        str(REPO_ROOT / "server/web_scraper/knowledge/json/meng-ru-shen-ji.json"),
    ),
    "偷步": (
        "To steal a move; to gain a tempo by improving the position while preserving the same underlying structure.",
        "https://www.xqinenglish.com/index.php?option=com_content&view=article&id=902&lang=en",
    ),
}


@dataclass
class TermEvidence:
    raw_variants: Counter[str] = field(default_factory=Counter)
    source_counts: Counter[str] = field(default_factory=Counter)
    categories: Counter[str] = field(default_factory=Counter)
    examples: list[dict[str, str]] = field(default_factory=list)

    def add(
        self,
        raw_term: str,
        source: str,
        category: str,
        context: str = "",
        extra: str = "",
    ) -> None:
        self.raw_variants[raw_term] += 1
        self.source_counts[source] += 1
        self.categories[category] += 1
        if len(self.examples) < 5:
            sample = {"raw_term": raw_term, "source": source}
            if context:
                sample["context"] = context[:240]
            if extra:
                sample["extra"] = extra[:240]
            self.examples.append(sample)


@dataclass
class TextDoc:
    title: str
    text: str
    url: str
    source_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Xiangqi terminology dictionary")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--fetch-web",
        action="store_true",
        help="Fetch default glossary/article pages and cache them locally before matching",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help=f"Cache directory for fetched HTML (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Additional dataset JSONL path(s) to scan",
    )
    parser.add_argument(
        "--knowledge-file",
        action="append",
        default=[],
        help="Additional knowledge JSON path(s) to scan",
    )
    return parser.parse_args()


def has_cjk(text: str) -> bool:
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def has_xiangqi_marker(text: str) -> bool:
    return bool(
        re.search(
            r"[炮车馬马兵卒象士将帅局类殺杀谱譜門门棋步河相宮宫着著胜勝和妙闲軟软先后攻守兑兌吃捉拦攔封弃棄跟困巧例欠排实實用残局开開中局]",
            text,
        )
    )


def is_bibliography_text(text: str) -> bool:
    lowered = text.lower()
    bad_markers = (
        "works cited",
        "reference material",
        "references",
        "isbn",
        "http://",
        "https://",
        "出版社",
        "cited:",
        "[online]",
        "taipei",
    )
    return any(marker in lowered for marker in bad_markers)


def is_valid_term(term: str) -> bool:
    term = compact_spaces(term)
    if term in ALWAYS_KEEP_TERMS:
        return True
    if not term or not has_cjk(term):
        return False
    if len(term) > 40:
        return False
    if re.match(r"^\d+[.)、:： ]", term):
        return False
    if any(ch in term for ch in "[]{}<>|"):
        return False
    if is_bibliography_text(term):
        return False
    if len(re.findall(r"[A-Za-z]{2,}", term)) > 1:
        return False
    if not has_xiangqi_marker(term):
        return False
    return True


def english_gloss_from_head(head: str) -> str | None:
    head = compact_spaces(head)
    head = re.sub(r"[一-龥0-9/＋+\-（）()、，。對对過过宮宫屏風屏风馬马炮車车兵卒象士將将帥帅河局類类著着勝胜和妙軟软閒闲先後后开開殘残殺杀譜谱夢梦神機机]+", " ", head)
    head = compact_spaces(head).strip(" ,;/-")
    if not head:
        return None
    if not re.search(r"[A-Za-z]", head):
        return None
    head = head[0].upper() + head[1:] if head and head[0].islower() else head
    return head


def normalize_term(raw_term: str) -> tuple[str, dict[str, str]]:
    raw = compact_spaces(unicodedata.normalize("NFKC", raw_term))
    meta: dict[str, str] = {}
    label = raw.rstrip(".。")
    label = re.sub(r"^This position demonstrates\s+", "", label, flags=re.IGNORECASE)

    for suffix in KNOWN_SUFFIXES:
        token = f"- {suffix}"
        if label.endswith(token):
            meta["taxonomy"] = suffix
            label = label[: -len(token)].strip()
            break

    if label.startswith("基本杀法"):
        meta.setdefault("taxonomy", "基本杀法")
        label = re.sub(r"^基本杀法\s*\d+[。.]\s*", "", label).strip()

    if re.match(r"^\d{3}", label):
        meta.setdefault("taxonomy", "梦入神机")
        label = re.sub(r"^\d{3}", "", label).strip()

    label = re.sub(r"[（(]\d+[）)]", "", label).strip()
    label = re.sub(r"\s+\d{2}$", "", label).strip()
    label = label.strip("- ").rstrip(".。")
    label = compact_spaces(label)
    return label, meta


def guess_category(raw_term: str, normalized: str, source_name: str) -> str:
    if source_name in {"dataset", "web_seed"}:
        if "残局攻杀谱" in raw_term or normalized.endswith("类") or "杀着" in normalized:
            return "endgame_attack_class"
        if "基本杀法" in raw_term:
            return "basic_kill"
        if "梦入神机" in raw_term:
            return "ancient_manual"
        if any(hint in normalized for hint in OPENING_HINTS):
            return "opening"
        return "term"

    if source_name == "advanced-checkmates":
        return "endgame_attack_class"
    if source_name == "basic-checkmates":
        return "basic_kill"
    if source_name == "opening-repertoire":
        return "opening"
    if source_name == "meng-ru-shen-ji":
        return "ancient_manual"
    if source_name == "endgames_all":
        return "material_endgame"
    return "term"


def maybe_extract_term_from_segment(segment: str) -> str | None:
    segment = compact_spaces(segment.strip(" :.-"))
    if not segment or len(segment) > 48 or not has_cjk(segment):
        return None
    if any(ch in segment for ch in "，。！？"):
        return None
    lowered = segment.lower()
    if lowered.startswith(
        (
            "this position demonstrates",
            "important variation",
            "opening system is defined",
            "red:",
            "black:",
        )
    ):
        return None
    if len(re.findall(r"[A-Za-z]{2,}", segment)) > 2:
        return None
    if not has_xiangqi_marker(segment):
        return None
    if not is_valid_term(segment):
        return None
    return segment


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


def load_datasets(paths: list[Path]) -> dict[str, TermEvidence]:
    found: dict[str, TermEvidence] = defaultdict(TermEvidence)
    for path in paths:
        if not path.exists():
            continue
        for row in iter_jsonl(path):
            text = row.get("text", "")
            if "<|assistant|>" not in text:
                continue
            assistant = text.split("<|assistant|>\n", 1)[-1].strip()
            if assistant.startswith("This position demonstrates "):
                raw_term = assistant[len("This position demonstrates ") :].rstrip(".")
                normalized, _ = normalize_term(raw_term)
                if is_valid_term(normalized):
                    category = guess_category(raw_term, normalized, "dataset")
                    found[normalized].add(
                        raw_term=raw_term,
                        source="dataset",
                        category=category,
                        context=assistant,
                        extra=str(path.relative_to(REPO_ROOT)),
                    )

            for part in assistant.split("||"):
                maybe = maybe_extract_term_from_segment(part)
                if maybe:
                    normalized, _ = normalize_term(maybe)
                    if is_valid_term(normalized):
                        category = guess_category(maybe, normalized, "dataset")
                        found[normalized].add(
                            raw_term=maybe,
                            source="dataset",
                            category=category,
                            context=assistant,
                            extra=str(path.relative_to(REPO_ROOT)),
                        )
    return found


def load_knowledge(paths: list[Path], found: dict[str, TermEvidence]) -> None:
    for path in paths:
        if not path.exists():
            continue
        source_name = path.stem
        try:
            with open(path, encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue

        for row in data:
            raw_term = ""
            extra = ""
            if source_name == "endgames_all":
                raw_term = compact_spaces(str(row.get("type", "")))
                extra = compact_spaces(str(row.get("result", "")))
            else:
                raw_term = compact_spaces(str(row.get("name", "")))
                extra = compact_spaces(str(row.get("bestMove", "")))
            if not raw_term or not has_cjk(raw_term):
                continue
            normalized, _ = normalize_term(raw_term)
            if not normalized or not is_valid_term(normalized):
                continue
            category = guess_category(raw_term, normalized, source_name)
            found[normalized].add(
                raw_term=raw_term,
                source=source_name,
                category=category,
                context=raw_term,
                extra=extra,
            )


def add_taxonomy_seeds(found: dict[str, TermEvidence]) -> None:
    seeds = [
        ("基本杀法", "basic_kill", "Webmaster taxonomy term for named basic mating techniques."),
        ("残局攻杀谱", "endgame_attack_class", "Manual-style taxonomy for attacking endgame classes."),
        ("梦入神机", "ancient_manual", "Classical composition/manual taxonomy."),
        ("偷步", "term", "A common Xiangqi term for stealing a move or gaining a tempo."),
    ]
    for term, category, context in seeds:
        found[term].add(
            raw_term=term,
            source="seed",
            category=category,
            context=context,
        )


def cache_path_for(source_id: str, cache_dir: Path) -> Path:
    return cache_dir / f"{source_id}.html"


def fetch_url(url: str) -> str:
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text("\n")
    else:  # pragma: no cover
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
    lines = [compact_spaces(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def load_web_docs(cache_dir: Path, fetch_web: bool) -> list[TextDoc]:
    docs: list[TextDoc] = []
    cache_dir.mkdir(parents=True, exist_ok=True)

    for source in DEFAULT_WEB_SOURCES:
        cache_file = cache_path_for(source["source_id"], cache_dir)
        html = ""
        if fetch_web:
            try:
                html = fetch_url(source["url"])
                cache_file.write_text(html, encoding="utf-8")
            except URLError as exc:
                print(
                    f"[WARN] Could not fetch {source['url']}: {exc}",
                    file=sys.stderr,
                )
        elif cache_file.exists():
            html = cache_file.read_text(encoding="utf-8")

        if not html:
            continue

        docs.append(
            TextDoc(
                title=source["title"],
                text=html_to_text(html),
                url=source["url"],
                source_id=source["source_id"],
            )
        )
    return docs


def simplify_definition(text: str) -> str:
    text = compact_spaces(text)
    text = re.sub(r"\s*\|+\s*", " ", text)
    text = re.sub(r"\bself explanatory\b\.?", "self-explanatory.", text, flags=re.IGNORECASE)
    text = re.sub(r"AXF defn?:.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"AXF definition:.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"For example,.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"More on this.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Please see AXF rules.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Discussion required\..*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Much to be discussed\..*", "", text, flags=re.IGNORECASE)
    text = compact_spaces(text)
    if len(text) > 220:
        sentences = re.split(r"(?<=[.!?。])\s+", text)
        text = compact_spaces(sentences[0])
    if len(text) > 200:
        text = compact_spaces(text[:197]).rstrip(" ,;:-") + "..."
    return text.rstrip(" :;-")


def clean_glossary_definition(head: str, tail: str) -> str:
    gloss = english_gloss_from_head(head)
    tail = compact_spaces(tail)
    tail = re.split(r"(?=\s+[一-龥/]{1,8}\s+[A-Za-z][^:]{0,30}:)", tail, maxsplit=1)[0]
    tail = re.split(r"(?=\s+[一-龥/]{1,8}\s*[:：])", tail, maxsplit=1)[0]
    if gloss and re.match(r"^[A-Z]\d[=+\-]\d", tail):
        notation = compact_spaces(re.split(r"\s+[一-龥]{2,}", tail, maxsplit=1)[0])
        return simplify_definition(f"{gloss}. Opening notation: {notation}.")
    if gloss and re.match(r"^\d+\.", tail):
        return simplify_definition(f"{gloss}. Defined by the move order {tail}")
    if gloss and len(tail) < 80 and not re.search(r"[A-Za-z]{4,}", tail):
        return simplify_definition(f"{gloss}. {tail}")
    return simplify_definition(tail)


def extract_terms_from_glossary_head(head: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"[一-龥0-9A-Za-z/＋+\-（）()、對对過过宮宫屏風屏风馬马炮車车兵卒象士將将帥帅河局類类著着勝胜和妙軟软閒闲先後后开開殘残殺杀譜谱夢梦神機机]{1,40}", head):
        token = compact_spaces(match.group(0))
        token = re.sub(r"[A-Za-z]+$", "", token).strip(" ,;/-")
        if not token:
            continue
        normalized, _ = normalize_term(token)
        if is_valid_term(normalized) and normalized not in terms:
            terms.append(normalized)
    return terms


def build_glossary_map(docs: list[TextDoc]) -> dict[str, dict[str, str]]:
    glossary: dict[str, dict[str, str]] = {}

    for doc in docs:
        if doc.source_id != "xqinenglish_simple_glossary":
            continue
        for line in doc.text.splitlines():
            line = compact_spaces(line)
            if ":" not in line or not has_cjk(line) or is_bibliography_text(line):
                continue
            head, tail = [part.strip() for part in line.split(":", 1)]
            terms = extract_terms_from_glossary_head(head)
            if not terms:
                continue
            definition = clean_glossary_definition(head, tail)
            if not definition:
                continue
            for term in terms:
                glossary.setdefault(
                    term,
                    {"definition": definition, "source": doc.url},
                )
    return glossary


def add_glossary_terms(glossary_map: dict[str, dict[str, str]], found: dict[str, TermEvidence]) -> None:
    for term in glossary_map:
        if not is_valid_term(term):
            continue
        category = guess_category(term, term, "web_seed")
        found[term].add(
            raw_term=term,
            source="web_seed",
            category=category,
        )


def tokenize_piece_term(body: str) -> list[str] | None:
    tokens: list[str] = []
    remainder = body
    while remainder:
        matched = False
        for raw_token, english in PIECE_TERM_TOKENS:
            if remainder.startswith(raw_token):
                tokens.append(english)
                remainder = remainder[len(raw_token) :]
                matched = True
                break
        if not matched:
            return None
    return tokens


def join_english_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return ", ".join(tokens[:-1]) + ", and " + tokens[-1]


def infer_piece_class(term: str, taxonomy: str | None) -> str | None:
    if term == "其它的杀着" or term == "其他的杀着":
        return "A catch-all class for attacking or mating techniques that do not fit the main named material families."

    if not term.endswith("类"):
        return None

    body = term[:-1]
    tokens = tokenize_piece_term(body)
    if not tokens:
        return None

    if taxonomy == "残局攻杀谱":
        definition = (
            "An endgame attacking class in the 残局攻杀谱 taxonomy, grouped by the material combination of "
            f"{join_english_tokens(tokens)}."
        )
    else:
        definition = (
            "A Xiangqi material or attacking class organized around "
            f"the material combination of {join_english_tokens(tokens)}."
        )
    return definition


def infer_opening_definition(term: str) -> str:
    hits = [eng for zh, eng in OPENING_TRANSLATIONS.items() if zh in term]
    deduped: list[str] = []
    for hit in hits:
        if hit not in deduped:
            deduped.append(hit)
    if deduped:
        family = " / ".join(deduped[:4])
        return f"A named Xiangqi opening or opening variation in the {family} family."
    return "A named Xiangqi opening or opening variation."


def infer_entry(term: str, category: str, taxonomies: list[str]) -> str | None:
    if term in CURATED_DEFINITIONS:
        return CURATED_DEFINITIONS[term][0]

    taxonomy = taxonomies[0] if taxonomies else None

    piece_class = infer_piece_class(term, taxonomy)
    if piece_class:
        return piece_class

    if category == "basic_kill":
        return "A named basic kill pattern in Xiangqi."

    if category == "ancient_manual":
        return "A named classical Xiangqi composition or study from the 梦入神机 tradition."

    if category == "opening":
        return infer_opening_definition(term)

    return None


def taxonomy_list(evidence: TermEvidence) -> list[str]:
    found: list[str] = []
    for raw in evidence.raw_variants:
        _, meta = normalize_term(raw)
        taxonomy = meta.get("taxonomy")
        if taxonomy and taxonomy not in found:
            found.append(taxonomy)
    return found


def source_for_inferred_term(category: str, evidence: TermEvidence) -> str:
    term_candidates = [raw for raw, _ in evidence.raw_variants.most_common(1)]
    if term_candidates and term_candidates[0] in CURATED_DEFINITIONS:
        return CURATED_DEFINITIONS[term_candidates[0]][1]
    if category == "basic_kill":
        return "https://www.xqinenglish.com/index.php?option=com_content&view=article&id=100&catid=207&Itemid=522&lang=en"
    if category == "opening":
        return str(REPO_ROOT / "server/web_scraper/knowledge/json/opening-repertoire.json")
    if category == "ancient_manual":
        return str(REPO_ROOT / "server/web_scraper/knowledge/json/meng-ru-shen-ji.json")
    if category == "endgame_attack_class":
        return str(REPO_ROOT / "server/web_scraper/knowledge/json/advanced-checkmates.json")
    if evidence.source_counts:
        top_source = evidence.source_counts.most_common(1)[0][0]
        return top_source
    return "inferred"


def build_dictionary(found: dict[str, TermEvidence], glossary_map: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    for term in sorted(found):
        if not is_valid_term(term):
            continue

        evidence = found[term]
        taxonomies = taxonomy_list(evidence)
        category = evidence.categories.most_common(1)[0][0]

        if term in glossary_map:
            definition = glossary_map[term]["definition"]
            source = glossary_map[term]["source"]
        elif term in CURATED_DEFINITIONS:
            definition, source = CURATED_DEFINITIONS[term]
        else:
            definition = infer_entry(term, category, taxonomies)
            if not definition:
                continue
            source = source_for_inferred_term(category, evidence)

        definition = simplify_definition(definition)
        if not definition or is_bibliography_text(definition):
            continue

        entries.append(
            {
                "term": term,
                "definition": definition,
                "source": source,
            }
        )

    return entries


def main() -> None:
    args = parse_args()

    dataset_paths = DEFAULT_DATASETS + [Path(p).resolve() for p in args.dataset]
    knowledge_paths = DEFAULT_KNOWLEDGE_FILES + [Path(p).resolve() for p in args.knowledge_file]
    cache_dir = Path(args.cache_dir).resolve()
    output = Path(args.output).resolve()

    found = load_datasets(dataset_paths)
    load_knowledge(knowledge_paths, found)
    add_taxonomy_seeds(found)

    web_docs = load_web_docs(cache_dir=cache_dir, fetch_web=args.fetch_web)
    glossary_map = build_glossary_map(web_docs)
    add_glossary_terms(glossary_map, found)

    dictionary = build_dictionary(found=found, glossary_map=glossary_map)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(dictionary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Wrote dictionary to: {output}")
    print(f"Terms: {len(dictionary)}")


if __name__ == "__main__":
    main()
