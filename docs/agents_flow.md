# Chess Coach Agents — Flow & Responsibilities

> **Scope:** This document describes the Go coaching service (`server/chess_coach/`, port 5002) — its agents, skills, tools, and how each one integrates with the state bridge and Rust engine in the physical-board use case.

---

## 1. Where the Coaching Service Fits

```
Physical Board
  └─ Player presses End Turn
         │
         ▼
  React Frontend
  ├─ sends End Turn → CV captures → POST /state/fen to State Bridge
  ├─ SSE fen_update received → board redraws
  └─ POST /dashboard/chat  ──────────────────────────────────────────┐
                                                                      ▼
                                                           Go Coach  :5002
                                                           ┌─────────────────┐
                                                           │  Agent Graph    │
                                                           │  (10 agents)    │
                                                           └────────┬────────┘
                                                                    │ REST
                                                                    ▼
                                                           State Bridge :5003
                                                                    │ REST
                                                                    ▼
                                                           Rust Engine :8080
```

The coaching service receives a chat message from the frontend (with FEN and/or move context), runs it through a pipeline of agents, and returns a coaching response. It never touches the board state directly — it reads it via the state bridge and calls the engine through the bridge's relay endpoints.

---

## 2. Agent Graph Pipeline

```
[Input: POST /coach or /dashboard/chat]
          │
          ▼
    ┌──────────┐
    │  Ingest  │  — parse FEN, move, question from raw input
    └────┬─────┘
         │
         ▼
    ┌────────────┐
    │ Inspection │  — validate FEN with engine
    └─────┬──────┘
          │
          ▼
    ┌──────────────┐
    │ Orchestrator │  — classify intent, set routing flags, check coach triggers
    └──────┬───────┘
           │
           ▼
    ┌──────────────────┐
    │ Blunder Detection│  — runs FIRST; checks if the submitted move is a blunder
    └────────┬─────────┘
             │
      ┌──────┴──────────────────────────────────┐
      │  BLUNDER DETECTED                        │  NO BLUNDER
      │  (blunder_abort = true)                  │
      ▼                                          ▼
 ┌──────────┐                         ┌──────────────────────────────────────┐
 │ Feedback │ ← ABORT all other flows │           PARALLEL                   │
 │ (blunder │                         │  ┌──────────────┐  ┌───────────────┐ │
 │  summary │                         │  │  Position    │  │    Puzzle     │ │
 │  only)   │                         │  │  Analyst     │  │    Curator    │ │
 └──────────┘                         │  └──────┬───────┘  └───────────────┘ │
                                       └─────────┼────────────────────────────┘
                                                 │
                                    ┌────────────┴────────────────┐
                                    │  FAST PATH                   │  SLOW PATH
                                    │  (no coach trigger)          │  (coach trigger met)
                                    │                              ▼
                                    │                        ┌──────────────┐
                                    │                        │ Coach Agent  │
                                    │                        │ (LLM call)   │
                                    │                        └──────┬───────┘
                                    │                               │
                                    │                        ┌──────▼───────┐
                                    │                        │ Guard Agent  │
                                    │                        │ (scoring:    │
                                    │                        │  approve or  │
                                    │                        │  reject      │
                                    │                        │  advice)     │
                                    │                        └──────┬───────┘
                                    │                               │
                                    └──────────────┬────────────────┘
                                                   │
                                                   ▼
                                           ┌──────────────┐
                                           │ Visualization│
                                           └──────┬───────┘
                                                  │
                                                  ▼
                                           ┌──────────┐
                                           │ Feedback │  — assemble final response
                                           └──────────┘
                                                  │
                                                  ▼
                                         [Response to frontend]
```

### Path Summary

| Path | Condition | Agents run |
|---|---|---|
| **Abort (blunder)** | Blunder detected | Ingest → Inspection → Orchestrator → Blunder Detection → Feedback |
| **Fast path** | No blunder, no coach trigger | → + Position Analyst ‖ Puzzle Curator → Visualization → Feedback |
| **Slow path** | No blunder, coach trigger met | → + Position Analyst ‖ Puzzle Curator → Coach → Guard → Visualization → Feedback |

---

## 3. Agent Responsibilities

### 3.1 Ingest Agent

**Role:** Normalize raw user input into structured fields.

