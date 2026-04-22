# Manual Testing Strategy — Guided Chinese Chess

> Covers the full system: engine, coaching, State Bridge, CV, LED, and client.
> Run tests top-to-bottom after any deployment or code change.

---

## Prerequisites

| Requirement | How to verify |
|---|---|
| Docker Desktop running | `docker info` succeeds |
| All services up | `docker compose ps` — all 7 "healthy" or "running" |
| No port conflicts | `lsof -i :3000,5001,5002,5003,8080` shows only expected processes |

---

## 1. Engine (Rust — port 8080)

| # | Test | Command / Steps | Expected |
|---|---|---|---|
| 1.1 | Health check | `curl http://localhost:8080/health` | `200 OK` |
| 1.2 | WS connection | Open `ws://localhost:8080/ws` in a WebSocket client (e.g. websocat, Postman) | Connection accepted |
| 1.3 | Get initial state | Send `{"type":"get_state"}` | `{"type":"state","fen":"rnbakabnr/...","side_to_move":"red","result":"in_progress","is_check":false}` |
| 1.4 | Legal move | Send `{"type":"move","move":"b0c2"}` (knight) | `{"type":"move_result","valid":true,...}` |
| 1.5 | Illegal move | Send `{"type":"move","move":"a0a5"}` (rook blocked by pawn) | `{"type":"move_result","valid":false,...}` |
| 1.6 | AI move | Send `{"type":"ai_move","difficulty":3}` | `{"type":"ai_move","move":"...","fen":"...","score":...}` |
| 1.7 | Reset | Send `{"type":"reset"}` then `{"type":"get_state"}` | Starting FEN returned |

---

## 2. State Bridge (Python FastAPI — port 5003)

### 2.1 Basic endpoints

| # | Test | Command | Expected |
|---|---|---|---|
| 2.1.1 | Health | `curl http://localhost:5003/health` | `{"status":"ok"}` |
| 2.1.2 | State snapshot | `curl http://localhost:5003/state` | JSON with `fen`, `side_to_move: "red"`, `game_result: "in_progress"` |
| 2.1.3 | Engine relay connected | Check bridge logs: `docker compose logs state-bridge` | `"Connected to engine"` (no repeated connection errors) |

### 2.2 FEN updates

| # | Test | Command | Expected |
|---|---|---|---|
| 2.2.1 | Engine FEN | `curl -X POST http://localhost:5003/state/fen -H 'Content-Type: application/json' -d '{"fen":"rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"}'` | `{"status":"FEN updated","source":"engine"}` |
| 2.2.2 | CV FEN | `curl -X POST http://localhost:5003/state/fen -H 'Content-Type: application/json' -d '{"fen":"test_cv_fen","source":"cv"}'` | `{"status":"FEN updated","source":"cv"}` |
| 2.2.3 | Verify CV FEN stored | `curl http://localhost:5003/state \| jq .cv_fen` | `"test_cv_fen"` |

### 2.3 SSE event stream

```bash
# Terminal 1: subscribe
curl -sN http://localhost:5003/state/events

# Terminal 2: trigger events
curl -X POST http://localhost:5003/state/fen -H 'Content-Type: application/json' -d '{"fen":"test","source":"cv"}'
curl -X POST http://localhost:5003/state/best-move -H 'Content-Type: application/json' -d '{"from_sq":"e3","to_sq":"e4"}'
curl -X POST http://localhost:5003/state/led-command -H 'Content-Type: application/json' -d '{"command":"off"}'
```

**Expected in Terminal 1:** Three SSE messages with event types `cv_capture`, `best_move`, `led_command`.

### 2.4 Engine passthrough

| # | Test | Command | Expected |
|---|---|---|---|
| 2.4.1 | Forward move | `curl -X POST http://localhost:5003/engine/move -H 'Content-Type: application/json' -d '{"move":"b0c2"}'` | `{"status":"Move forwarded to engine"}` + SSE `move_made` event |
| 2.4.2 | AI move | `curl -X POST http://localhost:5003/engine/ai-move -H 'Content-Type: application/json' -d '{"difficulty":3}'` | `{"status":"AI move requested"}` + SSE events |
| 2.4.3 | Reset | `curl -X POST http://localhost:5003/engine/reset` | `{"status":"Game reset"}` + SSE `game_reset` event |

### 2.5 LED-compat endpoints

| # | Test | Command | Expected |
|---|---|---|---|
| 2.5.1 | /fen compat | `curl -X POST http://localhost:5003/fen -H 'Content-Type: application/json' -d '{"fen":"test"}'` | `{"status":"FEN updated","source":"engine"}` |
| 2.5.2 | /opponent compat | `curl -X POST http://localhost:5003/opponent -H 'Content-Type: application/json' -d '{"from_r":0,"from_c":0,"to_r":1,"to_c":0}'` | `{"status":"Opponent move displayed"}` |

### 2.6 Side-to-move notation

| # | Test | Command | Expected |
|---|---|---|---|
| 2.6.1 | Default is "red" | `curl http://localhost:5003/state \| jq .side_to_move` | `"red"` |
| 2.6.2 | FEN "w" maps to "red" | POST FEN with `w` side token, then GET /state | `side_to_move: "red"` |
| 2.6.3 | FEN "b" maps to "black" | POST FEN with `b` side token, then GET /state | `side_to_move: "black"` |

---

## 3. Coaching Server (Python — port 5001)

