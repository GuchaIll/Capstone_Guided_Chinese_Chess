# LED Board Controller — User Manual

This document describes how the physical LED chess board works, what each light color means, and the step-by-step sequence for every game event.

---

## 1. Hardware Overview

| Component | Details |
|---|---|
| LED strip | NeoPixel GRBW, 400 pixels |
| Controller | Raspberry Pi, GPIO pin D18 |
| Layout | 10 rows × 9 columns (90 active cells + border/decorative pixels) |
| Brightness | 20% of maximum |
| Color order | Green, Red, Blue, White (GRBW) |

The board uses a lookup table (`BOARD_LED_MAP`) to map each (row, col) grid cell to a physical LED index. The mapping is non-sequential because of how the strip is routed around the board.

### Grid Coordinates

```
     a    b    c    d    e    f    g    h    i
 0 [ ][ ][ ][ ][ ][ ][ ][ ][ ]    ← Black's back rank (top)
 1 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 2 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 3 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 4 [ ][ ][ ][ ][ ][ ][ ][ ][ ]    ← River
 5 [ ][ ][ ][ ][ ][ ][ ][ ][ ]    ← River
 6 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 7 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 8 [ ][ ][ ][ ][ ][ ][ ][ ][ ]
 9 [ ][ ][ ][ ][ ][ ][ ][ ][ ]    ← Red's back rank (bottom)
```

- **Files:** `a`–`i` (columns, left → right)
- **Ranks:** `0`–`9` (rows, top → bottom)
- **Example square:** `e3` = column e, row 3

---

## 2. Color Reference

| Color | (G, R, B, W) | What it means |
|---|---|---|
| **Red** | (0, 255, 0, 0) | Piece currently selected by player |
| **White** | (0, 0, 0, 255) | Empty square the selected piece can legally move to |
| **Orange** | (0, 255, 80, 0) | Occupied square the selected piece can capture |
| **Blue** | (0, 0, 255, 0) | Square the opponent / AI piece moved **from** |
| **Purple** | (180, 0, 255, 0) | Square the opponent / AI piece moved **to** |
| **Green** | (0, 255, 0, 0) | Best-move destination recommended by the engine |
| **Cyan** | (0, 255, 255, 0) | Starting zone highlights (shown at game start) |
| **Yellow** | (255, 255, 0, 0) | Win celebration (3-second animation) |
| **Pink** | (0, 255, 120, 0) | Win celebration (alternates with yellow) |
| **Off** | (0, 0, 0, 0) | LED cleared — normal off state or during CV capture |

---

## 3. LED Server API Reference

The LED server runs as a Flask service (port 5000) on the Raspberry Pi. It is called by the **bridge_subscriber** in response to SSE events from the state bridge.

> Direct calls to the LED server are only made from `bridge_subscriber.py`. Do not call the LED server from other services.

| Endpoint | Method | Payload | Effect |
|---|---|---|---|
| `POST /fen` | POST | `{"fen": "..."}` | Redraws the full board from a FEN string |
| `POST /move` | POST | `{"row": 0–9, "col": 0–8}` | Lights up legal moves from piece at (row, col) |
| `POST /opponent` | POST | `{"from_r": int, "from_c": int, "to_r": int, "to_c": int}` | Highlights opponent/AI move: from=blue, to=purple |
| `POST /zones` | POST | `{}` | Highlights starting zones in cyan |
| `POST /win` | POST | `{"side": "red"\|"black"}` | Runs 3-second yellow/pink celebration animation |
| `POST /cv_pause` | POST | `{}` | Turns all LEDs off (CV capture blackout) |
| `POST /cv_resume` | POST | `{}` | Restores previous LED display after CV capture |

---

## 4. Bridge Subscriber — Event-to-LED Mapping

The bridge_subscriber (`/ledsystem/bridge_subscriber.py`) runs on the Raspberry Pi and listens to the state bridge SSE stream (`GET http://state-bridge:5003/state/events`). It automatically translates each SSE event into LED server calls.