**What it does:**
- Scans the incoming message text for a FEN string (regex pattern).
- Scans for a move in algebraic notation (e.g., `e3e5`).
- Extracts the user's natural-language question.
- Sets flags: `is_question`, `has_move`, `question_only`.

**Bridge/Engine calls:** None.

**State written:**

| Key | Type | Description |
|---|---|---|
| `fen` | string | Extracted FEN (or passed-through from request body) |
| `move` | string | Extracted move string |
| `question` | string | User's natural-language text |
| `is_question` | bool | True if message is a question, not a move submission |
| `has_move` | bool | True if a move was extracted |
| `question_only` | bool | True if no FEN/move detected — skip engine calls |

---

### 3.2 Inspection Agent

**Role:** Confirm the FEN is valid before the rest of the pipeline uses it.

**What it does:**
- Calls the bridge `/engine/validate-fen` endpoint.
- If `question_only` is set, skips validation entirely.
- Writes `fen_valid = true/false`.

**Bridge call:**

```
POST /engine/validate-fen
Body: { "fen": "<fen>" }
Response: { "valid": true }
```

**State written:**

| Key | Type | Description |
|---|---|---|
| `fen_valid` | bool | Whether the FEN passed engine validation |

---

### 3.3 Orchestrator Agent

**Role:** Interpret intent and route the request to the right downstream agents.

**What it does:**
- Determines which pipeline branches to activate based on what was provided (FEN, move, question keywords).
- Optionally makes a quick LLM call to classify the intent as: `ANALYZE`, `BLUNDER_CHECK`, `PUZZLE`, `EXPLAIN`, or `GENERAL_ADVICE`.
- Can call two tools to enrich context before routing.

**Bridge calls:**

```
POST /engine/suggest  (get a quick best-move for context)
Body: { "fen": "<fen>", "depth": 5 }
Response: { "move": "e3e5", "score": 120 }

(via get_position_features tool)
POST /engine/analyze
Body: { "fen": "<fen>", "depth": 5 }
Response: AnalysisResponse
```

**Routing logic:**

```
route_blunder_detection  = fen is present AND (move or moves present)
route_position_analysis  = fen is present AND NOT blunder_abort
route_puzzle             = (question contains "puzzle/practice/exercise/train/drill")
                           OR (set by BlunderDetection if blunders found in prior turns)
                           AND NOT blunder_abort
route_visualization      = fen is present AND NOT blunder_abort
```

**Coach trigger evaluation (Orchestrator sets `coach_trigger`):**

```
moves_since_last_coach >= 3                         → coach_trigger = "move_count"
│abs(current_score - prev_score)│ > 200 centipawns  → coach_trigger = "material_shift"
tactical_pattern_detected == true                   → coach_trigger = "tactical_pattern"
else                                                → coach_trigger = "none"  (fast path)
```

**State written:**

| Key | Description |
|---|---|
| `route_blunder_detection` | Activate BlunderDetection (runs first, always when move present) |
| `route_position_analysis` | Activate PositionAnalyst branch |
| `route_puzzle` | Activate PuzzleCurator branch |
| `route_visualization` | Activate VisualizationAgent |
| `coach_trigger` | `"move_count"` / `"material_shift"` / `"tactical_pattern"` / `"none"` |
| `classified_intent` | Intent string from LLM classification |
| `moves_since_last_coach` | How many moves since CoachAgent last ran |

---

### 3.4 Blunder Detection Agent

**Role:** First analysis node — run immediately after Orchestrator. Detect whether the submitted move is a blunder and abort all other flows if so.

**Execution order:** Runs **before** Position Analyst. Nothing else runs until this completes.

**What it does:**
- Runs only if `route_blunder_detection = true` (move or move sequence present).
- Analyzes the submitted move by comparing it against the engine's best alternative.
- A move is a **blunder** if its centipawn loss exceeds 150cp.
- **If a blunder is detected:**
  - Sets `blunder_abort = true`.
  - Sets `route_puzzle = true` (for the *next* turn, not the current one).
  - Stores blunder details and the FEN at the blunder position.
  - **All downstream agents are skipped.** Flow goes directly to Feedback.
- **If no blunder:** Sets `blunder_abort = false` and the pipeline continues normally.

**Bridge call:**

