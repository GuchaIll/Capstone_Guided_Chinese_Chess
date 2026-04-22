# Bridge Server — Full Sequence Flow

> **Purpose of this document:** Describe the current state of the bridge server and its role in the overall system.  
> This is a working document — revise it to mark anything that differs from your intended design.

---

## 1. Service Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (React)  :3000                                             │
│  - WebSocket to engine (via proxy /ws)                              │
│  - SSE from state-bridge /state/events                              │
│  - REST POST to coaching services                                   │
└─────────────────────────────────────────────────────────────────────┘
         │ WS (direct)             │ SSE              │ REST
         ▼                         ▼                   ▼
┌────────────────┐       ┌──────────────────┐    ┌──────────────────┐
│  Rust Engine   │◄─WS──►│  State Bridge    │    │ Go Coach  :5002  │
│  :8080/ws      │       │  (FastAPI) :5003 │◄───│  (Agent Graph)   │
└────────────────┘       └──────────────────┘    └──────────────────┘
                                  │                        │
                                  │ REST                   │ REST (tools)
                                  ▼                        ▼
                         ┌──────────────────┐    ┌──────────────────┐
                         │ Python Coach     │    │  ChromaDB  :8000 │
                         │ :5001  (LLM Orch)│    │  (Vector DB)     │
                         └──────────────────┘    └──────────────────┘
                                  │                        │
                                  │                        │
                                  ▼                        ▼
                         ┌──────────────────┐    ┌──────────────────┐
                         │  LLM Provider    │    │ Embedding :8100  │
                         │  (Anthropic /    │    │ (Sentence Trans.)│
                         │   OpenRouter)    │    └──────────────────┘
                         └──────────────────┘
```

### Port Summary

| Service | Port | Protocol |
|---|---|---|
| Rust engine | 8080 | WebSocket `/ws` |
| State bridge | 5003 | REST + SSE |
| Go coaching | 5002 | HTTP REST |
| Python coaching | 5001 | REST + WebSocket |
| ChromaDB | 8000 | HTTP |
| Embedding service | 8100 | HTTP |
| React client | 3000 / 80 | HTTP / WebSocket (proxy) |

---

## 2. State Bridge — Role

The state bridge is the **central coordination hub**.  It holds the canonical in-memory game state and owns three responsibilities:

1. **Relay** — maintains the persistent WebSocket connection to the Rust engine and forwards both interactive commands and request/response calls (analysis, suggestions).
2. **State** — keeps a live snapshot of the game (FEN, side to move, last move, selected square, best-move hint, LED state).
3. **Events** — broadcasts state changes over SSE to all interested subscribers (primarily the React frontend but also any monitoring).

```
            ┌──────────────────────────────────────────┐
            │             State Bridge                  │
            │                                          │
            │  ┌──────────┐   ┌──────────┐            │
            │  │EngineRelay│   │GameState │            │
            │  │  (WS)    │──►│ (memory) │            │
            │  └──────────┘   └────┬─────┘            │
            │                      │                   │
            │                 ┌────▼─────┐             │
            │                 │ EventBus │             │
            │                 └────┬─────┘             │
            │                      │ SSE broadcast     │
            └──────────────────────┼───────────────────┘
                                   ▼
                           /state/events (SSE)
```

---

## 3. Startup Sequence

```
docker-compose up
    │
    ├─ Rust engine starts, WebSocket ready at ws://engine:8080/ws
    │
    ├─ State bridge starts (FastAPI lifespan)
    │       │
    │       └─ Creates EngineRelay task
    │               │
    │               └─ Connects WS to engine (exponential backoff: 2 s → 30 s)
    │                       └─ On connect: sets relay.connected = True
    │
    ├─ Go coaching starts, registers engine client
    │       │
    │       ├─ If BRIDGE_URL set → uses BridgeClient (REST to state bridge)
    │       ├─ Elif ENGINE_WS_URL set → direct WSClient
    │       └─ Else → MockEngine fallback
    │
    ├─ Python coaching starts
    │       └─ Connects to engine, RAG, LLM
    │
    └─ React client loads
            └─ Opens WS to engine (via nginx proxy /ws → engine:8080/ws)
            └─ Opens SSE to state bridge /state/events