| SSE Event | LED Action |
|---|---|
| `fen_update` | `POST /fen` with the new FEN — redraws all pieces |
| `cv_capture` | `POST /fen` with the captured FEN |
| `piece_selected` | `POST /move` with row/col of selected square |
| `move_made` (source = ai or opponent) | `POST /opponent` with from/to row/col |
| `best_move` | `POST /move` from the suggested source square (green destination) |
| `led_command` {"command":"off"} | `POST /cv_pause` — all LEDs off |
| `led_command` {"command":"on"} | `POST /cv_resume` — restore display |
| `game_reset` | `POST /fen` with starting FEN, then pause/resume |

### Coordinate conversion used by bridge_subscriber

```python
# Algebraic square ("e3") → (row, col)
col = ord(sq[0]) - ord("a")   # "a"=0, "b"=1, ..., "i"=8
row = int(sq[1])               # "0"=0, ..., "9"=9
```

---

## 5. Step-by-Step: Starting a Game

1. **Power on the Raspberry Pi.** The LED server starts automatically.
2. **Start the Docker services** on the main machine: `docker-compose up`.
3. **Start the bridge_subscriber** on the Pi:
   ```bash
   export STATE_BRIDGE_TOKEN=integration-bridge-token
   python ledsystem/bridge_subscriber.py \
     --bridge-url http://<machine-ip>:5003 \
     --led-url http://localhost:5000
   ```
4. The subscriber connects to the state bridge SSE stream.
5. On connection, the bridge sends a `state_sync` event with the current FEN.
6. The LED board redraws to show the starting position.
7. Optionally call `POST /zones` to highlight starting zones in cyan.

---

## 6. Step-by-Step: Player's Turn (Physical Board)

### 6a. Player picks up a piece

> *This step is for future implementation — currently the LED "piece selected" highlight is driven by the frontend click, not physical pickup detection.*

1. Player lifts a piece from the board.
2. If piece detection is active: bridge posts `POST /state/select {"square":"e3"}`.
3. State bridge publishes `piece_selected {square:"e3", targets:[...]}`.
4. bridge_subscriber receives `piece_selected` → calls `POST /move {"row":3, "col":4}`.
5. **LED board shows:**
   - The selected square lights **Red**.
   - Empty legal destinations light **White**.
   - Capturable squares light **Orange**.

### 6b. Player places the piece (End Turn)

1. Player physically places the piece on the destination square.
2. Player presses the **End Turn** button in the frontend.
3. Frontend sends `POST /state/led-command {"command":"off"}` to state bridge.
4. State bridge publishes `led_command {"command":"off"}`.
5. bridge_subscriber calls `POST /cv_pause` → **all LEDs turn off (100 ms blackout)**.
6. CV camera captures the board image.
7. YOLO model detects pieces → generates new FEN.
8. Frontend posts `POST /state/fen {"fen":"...", "source":"cv"}` to state bridge.

### 6c. Validation — success path

9. State bridge validates the FEN (structure check + engine legal-move check).
10. Validation passes → state bridge accepts the new FEN.
11. State bridge publishes `led_command {"command":"on"}`.
12. bridge_subscriber calls `POST /cv_resume` → **LEDs restore**.
13. State bridge publishes `fen_update {fen, source:"cv", ...}`.
14. bridge_subscriber calls `POST /fen` with new FEN → **board redraws to new position**.
15. Frontend board also updates to match (via SSE `fen_update`).

### 6d. Validation — failure path

9. State bridge validates the FEN — validation **fails** (illegal move detected).
10. State bridge publishes `cv_validation_error {cv_fen, current_fen, reason}`.
11. State bridge publishes `led_command {"command":"on"}`.
12. bridge_subscriber calls `POST /cv_resume` → **LEDs restore to previous position** (the illegal move is NOT reflected on the board).
13. Frontend shows a **warning modal**: "Piece out of place — please correct and press End Turn again."
14. **All play is blocked** until the player corrects the piece and presses End Turn again.
15. Repeat from step 2.

---

## 7. Step-by-Step: AI Response + Coaching Suggestion

After the player's move is accepted:

1. State bridge requests a move suggestion from the engine.
2. Engine returns the best move (e.g., `e3e5`).
3. State bridge publishes `best_move {from:"e3", to:"e5"}`.
4. bridge_subscriber calls `POST /move {"row":3, "col":4}`.
5. **LED board shows:**
   - Source square (`e3`) lights **Red**.
   - Best destination (`e5`) lights **Green**.