```
POST /engine/batch-analyze
Body: {
  "moves": [
    { "fen": "<before-move-fen>", "move_str": "e3e5" },
    ...
  ]
}
Response: [
  {
    move_metadata: { move_str, from_square, to_square, piece_type, piece_side },
    search_metrics: { score, score_delta, centipawn_loss, depth_reached, pv },
    classification: { is_blunder, is_inaccuracy, is_good_move, is_brilliant, category },
    alternatives: [{ move, score, centipawn_diff }],
    post_move_fen
  },
  ...
]
```

**Routing on blunder:**

```
if blunders_found:
    state["blunder_abort"]    = true   ← signals Feedback to use blunder path
    state["blunder_analysis"] = [...]
    state["blunder_positions"] = [fens]
    state["route_puzzle"]     = true   ← PuzzleCurator runs next turn
    → SKIP: Position Analyst, Puzzle Curator, Coach, Guard, Visualization
    → DIRECT ROUTE → Feedback
```

**State written:**

| Key | Description |
|---|---|
| `blunder_abort` | `true` if blunder detected — aborts all other flows |
| `blunder_analysis` | Full per-move classification array |
| `blunder_positions` | FEN strings at each blunder moment |
| `route_puzzle` | Set to `true` if blunder detected (activates PuzzleCurator next turn) |

---

### 3.5 Position Analyst Agent

**Role:** Deep evaluation of the current board position.

**Execution order:** Runs in parallel with Puzzle Curator, after Blunder Detection passes (no blunder).

**What it does:**
- Skipped entirely if `blunder_abort = true`.
- Runs only if `route_position_analysis = true`.
- Calls the engine for a full position analysis (score, depth, PV, piece features).
- Extracts game phase, material balance, hanging pieces, forks, pins.
- Detects tactical patterns — a detected pattern sets `tactical_pattern_detected = true`, which can trigger the Coach Agent (slow path).
- Optionally queries ChromaDB for related opening/middlegame/endgame knowledge.
- **Always emits output to Feedback via the fast path**, regardless of whether the slow path (Coach) also runs.

**Bridge calls (sequential):**

```
1. POST /engine/analyze
   Body: { "fen": "<fen>", "depth": 20 }
   Response: {
     score, depth, pv,
     features: {
       fen, side_to_move, phase_name, phase_value, move_number,
       material: { red_pawns, red_rooks, ..., balance },
       mobility: { red_legal_moves, black_legal_moves, advantage },
       red_king_safety, black_king_safety,
       hanging_pieces: [...],
       forks: [...],
       pins: [...],
       cannon_screens: [...],
       rook_files: [...],
       cross_river_pieces: [...]
     }
   }

2. POST /engine/analyze  (same call — extracts principal variation)
   → pv: ["e3e5", "h9g7", ...]
```

**RAG calls (if ChromaDB available):**

```
Collection: openings / tactics / endgames
Query: position description or question text
Returns: relevant passages (top 3–5)
```

**Tactical pattern trigger:**

```
if forks OR pins OR hanging_pieces OR cannon_screens detected:
    state["tactical_pattern_detected"] = true
    → may trigger slow path (Coach Agent) if coach_trigger == "tactical_pattern"
```

**State written:**

| Key | Description |
|---|---|
| `engine_metrics` | Score, depth, best move |
| `game_phase` | Opening / Middlegame / Endgame |
| `material_info` | Per-piece counts, material balance |
| `hanging_pieces` | Pieces at risk |
| `forks` | Detected fork patterns |
| `pins` | Detected pin patterns |
| `principal_variation` | Best move sequence from engine |
| `tactical_pattern_detected` | `true` if any tactical motif found (fork/pin/hanging/cannon) |

---

### 3.6 Puzzle Curator Agent

**Role:** Generate a tactical training puzzle from a position.

**Execution order:** Runs **in parallel with Position Analyst**, after Blunder Detection passes. Skipped if `blunder_abort = true`.

**What it does:**
- Runs only if `route_puzzle = true`.
- Detects the tactical motif (fork, pin, skewer, discovered attack, hanging piece, check, checkmate, combination).
- Generates the solution by repeated `Suggest + MakeMove` calls to the engine.
- Rates the difficulty and tags the themes.
- Optionally generates layered hints (vague → moderate → specific).

**Bridge calls (sequential):**

