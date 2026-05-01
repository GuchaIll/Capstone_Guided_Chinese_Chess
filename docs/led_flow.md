# LED Flow

This document describes the intended LED behavior and the bridge events that now drive it.

## Goal

The LED board should no longer infer the intended lighting pattern from generic chess events alone.
Instead, the state bridge should publish explicit LED-intent events for the major use cases, and the LED subscriber should translate those events into concrete LED server calls.

## Pub/Sub Command Path

```
                                publish              SSE
[bridge endpoint / engine_relay] ─────► [EventBus] ──────► [bridge_subscriber.py]
                                                                  │
                                                          dispatch by event.type
                                                                  │
                                       ┌──────────────────────────┼──────────────────────────┐
                                       ▼                          ▼                          ▼
                                  /fen-sync               /player-turn / /engine-turn     /clear / /win / /draw
                                  (state-only)            (visible overlay)               (terminal / reset)
```

- The bridge is the only producer of LED-intent events
  ([state_bridge/app.py:484-527](../server/state_bridge/app.py#L484),
  [state_bridge/engine_relay.py:450-477](../server/state_bridge/engine_relay.py#L450)).
- `bridge_subscriber.py` is the only HTTP caller into the LED server in
  steady state. The one exception is the bridge's direct
  `cv_pause` / `cv_resume` HTTP path during `/capture`, used because SSE
  fan-out latency is too slow for the camera blackout window.
- Subscribers must be idempotent and order-tolerant — events carry a
  monotonically increasing `seq` (see
  [docs/server_orchestration.md](server_orchestration.md)) but the LED
  side does not currently enforce monotonicity on receipt.

## Event Contract

The state bridge now emits these LED-specific SSE events:

- `led_player_turn`
  - Carries `fen`, `side_to_move`, `selected_square`, `legal_targets`, `best_move_from`, `best_move_to`
  - Used to render the full player-turn overlay in one shot

- `led_engine_turn`
  - Carries `fen`, `from`, `to`, `side_to_move`, `result`
  - Used to render the engine move as blue source plus purple destination

- `led_game_result`
  - Carries `result` and optional `winner`
  - Used to trigger `/win` or `/draw`

- `led_reset`
  - Carries `reason`
  - Used to clear any active LEDs after reset or terminal sequences

The older generic events still exist:

- `state_sync`
- `fen_update`
- `move_made`
- `piece_selected`
- `best_move`
- `led_command`
- `game_reset`

Those generic events still matter for board-state sync and non-LED consumers, but the LED subscriber should prefer the explicit LED events for visible turn overlays.

## LED Server Endpoints

The LED subscriber now targets these endpoints:

- `POST /fen-sync`
  - Update internal board state without rendering a board-wide piece display

- `POST /player-turn`
  - Render the player overlay from explicit selected square, targets, and best move

- `POST /engine-turn`
  - Render the engine move overlay

- `POST /zones`
  - Startup region sequence

- `POST /win`
  - Winning sequence

- `POST /draw`
  - Draw sequence

- `POST /clear`
  - Turn off currently lit LEDs

- `POST /cv_pause`
- `POST /cv_resume`
  - Camera blackout / restore flow

## Use Case Flows

### 1. Startup Sequence

When the LED subscriber receives its first `state_sync`:

1. `POST /fen-sync` with the starting bridge FEN
   — non-rendering, just seeds the LED board model so later overlays know
   piece positions
2. `POST /zones` and **leave the zones display up for 20 seconds**
   — this is the visible startup hold; the subscriber must not POST any
   other rendering endpoint during this window
3. on the **first** `led_player_turn` or `led_engine_turn` event after
   startup, transition into the matching use case:
   - `led_player_turn` ⇒ Use Case 2 (`POST /player-turn`)
   - `led_engine_turn` ⇒ Use Case 4 (`POST /fen-sync` then `POST /engine-turn`)
4. if the 20-second window elapses with no `led_player_turn` or
   `led_engine_turn` having arrived, `POST /clear` so the board doesn't
   sit on the zones display indefinitely

Notes:

- This keeps the board model in sync for later capture highlighting.
- The startup region display runs once per subscriber process start.
- Startup must **not** fall back to a board-wide piece render.
- Startup must **not** synthesize a player- or engine-turn overlay from
  the `state_sync` snapshot — let the bridge publish the real
  `led_player_turn` / `led_engine_turn` event and react to that. The
  snapshot's `selected_square`, `best_move_*`, and `last_move` fields
  are advisory and may not be set on a fresh game.
- An `led_player_turn` or `led_engine_turn` arriving inside the 20 s
  window pre-empts it — the overlay wins, the zones disappear early.

### 1a. Implementation notes

The startup contract above is enforced by:

- [ledsystem/bridge_subscriber.py](../ledsystem/bridge_subscriber.py)
  `handle_state_sync` — POSTs `/fen-sync` then `/zones`, then arms a
  daemon `threading.Timer(STARTUP_HOLD_SECONDS, …)` that fires
  `_on_startup_hold_expired` to `POST /clear` if nothing else has
  rendered yet.
- `_cancel_startup_timer(reason)` — invoked at the top of
  `handle_led_player_turn` and `handle_led_engine_turn` so the first
  real overlay event pre-empts the pending `/clear`.
- The startup is one-shot per process: `_startup_completed` guards
  against re-running on SSE reconnects (subsequent `state_sync` events
  only POST `/fen-sync`).

There is **no** snapshot-synthesized overlay path on startup —
`led_player_turn` / `led_engine_turn` from the bridge are the only
inputs that drive the post-startup transition. Bridge producers are
unchanged: `_publish_led_player_turn`
([app.py:484-495](../server/state_bridge/app.py#L484)) and
`_publish_led_engine_turn`
([app.py:517-527](../server/state_bridge/app.py#L517),
[engine_relay.py:450-477](../server/state_bridge/engine_relay.py#L450))
fire on the natural action events.

### 2. Player Turn

When the player selects a piece or when the best move changes, the bridge emits `led_player_turn`.

The LED subscriber calls `POST /player-turn` with:

- current `fen`
- selected square
- legal targets
- best move source and destination

Rendering rules:

- when a piece is selected:
  - selected square: red
  - legal empty targets: white
  - legal capture targets: orange
- when no piece is selected:
  - highlight only the best-move source square: green
- do not light the best-move destination during the steady player-turn idle scene

Behavioral rule:

- selecting a different piece should replace the red/white/orange selection overlay
- with no selection, the green default should identify only the recommended piece to pick up next

### 3. End Turn Blackout

When the user presses End Turn and the client calls bridge `POST /capture`:

1. bridge directly calls LED `POST /cv_pause` for timing-critical blackout when `LED_SERVER_URL` is configured
2. bridge emits `led_command` with `off`
3. subscriber treats `source=bridge_direct_http` blackout commands as audit-only; if direct LED control is unavailable, the bridge marks them as `source=event_bus_fallback` and the subscriber performs the pause/resume itself
4. bridge starts a 200 ms blackout timer
5. bridge calls the CV capture service
6. once capture has completed and the 200 ms minimum blackout has elapsed, bridge directly calls LED `POST /cv_resume` when direct control is enabled
7. bridge emits `led_command` with `on`
8. subscriber calls `POST /cv_resume`

Important:

- the blackout window is owned by the bridge so every `/capture` caller gets the same behavior
- direct LED control is recommended for capture blackout because SSE subscriber latency can leave LEDs lit during the photo
- this direct path requires the bridge process to know a reachable LED endpoint, either via `LED_SERVER_URL` or via `RASPBERRY_PI_IP` / legacy `RASPBERY_PI_IP`
- `cv_resume` should not guess a new scene
- the next explicit LED event should define what gets shown

### 4. Engine Turn

When the engine move is committed, the bridge emits `led_engine_turn`.

The LED subscriber:

1. calls `POST /fen-sync` with the authoritative post-move FEN
2. calls `POST /engine-turn`

Rendering rules:

- engine source square: blue
- engine destination square: purple

### 5. Win / Draw Sequence

When the bridge observes a terminal result:

1. emit `led_game_result`
2. emit `led_reset`

Subscriber behavior:

- if `result == red_wins` or `black_wins`: call `POST /win`
- if `result == draw`: call `POST /draw`
- after the sequence completes: call `POST /clear` for the paired `led_reset`

### 6. Reset Sequence

When the user presses reset:

1. bridge resets engine / bridge state
2. bridge emits `game_reset`
3. bridge emits `led_reset`

Subscriber behavior:

1. sync the starting FEN through `POST /fen-sync`
2. clear LEDs through `POST /clear`

## Current Implementation Direction

The implementation is intentionally moving away from these older inferred flows:

- `piece_selected` -> `POST /move`
- `best_move` -> `POST /move`
- `move_made(ai)` -> `POST /opponent`

Those paths were too lossy because they could not preserve the full player-turn scene across reselection and could not express startup, draw, or explicit reset behavior cleanly.

The preferred path is now:

- explicit bridge LED event
- explicit LED server endpoint
- deterministic renderer in `led_board.py`
