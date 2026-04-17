"""
XQinEnglish Annotated Game Scraper
===================================

Crawls the *Games with English Commentaries* section of xqinenglish.com
(catid=291, master index article id=222) and extracts structured game data
from embedded **DhtmlXQ / CC Bridge** viewer blocks.

Site structure (3-level crawl)::

    Master index (id=222)
      +-- Year sub-pages (id=454, id=455 ...)
            +-- Game articles with [DhtmlXQ] blocks

All HTTP responses are cached to disk so re-runs are instant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup

from .dhtmlxq_parser import (
    DhtmlXQGame,
    game_to_training_entries,
    parse_all_games,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.xqinenglish.com/index.php"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; XiangqiCoachResearchBot/1.0; "
        "educational use)"
    ),
}
_MASTER_INDEX_ID = 222
_GAMES_CATID = 291


# ========================
#     ID EXTRACTION
# ========================

def _extract_id_from_href(href: str) -> Optional[int]:
    """Extract article ``id=NNN`` from a Joomla URL."""
    m = re.search(r"[?&]id=(\d+)", href)
    if m:
        return int(m.group(1))
    m = re.search(r"/(\d+)-", href)
    if m:
        return int(m.group(1))
    m = re.search(r":(\d+)$", href)
    if m:
        return int(m.group(1))
    return None


def _extract_js_embedded_games(html: str, url: str) -> list[DhtmlXQGame]:
    """Find DhtmlXQ data inside <script> blocks."""
    games: list[DhtmlXQGame] = []
    for m in re.finditer(
        r"""["'](\[DhtmlXQ\].*?\[/DhtmlXQ\])["']""", html, re.DOTALL
    ):
        inner = m.group(1).replace(r"\/", "/").replace(r"\n", "\n")
        games.extend(parse_all_games(inner, url))
    if not games:
        for script in re.finditer(
            r"<script[^>]*>(.*?)</script>", html, re.DOTALL
        ):
            if "[DhtmlXQ_movelist]" in script.group(1):
                games.extend(parse_all_games(script.group(1), url))
    return games


# ========================
#     GAME SCRAPER
# ========================