```
1. POST /engine/analyze          → get_tactical_patterns (features)
   Body: { "fen": "<fen>", "depth": 15 }

2. POST /engine/suggest          → find_tactical_motif (shallow look-ahead)
   Body: { "fen": "<fen>", "depth": 15 }

3. POST /engine/suggest          → generate_puzzle (step 1 of solution)
   Body: { "fen": "<fen>", "depth": 20 }

4. POST /engine/make-move        → generate_puzzle (apply move, repeat)
   Body: { "fen": "<fen>", "move": "e3e5" }
   (Repeated until mate/capture/solution depth reached)

5. POST /engine/suggest          → generate_hint (at lower depth)
   Body: { "fen": "<fen>", "depth": 5 }
```

**Motif detection logic (rule-based + engine confirmation):**

```
Examine features.hanging_pieces  → "hanging" motif
Examine features.forks            → "fork" motif
Examine features.pins             → "pin" motif
Examine features.cannon_screens   → "cannon" motif
Engine check detection            → "check" / "checkmate" motif
Engine shallow search confirms forced sequence
```

**Difficulty rating formula:**

```
base_rating  = 800
depth_bonus  = solution_depth × 200
piece_bonus  = piece_count × 5
final_rating = base_rating + depth_bonus + piece_bonus
```

**Theme tagging logic:**

```
solution_depth == 1   → "one_move"
solution_depth >= 3   → "combination"
solution_depth == 2   → "two_move"
phase == endgame      → "endgame"
is_capture in moves   → "tactical"
else                  → "middlegame"
```

**State written:**

| Key | Description |
|---|---|
| `tactical_patterns` | Raw pattern features from engine |
| `tactical_motifs` | Classified motif types |
| `puzzle` | Puzzle object: FEN, solution moves, hints |
| `puzzle_difficulty` | Estimated Elo rating |
| `puzzle_themes` | Theme tags array |

---

### 3.7 Coach Agent (Explainer)

**Role:** Synthesize all analysis results into a natural-language coaching response.

**Execution order:** Slow path only — runs after Position Analyst and Puzzle Curator complete, and only when a coach trigger condition is satisfied. If no trigger is met, this agent is skipped and Visualization + Feedback run directly with the Position Analyst output.

**Trigger conditions (ANY one is sufficient):**

| Trigger | Condition | State key |
|---|---|---|
| **Move count** | Player has made 3 or more moves since Coach last ran | `moves_since_last_coach >= 3` |
| **Material shift** | Evaluation swing ≥ 200 centipawns from previous turn | `coach_trigger == "material_shift"` |
| **Tactical pattern** | Position Analyst detected a fork, pin, hanging piece, or cannon threat | `coach_trigger == "tactical_pattern"` |

```
if coach_trigger == "none":
    SKIP Coach Agent and Guard Agent
    → fast path directly to Visualization → Feedback

if coach_trigger in ["move_count", "material_shift", "tactical_pattern"]:
    RUN Coach Agent → Guard Agent → Visualization → Feedback
```

**What it does:**
- Receives all prior state (engine metrics, puzzle, game phase, material, PV).
- Applies the `beginner_coaching` skill to frame the LLM system prompt.
- Makes a single LLM call with a structured prompt containing all context.
- Output is the human-readable coaching advice — sent to Guard for approval before it reaches the user.

**LLM prompt structure:**

```
System (from beginner_coaching skill):
  "You are a xiangqi coach for beginners. Keep answers concise.
   Explain key turns. Always use full piece names (e.g. 'the Red Chariot on f3')."

User context assembled from state:
  - FEN and student question
  - Engine score, best move, principal variation
  - Puzzle solution and themes (if generated)
  - Game phase: {opening|middlegame|endgame}
  - Material balance: {piece counts}
  - coach_trigger: why this advice was triggered
```

**Skills applied:**

| Skill | When | Effect |
|---|---|---|
| `beginner_coaching` | Always | Appends beginner-friendly system prompt |
| `explain_tactic` | If move provided | RAG-retrieves tactic explanation, validates move, explains pattern |
| `general_advice` | If question_only | RAG-retrieves general principles |

**State written:**

| Key | Description |
|---|---|
| `coaching_advice` | LLM-generated coaching text (pending Guard approval) |
| `strategy_advice` | Alias (backward compatibility) |

---

### 3.8 Guard Agent (Scoring)