```

---

## 4. Interactive Play — Full Sequence (Player Move + AI Response)

```
Player                  React Frontend           Rust Engine          State Bridge         Go Coach
  │                          │                       │                     │                   │
  │  Click piece "e3"        │                       │                     │                   │
  ├─────────────────────────►│                       │                     │                   │
  │                          │ WS → {type:"legal_moves", square:"e3"}      │                   │
  │                          ├──────────────────────►│                     │                   │
  │                          │ WS ← {type:"legal_moves",                   │                   │
  │                          │        square:"e3", targets:["e4","e5",...]}│                   │
  │                          │◄──────────────────────┤                     │                   │
  │  Board highlights        │                       │                     │                   │
  │◄─────────────────────────┤                       │                     │                   │
  │                          │                       │                     │                   │
  │  Drag piece to "e5"      │                       │                     │                   │
  ├─────────────────────────►│                       │                     │                   │
  │                          │ WS → {type:"move", move:"e3e5"}             │                   │
  │                          ├──────────────────────►│                     │                   │
  │                          │ WS ← {type:"move_result",                   │                   │
  │                          │        valid:true, move:"e3e5",             │                   │
  │                          │        fen:"...", result:"in_progress",     │                   │
  │                          │        is_check:false, score:50}            │                   │
  │                          │◄──────────────────────┤                     │                   │
  │  Board updates           │                       │                     │                   │
  │◄─────────────────────────┤                       │                     │                   │
  │                          │                       │                     │                   │
  │                          │ [500 ms delay] WS → {type:"ai_move",        │                   │
  │                          │                        difficulty:4}        │                   │
  │                          ├──────────────────────►│                     │                   │
  │  "AI thinking" spinner   │                       │                     │                   │
  │◄─────────────────────────┤                       │  Engine computes    │                   │
  │                          │                       │  best move ...      │                   │
  │                          │ WS ← {type:"ai_move",                       │                   │
  │                          │        move:"h9g7", fen:"...",              │                   │
  │                          │        result:"in_progress", score:-30}     │                   │
  │                          │◄──────────────────────┤                     │                   │
  │  Board updates           │                       │                     │                   │
  │◄─────────────────────────┤                       │                     │                   │
```

> **Note:** The React client connects **directly** to the engine WebSocket for interactive play. The state bridge is NOT in this hot path — it is notified via its own relay connection when engine state changes.

---

## 5. Suggestion (Best-Move Hint) Sequence

```
React Frontend                    Rust Engine
      │                                │
      │  (first piece selection)       │
      │  WS → {type:"suggest",         │
      │          difficulty:4}         │
      ├───────────────────────────────►│
      │  WS ← {type:"suggestion",      │
      │          move:"e3e5",          │
      │          score:120}            │
      │◄───────────────────────────────┤
      │                                │
      │  Highlights suggested          │
      │  from/to squares               │
```

> `suggestionRequestedRef` guards this — only one suggestion is requested per turn.

---

## 6. Coaching Chat — Frontend → Go Coach

```
React (ChatPanel)                  Go Coach :5002              State Bridge :5003          Rust Engine
       │                                 │                              │                       │
       │  POST /dashboard/chat           │                              │                       │
       │  {message, session_id, fen,     │                              │                       │
       │   move}                         │                              │                       │
       ├────────────────────────────────►│                              │                       │
       │                                 │                              │                       │
       │                         ┌───────┴─────────────────────────────────────────────┐        │
       │                         │               Agent Graph Pipeline                   │        │
       │                         │                                                     │        │
       │                         │  IngestAgent → InspectionAgent → OrchestratorAgent  │        │
       │                         │       ↓                                             │        │
       │                         │  [parallel]                                         │        │
       │                         │  PositionAnalystAgent  BlunderDetectionAgent         │        │
       │                         │       ↓                      ↓                      │        │
       │                         │  PuzzleCuratorAgent (optional)                      │        │
       │                         │       ↓                                             │        │
       │                         │  CoachAgent (LLM call)                              │        │
       │                         │       ↓                                             │        │
       │                         │  VisualizationAgent → FeedbackAgent                │        │
       │                         └───────┬─────────────────────────────────────────────┘        │
       │                                 │  (tools call REST on state bridge)                    │
       │                                 │  POST /engine/analyze  {fen, depth}                   │
       │                                 ├─────────────────────────────────────────────────────►│
       │                                 │  (bridge relays over WS, waits for engine response)   │
       │                                 │◄─────────────────────────────────────────────────────┤
       │                                 │                                                       │
       │  Response {text, fen?, ...}     │                                                       │
       │◄────────────────────────────────┤                                                       │
       │                                 │                                                       │
       │  Display + TTS                  │                                                       │
