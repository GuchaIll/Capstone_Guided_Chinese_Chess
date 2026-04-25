# Architectural Revision

This document revises the bridge remediation plan in response to the failure documented in
[docs/state_bridge_test_report.md](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/docs/state_bridge_test_report.md),
especially the gap where direct browser WebSocket moves are not observable by the bridge.

The target architecture remains:

- the bridge is the single orchestrator and external gateway
- the engine is reduced to pure game logic plus stateless analysis
- helper operations never mutate live game state
- UI, CV, LED, and coaching all converge on one bridge-owned command/event model

## Goals

1. Eliminate split-brain state between browser, bridge, and physical board.
2. Ensure every authoritative move becomes a bridge event visible to all observers.
3. Prevent helper and analysis requests from corrupting live play.
4. Support physical-board CV move attempts as first-class command sources.
5. Provide a safe migration path from the current direct-engine-WS model.

## Core Revisions

### 1. Single Writer Rule During Migration

The previous phased plan left a dangerous window where both:

- the browser could send gameplay commands directly to the engine
- the bridge could send gameplay commands through its own command channel

That is not acceptable.

Revised rule:

- at any point in time, exactly one transport path is allowed to issue authoritative gameplay commands

Implementation policy:

- Phase 1 may still allow direct browser engine WS, because the bridge is not yet the gameplay gateway
- once Phase 2 bridge command routing is enabled for gameplay, the browser must stop issuing authoritative commands directly to the engine
- the browser cutover is enforced with a runtime configuration flag such as `USE_BRIDGE_COMMANDS`

Concrete browser migration behavior:

- during the migration window, the React client may keep:
  - a direct engine WS for read-only compatibility
  - a bridge WS for authoritative gameplay commands
- the runtime flag determines which transport is used for `move`, `reset`, `ai_move`, and other state-changing commands
- when Phase 3 is enabled, the client never sends non-readonly commands to the direct engine WS
- engine-side rejection of non-primary or deprecated gameplay clients remains an additional safety net, not the primary enforcement mechanism

Allowed migration strategies:

1. Preferred:
   - move browser gameplay commands to bridge immediately after bridge command routing is ready
   - leave engine direct WS available only for read-only compatibility
2. Temporary fallback:
   - engine designates one connection as the primary command channel
   - non-primary clients attempting `move`, `reset`, or `ai_move` receive a rejection error

Explicit non-goal:

- tagging commands alone is not enough; tags help tracing, but they do not prevent conflicting writes

### 2. Serialized Command Handling and Idempotency

The bridge command handler must be explicit, not implied.

Required runtime behavior:

- the bridge processes authoritative commands from all external clients on one asynchronous FIFO queue
- exactly one authoritative command is in flight at a time
- no lock-based cross-client mutation scheme is required because ordering is defined by the queue

This applies to authoritative commands from:

- React UI
- CV/physical-board ingestion
- operator or admin reset flows

Idempotency requirement:

- every authoritative `move` and `reset` carries a `command_id`
- the bridge should accept a caller-provided UUID when available and otherwise generate one
- duplicate `command_id` values within the live session are rejected
- the engine also tracks processed `command_id` values as a second safety net for retries and reconnect races

Design rule:

- retries must be safe
- the same physical or network action must never create two authoritative state transitions

## Target Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  EXTERNAL CLIENTS                               │
├──────────────┬───────────────┬─────────────────┬───────────────┬────────────────┤
│  React UI    │  CV + Board   │   LED Ctrl      │   Coaching    │   Observer     │
│  (browser)   │  (physical)   │   (hardware)    │   dashboard   │   (metrics)    │
└──────┬───────┴───────┬───────┴────────┬────────┴───────┬───────┴───────┬────────┘
       │               │                │               │               │
       │ (WS/SSE)      │ (WS/HTTP)      │ (WS/SSE)      │ (WS/SSE)      │ (WS/SSE)
       ▼               ▼                ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BRIDGE (Orchestrator)                              │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ Connection Manager                                                        │  │
