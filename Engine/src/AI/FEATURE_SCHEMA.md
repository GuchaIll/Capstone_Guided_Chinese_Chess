# Feature Extraction Schema for Xiangqi LLM Fine-Tuning

This document describes the complete set of metrics and features extracted by the engine's
position analysis pipeline. These features are designed to be paired with expert commentary
text for fine-tuning an LLM model that can generate contextual, accurate move explanations.

## Overview

Each move in a game produces a `MoveFeatureVector` containing three major sections:
1. **Position Analysis** — deep positional snapshot *before* the move
2. **Search Metrics** — engine evaluation data from the alpha-beta search
3. **Move Metadata** — details about the specific move played

## 1. Position Analysis (`position_analysis`)

### 1.1 Basic State
| Field | Type | Description |
|-------|------|-------------|
| `fen` | string | FEN string of the position |
| `side_to_move` | string | "red" or "black" |
| `phase_value` | float | Game phase: 1.0 = opening, 0.0 = endgame |
| `phase_name` | string | "opening", "midgame", or "endgame" |
| `move_number` | int | Full move number |
| `halfmove_clock` | int | Moves since last capture/pawn move (for 60-move rule) |

### 1.2 Material (`material`)
| Field | Type | Description |
|-------|------|-------------|
| `red_pawns` ... `red_rooks` | int | Count of each piece type for Red |
| `black_pawns` ... `black_rooks` | int | Count of each piece type for Black |
| `red_material_value` | int | Total Red material in centipawns |
| `black_material_value` | int | Total Black material in centipawns |
| `material_balance` | int | Red advantage (positive = Red ahead) |

### 1.3 Mobility (`mobility`)
| Field | Type | Description |
|-------|------|-------------|
| `red_legal_moves` | int | Number of legal moves for Red |
| `black_legal_moves` | int | Number of legal moves for Black |
| `mobility_advantage` | int | Red legal moves minus Black legal moves |

### 1.4 King Safety (`red_king_safety`, `black_king_safety`)
| Field | Type | Description |
|-------|------|-------------|
| `king_square` | string | Square where the king sits (e.g. "e0") |
| `advisor_count` | int | Number of advisors remaining (0-2) |
| `elephant_count` | int | Number of elephants remaining (0-2) |
| `palace_integrity` | float | 0.0 (no defenders) to 1.0 (full palace guard) |
| `attackers_near_king` | int | Opponent pieces attacking king-adjacent squares |
| `king_file_open` | bool | No friendly pieces shielding the king's file |
| `king_exposed` | bool | In check OR open file with no advisors |

### 1.5 Piece-Square Table Scores
| Field | Type | Description |
|-------|------|-------------|
| `red_pst_score` | int | Total positional bonus for Red pieces |
| `black_pst_score` | int | Total positional bonus for Black pieces |

### 1.6 Piece Locations (`piece_locations`)
Array of all non-king pieces with:
| Field | Type | Description |
|-------|------|-------------|
| `piece_type` | string | "pawn", "advisor", "elephant", "knight", "cannon", "rook" |
| `side` | string | "red" or "black" |
| `square` | string | Board square (e.g. "a0") |
| `file` | int | File index 0-8 |
| `rank` | int | Rank index 0-9 |
| `crossed_river` | bool | Whether piece has crossed the river |

## 2. Relational Mappings

### 2.1 Hanging Pieces (`hanging_pieces`)
Pieces that are attacked by the opponent but NOT defended by their own side.
| Field | Type | Description |
|-------|------|-------------|
| `piece_type` | string | Type of the hanging piece |
| `side` | string | Owner of the hanging piece |
| `square` | string | Square |
| `value` | int | Material value in centipawns |
| `attacked_by` | string[] | Types of attacking pieces |

### 2.2 Piece Relations (`piece_relations`)
Attack, defense, and distance relationships between key pieces (rooks, cannons, knights, kings).
| Field | Type | Description |
|-------|------|-------------|
| `piece_a` | string | e.g. "red rook at a0" |
| `piece_b` | string | e.g. "black king at e9" |
| `relation` | string | "attacks", "defends", or "distance" |
| `distance` | int | Manhattan distance between pieces |