class GameScraper:
    """Crawl annotated Xiangqi games from xqinenglish.com.

    Parameters
    ----------
    cache_dir : str
        Directory to store cached HTML.
    rate_limit : float
        Minimum seconds between uncached HTTP requests.
    max_games : int | None
        Stop after this many games.
    commentary_only : bool
        Skip games with no expert commentary.
    """

    def __init__(
        self,
        cache_dir: str = "./data/cache/xqinenglish_games",
        rate_limit: float = 1.5,
        max_games: Optional[int] = None,
        commentary_only: bool = False,
    ) -> None:
        self._cache = Path(cache_dir)
        self._cache.mkdir(parents=True, exist_ok=True)
        self._rate = rate_limit
        self._max = max_games
        self._commentary_only = commentary_only
        self._sess = requests.Session()
        self._sess.headers.update(_HEADERS)

    # -------------------------------------------------------------- caching

    def _ckey(self, params: dict) -> str:
        return hashlib.md5(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()

    def _get_cached(self, params: dict) -> Optional[str]:
        p = self._cache / f"{self._ckey(params)}.json"
        if p.exists():
            return json.loads(p.read_text("utf-8")).get("html")
        return None

    def _put_cache(self, params: dict, html: str) -> None:
        p = self._cache / f"{self._ckey(params)}.json"
        p.write_text(
            json.dumps({"params": params, "html": html}), "utf-8"
        )

    # -------------------------------------------------------------- fetch

    def _fetch(self, params: dict) -> Optional[str]:
        cached = self._get_cached(params)
        if cached is not None:
            return cached
        try:
            r = self._sess.get(_BASE_URL, params=params, timeout=30)
            r.raise_for_status()
            self._put_cache(params, r.text)
            time.sleep(self._rate)
            return r.text
        except requests.RequestException as e:
            logger.warning("Fetch failed %s: %s", params, e)
            return None

    def _soup(self, params: dict) -> Optional[BeautifulSoup]:
        html = self._fetch(params)
        return BeautifulSoup(html, "html.parser") if html else None

    # -------------------------------------------------------------- helpers

    def _article_params(self, aid: int) -> dict:
        return {
            "option": "com_content",
            "view": "article",
            "id": aid,
            "lang": "en",
        }

    def _ids_from_soup(
        self, soup: BeautifulSoup, exclude: Optional[set[int]] = None,
    ) -> list[int]:
        ids: list[int] = []
        seen = set(exclude or set())
        for a in soup.find_all("a", href=True):
            aid = _extract_id_from_href(a["href"])
            if aid and aid not in seen:
                seen.add(aid)
                ids.append(aid)
        return ids

    # -------------------------------------------------------------- discovery

    def _discover_year_pages(self) -> list[int]:
        """Level 1: master index -> year sub-page IDs."""
        logger.info("Fetching master index (id=%d)...", _MASTER_INDEX_ID)
        soup = self._soup(self._article_params(_MASTER_INDEX_ID))
        if not soup:
            return []
        ids = self._ids_from_soup(soup, {_MASTER_INDEX_ID})
        logger.info("Found %d year sub-page links", len(ids))
        return ids

    def _discover_game_ids(self, year_id: int) -> list[int]:
        """Level 2: year sub-page -> game article IDs."""
        soup = self._soup(self._article_params(year_id))
        if not soup:
            return []
        ids = self._ids_from_soup(soup, {year_id, _MASTER_INDEX_ID})
        logger.info("  Year id=%d: %d game links", year_id, len(ids))
        return ids

    def _discover_category_ids(self) -> list[int]:
        """Crawl catid=291 category listing for more articles."""
        ids: list[int] = []
        seen: set[int] = set()
        start = 0
        while True:
            params = {
                "option": "com_content",
                "view": "category",
                "id": _GAMES_CATID,
                "lang": "en",
                "start": start,
            }
            soup = self._soup(params)
            if not soup:
                break
            found = 0
            for a in soup.select("a[href*='view=article']"):
                aid = _extract_id_from_href(a.get("href", ""))
                if aid and aid not in seen:
                    seen.add(aid)
                    ids.append(aid)
                    found += 1
            if found == 0:
                break
            nxt = soup.select_one(
                "a.pagination-next, li.pagination-next a, "
                "a[title='Next']"
            )
            if not nxt:
                break
            start += 20
        logger.info("Category %d: %d article IDs", _GAMES_CATID, len(ids))
        return ids

    # -------------------------------------------------------------- article scrape

    def _scrape_article(self, aid: int) -> list[DhtmlXQGame]:
        """Level 3: fetch article, parse DhtmlXQ blocks."""
        html = self._fetch(self._article_params(aid))
        if not html:
            return []

        url = (
            f"{_BASE_URL}?option=com_content&view=article"
            f"&id={aid}&lang=en"
        )
        games = parse_all_games(html, source_url=url)

        # Fallback: JS-embedded DhtmlXQ
        if not games:
            games = _extract_js_embedded_games(html, url)

        # Fill missing titles from the HTML <title>
        if games:
            soup = BeautifulSoup(html, "html.parser")
            title = ""
            for sel in ["h2.article-title", "h1.page-title", "title"]:
                el = soup.select_one(sel)
                if el:
                    title = el.get_text(strip=True).replace(
                        " - XQinEnglish.com", ""
                    )
                    break
            for g in games:
                if not g.title and title:
                    g.title = title

        return games

    # -------------------------------------------------------------- public API

    def scrape_all(self) -> Iterator[DhtmlXQGame]:
        """Yield all discovered :class:`DhtmlXQGame` objects."""
        total = 0
        seen: set[int] = set()
        all_ids: list[int] = []

        # Level 1+2
        for yid in self._discover_year_pages():
            for gid in self._discover_game_ids(yid):
                if gid not in seen:
                    seen.add(gid)
                    all_ids.append(gid)

        # Category fallback
        for gid in self._discover_category_ids():
            if gid not in seen:
                seen.add(gid)
                all_ids.append(gid)

        logger.info("Total unique article IDs: %d", len(all_ids))

        for aid in all_ids:
            if self._max is not None and total >= self._max:
                logger.info("Reached max_games=%d, stopping.", self._max)
                return

            for game in self._scrape_article(aid):
                if self._commentary_only and not game.has_commentary:
                    continue
                total += 1
                logger.info(
                    "  [%d] %s (%d moves, %.0f%% commented)",
                    total,
                    game.title or f"article_{aid}",
                    game.total_moves,
                    game.commentary_coverage * 100,
                )
                yield game

        logger.info("Scraping complete: %d games", total)

    def export_training_jsonl(
        self,
        output_path: str,
        include_uncommented: bool = True,
    ) -> dict:
        """Scrape all games -> write JSONL training data.

        Returns summary stats dict.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        stats = {
            "total_games": 0,
            "total_moves": 0,
            "commented_moves": 0,
            "written_entries": 0,
        }

        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "_meta": True,
                "source": "xqinenglish.com",
                "scraper": "GameScraper",
                "format": "DhtmlXQ",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }) + "\n")

            for game in self.scrape_all():
                stats["total_games"] += 1
                entries = game_to_training_entries(game)
                stats["total_moves"] += len(entries)
                stats["commented_moves"] += sum(
                    1 for e in entries if e["expert_commentary"]
                )
                for e in entries:
                    if not include_uncommented and not e["expert_commentary"]:
                        continue
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
                    stats["written_entries"] += 1

        logger.info(
            "Export: %d games, %d/%d commented, %d entries -> %s",
            stats["total_games"],
            stats["commented_moves"],
            stats["total_moves"],
            stats["written_entries"],
            out,
        )
        return stats
