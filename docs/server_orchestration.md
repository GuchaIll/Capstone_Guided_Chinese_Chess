# Server Orchestration: Pub/Sub & Command Flow

This document describes how events and commands flow through the server stack —
from the Rust Xiangqi engine, through the Python state bridge, into the Go and
Python coaching layers, and out to frontend clients. It is sourced from a
direct read of the code; file:line citations are inline so the doc can be
re-verified as the code evolves.

## High-level architecture

```
┌──────────────────────┐    WebSocket (dual)    ┌────────────────────────┐
│  Rust Xiangqi engine │ ◄────────────────────► │  Python state_bridge   │
│  (authoritative      │     observer + cmd      │  (FastAPI + asyncio    │
│   board / legality)  │                         │   in-process EventBus) │
└──────────────────────┘                         └────────────────────────┘
                                                    ▲          │   ▲
                                                HTTP│          │SSE│WS
                                                    │          ▼   ▼
                                          ┌──────────────┐  ┌──────────────────┐
                                          │ Go chess_coach│  │ React frontend   │
                                          │ (LLM graph,   │  │ (board, kibo,    │
                                          │  POST /coach) │  │  coaching chat)  │
                                          └──────────────┘  └──────────────────┘
                                                  ▲
                                            HTTP  │
                                                  ▼
                                          ┌────────────────────────┐
                                          │ Python agent_orchestr. │
                                          │ (FastAPI /ws/chat,     │
                                          │  fallback agent graph) │
                                          └────────────────────────┘
```

Three transport mechanisms in play:
- **WebSocket** for engine ↔ bridge and bridge ↔ frontend (low-latency, bidi).
- **HTTP/REST** for Go coach ↔ bridge and orchestrator ↔ Go coach (request/reply).
- **SSE + in-process asyncio queues** for the bridge's broadcast event bus.

For LED capture blackout there is now a fourth pattern layered on top of the
existing event bus: the bridge may issue **direct HTTP control** to the LED
server (`LED_SERVER_URL`, or derived from `RASPBERRY_PI_IP`, typically
`http://<raspberry-pi-ip>:5000`) for timing-critical `cv_pause` / `cv_resume`,
while still emitting SSE events for observability and fallback.

There is **no external message broker** (no Redis, NATS, Kafka). All pub/sub is
in-process within the bridge; cross-process delivery rides on WebSocket/SSE
fan-out from the bridge.

---

## 1. State Bridge: the in-process event bus

The state bridge ([server/state_bridge/](../server/state_bridge/)) is the
canonical source of derived state for everything except the Rust engine itself,
which is the source of truth for board legality.

### Transport

In-process pub/sub, implemented in
[server/state_bridge/events.py:69-118](../server/state_bridge/events.py). The
`EventBus` keeps a list of `asyncio.Queue` subscribers (default `maxsize=256`)
and broadcasts each published event to all of them. There is no persistence,
no replay, no cross-process delivery — when the FastAPI process restarts, the
bus restarts empty. Sequence numbers are attached on publish so clients can
detect drops.

### Event types

Defined as `EventType` in
[server/state_bridge/events.py:19-36](../server/state_bridge/events.py),
21 total, grouped:

| Group     | Types |
|-----------|-------|
| Movement  | `FEN_UPDATE`, `MOVE_MADE`, `CV_CAPTURE`, `PIECE_SELECTED`, `BEST_MOVE`, `GAME_RESET` |
| CV        | `CV_CAPTURE_REQUESTED`, `CV_CAPTURE_RESULT`, `CV_VALIDATION_ERROR`, `CV_AMBIGUOUS` |
| LED       | `LED_COMMAND`, `LED_PLAYER_TURN`, `LED_ENGINE_TURN`, `LED_GAME_RESULT`, `LED_RESET` |
| Coaching  | `KIBO_TRIGGER` |
| Sync      | `STATE_SYNC` |