**Role:** Quality gate — scores the Coach Agent's advice and decides whether to approve it before it reaches the user.

**Execution order:** Runs immediately after Coach Agent, on the slow path only. Never runs if `coach_trigger == "none"` or `blunder_abort == true`.

**What it does:**
1. **Candidate move check** — verifies the advice references a move that exists in the engine's legal moves list (the coach isn't suggesting an illegal move).
2. **Move legality sweep** — checks every move string mentioned in the coaching text against `POST /engine/is-move-legal`.
3. **Approval decision** — if all moves are legal and at least one candidate move is present, the advice is approved. Otherwise it is rejected and `coaching_advice` is cleared.

**Bridge calls:**

```
1. POST /engine/legal-moves
   Body: { "fen": "<current_fen>" }
   Response: { "moves": ["e3e5", "h9g7", ...] }
   → verify that the Coach's recommended move ∈ legal_moves

2. POST /engine/is-move-legal  (for each move mentioned in advice text)
   Body: { "fen": "<fen>", "move": "<move_str>" }
   Response: { "legal": bool }
```

**Approval logic:**

```
candidate_move_valid  = coach's primary recommendation ∈ engine legal_moves
all_mentioned_legal   = all move strings in advice text pass is-move-legal
advice_approved       = candidate_move_valid AND all_mentioned_legal

if advice_approved:
    state["coach_advice_approved"] = true
    coaching_advice is kept → forwarded to Feedback

if NOT advice_approved:
    state["coach_advice_approved"]  = false
    state["coach_abort_reason"]     = "<which check failed>"
    state["coaching_advice"]        = ""   ← cleared, not shown to user
    → Feedback uses fast-path output only (no coaching text)
```

**State written:**

| Key | Description |
|---|---|
| `coach_advice_approved` | Whether Guard approved the advice |
| `coach_abort_reason` | Reason if advice was rejected (for logging) |
| `move_legal` | Legality result for the primary submitted move |

---

### 3.9 Visualization Agent  *(unchanged)*

**Role:** Render the board position as ASCII art.

**What it does:**
- Runs only if `route_visualization = true`.
- Converts the FEN to a 9×10 ASCII grid.
- No engine call — pure computation.
- Non-fatal: if it fails, the pipeline continues.

**Tool call:** Local ASCII renderer (no bridge/engine call).

**Output format:**

```
  a b c d e f g h i
0 r n b a k a b n r
1 . . . . . . . . .
2 . c . . . . . c .
3 p . p . p . p . p
4 . . . . . . . . .
5 . . . . . . . . .
6 P . P . P . P . P
7 . C . . . . . C .
8 . . . . . . . . .
9 R N B A K A B N R
```

**State written:**

| Key | Description |
|---|---|
| `board_visualization` | ASCII board string |

---

### 3.10 Feedback Agent

**Role:** Assemble the final response from all pipeline outputs. Handles three distinct output shapes depending on which path was taken.

**What it does:**
- Reads state to determine which path completed.
- Assembles the response in the appropriate format.
- Returns the final `feedback` string to the HTTP handler, which sends it to the frontend.

**Blunder-abort path (highest priority):**

```
if blunder_abort == true:
  → Output ONLY blunder information
  → All other sections suppressed (Position Analyst, Coach, Puzzle not populated)

  "⚠ BLUNDER DETECTED"
  "Move: e3d4 | Centipawn loss: 180 | Category: Blunder"
  "Better move: e3e5 (score: +120)"
  "A puzzle has been queued for your next turn."
```

**Fast path (no Coach):**

```
if blunder_abort == false AND coach_trigger == "none":

  1. Board visualization (ASCII grid)
  2. Engine evaluation
     "Evaluation: +120 | Best move: e3e5 | Depth: 20"
  3. Principal variation
     "Best line: e3e5 → h9g7 → e5e7"
  4. Puzzle (if generated from prior blunder)
     "Puzzle: find the winning move. Theme: fork. Difficulty: 1200"
  [No coaching advice section]
```

**Slow path (Coach ran and Guard approved):**

```
if blunder_abort == false AND coach_advice_approved == true:

  1. Board visualization (ASCII grid)
  2. Engine evaluation
  3. Principal variation
  4. Puzzle (if generated)
  5. Coaching advice (LLM output, approved by Guard)
     "[Triggered by: move_count | material_shift | tactical_pattern]"
```

