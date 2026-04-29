from __future__ import annotations

import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from finetunning.strategy_dictionary_agent import (
    CombinedSearchProvider,
    DuckDuckGoHTMLSearchProvider,
    Evidence,
    HeuristicSynthesizer,
    LocalCacheSearchProvider,
    SearchResult,
    StrategyTerm,
    batch_approve_candidates,
    proposal_quality_reason,
    rank_search_results,
)


class StrategyDictionaryLiveSearchTests(unittest.TestCase):
    def test_batch_approve_marks_only_high_confidence_pending_rows(self) -> None:
        rows = [
            {"term": "屏风马双炮过河", "status": "pending", "confidence": 0.82, "reason": "ok"},
            {"term": "斗列炮", "status": "pending", "confidence": 0.50, "reason": "ok"},
            {"term": "中炮", "status": "approved", "confidence": 0.95, "reason": "ok"},
        ]
        updated = batch_approve_candidates(rows, threshold=0.75, limit=0)
        by_term = {row["term"]: row for row in updated}
        self.assertEqual(by_term["屏风马双炮过河"]["status"], "approved")
        self.assertEqual(by_term["斗列炮"]["status"], "pending")
        self.assertEqual(by_term["中炮"]["status"], "approved")

    def test_opening_quality_rejects_notational_stub(self) -> None:
        strategy = StrategyTerm("屏风马平炮兑车", "opening", "", "opening variation strategy")
        self.assertEqual(
            proposal_quality_reason(strategy, "1."),
            "degenerate move-tree proposal",
        )

    def test_search_ranking_drops_forumish_results(self) -> None:
        strategy = StrategyTerm("中炮對屏風馬", "opening", "", "opening variation strategy")
        results = [
            SearchResult(
                title="中炮對屏風馬 discussion",
                url="https://forum.example.com/post",
                snippet="中炮對屏風馬 opening talk",
                provider="fake",
                provider_rank=0,
            ),
            SearchResult(
                title="中炮對屏風馬 opening notes",
                url="https://www.xqinenglish.com/opening",
                snippet="中炮對屏風馬 is an opening system.",
                provider="fake",
                provider_rank=1,
            ),
        ]
        ranked = rank_search_results("中炮對屏風馬", strategy, results)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].url, "https://www.xqinenglish.com/opening")

    def test_heuristic_synthesizer_uses_head_for_opening_context(self) -> None:
        strategy = StrategyTerm("斗顺炮", "opening", "", "opening variation strategy")
        evidence = [
            Evidence(
                url="https://example.com",
                title="斗顺炮",
                snippet="斗顺炮 Same Direction Cannons, Mirror Cannon defense : Black answers red’s C2=5 with C8=5.",
                score=4.2,
            )
        ]
        text = HeuristicSynthesizer().summarize("斗顺炮", strategy, evidence)
        self.assertIn("Mirror Cannon defense", text)
        self.assertIn("opening or defense", text)

    def test_duckduckgo_provider_returns_empty_results_on_http_error(self) -> None:
        provider = DuckDuckGoHTMLSearchProvider()
        with patch(
            "finetunning.strategy_dictionary_agent.urlopen",
            side_effect=HTTPError(provider.endpoint, 403, "Forbidden", hdrs=None, fp=None),
        ):
            self.assertEqual(provider.search("屏风马 xiangqi"), [])

    def test_combined_provider_keeps_cached_results_when_live_provider_fails(self) -> None:
        class FailingProvider:
            def name(self) -> str:
                return "failing"

            def search(self, query: str) -> list[SearchResult]:
                raise RuntimeError("boom")

        query = "中炮 xiangqi 象棋 opening variation strategy"
        provider = CombinedSearchProvider(FailingProvider(), LocalCacheSearchProvider())
        results = provider.search(query)
        self.assertTrue(results)
        self.assertTrue(any("中炮" in result.title or "中炮" in result.snippet for result in results))


if __name__ == "__main__":
    unittest.main()
