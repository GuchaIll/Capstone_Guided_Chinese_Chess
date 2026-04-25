# RAG Knowledge Acquisition Plan

This document is the authoritative reference for building the Xiangqi RAG corpus used by the Go coaching pipeline. It defines the collection structure, source priorities, URL discovery process, and wave-by-wave acquisition plan.

---

## Collections

The Go coach queries four ChromaDB collections. Every source in `sources.yaml` targets at least one.

| Collection | Purpose | Primary retrieval queries |
|---|---|---|
| `openings` | Opening theory, system names, opening principles | "how should I open?", "what does this move prepare?" |
| `tactics` | Tactical patterns: clearance, dislodge, fork, pin, discovered check, sacrifice | "explain this tactic", "why is my piece hanging?" |
| `endgames` | Endgame patterns, checkmate constructions, practical endgame motifs | "how do I convert this endgame?", "explain this puzzle" |
| `beginner_principles` | General principles, proverbs, piece values, phase advice | "how do I improve?", "what should I prioritize?" |

---

## URL Discovery — 2026-04-22 Crawl Results

The master category pages below were crawled to discover correct canonical article URLs. All sources were matched against these listings. Ten xqinenglish URLs were corrected as a result (see Corrections section).

### xqinenglish.com Category Structure

| Master URL | Category | Subcategories / Notable Articles |
|---|---|---|
| `catid=110, Itemid=504` | Basics of Xiangqi | Basics 01–08 series (IDs: 167, 101, 166, 168, 169, 170, 171, 172), Proverbs (924), Tips (946, 947) |
| `catid=226, Itemid=511` | Opening Basics | Intro Opening (105), Choosing Opening (983), ECCO Intro (443), Basic Concepts (449-452) |
| `catid=225, Itemid=510` | Midgame Introduction | Intro Midgame (104), Defining Midgame (972), Strategical Advice (1076), Tactics Overview (1050-1059, 1080) |
| `catid=223, Itemid=510` | Basic Midgame Tactics | 45 articles; Tactic series (01a-07c+); Clearance 01c (1178), Dislodge 07c (1103) |
| `catid=106/207, Itemid=522` | Basic Kills | Intro (100), King kills (125, 127, 130), Chariot kills (126, 129, 379), Horse kills (139-144, 286), Cannon kills (131-137), Pawn kills (145-147) |
| `catid=220, Itemid=509` | TJM Practical Endgames | 31 articles (individual article IDs not yet crawled) |
| `catid=112, Itemid=511` | Opening Theory hub | 18 subcategories including Same-Direction Cannons, Screen Horse Defense, Sandwiched Horse, Pawn Opening, Elephant Opening |
| `catid=113, Itemid=510` | Midgame hub | Subcategories: Midgame Intro (225), Basic Midgame Tactics (223), Sun Zi Art of War (314, 319) |
| `catid=111, Itemid=509` | Endgame hub | Subcategories: Endgame Intro (287), TJM Practical Endgames (220) |

### Other Sources

| Site | URL | Status |
|---|---|---|
| boardgamearena | `https://en.doc.boardgamearena.com/Tips_xiangqi` | Valid — 5 sections: Opening, Development, Check, Defense, Overall |
| xiangqi.com | `https://www.xiangqi.com/how-to-play-xiangqi` | Valid — comprehensive beginner guide |
| xiangqi.com | `https://www.xiangqi.com/help/pieces-and-moves` | Valid — all 7 piece types with movement rules |
| wxf-xiangqi.org | `https://www.wxf-xiangqi.org/...id=235:en36stratagems00...` | Valid — 36 Stratagems article + video series hub |

---

## Corrections Applied (2026-04-22)

The following sources had wrong article IDs in the original `sources.yaml`. All were discovered by crawling the master category pages listed above. The Joomla CMS routes articles by ID regardless of catid slug, so wrong IDs either returned HTTP 404 or fetched a completely unrelated article at the same numeric ID.

| source_id | Old ID | New ID | Old catid | New catid | Status |
|---|---|---|---|---|---|
| `xqinenglish_opening_basics_05` | 108 | **169** | 110 | 110 | Was HTTP 404 |
| `xqinenglish_choosing_opening` | 107 | **983** | 110 | 226 | Likely wrong article |
| `xqinenglish_intro_opening` | 106 | **105** | 110 | 226 | Likely wrong article |
| `xqinenglish_how_to_play_basics_02` | 105 | **101** | 110 | 110 | id=105 is a different article |
| `xqinenglish_strategical_advice_middle_game` | 152 | **1076** | 111 | 225 | Wrong article fetched |
| `xqinenglish_tactics_01c_clearance` | 166 | **1178** | 111 | 223 | id=166 is "Basics 03 Chessboard" |
| `xqinenglish_tactics_07c_dislodge` | 179 | **1103** | 111 | 223 | Wrong article fetched |
| `xqinenglish_endgame_basics_08` | 109 | **172** | 110 | 110 | Was HTTP 404 |
| `xqinenglish_basic_checkmate_methods` | 446 | **100** | 273 | 207 | Was HTTP 404 |
| `xqinenglish_basics_of_play` | 107 | **167** | 110 | 110 | id=107 not in catid=110 |