│  │ - owns all external client sessions                                       │  │
│  │ - applies role and topic filtering                                        │  │
│  │ - partitions naturally by game_id when multi-session support is added     │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ Command Handler                                                            │  │
│  │ - single asynchronous FIFO queue                                          │  │
│  │ - one authoritative command at a time                                     │  │
│  │ - assigns or validates command_id                                         │  │
│  │ - rejects duplicate command_id within the session                         │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ Canonical Snapshot + Event Bus                                            │  │
│  │ - tracks current state and last_seq                                       │  │
│  │ - subscribes to engine observer events                                    │  │
│  │ - gap seq > 1 triggers get_state resync                                   │  │
│  │ - fans out authoritative events to clients                                │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ Helper Request Handler                                                    │  │
│  │ - forwards analysis to cloned/stateless engine state                      │  │
│  │ - returns private replies only                                            │  │
│  │ - never mutates live state or publishes gameplay events                   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ CV Resolution                                                              │  │
│  │ - validates board diffs against authoritative snapshot                    │  │
│  │ - deduplicates repeated detections in a short time window                 │  │
│  │ - submits only validated commands into the FIFO command queue             │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬─────────────────┬─────────────────────────────┘
                                │                 │
                    command_ws  │                 │  observer_ws
                    (gRPC/WS)   │                 │  (authoritative events)
                                ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ENGINE (Pure Logic Core)                             │
│  ┌─────────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │ Live Game Session           │    │ Stateless Analysis / Cloned State       │ │
│  │ - apply authoritative cmd   │    │ - legal_moves(clone)                    │ │
│  │ - validate move/reset       │    │ - suggestion(clone)                     │ │
│  │ - emit seq++ per session    │    │ - analyze(clone)                        │ │
│  │ - reject duplicate command  │    │ - validate_fen(clone)                   │ │
│  └─────────────────────────────┘    └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Bridge ownership:

- all external client connections
- canonical session snapshot
- command arbitration
- event fan-out
- CV validation policy
- reconnection state sync for observers

Engine ownership:

- move validation
- move application
- AI search
- state transition generation
- stateless analysis on snapshots

## Bridge Snapshot Model

The bridge caches a full in-memory canonical snapshot, not just a FEN string.

Snapshot contents:

- current FEN
- side to move
- result and check state
- last move
- selection and overlay state
- best-move hint
- CV advisory state
- last observed authoritative event sequence

Update rule:

- the bridge updates its `GameStateBridge` snapshot atomically on every authoritative observer event
- helper replies never update the live snapshot

Ordering rule:

- every authoritative engine event includes a monotonically increasing `seq` scoped to the live game session
- observer-channel events are assumed FIFO ordered from the engine, but the bridge still validates `seq`
- if `seq` is missing, stale, or jumps by more than 1, the bridge must request a fresh `get_state` and rebuild from snapshot rather than trying to replay missing events

## Session Scope

The current plan is intentionally session-specific.

That is acceptable for a single-game deployment, but the boundaries must be explicit:

- bridge snapshots, command queues, deduplication caches, and observer streams are currently scoped to one live game session
- multi-game support is an extension, not a redesign
- when multiple sessions are added, the bridge should partition:
  - connections by `game_id`
  - canonical snapshots by `game_id`
  - `last_seq` tracking by `game_id`
  - processed `command_id` caches by `game_id`

## Revised Phase Plan

### Phase 1. Engine Broadcast and Helper Isolation

Objective:

- make engine-originated gameplay events observable
- isolate helper requests from the live session

Changes:

- add engine-side observer support for state-changing commands only
- keep helper replies private and non-broadcast
- implement helper operations on cloned or temporary game state
- include authoritative `seq` on every live gameplay event from the engine
- reject duplicate authoritative `command_id` values within the live session

Broadcasted messages:

- valid `move_result`
- `ai_move`
- `state` after `reset`
- other authoritative state changes that alter the live session

Never broadcast:

- `legal_moves`
- `suggestion`
- `analysis`
- `batch_analysis`
- helper-only `set_position`
- invalid move errors except to the requesting caller

Acceptance criteria:

- `cargo test` includes a unit test proving an observer receives `move_result`
- `cargo test` includes a unit test proving an observer does not receive `legal_moves`
- `cargo test` includes a unit test proving authoritative engine events use strictly increasing `seq`
- helper regression tests prove `suggest`, `validate_fen`, `legal_moves`, and analysis-only `make_move` do not mutate the live session

### Phase 2. Bridge Dual-Channel Relay

Objective:

- separate live event observation from request/response helper traffic

Bridge engine channels:

- `observer_ws`
  - subscribes to authoritative live game events only
  - drives bridge SSE and bridge-side state updates