```

---

## 7. State Bridge — Engine Relay (Request/Response Pattern)

When the Go coach calls `/engine/analyze` on the state bridge, the relay wraps the call in a request/response over the persistent WebSocket:

```
Go Coach                State Bridge / EngineRelay              Rust Engine
    │                              │                                  │
    │  POST /engine/analyze        │                                  │
    │  {fen, depth}                │                                  │
    ├─────────────────────────────►│                                  │
    │                              │  WS → {type:"analyze_position",  │
    │                              │          fen, difficulty:depth}  │
    │                              ├─────────────────────────────────►│
    │                              │  (relay stores future in         │
    │                              │   _pending["analysis"])          │
    │                              │  WS ← {type:"analysis",          │
    │                              │          features:{...},         │
    │                              │          score, depth, pv}       │
    │                              │◄─────────────────────────────────┤
    │                              │  (future resolved)               │
    │  JSON response               │                                  │
    │◄─────────────────────────────┤                                  │
```

**Timeouts:**
- `/engine/analyze` — 60 s
- `/engine/suggest` — 30 s
- `/engine/validate-fen`, `/engine/legal-moves`, `/engine/make-move` — 15 s

---

## 8. SSE Event Bus (State Bridge → Frontend)

The state bridge maintains an SSE endpoint (`GET /state/events`) that broadcasts events whenever game state changes. The frontend subscribes on load and reacts to events to keep the board and UI in sync.

### Events emitted and their triggers

| Event | Trigger | Board state updated? |
|---|---|---|
| `fen_update` | Validated CV FEN accepted by engine | **Yes** |
| `move_made` | Engine reports `move_result` or `ai_move` | **Yes** |
| `piece_selected` | `POST /state/select` called | No |
| `best_move` | Engine suggestion computed post-turn | No (UI highlight only) |
| `led_command` | LED on/off/clear called | No |
| `game_reset` | Engine relay receives reset ack | **Yes** |
| `state_sync` | Client connects — full snapshot | **Yes** |
| `cv_validation_error` | CV FEN rejected by engine (illegal move) | **No — state frozen** |

### Event payload shapes

```json
// fen_update  (board state accepted — update board)
{ "fen": "rnba...", "source": "cv", "side_to_move": "red|black",
  "result": "in_progress|red_win|black_win", "is_check": false }

// move_made  (authoritative move recorded)
{ "from": "e3", "to": "e5", "piece": "P", "source": "player|ai",
  "fen": "...", "result": "in_progress", "is_check": false, "score": 50 }

// piece_selected
{ "square": "e3", "targets": ["e4", "e5"] }

// best_move  (highlight suggestion on board AND LED simultaneously)
{ "from": "e3", "to": "e5" }

// led_command
{ "command": "on|off|clear" }

// cv_validation_error  (NEW — illegal board detected, block play)
{ "source": "cv", "cv_fen": "...", "current_fen": "...",
  "reason": "no legal move matches detected board change" }