Additionally:
- `xqinenglish_tjm_practical_endgames` was `url_status: unresolved`. Now resolved to `catid=220, Itemid=509`.
- Added two new Wave 1 sources: `xiangqi_com_how_to_play` and `xiangqi_com_pieces_and_moves`.

---

## Re-Acquisition Instructions

All entries in `acquisition_runs.jsonl` with `status: "url_corrected"` need to be re-fetched. The raw HTML files in `raw/xqinenglish/` for those sources contain wrong content and must be replaced.

```bash
cd server/web_scraper/knowledge

# Re-fetch all corrected xqinenglish Wave 1 sources
python acquire.py --wave 1 --force

# Or individually:
python acquire.py --source-id xqinenglish_opening_basics_05 --force
python acquire.py --source-id xqinenglish_choosing_opening --force
python acquire.py --source-id xqinenglish_intro_opening --force
python acquire.py --source-id xqinenglish_how_to_play_basics_02 --force
python acquire.py --source-id xqinenglish_strategical_advice_middle_game --force
python acquire.py --source-id xqinenglish_tactics_01c_clearance --force
python acquire.py --source-id xqinenglish_tactics_07c_dislodge --force
python acquire.py --source-id xqinenglish_endgame_basics_08 --force
python acquire.py --source-id xqinenglish_basic_checkmate_methods --force
python acquire.py --source-id xqinenglish_basics_of_play --force
python acquire.py --source-id xqinenglish_how_to_play_basics_02 --force

# Fetch new Wave 1 sources:
python acquire.py --source-id xiangqi_com_how_to_play
python acquire.py --source-id xiangqi_com_pieces_and_moves
```

After re-fetching, run the normalizer and chunker pipeline to update ChromaDB.

---

## Wave Plan

### Wave 1 — Core Corpus (P0 sources, required for coaching)

Target: all four collections populated with at least 3 high-quality sources each.

| source_id | Collection(s) | Phase | Notes |
|---|---|---|---|
| `xqinenglish_basics_of_play` | beginner_principles, openings, endgames | all | Basics 01 General Intro |
| `xqinenglish_how_to_play_basics_02` | beginner_principles | all | Basics 02 How to Play |
| `xqinenglish_opening_basics_05` | openings, beginner_principles | opening | Basics 05 Opening Phase |
| `xqinenglish_choosing_opening` | openings, beginner_principles | opening | Choosing an Opening |
| `xqinenglish_intro_opening` | openings, beginner_principles | opening | Intro to Opening Theory |
| `xqinenglish_strategical_advice_middle_game` | tactics, beginner_principles | middlegame | Strategic Middlegame Advice |
| `xqinenglish_intro_midgame` | tactics, beginner_principles | middlegame | Midgame Introduction |
| `xqinenglish_tactics_01c_clearance` | tactics, beginner_principles | middlegame | Clearance Tactic |
| `xqinenglish_tactics_07c_dislodge` | tactics, beginner_principles | middlegame | Dislodge Tactic |
| `xqinenglish_endgame_basics_08` | endgames, beginner_principles | endgame | Basics 08 Endgame |
| `xqinenglish_tjm_practical_endgames` | endgames | endgame | 31-article practical endgame category |
| `xqinenglish_proverbs_84_play` | beginner_principles, tactics | general | 84 Proverbs (one chunk per proverb) |
| `xqinenglish_basic_checkmate_methods` | endgames, beginner_principles | general | Basic Kills intro (all piece types) |
| `xiangqi_com_how_to_play` | beginner_principles, openings, endgames | all | Comprehensive beginner guide |
| `xiangqi_com_pieces_and_moves` | beginner_principles | all | All piece types and rules |

### Wave 2 — Expanded Coverage (P0–P1 sources)

| source_id | Collection(s) | Phase | Notes |
|---|---|---|---|
| `xiangqi_com_opening_principles_10` | openings, beginner_principles | opening | 10 key opening principles |
| `boardgamearena_tips_xiangqi` | beginner_principles, openings | opening | Compact tips page |
| `xiangqi_com_midgame_step_by_step` | tactics, beginner_principles | middlegame | Strategic midgame guide |
| `xiangqi_com_midgame_capture_pieces` | tactics | middlegame | Tactical capture patterns |
| `xiangqi_com_eleven_endgame_compositions` | endgames | endgame | Classic endgame compositions |
| `xqinenglish_puzzles_henry_hong_congfa` | endgames | endgame | Puzzle table (one doc per puzzle) |
| `xqinenglish_proverbs_47_life` | beginner_principles | general | 47 life proverbs |
| `xqinenglish_sunzi_ch06d` | tactics, beginner_principles | general | Sun Zi strategy crossover |
| `xiangqi_master_modern_two_horses_defense` | openings | opening | Named opening system |
| `chess_polyglot_xiangqi_proverbs` | beginner_principles | general | Deduplicate against xqinenglish proverbs |
| `felicity_egtb` | endgames | endgame | Endgame tablebase docs |
| `wxf_introduction_to_xiangqi` | beginner_principles, openings, endgames | all | Official WXF intro PDF |
| `wxf_website` | beginner_principles, endgames | all | Official rules and PDFs |
| `xiangqi_com_resources_hub` | — | all | Discovery page; extract linked lessons |
| `chessdb_opening_api` | openings | opening | API-based opening database (seed FENs required) |