- `command_ws`
  - sends gameplay commands during migration
  - sends helper requests
  - never directly publishes to public observers

Important revision:

- Phase 2 and Phase 3 should be treated as a tight cutover, not a long-lived intermediate state
- the bridge command handler is explicitly FIFO and processes one authoritative command at a time
- duplicate `command_id` values are rejected at the bridge boundary before they can create duplicate mutations

Acceptance criteria:

- bridge integration test:
  - send gameplay command via `command_ws` → `observer_ws` receives exactly one authoritative event
  - send helper call via `command_ws` → `observer_ws` receives zero gameplay events
- bridge integration test rejects duplicate `command_id` within a session
- reconnect logic is independent per channel
- on observer reconnect, bridge performs a fresh `get_state` sync instead of relying on event replay
- bridge treats command and observer connectivity as one authoritative session bundle for gameplay readiness

### Phase 3. Browser Migration to Bridge

Objective:

- make the bridge the sole external gameplay gateway

Required behavior:

- React UI stops sending authoritative gameplay commands directly to engine WS
- browser uses bridge WS for:
  - `move`
  - `reset`
  - `get_state`
  - `legal_moves`
  - optional `suggest`
- browser continues using bridge SSE for synchronized state events
- browser cutover is controlled by a runtime flag so the command path can be switched intentionally and observed during rollout

Migration guardrail:

- once browser gameplay cutover is enabled, direct engine WS must become read-only or rejected for gameplay commands

Acceptance criteria:

- end-to-end test where React-like bridge client and simulated physical-board bridge client send alternating moves
- both clients receive identical bridge event streams
- no direct browser dependency remains on engine WS for gameplay

### Phase 4. Engine Transport Simplification

Objective:

- remove client-facing network topology responsibility from the engine

Critical clarification:

- this phase is not complete until the engine no longer manages external WebSocket roles or observer broadcast semantics

Target state:

- engine exposes only internal transport to bridge
- bridge is the sole external publisher of gameplay events

Preferred options:

1. internal gRPC between bridge and engine
2. in-process library boundary if operationally acceptable
3. internal-only message queue/channel model

Decision guidance:

- if bridge and engine remain in separate processes or containers, prefer gRPC with streaming
- if bridge and engine are embedded into one binary, in-process calls are acceptable
- queue-based transport is only preferred if buffering or isolation requirements justify the extra operational cost

Current recommendation:

- Phase 4 should target gRPC streaming as the default internal transport
- that gives typed commands plus streamed authoritative events without preserving any public client-facing WebSocket role in the engine

Explicit requirement:

- engine has no knowledge of browser, observer, LED, or helper client roles
- engine does not publish directly to external clients

Acceptance criteria:

- engine binary can run without any public WebSocket listener
- bridge is the only public gameplay gateway

## CV-Initiated Move Pipeline

The previous plan did not fully define how CV move attempts become authoritative actions.

Revised CV flow:

1. CV service submits a detected board result to bridge
   - payload may include `fen`, confidence, timestamp, and capture metadata
2. Bridge derives the move attempt against the current authoritative snapshot
3. Bridge validates on cloned state first
   - structural FEN validation
   - board diff derivation
   - legal move check
   - optional confidence threshold policy
4. If valid:
   - bridge forwards the move through the live command channel
   - engine applies it
   - authoritative event returns through observer channel
5. If invalid:
   - bridge publishes an error event for UI and physical-board consumers
   - no live state mutation occurs

## CV Move Ambiguity Resolution

CV input may yield zero, one, or multiple plausible legal moves.

Bridge policy:

1. compute legal moves from the current authoritative snapshot
2. filter candidate moves using the CV board diff
3. if exactly one legal move matches:
   - accept and forward the move
4. if zero legal moves match:
   - emit validation failure
5. if multiple legal moves match:
   - emit a `cv_ambiguous` event with the candidate set and CV metadata
   - require UI or operator confirmation before any authoritative mutation

Design principle:

- the bridge never guesses among multiple valid move candidates
- repeated CV detections of the same observation in a short time window are deduplicated before entering the authoritative command path

Error event behavior:

- UI receives actionable validation feedback
- LED/physical board can be instructed to restore previous visual state
- repeated CV submissions are allowed after correction

Design rule:

- CV is a command source, not a state owner
- authoritative state always comes from the bridge/engine live session

## Reconnect and Missed Event Recovery

The engine does not need event replay history.