| # | Test | Command / Steps | Expected |
|---|---|---|---|
| 3.1 | Health | `curl http://localhost:5001/health` | `200 OK` |
| 3.2 | Agent graph | `curl http://localhost:5001/agent-state/graph` | JSON with agent nodes and edges |
| 3.3 | Agent registry | `curl http://localhost:5001/agents` | JSON array of agent names and statuses |
| 3.4 | Coaching WS | Connect to `ws://localhost:5001/ws` and send `{"type":"chat","message":"explain the opening"}` | Coaching response with agent trace |

---

## 4. Go Coaching Service (port 5002)

| # | Test | Command / Steps | Expected |
|---|---|---|---|
| 4.1 | Health | `curl http://localhost:5002/health` | `{"status":"ok"}` |
| 4.2 | Dashboard UI | Open `http://localhost:5002/dashboard/` in browser | Agent graph visualization renders |
| 4.3 | Graph API | `curl http://localhost:5002/dashboard/graph` | JSON with 10 agents, tools, skills |
| 4.4 | Metrics | `curl http://localhost:5002/metrics` | Prometheus text format |

---

## 5. CV Pipeline (laptop / standalone)

> Run on the machine with the USB camera — not in Docker.

| # | Test | Steps | Expected |
|---|---|---|---|
| 5.1 | Camera opens | `python cv/board_pipeline_yolo8.py` | Camera feed window appears |
| 5.2 | ArUco detection | Place 4 ArUco markers (IDs 0-3) at board corners | Green overlay on warped frame |
| 5.3 | Piece detection | Place pieces on board, press `c` to capture | Console prints `fen:` line with valid FEN |
| 5.4 | Bridge publish | Set `BRIDGE_URL=http://<host>:5003` env var and trigger capture | Bridge logs show `POST /state/fen` from cv; `curl localhost:5003/state \| jq .cv_fen` shows the captured FEN |
| 5.5 | LED handshake | With `LED_HANDSHAKE_ENABLED=True`, trigger capture | Bridge receives `POST /state/led-command {"command":"off"}` then `{"command":"on"}` |

---

## 6. LED System (Raspberry Pi)

> Run on the Pi connected to the NeoPixel strip.

### 6.1 Direct LED test (no network)

```bash
# SSH into Pi
sudo python ledsystem/ledsystem.py
# CLI prompt appears. Type:
#   fen rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR
# LEDs should light up showing starting position
```

### 6.2 Bridge subscriber (network)

```bash
# On the Pi — point to the machine running State Bridge
sudo python ledsystem/bridge_subscriber.py --bridge-url http://<BRIDGE_IP>:5003

# From another terminal — trigger events
curl -X POST http://<BRIDGE_IP>:5003/state/fen -H 'Content-Type: application/json' \
  -d '{"fen":"rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"}'
```

| # | Test | Trigger | Expected LED behaviour |
|---|---|---|---|
| 6.2.1 | FEN update | POST /state/fen | LEDs show piece positions from FEN |
| 6.2.2 | Best move | POST /state/best-move `{"from_sq":"e3","to_sq":"e4"}` | Green glow on e3 and e4 |
| 6.2.3 | Piece selected | POST /state/select `{"square":"e3"}` | Piece square highlighted, legal targets shown |
| 6.2.4 | Opponent move | POST /state/move `{"from_sq":"e6","to_sq":"e5"}` | Blue/purple highlights on move squares |
| 6.2.5 | LED off | POST /state/led-command `{"command":"off"}` | All LEDs turn off |
| 6.2.6 | LED on | POST /state/led-command `{"command":"on"}` | LEDs restore previous state |
| 6.2.7 | Game reset | POST /engine/reset | LEDs show starting position |

---

## 7. Client UI (React — port 3000)

| # | Test | Steps | Expected |
|---|---|---|---|
| 7.1 | Board loads | Open `http://localhost:3000` | 9×10 board with starting position |
| 7.2 | Drag move | Drag red cannon from b2 to e2 | Piece moves; engine validates; board updates |
| 7.3 | AI response | After red move | Black side plays automatically |
| 7.4 | Chat panel | Type "why was that a good move?" | Coaching response appears |
| 7.5 | Kibo animation | Type "great move" in chat | Kibo avatar plays ThumbsUp animation |
| 7.6 | Voice | Say "Kibo, suggest a move" | Voice-recognized text appears; coaching responds with suggestion |
| 7.7 | Agent inspector | Navigate to `/agents` | Graph shows active agent pipeline with transitions |

---

## 8. Full Integration Flow

This end-to-end test validates the complete pipeline with all subsystems running.

### Setup
1. Start all Docker services: `docker compose up --build -d`
2. On the CV machine: `BRIDGE_URL=http://<DOCKER_HOST>:5003 python cv/board_pipeline_yolo8.py`
3. On the Pi: `sudo python ledsystem/bridge_subscriber.py --bridge-url http://<DOCKER_HOST>:5003`
4. Open `http://localhost:3000` in browser

### Test sequence

| Step | Action | Verify |
|---|---|---|
| 8.1 | Place physical board under camera with ArUco markers | CV window shows warped board |
| 8.2 | Press `c` to capture | CV publishes FEN → bridge SSE emits `cv_capture` → Pi LEDs show detected position |
| 8.3 | Make a move on the web UI | Engine SSE emits `move_made` → Pi LEDs update → coaching analyses |
| 8.4 | Request AI move via UI | Engine plays → bridge relays → Pi LEDs highlight AI move |
| 8.5 | Coaching best-move hint | Go coaching POSTs to bridge → Pi LEDs show green best-move |
| 8.6 | LED handshake during capture | Press `c` → LEDs turn off → capture → LEDs restore |