### 2.3 Cannon Screens (`cannon_screens`)
For each cannon, all orthogonal directions where a screen piece exists.
| Field | Type | Description |
|-------|------|-------------|
| `cannon_square` | string | Cannon position |
| `cannon_side` | string | Cannon owner |
| `screen_square` | string | Screen piece position |
| `screen_piece` | string | e.g. "red pawn" |
| `target_square` | string? | Piece behind screen (capture target) |
| `target_piece` | string? | Type of piece behind screen |
| `direction` | string | "up", "down", "left", "right" |

### 2.4 Rook File Analysis (`rook_files`)
| Field | Type | Description |
|-------|------|-------------|
| `rook_square` | string | Rook position |
| `rook_side` | string | Rook owner |
| `file` | int | File index |
| `is_open_file` | bool | No pawns of either side on this file |
| `is_semi_open` | bool | No friendly pawns, but enemy pawns present |
| `controls_rank` | bool | Rook is on enemy back ranks |

### 2.5 Pawn Chains (`pawn_chains`)
Groups of connected pawns (adjacent files/ranks).
| Field | Type | Description |
|-------|------|-------------|
| `side` | string | Pawn owner |
| `squares` | string[] | List of squares in the chain |
| `crossed_river` | bool | Any pawn in chain has crossed the river |
| `connected` | bool | Multiple pawns in this chain |

### 2.6 Cross-River Pieces (`cross_river_pieces`)
Pieces that have crossed into enemy territory.
| Field | Type | Description |
|-------|------|-------------|
| `piece_type` | string | Type |
| `side` | string | Owner |
| `square` | string | Square |
| `depth_into_enemy` | int | Ranks past the river (1-5) |

### 2.7 Forks (`forks`)
A piece attacking 2+ valuable enemy pieces simultaneously.
| Field | Type | Description |
|-------|------|-------------|
| `attacker_type` | string | Type of forking piece |
| `attacker_square` | string | Square |
| `attacker_side` | string | Owner |
| `targets` | string[] | e.g. ["rook at e5", "king at e9"] |

### 2.8 Pins (`pins`)
Pieces pinned to the king by a sliding piece.
| Field | Type | Description |
|-------|------|-------------|
| `pinned_piece` | string | e.g. "black knight" |
| `pinned_square` | string | Square |
| `pinner_type` | string | Type of pinning piece (usually rook) |
| `pinner_square` | string | Square |
| `pinned_to` | string | Usually "king" |

## 3. Search Metrics (`search_metrics`)

| Field | Type | Description |
|-------|------|-------------|
| `score` | int | Engine evaluation in centipawns |
| `score_delta` | int | Change from previous move's score |
| `centipawn_loss` | int | How much worse than the best move (0 = best) |
| `depth_reached` | int | Search depth completed |
| `nodes_searched` | int | Total nodes evaluated |
| `nodes_per_second` | float | Search speed |
| `search_time_ms` | float | Wall-clock search time |
| `principal_variation` | string[] | Best line of play |
| `tt_hits` | int | Transposition table hits |
| `tt_cuts` | int | TT cutoffs (saved full searches) |
| `tt_stores` | int | TT entries stored |
| `tt_collisions` | int | TT hash collisions |
| `tt_hit_rate` | float | Ratio of hits to total lookups |

## 4. Move Metadata (`move_metadata`)

| Field | Type | Description |
|-------|------|-------------|
| `move_str` | string | e.g. "e3e4" |
| `from_square` | string | Origin square |
| `to_square` | string | Destination square |
| `piece_type` | string | Moving piece type |
| `piece_side` | string | Moving piece owner |
| `is_capture` | bool | Whether the move captures |
| `captured_piece_type` | string? | Type of captured piece |
| `captured_value` | int? | Value of captured piece |
| `gives_check` | bool | Move puts opponent in check |
| `is_checkmate` | bool | Move delivers checkmate |
| `move_number` | int | Full move number |

## 5. Move Classification (`classification`)

| Field | Type | Description |
|-------|------|-------------|
| `is_sacrifice` | bool | Captures less-valuable piece but engine likes it |
| `is_blunder` | bool | Centipawn loss > 200 |
| `is_inaccuracy` | bool | Centipawn loss 50-200 |
| `is_good_move` | bool | Centipawn loss < 10 |
| `is_brilliant` | bool | Only/best move with high node count |
| `is_book_move` | bool | Matches known opening (future) |
| `category` | string | "brilliant", "good", "acceptable", "inaccuracy", "mistake", "blunder" |

## 6. Alternatives (`alternatives`)