**Slow path (Guard rejected advice):**

```
if blunder_abort == false AND coach_advice_approved == false:
  → Same as fast path (coaching advice section suppressed)
  → coach_abort_reason logged server-side, not shown to user
```

**State written:**

| Key | Description |
|---|---|
| `feedback` | Final response string returned to frontend |

---

## 4. Tool Registry — Full Reference

### Engine Tools (call State Bridge REST → Rust Engine)

| Tool Name | Bridge Endpoint | Payload | Returns |
|---|---|---|---|
| `validate_fen` | `POST /engine/validate-fen` | `{fen}` | `{valid: bool}` |
| `analyze_position` | `POST /engine/analyze` | `{fen, depth}` | Full `AnalysisResponse` |
| `get_principal_variation` | `POST /engine/analyze` | `{fen, depth}` | `{pv: [], score, depth}` |
| `get_move_rankings` | `POST /engine/batch-analyze` | `{moves: [{fen, move_str}]}` | `[]MoveFeatureVector` |
| `detect_blunders` | `POST /engine/batch-analyze` | `{moves: [...], threshold: 150}` | `{blunders: [...]}` |
| `is_move_legal` | `POST /engine/is-move-legal` | `{fen, move}` | `{legal: bool}` |
| `validate_move_legality` | `POST /engine/is-move-legal` | `{fen, move}` | `{legal: bool}` |
| `get_game_state` | `GET /state` | — | Current game state snapshot |
| `make_move` | `POST /engine/make-move` | `{fen, move}` | `{fen, valid}` |
| `suggest_best_move` | `POST /engine/suggest` | `{fen, depth}` | `{move, score}` |
| `classify_move` | `POST /engine/batch-analyze` | single-move batch | `MoveFeatureVector` |

### Feature Tools

| Tool Name | Bridge Endpoint | Extracts |
|---|---|---|
| `get_position_features` | `POST /engine/analyze` | Subset: `material`, `mobility`, `king_safety`, `hanging_pieces`, `forks`, `pins`, `cannon_screens` |
| `get_tactical_patterns` | `POST /engine/analyze` | Forks, pins, hanging pieces, cannon screens |

### Puzzle Tools

| Tool Name | Calls | Purpose |
|---|---|---|
| `find_tactical_motif` | `suggest` (depth 15) | Identify fork/pin/skewer/check/mate/hanging |
| `generate_puzzle` | `suggest` + `make-move` (loop) | Build forced solution sequence |
| `validate_puzzle_solution` | `batch-analyze` | Verify user's solution moves |
| `rate_difficulty` | Local heuristic | Estimate Elo: 800 + depth×200 + pieces×5 |
| `tag_puzzle_themes` | Local heuristic | one_move / combination / tactical / endgame |
| `generate_hint` | `suggest` (depth 5/10/20) | Vague/moderate/specific hint |

### RAG Tools (ChromaDB)

| Tool Name | Collection | Query Source |
|---|---|---|
| `get_opening_plan` | `openings` | Position description |
| `get_middlegame_theme` | `tactics` | Position features |
| `get_endgame_principle` | `endgames` | Position features |
| `get_general_advice` | `beginner_principles` | User question |
| `explain_tactic` | `beginner_principles` | User question + move |
| `explain_puzzle_objective` | `beginner_principles` | Puzzle context |

### Visualization & PGN Tools

| Tool Name | Purpose |
|---|---|
| `visualize_board` | FEN → ASCII grid (local, no bridge call) |
| `load_pgn` | Parse PGN text to move list |
| `save_pgn` | Serialize move history to PGN |

---

## 5. Skills Reference

### `beginner_coaching`

Modifies CoachAgent's LLM system prompt for beginner-friendly output.

```json
{
  "name": "beginner_coaching",
  "steps": [{
    "kind": "llm",
    "system_prompt": "You are a xiangqi coach for beginners.
      1) Keep answers concise.
      2) Explain key turns.
      3) Always use full piece names (e.g. 'the Red Chariot on f3')."
  }]
}
```

### `evaluate_position`

Multi-step skill: runs engine analysis → extracts features → LLM interprets.

```
Step 1: tool "analyze_position"   {fen, depth: 20}
Step 2: tool "get_position_features"  depends_on step 1
Step 3: llm  "Expert xiangqi coach. Assess: material, king safety, threats, mobility, overall plan."
```