Each event's payload is validated by a Pydantic model in
[server/state_bridge/event_models.py:19-180](../server/state_bridge/event_models.py)
— e.g. `FenUpdateData`, `MoveMadeData`, `CvCaptureResultData`,
`LedPlayerTurnData`, `KiboTriggerData`, `StateSyncData`. Wire serialization
goes through `model_to_event_data()` at
[event_models.py:172](../server/state_bridge/event_models.py#L172) using
`by_alias=True`, so field names on the wire come from the Pydantic aliases
rather than the Python attribute names.

### Producers

Inside `state_bridge/app.py`:

| Endpoint / source           | Event(s) emitted                             | Location |
|-----------------------------|----------------------------------------------|----------|
| `POST /state/fen` (engine)  | `FEN_UPDATE`                                 | [app.py:708-719](../server/state_bridge/app.py#L708) |
| `POST /state/fen` (CV-derived valid move) | `CV_CAPTURE`, `BEST_MOVE`        | [app.py:689-699](../server/state_bridge/app.py#L689) |
| `POST /capture`             | `CV_CAPTURE_REQUESTED`, `CV_CAPTURE_RESULT`  | [app.py:780-837](../server/state_bridge/app.py#L780) |
| `POST /state/move`          | `MOVE_MADE`                                  | [app.py:725-733](../server/state_bridge/app.py#L725) |
| `POST /state/select`        | `PIECE_SELECTED`                             | [app.py:748-751](../server/state_bridge/app.py#L748) |
| `POST /state/best-move`     | `BEST_MOVE`                                  | [app.py:759-762](../server/state_bridge/app.py#L759) |
| `POST /state/led-command`   | `LED_COMMAND`                                | [app.py:768-770](../server/state_bridge/app.py#L768) |

The relay (engine → bridge), in
[server/state_bridge/engine_relay.py](../server/state_bridge/engine_relay.py),
publishes from authoritative engine messages:

| Engine msg                  | Event(s) emitted                             | Location |
|-----------------------------|----------------------------------------------|----------|
| `state` / `move_result`     | `FEN_UPDATE`, `MOVE_MADE`                    | [engine_relay.py:543-586](../server/state_bridge/engine_relay.py#L543) |
| `legal_moves`               | `PIECE_SELECTED`                             | [engine_relay.py:592-595](../server/state_bridge/engine_relay.py#L592) |
| `ai_move`                   | `MOVE_MADE`, `LED_ENGINE_TURN`               | [engine_relay.py:569-585](../server/state_bridge/engine_relay.py#L569) |
| terminal `result` field     | `LED_GAME_RESULT`, `LED_RESET`               | [engine_relay.py:462-477](../server/state_bridge/engine_relay.py#L462) |

### Subscribers

Four subscriber surfaces, all in `state_bridge/app.py`:

1. **SSE stream** at `GET /state/events` —
   [app.py:1202-1239](../server/state_bridge/app.py#L1202). Clients with
   `Accept: text/event-stream`. Filterable via `?types=FEN_UPDATE,MOVE_MADE,…`.
   Initial `STATE_SYNC` snapshot is sent before live events.
2. **Main board WebSocket** at `GET /ws` —
   [app.py:1242-1326](../server/state_bridge/app.py#L1242). Bidirectional;
   accepts commands (`move`, `reset`, `ai_move`, `legal_moves`, `suggest`) and
   relays engine replies. Tracks `seq` for ordering.
3. **Kibo WebSocket** at `GET /ws/kibo` —
   [app.py:1149-1195](../server/state_bridge/app.py#L1149). Subscribes to
   `KIBO_TRIGGER` only and forwards animation cues to the 3D character on the
   frontend.
4. **Engine relay (internal)** —
   [engine_relay.py:227-307](../server/state_bridge/engine_relay.py#L227).
   Holds two WebSocket connections to the Rust engine: an *observer* channel
   that publishes events to the bus, and a *command* channel that does
   request/reply with `command_id` correlation and a `suppress_side_effects`
   flag to avoid double-publishing.

---

## 2. Engine relay: Rust ↔ Python protocol

The relay is the only thing in the stack that holds a stable connection to the
Rust engine, with reconnect + session restore at
[engine_relay.py:357-370](../server/state_bridge/engine_relay.py#L357).

### Message shapes (selected)

Bridge → Engine:

| Type                      | Payload fields                                          | Source line |
|---------------------------|----------------------------------------------------------|-------------|
| `move`                    | `move`, `command_id?`                                    | [69-73](../server/state_bridge/engine_relay.py#L69) |
| `ai_move`                 | `difficulty?`                                            | [90-94](../server/state_bridge/engine_relay.py#L90) |
| `reset`                   | `command_id?`                                            | [113-117](../server/state_bridge/engine_relay.py#L113) |
| `set_position`            | `fen`, `resume_seq?`                                     | [107-111](../server/state_bridge/engine_relay.py#L107) |
| `legal_moves_for_fen`     | `fen`, `square`                                          | [207-213](../server/state_bridge/engine_relay.py#L207) |
| `analyze_position`        | `fen`, `difficulty`                                      | [166-172](../server/state_bridge/engine_relay.py#L166) |
| `batch_analyze`           | `moves: [{fen, move_str}]`                               | [174-180](../server/state_bridge/engine_relay.py#L174) |
| `detect_puzzle`           | `fen`, `depth`                                           | [191-197](../server/state_bridge/engine_relay.py#L191) |

Engine → Bridge:

| Type           | Payload fields                                                       | Source line |
|----------------|-----------------------------------------------------------------------|-------------|
| `state`        | `fen`, `side_to_move`, `result`, `is_check`, `seq`                    | [524-526](../server/state_bridge/engine_relay.py#L524) |
| `move_result`  | `valid`, `fen`, `move`, `result`, `is_check`, `seq`, `command_id?`    | [528-552](../server/state_bridge/engine_relay.py#L528) |
| `ai_move`      | `fen`, `move`, `result`, `is_check`, `score`, `seq`                   | [555-586](../server/state_bridge/engine_relay.py#L555) |
| `legal_moves`  | `square`, `targets`, `seq?`                                           | [588-595](../server/state_bridge/engine_relay.py#L588) |
| `error`        | `message`                                                             | [597-599](../server/state_bridge/engine_relay.py#L597) |

### Suppression flag

When the orchestrator (or a Go agent via the bridge) calls a *command* path
that already returns the new state in the reply, the relay marks
`suppress_side_effects=True` so it does **not** also broadcast a
`MOVE_MADE`/`FEN_UPDATE` from the observer channel. This avoids double-emit.

---

## 3. Authorization: `STATE_BRIDGE_TOKEN`

Introduced in commit `c230acf` (April 2026).

- Read once at startup at
  [app.py:76](../server/state_bridge/app.py#L76).
- Required on every endpoint except `/health` —
  [app.py:223-230](../server/state_bridge/app.py#L223). Accepted via
  `Authorization: Bearer <token>` header
  ([app.py:89-95](../server/state_bridge/app.py#L89)) **or** `?token=...` query
  param ([app.py:112-113](../server/state_bridge/app.py#L112)).
- Constant-time comparison via `secrets.compare_digest` at
  [app.py:98-101](../server/state_bridge/app.py#L98).
- WebSocket handshake validates the same token —
  [app.py:119-128](../server/state_bridge/app.py#L119).
- Go side: `BridgeClient` reads `STATE_BRIDGE_TOKEN` from env and stamps
  `Authorization: Bearer` on every request —
  [chess_coach/engine/bridge_client.go:29,45-46,114](../server/chess_coach/engine/bridge_client.go).

> **Gap.** The token is read once at startup; rotation requires a process
> restart. Clients must source the same env var.

---

## 4. Agent orchestration: Python pipeline

Entry: [server/agent_orchestration/app.py](../server/agent_orchestration/app.py).

### Channels

1. **`POST /ws/chat`** —
   [app.py:188-380](../server/agent_orchestration/app.py#L188). Browser sends
   `{type: "chat", message}`; orchestrator replies with
   `{type: "coach_response", source, response_type, message, data}`.
2. **`POST /ws/chat` move events** —
   [app.py:319-350](../server/agent_orchestration/app.py#L319). Browser sends
   `{type: "move_event", move, fen, side, result, is_check, score}`. The
   orchestrator runs analysis only — it does **not** re-apply the move (the
   bridge has already done that). Returns coaching/blunder responses.

### Pipeline

In `Orchestrator.process_input` —
[orchestrator.py:176-296](../server/agent_orchestration/orchestrator.py#L176):

```
input
 ├── OnboardingAgent          (if !onboarding_complete)
 ├── Go coach bridge          (POST /coach, see §5)
 │     └── on failure → fallback
 └── fallback (Python):
       ├── IntentClassifierAgent
       ├── dispatch to target (GameEngine | Coach | Puzzle | RAG | Memory | …)
       ├── follow-up chain (max 3 hops)
       └── OutputAgent (UI formatting)
```

Agent registry is constructed at
[orchestrator.py:94-104](../server/agent_orchestration/orchestrator.py#L94).
Shared mutable context lives in `SessionState`
([session_state.py:59-176](../server/agent_orchestration/session_state.py#L59)):
`board_fen`, `side_to_move`, `game_result`, `turn_phase` (enum), `move_number`,
`last_move`, `last_eval`, `is_check`, `puzzle_mode`, and a bounded
`conversation_history` (max 50).

> **Gap.** Session state is in-memory only ([app.py:68](../server/agent_orchestration/app.py#L68)).
> A `profile_dir` field is set at
> [app.py:150](../server/agent_orchestration/app.py#L150) but its read/write
> path is not wired up consistently — players don't carry across restarts.

> **Gap.** Go-coach availability is health-checked once and cached at
> [orchestrator.py:307-308](../server/agent_orchestration/orchestrator.py#L307).
> If it goes down mid-session, the orchestrator stays in fallback mode for the
> rest of the session — no retry.

---

## 5. Go chess_coach: LLM graph behind HTTP

Entry: [server/chess_coach/cmd/main.go:24-76](../server/chess_coach/cmd/main.go#L24).

### Endpoints

| Route                         | Purpose                            | Source |
|-------------------------------|------------------------------------|--------|
| `GET  /health`                | liveness                            | [main.go:53-56](../server/chess_coach/cmd/main.go#L53) |
| `POST /coach`                 | full graph (default coaching)       | [main.go:58](../server/chess_coach/cmd/main.go#L58) |
| `POST /coach/analyze`         | position analyst only               | [main.go:59](../server/chess_coach/cmd/main.go#L59) |
| `POST /coach/blunder`         | blunder detection only              | [main.go:60](../server/chess_coach/cmd/main.go#L60) |
| `POST /coach/puzzle`          | puzzle curation                     | [main.go:61](../server/chess_coach/cmd/main.go#L61) |
| `POST /coach/features`        | feature extraction                  | [main.go:62](../server/chess_coach/cmd/main.go#L62) |
| `POST /coach/classify-move`   | label a single move                 | [main.go:63](../server/chess_coach/cmd/main.go#L63) |

### Agent graph

[server/chess_coach/graph.go:9-37](../server/chess_coach/graph.go#L9):

```
IngestAgent
  → InspectionAgent
    → OrchestratorAgent (LLM router)
      → BlunderDetectionAgent  (short-circuits via blunder_abort flag)
        → [parallel] PositionAnalystAgent ‖ PuzzleCuratorAgent
          → CoachAgent (LLM, conditional)
            → GuardAgent (scores advice)
              → FeedbackAgent
```

### Engine access

Go's coach calls back into the bridge for engine-truthy questions, via
`BridgeClient` ([chess_coach/engine/bridge_client.go](../server/chess_coach/engine/bridge_client.go)):

| Method            | Bridge endpoint                | Purpose |
|-------------------|--------------------------------|---------|
| `ValidateFEN`     | `POST /engine/validate-fen`    | parse check |
| `Analyze`         | `POST /engine/analyze`         | features at depth |
| `IsMoveLegal`     | `POST /engine/is-move-legal`   | legality |
| `LegalMoves`      | `POST /engine/legal-moves`     | piece moveset |
| `GetState`        | `GET  /state`                  | current FEN |
| `MakeMove`        | `POST /engine/make-move`       | apply move |
| `BatchAnalyze`    | `POST /engine/batch-analyze`   | many positions |
| `Suggest`         | `POST /engine/suggest`         | best move |
| `DetectPuzzle`    | `POST /engine/puzzle-detect`   | puzzle hook |

There is also a `WebSocketClient` fallback that talks directly to the Rust
engine, but `BridgeClient` is the default so requests pass through bridge auth
and so the bridge can publish derived events to subscribers.

---

## 6. End-to-end command flows

### Player makes a move (CV-detected)

1. CV worker sends `POST /capture` to the bridge — bridge publishes
   `CV_CAPTURE_REQUESTED` immediately, awaits the camera/diff result.
2. On success, bridge publishes `CV_CAPTURE_RESULT` and, if a legal move was
   inferred, `POST /state/fen` runs the diff path at
   [app.py:689-699](../server/state_bridge/app.py#L689) and emits `CV_CAPTURE`
   + `BEST_MOVE`.
3. Bridge forwards the move to the Rust engine via the relay's command channel.
4. Engine replies `move_result`; relay publishes `FEN_UPDATE` + `MOVE_MADE`.
5. Frontend SSE/`/ws` clients receive the events; the LED service receives
   the matching LED event; the orchestrator receives a `move_event` over
   `/ws/chat` and runs blunder/coaching analysis (no re-apply).

### Player asks the coach a question

1. Frontend sends `{type:"chat", message:"why was that bad?"}` on
   `/ws/chat`.
2. Orchestrator builds the prompt, tries `POST /coach` against the Go service.
3. Go graph runs Ingest → Inspect → Orchestrate → BlunderDetect → (Analyst ‖
   Puzzle) → Coach → Guard → Feedback. It calls back to the bridge for any
   engine truth (FEN parse, legality, suggest).
4. Result returns to the orchestrator, gets formatted by `OutputAgent`, and is
   streamed back over `/ws/chat` as `{type:"coach_response", …}`.
5. If the coach text contains an animation cue, `KIBO_TRIGGER` is published on
   the bridge bus and the kibo WebSocket forwards it to the browser.

---

## 7. Schemas & contracts (canonical references)

- Event payloads — [server/state_bridge/event_models.py:19-180](../server/state_bridge/event_models.py)
- Engine wire protocol — [server/state_bridge/engine_relay.py:69-599](../server/state_bridge/engine_relay.py)
- Session state — [server/agent_orchestration/session_state.py:59-176](../server/agent_orchestration/session_state.py)
- Move record — [server/state_bridge/state.py:16-22](../server/state_bridge/state.py#L16)
- Agent response shape — [server/agent_orchestration/agents/base_agent.py](../server/agent_orchestration/agents/base_agent.py)
- Bridge auth — [server/state_bridge/app.py:76-230](../server/state_bridge/app.py#L76)
- Go bridge client — [server/chess_coach/engine/bridge_client.go](../server/chess_coach/engine/bridge_client.go)

---

## 8. Known gaps

1. **No durable event log.** Bus is in-memory; restart drops history. SSE
   sends a one-shot `STATE_SYNC` snapshot but no replay.
2. **Session state is volatile.** `SessionState` lives in-process; no DB or
   file-backed persistence is wired through reliably ([app.py:68](../server/agent_orchestration/app.py#L68),
   [app.py:150](../server/agent_orchestration/app.py#L150)).
3. **Go-coach availability is sticky.** Cached health check at
   [orchestrator.py:307-308](../server/agent_orchestration/orchestrator.py#L307);
   no recovery without restart.
4. **Token rotation.** `STATE_BRIDGE_TOKEN` is read once at startup; rotation
   needs a redeploy.
5. **Sequence ordering.** Relay attaches `seq`
   ([engine_relay.py:90-91](../server/state_bridge/engine_relay.py#L90)) but
   it's unclear whether all subscribers enforce monotonicity on receipt.
6. **Rate limiting.** Only the CV dedup window
   ([app.py:60](../server/state_bridge/app.py#L60), default 0.5s); no
   per-endpoint limits.
7. **Puzzle-mode lifecycle.** Auto-enter at
   [orchestrator.py:374-381](../server/agent_orchestration/orchestrator.py#L374),
   exit on solve at
   [orchestrator.py:455-456](../server/agent_orchestration/orchestrator.py#L455);
   no timeout, no explicit abort path.
