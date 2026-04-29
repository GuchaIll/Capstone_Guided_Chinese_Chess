from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from finetunning.strategy_dictionary_agent import (
    Evidence,
    HeuristicSynthesizer,
    SearchResult,
    StrategyTerm,
    WorkItem,
    apply_approved_candidates,
    collect_worklist,
    rank_search_results,
    rewrite_reason,
)


class StrategyDictionaryAgentTests(unittest.TestCase):
    def test_collect_worklist_flags_generic_strategy_definitions(self) -> None:
        dictionary_rows = [
            {
                "term": "中炮對屏風馬",
                "definition": "A named Xiangqi opening or opening variation in the Central Cannon / Screen Horse family.",
                "source": "opening-repertoire.json",
            },
            {
                "term": "三步虎",
                "definition": "Step Tiger defense. Defined by the move order 1. C2=5 N8+7 2. N2+3 R9=8.",
                "source": "glossary",
            },
            {
                "term": "中局",
                "definition": "aka Middle Game or Midgame Phase.",
                "source": "glossary",
            },
        ]
        strategy_terms = {
            "中炮對屏風馬": StrategyTerm("中炮對屏風馬", "opening", "", "opening variation strategy"),
            "三步虎": StrategyTerm("三步虎", "opening", "", "opening variation strategy"),
        }

        worklist = collect_worklist(dictionary_rows, strategy_terms)
        by_term = {item.strategy.term: item for item in worklist}

        self.assertEqual(by_term["中炮對屏風馬"].action, "needs_rewrite")
        self.assertEqual(by_term["中炮對屏風馬"].reason, "generic placeholder definition")
        self.assertEqual(by_term["三步虎"].action, "keep")
        self.assertNotIn("中局", by_term)

    def test_rank_search_results_prefers_exact_title_matches(self) -> None:
        strategy = StrategyTerm("中炮對屏風馬", "opening", "", "opening variation strategy")
        results = [
            SearchResult(
                title="Opening principles in Xiangqi",
                url="https://example.com/opening",
                snippet="This page mentions 中炮對屏風馬 in passing.",
                provider="fake",
                provider_rank=0,
            ),
            SearchResult(
                title="中炮對屏風馬 - Xiangqi opening notes",
                url="https://www.xqinenglish.com/strategy",
                snippet="Detailed notes on 中炮對屏風馬.",
                provider="fake",
                provider_rank=3,
            ),
        ]

        ranked = rank_search_results("中炮對屏風馬", strategy, results)
        self.assertEqual(ranked[0].url, "https://www.xqinenglish.com/strategy")

    def test_heuristic_synthesizer_returns_one_sentence(self) -> None:
        strategy = StrategyTerm("夹车炮", "basic_kill", "基本杀法", "basic kill mating pattern")
        evidence = [
            Evidence(
                url="https://example.com",
                title="夹车炮",
                snippet="夹车炮: A basic kill in which the cannon and rook coordinate to trap the king. It often appears when the king is short of escape squares.",
                score=4.5,
            )
        ]
        text = HeuristicSynthesizer().summarize("夹车炮", strategy, evidence)
        self.assertTrue(text.endswith("."))
        self.assertEqual(text.count("."), 1)
        self.assertIn("cannon and rook coordinate", text)

    def test_apply_approved_candidates_updates_only_approved_rows(self) -> None:
        dictionary_rows = [
            {"term": "中炮", "definition": "Old definition.", "source": "old"},
            {"term": "三步虎", "definition": "Keep me.", "source": "old"},
        ]
        candidate_rows = [
            {
                "term": "中炮",
                "proposed_definition": "The Central Cannon, a major Xiangqi opening built around moving the cannon to the central file.",
                "source": "https://xqinenglish.com/central-cannon",
                "status": "approved",
            },
            {
                "term": "三步虎",
                "proposed_definition": "Rejected replacement.",
                "source": "https://example.com/rejected",
                "status": "rejected",
            },
            {
                "term": "夹车炮",
                "proposed_definition": "A basic kill where rook and cannon coordinate to box in the king.",
                "source": "https://example.com/jia-che-pao",
                "status": "approved",
            },
        ]

        applied = apply_approved_candidates(dictionary_rows, candidate_rows)
        by_term = {row["term"]: row for row in applied}

        self.assertEqual(
            by_term["中炮"]["definition"],
            "The Central Cannon, a major Xiangqi opening built around moving the cannon to the central file.",
        )
        self.assertEqual(by_term["三步虎"]["definition"], "Keep me.")
        self.assertEqual(
            by_term["夹车炮"]["definition"],
            "A basic kill where rook and cannon coordinate to box in the king.",
        )
        self.assertEqual(set(by_term["中炮"].keys()), {"term", "definition", "source"})

    def test_rewrite_reason_catches_reference_noise(self) -> None:
        strategy = StrategyTerm("中炮對屏風馬", "opening", "", "opening variation strategy")
        reason = rewrite_reason(
            "中炮對屏風馬",
            strategy,
            "Reference Material: 1. 某某出版社 978-7-0000-0000-0",
        )
        self.assertEqual(reason, "reference or glossary noise")


if __name__ == "__main__":
    unittest.main()