### `explain_tactic`

RAG-augmented explanation skill.

```
Step 1: rag  collection: "beginner_principles"  query_from: question
Step 2: tool "validate_move_legality"  {fen, move}
Step 3: llm  depends_on steps 1+2  "Explain why this tactic works and how to recognize it again."
```

---

## 6. Specialized HTTP Endpoints & Their Routing Presets

The coaching service exposes focused endpoints that bypass the Ingest/Orchestrator routing logic and directly preset the route flags:

| Endpoint | route_position | route_blunder | route_puzzle | Use case |
|---|---|---|---|---|
| `POST /coach` | (orchestrator decides) | (orchestrator decides) | (orchestrator decides) | General chat from `ChatPanel` |
| `POST /coach/analyze` | ✓ | ✗ | ✗ | Frontend requests position analysis |
| `POST /coach/blunder` | ✓ | ✓ | ✗ | Frontend sends move list for review |
| `POST /coach/puzzle` | ✓ | ✗ | ✓ | Frontend requests puzzle generation |
| `POST /coach/features` | — | — | — | Direct tool call, bypasses graph |
| `POST /coach/classify-move` | — | — | — | Direct tool call, bypasses graph |
| `POST /dashboard/chat` | (orchestrator decides) | (orchestrator decides) | (orchestrator decides) | Same as `/coach` — used by ChatPanel |

---

## 7. Engine Client Fallback Chain

```
BRIDGE_URL env set?
  YES → BridgeClient
        Base URL: http://state-bridge:5003
        All calls go through bridge REST endpoints
        (bridge relays to Rust engine over persistent WebSocket)
  NO  → ENGINE_WS_URL env set?
           YES → WSClient (direct WebSocket to Rust engine :8080)
           NO  → MockEngine (canned responses — for offline testing)
```

When `BridgeClient` is active, every tool call in the agent graph hits the **state bridge**, which relays the request to the Rust engine. This means:
- The bridge logs all coaching-triggered engine calls.
- The bridge can track which engine calls happen per turn.
- No agent calls the Rust engine directly.

---

## 8. State Shared Between Agents (Full Schema)

```
GraphState {
  // ── Input (written by Ingest) ────────────────────────────────────────
  fen:              string
  move:             string
  question:         string
  is_question:      bool
  has_move:         bool
  question_only:    bool
  moves:            string   // space-separated move list (for blunder check)

  // ── Routing (written by Orchestrator) ────────────────────────────────
  route_blunder_detection:  bool
  route_position_analysis:  bool
  route_puzzle:             bool
  route_visualization:      bool
  classified_intent:        string

  // ── Coach trigger (written by Orchestrator) ──────────────────────────
  coach_trigger:           "move_count"|"material_shift"|"tactical_pattern"|"none"
  moves_since_last_coach:  int
  prev_score:              int    // score from previous turn (for shift detection)

  // ── Blunder Detection (written by BlunderDetection — runs first) ─────
  blunder_abort:      bool              // true = skip all other agents
  blunder_analysis:   []MoveClassification
  blunder_positions:  []string (FENs)

  // ── FEN Validation (written by Inspection) ───────────────────────────
  fen_valid:    bool

  // ── Position Analysis (written by PositionAnalyst) ───────────────────
  engine_metrics:          {score, best_move, nodes}
  game_phase:              "opening"|"middlegame"|"endgame"
  material_info:           {per-piece counts, balance}
  hanging_pieces:          []
  forks:                   []
  pins:                    []
  principal_variation:     []string
  tactical_pattern_detected: bool      // triggers slow path if true

  // ── Puzzle Curator (written by PuzzleCurator — parallel with Analyst) ─
  tactical_patterns:  {}
  tactical_motifs:    []string
  puzzle:             {fen, solution_moves, hints}
  puzzle_difficulty:  int
  puzzle_themes:      []string

  // ── Coaching (written by Coach — slow path only) ─────────────────────
  coaching_advice:   string

  // ── Guard scoring (written by Guard — after Coach) ───────────────────
  move_legal:            bool    // primary submitted move is legal
  coach_advice_approved: bool    // Guard approved the coaching text
  coach_abort_reason:    string  // reason if Guard rejected (logged only)

  // ── Visualization (written by Visualization) ─────────────────────────
  board_visualization: string  // ASCII art

  // ── Final output (written by Feedback) ───────────────────────────────
  feedback: string
}
```