```

---

## 9. End-Turn + CV Capture + Validation Flow (Physical Board)

This is the **primary flow for physical board play**. The player moves a piece on the physical board and presses "End Turn" to submit their move. CV validates it before anything updates.

```
Player            Frontend (React)       State Bridge          Rust Engine        LED Board
  │                     │                     │                     │                  │
  │ Move piece           │                     │                     │                  │
  │ physically           │                     │                     │                  │
  │                      │                     │                     │                  │
  │ Press "End Turn"     │                     │                     │                  │
  ├────────────────────► │                     │                     │                  │
  │                      │ POST /state/led-command {"command":"off"} │                  │
  │                      ├────────────────────►│                     │                  │
  │                      │                     │ SSE → led_command   │                  │
  │                      │                     │ {"command":"off"}   │                  │
  │                      │                     ├──────────────────────────────────────► │
  │                      │                     │                     │  LEDs OFF (100ms)│
  │                      │                     │                     │                  │
  │                  [CV activates, captures board image]            │                  │
  │                  [YOLO detects pieces, generates FEN]            │                  │
  │                      │                     │                     │                  │
  │                      │ POST /state/fen      │                     │                  │
  │                      │ {"fen":"...","source":"cv"}               │                  │
  │                      ├────────────────────►│                     │                  │
  │                      │                     │                     │                  │
  │                      │              ┌──────┴──────────────────────────┐             │
  │                      │              │  Bridge validates CV FEN        │             │
  │                      │              │                                 │             │
  │                      │              │  1. Structural check (10×9,     │             │
  │                      │              │     valid pieces, valid side)   │             │
  │                      │              │                                 │             │
  │                      │              │  2. Engine legal-move check:    │             │
  │                      │              │     GET /engine/legal-moves     │             │
  │                      │              │     for current position        │             │
  │                      │              │                                 │             │
  │                      │              │  3. Diff current_fen vs cv_fen  │             │
  │                      │              │     → derive move (from/to)     │             │
  │                      │              │                                 │             │
  │                      │              │  4. Check move ∈ legal_moves    │             │
  │                      │              └──────┬──────────────────────────┘             │
  │                      │                     │                     │                  │
  │          ┌───────────┤◄────────────────────┤  FAIL PATH          │                  │
  │          │           │  SSE cv_validation_error                  │                  │
  │          │           │  {cv_fen, current_fen, reason}            │                  │
  │          │           │                     │  (state NOT updated)│                  │
  │          │           │                     │                     │  LEDs back ON    │
  │          │           │                     ├──────────────────────────────────────► │
  │          │           │                     │   (restore previous │  (restore prev.  │
  │          │           │                     │    board position)  │   board display) │
  │ Warning modal shown  │                     │                     │                  │
  │ "Piece out of place, │                     │                     │                  │
  │  please correct and  │                     │                     │                  │
  │  press End Turn"     │                     │                     │                  │
  │◄─────────────────────┤                     │                     │                  │
  │                      │    [Flow BLOCKED until player corrects]   │                  │
  │                      │                     │                     │                  │
  │ Correct piece,       │                     │                     │                  │
  │ press End Turn again │                     │                     │                  │
  ├────────────────────► │ (repeat from top)   │                     │                  │
  │                      │                     │                     │                  │
  │          ┌───────────┴─────────────────────┤  PASS PATH          │                  │
  │          │           │  SSE fen_update      │                     │                  │
  │          │           │  {fen, source:"cv",  │                     │                  │
  │          │           │   side_to_move,      │                     │                  │
  │          │           │   result, is_check}  │                     │                  │
  │          │           │                     │                     │                  │
  │  Board updates       │                     │                     │  LED → show move │
  │  to new position     │                     │  SSE led_command     │  (blue=from,     │
  │◄─────────────────────┤                     ├──────────────────────────────────────► │
  │                      │                     │  {"command":"on"}   │  purple=to)      │
  │                      │                     │                     │                  │
  │                      │                     │  Engine: get best   │                  │
  │                      │                     │  move + AI move     │                  │
  │                      │                     │─────────────────────►                  │
  │                      │                     │◄─────────────────────                  │
  │                      │                     │                     │                  │
  │                      │  SSE best_move       │                     │                  │
  │                      │  {from:"e3",to:"e5"} │                     │                  │
  │◄─────────────────────┤◄────────────────────┤                     │                  │
  │  Suggestion          │                     │                     │  LED → show      │
  │  highlighted         │                     │  SSE led highlight  │  best move       │
  │  on board            │                     ├──────────────────────────────────────► │
  │                      │                     │                     │  (green=dest)    │
  │                      │                     │                     │                  │
  │                      │  SSE move_made       │                     │                  │
  │                      │  {source:"ai",...}   │                     │                  │
  │◄─────────────────────┤◄────────────────────┤                     │                  │
  │  AI move shown       │                     │                     │  LED → show      │
  │  on board            │                     │                     │  AI move         │
  │                      │                     │                     │  (blue/purple)   │