Recovery model:

- bridge caches the latest full authoritative snapshot
- any observer reconnect gets:
  - immediate `state_sync` from bridge
  - then new live events

For bridge observer-channel reconnect:

- bridge re-establishes `observer_ws`
- if the engine process restarted, the bridge re-initializes the fresh engine instance with the last known state from bridge memory or persistent storage
- immediately performs a live `get_state`
- updates its canonical snapshot
- resumes fan-out from the new baseline

Requirement:

- no client should depend on replaying all missed historical events to recover correctness

## Topic-Based Event Filtering

The bridge event bus should support topic-based or event-type filtering.

Examples:

- React UI subscribes to the full gameplay stream
- LED controller subscribes only to:
  - `move_made`
  - `piece_selected`
  - `game_reset`
- monitoring or coaching tools may subscribe to narrower subsets

Clarification:

- the bridge should not invent LED-specific hardware commands as part of the authoritative gameplay model
- the LED controller derives its own device actions from gameplay events

Filtering rule:

- authoritative state is computed once, then projected per subscriber
- filtered subscribers never affect canonical snapshot state

## Bridge–Engine Session Health

The bridge must treat engine connectivity as a session bundle.

Required behavior:

- if either authoritative channel becomes unhealthy during the dual-channel architecture:
  - bridge stops accepting new authoritative gameplay commands
  - bridge reports degraded mode to clients
  - bridge attempts reconnect and resynchronization
- gameplay resumes only after the required engine channel set is healthy and the bridge snapshot has been refreshed

During the current single-relay architecture:

- the bridge should already expose relay health and last-sync metadata
- that provides the baseline for the stricter dual-channel health model

## Backward Compatibility and Deprecation

The direct engine WS cannot disappear abruptly.

Deprecation policy:

1. Release N:
   - direct engine WS still exists
   - gameplay commands are deprecated
   - warning log emitted on direct gameplay command use
2. Release N+1:
   - direct engine WS is read-only or compatibility-only
   - authoritative gameplay commands rejected with migration guidance
3. Release N+2:
   - direct public engine WS removed or made internal-only

Compatibility note:

- existing tests and tools that only read state may continue temporarily
- all gameplay automation should be migrated to bridge-owned APIs

## Revised Test Matrix

### Engine Unit Tests

- observer receives valid `move_result`
- observer does not receive `legal_moves`
- observer receives `ai_move`
- authoritative events include strictly increasing `seq`
- helper `set_position` does not alter live session
- helper `make_move` on snapshot does not alter live session

### Bridge Integration Tests

- command channel gameplay request produces exactly one observer event
- helper request produces zero observer gameplay events
- observer reconnect triggers fresh `state_sync`
- command and observer channels reconnect independently
- duplicate `command_id` is rejected within the live bridge session

### End-to-End Tests

- React-like bridge client sends move, LED-like observer sees same event
- CV-like client submits detected move, bridge validates and either commits or emits error
- simulated UI client and simulated physical-board client alternate turns and stay in sync
- concurrent move attempts from two clients are serialized by the bridge FIFO queue and final state is deterministic

### Concurrency Tests

- two near-simultaneous move submissions do not produce divergent state
- event ordering to observers matches engine-applied command order
- concurrency tests should use controlled scheduling against a single-threaded bridge command queue, not timing-sensitive sleeps

### Resilience Tests

- engine restarts, bridge reconnects, re-initializes state, fetches fresh snapshot, and resumes broadcasting
- observer `seq` gap forces `get_state` resynchronization instead of silent continuation

## Delivery Order

Recommended execution order:

1. Phase 1
   - engine observer broadcast
   - helper isolation
2. Phase 2 + Phase 3 cutover
   - dual-channel bridge relay
   - browser gameplay migration to bridge immediately after relay readiness
3. CV pipeline hardening
   - command-source normalization
   - bridge-side validation policy
4. Phase 4
   - internalize engine transport
   - remove public engine WS gameplay path

This ordering minimizes the split-writer window and gets to bridge-owned command authority earlier.

## Final Architecture Decision

The bridge is not a passive relay.

It is the orchestrator that:

- owns all external connectivity
- arbitrates all authoritative commands
- publishes all client-visible events
- normalizes UI and physical-board interactions
- shields the live game session from helper-side mutations

The engine is not a broker.

It is a deterministic game and analysis core behind the bridge.