### Wave 3 — Supplementary (P2–P3 sources)

| source_id | Notes |
|---|---|
| `wxf_36_stratagems` | Only if reliable transcript is available |
| `xqinenglish_endgame_puzzles_chinese_characters` | Requires specialized parser |
| `awesome_xiangqi` | Discovery source; not direct corpus |
| `brainking_chinese_chess_forum` | High noise; manual filtering required |
| `pychess_xiangqi` | Dynamic web; network API analysis needed |
| `android_chinese_chess_easy_to_expert` | Deferred; licensing unclear |

---

## Next Steps for Expanded Coverage

The following article groups were discovered during the 2026-04-22 crawl and are candidates for future source entries. Add these to `sources.yaml` as Wave 2 or Wave 3 entries.

### xqinenglish Basic Kills (catid=207, Itemid=522)
Each of the named kill patterns below is a separate article and strong candidate for the `endgames` and `tactics` collections:

| Article ID | Title |
|---|---|
| 100 | Introduction to Basic Kills *(already in Wave 1 as `xqinenglish_basic_checkmate_methods`)* |
| 125 | White Faced General Checkmate |
| 126 | Throat Cutting Checkmate |
| 127 | Iron Bolt Checkmate (King) |
| 129 | Double Chariots Checkmate |
| 130 | Moon Scooping Checkmate |
| 131 | Detonating Mine Attack |
| 132 | Cannons Sandwiching Chariot |
| 133 | Double Cannons Checkmate |
| 134 | Smothered Cannon Checkmate |
| 135 | Double Toast Checkmate |
| 136 | Headhunter Cannon Kill |
| 137 | Heaven and Earth Cannons |
| 139 | Double Horses Checkmate |
| 140 | Elbow Horse Checkmate |
| 141 | Palcorner Horse Checkmate |
| 142 | Octagonal Horse Checkmate |
| 143 | Angler Horse Checkmate |
| 144 | Tiger Silhouette Checkmate |
| 145 | Two Devils Knocking Checkmate |
| 146 | Eunuch Chasing Emperor |
| 147 | Repatriation of Buddha Checkmate |

### xqinenglish Basic Midgame Tactics (catid=223, Itemid=510)
45 articles organized into numbered tactic series (01–07+). Beyond the two already in Wave 1 (`1178` clearance, `1103` dislodge), the remaining series are strong `tactics` collection candidates:

| Article ID | Title |
|---|---|
| 423 | Tactics 00 Intro |
| 424 | Tactics 01a Clearance |
| 1177 | Tactics 01b Clearance |
| 915 | Tactics 02a Discovered Check |
| 1180 | Tactics 02b Discovered Check |
| 1181 | Tactics 02c Discovered Check |
| 926 | Tactics 03a Capturing Material |
| 1101 | Tactics 07a Dislodge |
| 1102 | Tactics 07b Dislodge |
| *(+35 more — crawl remaining pages of catid=223)* | |

### xqinenglish Opening Basics (catid=226, Itemid=511)
| Article ID | Title |
|---|---|
| 983 | Choosing your Opening *(Wave 1)* |
| 105 | Introduction to Opening *(Wave 1)* |
| 984 | A Brief History of the Opening |
| 1000 | Glossary of Opening Terms |
| 1001 | Glossary of Opening Systems |
| 449–452 | Basic Concepts in Opening Theory 01–04 |
| 443 | Introduction to ECCO Classification |
| 896 | Orthodox Opening Systems |
| 897 | Unorthodox Opening Systems |

---

## Chunking Strategy

| Source type | Chunk strategy |
|---|---|
| Long articles (>1500 words) | Split at H2/H3 headings; ~300–500 tokens per chunk |
| Proverb lists | One proverb per chunk + optional theme-group summary |
| Tactic articles | Motif definition chunk + one chunk per worked example |
| Endgame category hubs | Crawl individual article URLs; one article = one or more chunks |
| Puzzle articles | One puzzle per chunk; include FEN if extractable |
| PDF sources | Extract text; chunk at ~500 tokens with 100-token overlap |

---

## Metadata Schema

Each embedded chunk should carry:

```json
{
  "source_id": "xqinenglish_tactics_01c_clearance",
  "title": "...",
  "phase": "middlegame",
  "collection": "tactics",
  "tags": ["clearance", "tactic"],
  "chunk_index": 0,
  "total_chunks": 4,
  "url": "https://..."
}
```