```

### Validation Logic (State Bridge)

```
POST /state/fen {fen: cv_fen, source: "cv"}

Step 1 — Structural validation
  _looks_like_xiangqi_fen(cv_fen) ?
    No  → publish cv_validation_error {reason: "malformed FEN"}
          return 400, do NOT update state

Step 2 — Derive move from diff
  diff(current_fen, cv_fen)
    → identify which piece moved: from_sq, to_sq
    No single-piece change detected
      → publish cv_validation_error {reason: "ambiguous board change"}
          return 422, do NOT update state

Step 3 — Engine legal-move check
  POST /engine/is-move-legal {fen: current_fen, move: "e3e5"}
    {legal: false}
      → publish cv_validation_error {reason: "move not in legal moves"}
          return 422, do NOT update state

Step 4 — Accept
  state.apply_fen(cv_fen)
  publish fen_update
  request engine best-move + schedule AI turn
  return 200 {accepted: true}
```

> **Rule:** `cv_fen` is promoted to the authoritative `fen` ONLY after Step 4. Until then, `state.fen` is never touched.

---

## 10. Post-Validation: Best Move + AI Turn + LED Sync

Once the CV FEN is accepted, the bridge triggers two simultaneous actions and the LED board mirrors the client highlights at each step.

```
State Bridge                   Rust Engine          Frontend (SSE)        LED Board (SSE)
     │                              │                     │                    │
     │  Step A — Request suggestion │                     │                    │
     │  POST /engine/suggest        │                     │                    │
     │  {fen: new_fen, depth:5}     │                     │                    │
     ├─────────────────────────────►│                     │                    │
     │  ← {type:"suggestion",       │                     │                    │
     │      move:"e3e5", score:120} │                     │                    │
     │◄─────────────────────────────┤                     │                    │
     │  publish best_move           │                     │                    │
     │  {from:"e3", to:"e5"}        │                     │                    │
     ├──────────────────────────────────────────────────► │  Green highlight   │
     │                              │                     │  on board          │
     ├──────────────────────────────────────────────────────────────────────── │
     │  bridge_subscriber receives best_move → POST /move (row/col)            │
     │  LED server lights destination GREEN                                    │
     │                              │                     │                    │
     │  Step B — AI move (500ms)    │                     │                    │
     │  WS → {type:"ai_move",       │                     │                    │
     │         difficulty:4}        │                     │                    │
     ├─────────────────────────────►│                     │                    │
     │  ← {type:"ai_move",          │                     │                    │
     │      move:"h9g7", fen:"...", │                     │                    │
     │      score:-30}              │                     │                    │
     │◄─────────────────────────────┤                     │                    │
     │  publish move_made           │                     │                    │
     │  {source:"ai", from,to,fen}  │                     │                    │
     ├──────────────────────────────────────────────────► │  AI move shown     │
     │                              │                     │  on board          │
     ├──────────────────────────────────────────────────────────────────────── │
     │  bridge_subscriber receives move_made (source=ai)                       │
     │  → POST /opponent {from_r, from_c, to_r, to_c}                         │
     │  LED server lights from=BLUE, to=PURPLE                                 │
