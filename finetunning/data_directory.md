# Fine-tuning Data Directory

Hierarchy of every data source used by the Xiangqi chess-coach LoRA pipeline.
All paths are relative to the repository root.

---

```
finetunning/data/
│
├── dataset.train.jsonl          ← BUILT — 2,549 Qwen-format training examples
│   Format : {"messages": [{role,content}, ...]}  (system / user / assistant)
│   Content: merged Source A + Source B, shuffled, 90 % split
│   User block contains [POSITION] (FEN + board summary) and [RELATIONS]
│   (relational features). Assistant block = instructive commentary.
│
├── dataset.val.jsonl            ← BUILT — 283 Qwen-format validation examples
│   Same format as dataset.train.jsonl; 10 % held-out split.
│
├── dictionary.json              ← SCRAPED Xiangqi term glossary
│   Format : [{"term": "三步虎", "definition": "...", "source": "url"}, ...]
│   Content: Classical pattern names, opening names, kill-pattern labels scraped
│   from xqinenglish.com.  Used as a look-up reference; not a direct training
│   input but informs the enrichment prompt in clean_dataset.py.
│
├── dictionary_candidates.strategy.jsonl
│   Format : JSONL {term, current_definition, proposed_definition, source,
│             evidence_urls, evidence_snippets, confidence, status, reason}
│   Content: LLM-driven dictionary-enrichment attempts.  Most records have
│   status="rejected" (missing evidence or generic placeholder definitions).
│   Produced by strategy_dictionary_agent.py.  Archive only — not used in
│   training directly.
│
├── raw/
│   └── games/
│       └── xqinenglish_games.jsonl   ← RAW scraper output (Source A)
│           Format : JSONL, line 1 = metadata header {"_meta": true, ...}
│           Remaining lines: one move per line
│             {fen, move_str, expert_commentary, move_index, side,
│              game_title, red_player, black_player, event, result, source_url}
│           Content: 654 tournament games from xqinenglish.com.  Delta-filtered
│           so only moves with substantive expert_commentary (≥20 chars) survive
│           into the dataset.  ~1,791 training-eligible moves after filtering.
│
└── term_cache/                  ← Cached raw HTML from xqinenglish.com
    ├── xqinenglish_basic_checkmate_methods.html
    │   Page: /basic-checkmate-methods — overview of 基本杀法 (basic kill
    │   patterns); used by build_dictionary.py to resolve pattern names.
    ├── xqinenglish_intro_opening.html
    │   Page: intro to openings — canonical Chinese names mapped to English
    │   descriptions; seeded the opening entries in dictionary.json.
    └── xqinenglish_simple_glossary.html
        Page: simple Xiangqi glossary — ~200 terms; primary source for the
        definition fields in dictionary.json.


server/web_scraper/knowledge/json/     ← Source B: tactical / strategic positions
│
├── basic-checkmates.json        ← 66 basic kill-pattern positions
│   Format : [{"fen", "name", "result", "bestMove", "timestamp"}, ...]
│   Content: Canonical 基本杀法 (basic checkmate patterns) such as
│   "对面笑", "马后炮", "卧槽马".  FEN + best move + pattern name.
│   Low noise; nearly all entries have clean pattern names.
│
├── advanced-checkmates.json     ← 574 advanced kill-pattern positions
│   Format : same as basic-checkmates.json
│   Content: Compound kill-patterns (双炮马类, 车马炮类, etc.) from the
│   残局攻杀谱 collection.  Pattern names are numeric sub-types (e.g. 双炮马类(04)).
│   Commentary is sparse — high-priority target for LLM enrichment.
│
├── endgames_all.json            ← 7,346 endgame positions  (UTF-8 BOM — read with utf-8-sig)
│   Format : [{"fen", "type", "classification", "materialValue", "result",
│              "bestMove", "timestamp"}, ...]
│   Content: Broad endgame database.  No "name" field; entries are classified
│   by material type (e.g. "车兵 vs 车") and result.  Not used directly in the
│   current build_dataset.py (excluded from _KNOWLEDGE_FILES list) because
│   entries have no pattern name and commentary would need to be fully
│   generated.  Candidate for enrichment-pipeline expansion.
│
├── meng-ru-shen-ji.json         ← 151 positions from the classical manual 梦入神机
│   Format : same as basic-checkmates.json
│   Content: Positions from the Ming-dynasty Xiangqi manual "Dreaming of
│   Entering the Realm of the Gods".  Entries have structured names like
│   "001由中应外".  Good signal for classical tactical motifs.
│
├── opening-repertoire.json      ← 264 opening-repertoire positions
│   Format : same as basic-checkmates.json
│   Content: Named opening lines (e.g. "順相局", "五七炮進三兵對屏風馬").
│   FEN is the position after the opening sequence; bestMove is the
│   thematic continuation.
│
├── knowledge_base.json          ← Index / manifest of all knowledge collections
│   Format : {"schema_version", "description", "collections", "total_chunks"}
│   Content: Top-level catalogue referencing all other files; used by the
│   RAG retrieval layer (server/agent_orchestration/).  Not used by the
│   fine-tuning pipeline directly.
│
└── patterns_index.json          ← File-list manifest for the pattern collections
    Format : {"files": [...], "total": N, "generated": "..."}
    Content: Auto-generated index of which JSON files exist under this
    directory.  Used by the web scraper's knowledge-loader.
```

---

## Data-flow summary

```
xqinenglish.com  ─── scrape_games.py ──►  raw/games/xqinenglish_games.jsonl  (Source A)
                                                          │
knowledge/json/*.json  (Source B) ────────────────────────┤
                                                          │
                                               build_dataset.py
                                           (enrich_fen + relations_to_text)
                                                          │
                                          ┌───────────────┴──────────────┐
                                          ▼                              ▼
                               dataset.train.jsonl            dataset.val.jsonl
                               (2,549 examples)               (283 examples)
                                          │
                               clean_dataset.py  ◄── optional: --enrich (LLM API)
                                          │
                          ┌───────────────┴──────────────┐
                          ▼                              ▼
               dataset.train.clean.jsonl     dataset.val.clean.jsonl
                                          │
                               train_lora.py  (Qwen2.5-7B-Instruct + LoRA)
                                          │
                               finetunning/output/xiangqi-lora/
```

---

## Noise statistics (as of last dataset build)

| Metric | Train (2,549) |
|--------|--------------|
| Assistant responses < 50 chars | ~1,228 (48 %) |
| Contain noise phrases (`\|\|`, "see variation", "ancient manual") | ~721 (28 %) |

Run `python finetunning/clean_dataset.py --dry-run` to see current stats before cleaning.