---

## 9. Bridge Server Endpoints Used by Agents (Summary)

| Bridge Endpoint | Called By | When | Purpose |
|---|---|---|---|
| `POST /engine/validate-fen` | Inspection | Always (if FEN present) | Structural FEN validation |
| `POST /engine/batch-analyze` | Blunder Detection | Always (if move present) | **First call — blunder check** |
| `POST /engine/analyze` | Position Analyst, Puzzle Curator, Orchestrator | No-blunder path only | Full position evaluation with features |
| `POST /engine/legal-moves` | Guard | Slow path only | Verify Coach's recommended move is legal |
| `POST /engine/is-move-legal` | Guard | Slow path only (per move in advice) | Sweep all moves mentioned in coaching text |
| `POST /engine/suggest` | Orchestrator, Puzzle Curator | No-blunder path only | Get engine's best move |
| `POST /engine/make-move` | Puzzle Curator | No-blunder path only | Apply move for puzzle solution building |
| `GET  /state` | Any agent via `get_game_state` | Any time | Read current game state snapshot |

---

## 10. End-Turn Integration (Physical Board Use Case)

When a player presses **End Turn** on the physical board:

1. CV captures the board → state bridge validates the new FEN (see `bridge_server_flow.md` §9).
2. On success, `fen_update` SSE event fires — frontend board updates.
3. Simultaneously, state bridge publishes `best_move` SSE — LED board and frontend highlight the suggestion.
4. The frontend's ChatPanel sends a move event to `POST /dashboard/chat`:

   ```json
   {
     "message": "Red played e3e5. Check: false, score: +50. Comment.",
     "session_id": "chat-<timestamp>",
     "fen": "<new fen after move>",
     "move": "e3e5"
   }
   ```

5. The coaching graph runs:

   **Step A — Ingest + Inspection + Orchestrator**
   - Extract FEN, move.
   - Evaluate coach trigger: is `moves_since_last_coach >= 3`? Did eval shift ≥ 200cp?
   - Set `route_blunder_detection = true`, `route_position_analysis = true`.

   **Step B — Blunder Detection (first, always)**
   - Calls `POST /engine/batch-analyze` on the submitted move.
   - **If blunder detected:**
     - Set `blunder_abort = true`.
     - Skip Position Analyst, Puzzle Curator, Coach, Guard, Visualization.
     - **Go directly to Feedback** with blunder summary only.
     - ChatPanel displays: "⚠ BLUNDER DETECTED — e3d4 lost 180cp. Better: e3e5."
     - `route_puzzle = true` is saved for the **next** turn's graph invocation.
     - **Flow ends here for this turn.**

   **Step C — Parallel: Position Analyst ‖ Puzzle Curator** (no-blunder path)
   - Position Analyst evaluates the new position.
   - If `tactical_pattern_detected` → may upgrade `coach_trigger` to `"tactical_pattern"`.
   - Puzzle Curator runs in parallel if `route_puzzle = true` (from a prior blunder turn).

   **Step D — Coach Agent + Guard** (slow path only, if `coach_trigger != "none"`)
   - Coach generates LLM advice citing trigger reason.
   - Guard verifies all moves in advice are legal; approves or rejects.

   **Step E — Visualization → Feedback**
   - Feedback assembles output in the appropriate format for the active path.

6. ChatPanel displays the response and speaks it via TTS.

### Per-Turn Decision Tree

```
End Turn pressed
  → CV validates FEN  → bridge posts fen_update + best_move SSE
  → ChatPanel POST /dashboard/chat

  Blunder Detection:
    BLUNDER?  ──YES──►  Feedback (blunder summary only, all flows aborted)
        │
       NO
        │
        ▼
  Parallel: Position Analyst + Puzzle Curator
        │
        ▼
  Coach trigger?
    NONE  ──────────►  Visualization → Feedback (fast path, no LLM)
        │
    TRIGGERED
        │
        ▼
  Coach Agent (LLM)
        │
  Guard Agent (legal-move scoring)
    FAIL ────────────►  Visualization → Feedback (advice suppressed)
        │
       PASS
        │
        ▼
  Visualization → Feedback (full response with coaching advice)
```