Top 5 alternative moves with their evaluation:
| Field | Type | Description |
|-------|------|-------------|
| `move_str` | string | Alternative move |
| `score` | int | Evaluation of the alternative |
| `piece_type` | string | Piece type |
| `is_capture` | bool | Whether it's a capture |

## 7. Post-Move State

| Field | Type | Description |
|-------|------|-------------|
| `post_move_fen` | string | FEN after the move |
| `post_move_in_check` | bool | Opponent in check after move |
| `post_move_is_game_over` | bool | Game ended |
| `post_move_result` | string | "in_progress", "red_wins", "black_wins", "draw" |

## Usage for Fine-Tuning

Each training example pairs a `MoveFeatureVector` (structured input) with expert
commentary text (target output). The LLM learns to generate contextual explanations
given the rich positional, relational, and search features.

### Example Training Pair

```json
{
  "features": {
    "position_analysis": {
      "phase_name": "opening",
      "material": { "material_balance": 0 },
      "mobility": { "red_legal_moves": 44, "black_legal_moves": 44 },
      "cannon_screens": [{"cannon_square": "b2", "screen_piece": "red pawn", ...}],
      "cross_river_pieces": []
    },
    "search_metrics": { "score": 50, "depth_reached": 4 },
    "move_metadata": { "move_str": "h2e2", "piece_type": "cannon", "is_capture": false },
    "classification": { "category": "good" }
  },
  "expert_commentary": "Central cannon opening - the most popular first move in Xiangqi. Controls the central file and threatens the opponent's e6 pawn."
}
```

### Pipeline Command

```bash
python generate_training_data.py \
  --input games/expert_game.jsonl \
  --output training_data/features.jsonl \
  --depth 4
```

## 8. Data Acquisition — DhtmlXQ Game Scraper

Expert commentary data is sourced from xqinenglish.com's annotated game collection,
which uses the **DhtmlXQ / CC Bridge** embedded viewer format.

### DhtmlXQ Format

Games are embedded in HTML pages within `[DhtmlXQ]...[/DhtmlXQ]` blocks containing:
- `[DhtmlXQ_movelist]` — moves as 4-digit coordinate groups (col+row pairs)
- `[DhtmlXQ_commentN]` — per-move expert commentary (1-indexed)
- `[DhtmlXQ_title/red/black/event/result]` — game metadata

### Coordinate System

DhtmlXQ uses: column 0-8 (a-i), row 0-9 (0 = Black back rank, 9 = Red back rank).
Conversion to engine algebraic: `file = chr('a' + col)`, `rank = 9 - row`.

Example: `7747` → col7,row7 → col4,row7 → `h2e2` (central cannon opening).

### Scraper Pipeline

```
xqinenglish.com (DhtmlXQ pages)
  └─ scrape_games.py (3-level crawl: index → years → games)
       └─ dhtmlxq_parser.py (parse blocks → DhtmlXQGame objects)
            └─ FEN generation (replay moves on 10×9 board)
                 └─ JSONL output (FEN + move + commentary per entry)
                      └─ generate_training_data.py (engine analysis → features)
                           └─ Final JSONL (features + expert commentary)
```

### Commands

```bash
# Step 1: Scrape games from xqinenglish.com
cd server/web_scraper
python scrape_games.py \
  --output data/raw/games/xqinenglish_games.jsonl \
  --commentary-only

# Step 2: Run through engine analysis pipeline (from server/ directory)
cd server
python -m agent_orchestration.tools.generate_training_data \
  --input web_scraper/data/raw/games/xqinenglish_games.jsonl \
  --output training_data/features.jsonl \
  --depth 4

# OR run the script directly (from project root):
python server/agent_orchestration/tools/generate_training_data.py \
  --input server/web_scraper/data/raw/games/xqinenglish_games.jsonl \
  --output training_data/features.jsonl \
  --depth 4

# Quick test (5 games only)
cd server/web_scraper
python scrape_games.py --max-games 5 --output data/raw/games/test.jsonl
```

### Output Format (scraper JSONL)

Each line is a single move entry:

```json
{
  "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
  "move_str": "h2e2",
  "expert_commentary": "Central cannon opening - controls the center file.",
  "move_index": 0,
  "side": "red",
  "game_title": "2024 Championship Rd 1",
  "red_player": "Wang Tianyi",
  "black_player": "Zheng Weitong",
  "event": "National Championship",
  "result": "1-0",
  "source_url": "https://www.xqinenglish.com/index.php?..."
}
```