```

### LED Color Meanings (Physical Board)

| Color | Meaning | Trigger |
|---|---|---|
| **Red** | Selected piece | Player picks up a piece |
| **White** | Empty legal destination | Piece selected, valid empty target |
| **Orange** | Capture legal destination | Piece selected, valid capture target |
| **Blue** | Move origin | Opponent / AI piece that moved |
| **Purple** | Move destination | Where opponent / AI piece landed |
| **Green** | Best move destination | Coaching suggestion |
| **Cyan** | Starting zones | `POST /zones` |
| **Yellow / Pink** | Win celebration | Game over |
| **Off** | LEDs cleared | Before CV capture (100 ms blackout) |

---

## 11. In-Memory Game State Schema

```
GameStateBridge {
  fen:              str   // Current authoritative FEN
  side_to_move:     "red" | "black"
  game_result:      "in_progress" | "red_win" | "black_win"
  is_check:         bool
  last_move: {
    from_sq:        str   // e.g. "e3"
    to_sq:          str
    piece:          str   // e.g. "P"
    fen_after:      str
  } | null
  move_history:     [MoveRecord]
  selected_square:  str | null
  legal_moves:      [str]   // target squares for selected piece
  best_move_from:   str | null
  best_move_to:     str | null
  cv_fen:           str | null   // advisory camera reading
  leds_off:         bool
}
```

---

## 12. Engine Message Format Reference

### Frontend → Engine (over WebSocket)

```json
{type: "legal_moves",    square: "e3"}
{type: "move",           move: "e3e5"}
{type: "ai_move",        difficulty: 4}
{type: "suggest",        difficulty: 4}
{type: "reset"}
{type: "get_state"}
{type: "set_position",   fen: "..."}
```

### Bridge Relay → Engine (over WebSocket)

```json
{type: "analyze_position",  fen: "...", difficulty: 5}
{type: "batch_analyze",     moves: [{fen, move_str}]}
{type: "validate_fen",      fen: "..."}
{type: "legal_moves",       square: ""}   // all legal moves
{type: "make_move",         fen: "...", move: "e3e5"}
{type: "suggest",           difficulty: 5}
```

### Engine → Anyone (over WebSocket)

```json
{type: "move_result",    valid, move, fen, result, is_check, score}
{type: "ai_move",        move, fen, result, is_check, score}
{type: "legal_moves",    square, targets: []}
{type: "suggestion",     move, score}
{type: "analysis",       score, depth, pv, features: {...}}
{type: "batch_analysis", results: [{features}], total_moves}
{type: "state",          fen, side_to_move, result, is_check}
{type: "error",          message}
```

---

## 13. Move & Square Notation

| Concept | Format | Example |
|---|---|---|
| Square | `{file}{rank}` | `e3` (file e, rank 3) |
| Move | `{from_file}{from_rank}{to_file}{to_rank}` | `e3e5` |
| Files | `a`–`i` (left → right) | |
| Ranks | `0`–`9` (top → bottom) | |
| FEN pieces (red) | uppercase `P A E H C R K` | |
| FEN pieces (black) | lowercase `p a e h c r k` | |
| Starting FEN | `rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1` | |

---

## 14. Engine Client Fallback Chain (Go Coach)

```
BRIDGE_URL env set?
  Yes → BridgeClient (REST calls to state-bridge :5003)
  No  → ENGINE_WS_URL env set?
           Yes → WSClient (direct WebSocket to engine :8080/ws)
           No  → MockEngine (canned responses, for testing)
```

---

## 15. Design Decisions & Items to Verify

### Resolved by the End-Turn + CV design

- **Who triggers CV?** The frontend "End Turn" button — not the autonomous CV 'c' key press.
- **Who posts `/state/fen`?** The frontend (triggered by End Turn) posts to state bridge with `source:"cv"`.
- **Is the CV FEN advisory or authoritative?** It becomes authoritative only after engine validation passes.
- **LED sync:** bridge_subscriber mirrors every SSE event to the LED board simultaneously with the frontend.
- **`/state/best-move`** is called by the bridge itself after validation passes, once the engine returns a suggestion.

### Still to verify / implement

- [ ] **End Turn button:** Needs to be added to the React frontend (not currently present).
- [ ] **`cv_validation_error` SSE event:** Needs to be added to the state bridge events module and published on validation failure.
- [ ] **Warning modal:** Needs to be added to the React frontend — listens for `cv_validation_error` SSE, shows message, blocks UI until dismissed (player corrects piece and presses End Turn again).
- [ ] **Validation diff logic (Step 2):** The bridge needs a `diff_fen()` utility to detect which piece moved from current→cv FEN and extract `from_sq, to_sq`.
- [ ] **Simultaneous LED + frontend update:** The bridge_subscriber currently handles SSE events independently. Verify there is no ordering issue between the frontend receiving `fen_update` and the LED updating — both subscribe to the same SSE stream, so they should fire concurrently.
- [ ] **Python coaching server (:5001):** Confirm whether it is still active or fully replaced by the Go coaching service (:5002).
- [ ] **LED blackout during CV:** The 100 ms LED-off window before capture is currently implemented in the CV pipeline. With the new design (End Turn button), this needs to be coordinated: frontend posts `led-command off` → waits → triggers CV capture → posts FEN.