6. Frontend simultaneously highlights the suggestion on the digital board.

Then the AI makes its move:

7. State bridge requests AI move from engine.
8. Engine computes and returns AI move (e.g., `h9g7`).
9. State bridge publishes `move_made {source:"ai", from:"h9", to:"g7", fen:"..."}`.
10. bridge_subscriber calls `POST /opponent {"from_r":9, "from_c":7, "to_r":7, "to_c":6}`.
11. **LED board shows:**
    - AI's source square (`h9`) lights **Blue**.
    - AI's destination square (`g7`) lights **Purple**.
12. Frontend simultaneously updates the digital board with the AI move.

---

## 8. Step-by-Step: Game Over

1. Engine returns `result: "red_win"` or `result: "black_win"` in a `move_made` event.
2. State bridge publishes `move_made` with the result.
3. Frontend shows the **Game Over modal**.
4. bridge_subscriber calls `POST /win {"side":"red"}` (or "black").
5. **LED board runs a 3-second celebration animation** (yellow and pink flashing pattern).
6. After animation, LEDs stay at the current board position.

---

## 9. Step-by-Step: Game Reset

1. Frontend sends reset (via WebSocket `{type:"reset"}` to engine, or state bridge REST).
2. Engine resets to starting position.
3. State bridge publishes `game_reset {}`.
4. bridge_subscriber calls `POST /fen` with the starting FEN.
5. **LED board redraws to the starting position.**
6. bridge_subscriber optionally calls `POST /zones` to show starting zones in cyan.

---

## 10. Running the Bridge Subscriber

### On the Raspberry Pi

```bash
# Standard start (connects to Docker host at 192.168.1.x)
export STATE_BRIDGE_TOKEN=integration-bridge-token
python ledsystem/bridge_subscriber.py \
  --bridge-url http://192.168.1.100:5003 \
  --led-url http://localhost:5000

# If running bridge locally (development)
export STATE_BRIDGE_TOKEN=integration-bridge-token
python ledsystem/bridge_subscriber.py \
  --bridge-url http://localhost:5003 \
  --led-url http://localhost:5000

# Legacy interactive CLI mode (manual commands, no SSE)
python ledsystem/bridge_subscriber.py --mode cli
```

### Environment variables (alternative to flags)

```bash
export BRIDGE_URL=http://192.168.1.100:5003
export STATE_BRIDGE_TOKEN=integration-bridge-token
python ledsystem/bridge_subscriber.py
```

### Reconnection behavior

The subscriber automatically reconnects to the state bridge SSE stream on disconnect using exponential backoff. No manual restart is needed if the bridge temporarily goes down.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Board stays dark after startup | bridge_subscriber not running | Start `bridge_subscriber.py` on the Pi |
| bridge_subscriber logs `401 Unauthorized` | Missing or incorrect bridge token | Export `STATE_BRIDGE_TOKEN` or pass `--bridge-token <token>` |
| Board shows wrong position | `fen_update` event missed during reconnect | On reconnect, bridge sends `state_sync` — board redraws automatically |
| LEDs don't turn off for CV capture | `led_command off` event not reaching bridge_subscriber | Check bridge_subscriber log for SSE connection errors |
| Board shows previous position after End Turn | CV validation failed — intended behavior | Player must correct piece and press End Turn again |
| Board stays off after CV capture | `cv_resume` not called | Check state bridge log: `POST /state/led-command {"command":"on"}` should fire after FEN post |
| Win animation doesn't play | `move_made` event has wrong `result` field | Verify engine returns `result: "red_win"` or `"black_win"`, not `"checkmate"` |
| Colors look wrong (shifted) | Wrong pixel_order in NeoPixel init | Verify `pixel_order=neopixel.GRBW` in `led_board.py` |
| LEDs too bright / too dim | Brightness setting | Adjust `brightness=0.20` in `led_board.py` (range 0.0–1.0) |

---

## 12. Quick Reference Card

```
End Turn pressed
  → LEDs off (100ms CV blackout)
  → CV captures board
  → Bridge validates FEN
      FAIL → LEDs restore to current position, warning modal on screen
      PASS → LEDs redraw new position
           → Best move: green destination
           → AI move: blue origin + purple destination
           → Game over: yellow/pink celebration
```
