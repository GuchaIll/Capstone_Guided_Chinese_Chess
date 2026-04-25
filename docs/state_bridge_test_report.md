# State Bridge Test Report

## Scope

This report tracks the bridge-first validation layers defined in
[docs/bridge_server_flow.md](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/docs/bridge_server_flow.md):

- bridge-local unit and async integration tests under `server/state_bridge/tests`
- compose-backed cross-service integration tests under `integration_tests/`

The expected system sequence includes:

- authoritative engine state mirrored into the bridge
- CV-driven physical-board turn submission through `POST /state/fen`
- validation failures surfaced as `cv_validation_error`
- LED blackout and restore commands around CV capture
- Go coaching and Python coaching interoperability with the bridge/engine stack

## Suites Run

### Executed

Command:

```bash
/tmp/state_bridge_test_env/bin/python -m pytest -c server/state_bridge/pytest.ini server/state_bridge/tests
```

Result:

- `39 passed in 0.36s`

Covered subsystems:

- bridge REST contracts
- bridge SSE ordering and payload shape
- CV FEN diff validation helper
- accepted and rejected physical-board CV flows
- engine relay async request/response helpers
- LED bridge subscriber HTTP adapter behavior

### Compose-backed Integration

Command:

```bash
/tmp/state_bridge_test_env/bin/python -m pytest -c integration_tests/pytest.ini integration_tests -q
```

Result on a Docker-enabled local run:

- `11 passed`

In restricted environments where Docker or loopback access is blocked, the
integration fixture converts those permission failures into a clean
session-level skip instead of a hard error.

## Pass/Fail by Subsystem

### Bridge

- Status: passed
- Evidence:
  - `GET /health`
  - `GET /state`
  - `POST /state/fen`
  - `POST /state/move`
  - `POST /state/select`
  - `POST /state/best-move`
  - `POST /state/led-command`
  - compatibility endpoints `/fen` and `/opponent`

### Relay

- Status: passed
- Evidence:
  - outbound helper coverage for `move`, `ai_move`, `legal_moves`, `set_position`
  - request/response helper coverage for `analyze`, `suggest`, `validate_fen`, `make_move`
  - inbound event handling for `state`, `move_result`, `ai_move`, `legal_moves`, `analysis`, `suggestion`, `error`
  - reconnect behavior

### LED Bridge Subscriber

- Status: passed
- Evidence:
  - SSE parsing
  - FEN update forwarding
  - piece selection forwarding
  - opponent/AI move highlighting route
  - best-move highlighting route
  - LED pause/resume commands

### Rust Engine

- Status: passed for the covered integration scenarios
- Covered scenarios:
  - direct WebSocket move/reset/get_state path
  - bridge observation of engine-originated moves
  - bridge passthrough endpoints

### Go Coaching

- Status: implemented in compose-backed suite, not executable in this sandbox
- Covered scenarios:
  - `/coach/features`
  - `/coach/classify-move`
  - `/dashboard/chat`

### Python Coaching

- Status: implemented in compose-backed suite, not executable in this sandbox
- Covered scenarios:
  - `/health`
  - `/health/llm`
  - `/agents`
  - `/agent-state/graph`

## Event Timelines

### Physical-board Success Flow

Expected and tested in the integration suite:

1. `state_sync`
2. `led_command` with `{"command": "off"}`
3. `led_command` with `{"command": "on"}`
4. `fen_update` with `source="cv"`
5. `best_move`
6. `move_made` with `source="ai"`

### Physical-board Failure Flow

Expected and tested in both bridge-local and integration suites:

1. `state_sync`
2. `led_command` with `{"command": "off"}`
3. `cv_validation_error`
4. `led_command` with `{"command": "on"}`

Failure invariants:

- authoritative `state.fen` remains unchanged
- `cv_fen` keeps the rejected board snapshot for inspection
- no move is recorded
- LEDs are restored

## Doc-to-Implementation Gaps Found and Addressed

- Added explicit `cv_validation_error` event coverage in tests.
- Added direct FEN-diff helper tests for:
  - quiet move derivation
  - capture derivation
  - zero-change rejection
  - ambiguous diff rejection
  - own-piece capture rejection
  - side-mismatch rejection
- Implemented and verified engine WebSocket fan-out for authoritative gameplay
  events so bridge observers now receive direct client move/reset/AI updates.
- Implemented snapshot-based helper endpoints in the engine so
  `validate_fen`, `legal_moves_for_fen`, `make_move_for_fen`, and
  `suggest_for_fen` no longer depend on mutating the live session.
- Updated bridge-local SSE capture to ignore the initial `state_sync` event by default so mutation tests assert the intended emitted event.
- Realigned LED subscriber tests to the recovered HTTP LED server adapter instead of the older direct NeoPixel helpers.

## Blocked vs Executable

### Executable in this environment

- all bridge-local tests under `server/state_bridge/tests`

### Conditionally blocked

- compose-backed tests under `integration_tests/` are blocked only when the
  environment disallows loopback HTTP or Docker socket access

## Recommended Follow-up

- Start Phase 2 of the architectural revision: split the bridge relay into
  dedicated observer and command channels so helper traffic is isolated even
  before the browser cutover.
- Add an engine-level regression test for helper endpoints staying side-effect
  free across `analyze_position`, `batch_analyze`, and `detect_puzzle`, not
  just `make_move_for_fen` and `legal_moves_for_fen`.
- Run the compose-backed suite on CI with Docker daemon access and loopback
  networking enabled so the live cross-service checks become a required gate.
- If the documented bridge flow continues to evolve, keep the physical-board success and failure event timelines in sync with [docs/bridge_server_flow.md](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/docs/bridge_server_flow.md).
- Consider adding one dedicated integration assertion for a Go coaching request that consumes a bridge-originated `best_move` event after a successful CV turn.
