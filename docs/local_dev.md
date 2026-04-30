# Local Development (Without Docker)

Use this guide when you want to run individual services directly on your machine, without Docker Compose. All services can be run simultaneously — they communicate over localhost.

---

## Startup Order

Start services in this order to avoid connection errors at boot:

1. Rust Engine
2. State Bridge
3. Go Coaching Service
4. Python Coaching Server (optional)
5. React Client

---

## Rust Engine

```bash
cd Engine
cargo run --release
# Binds to 127.0.0.1:8080 by default
```

The engine exposes an HTTP + WebSocket server. The state bridge connects to `ws://localhost:8080/ws`.

---

## State Bridge

```bash
cd server/state_bridge
pip install -r requirements.txt
ENGINE_WS_URL=ws://localhost:8080/ws uvicorn app:app --port 5003 --reload
```

Public gameplay endpoints once running:

```
ws://localhost:5003/ws          — gameplay WebSocket
http://localhost:5003/state/events  — SSE stream
http://localhost:5003/health    — health check
```

---

## Go Coaching Service

```bash
cd server/chess_coach
BRIDGE_URL=http://localhost:5003 go run ./cmd/main.go
# http://localhost:5002
```

The agent graph dashboard is available at `http://localhost:5002/dashboard/`.

---

## Python Coaching Server (optional)

```bash
cd server
pip install -r requirements.txt
ENGINE_WS_URL=ws://localhost:8080/ws uvicorn app:app --port 5001 --reload
```

---

## React Client

```bash
cd client/Interface
npm install
npm run dev
# http://localhost:3000
```

---

## Kibo Avatar

```bash
cd Kibo
npm install
echo 'VITE_STATE_BRIDGE_TOKEN=integration-bridge-token' > .env.local
npm run dev
# http://localhost:5173 (Vite default)
```

By default the avatar now connects to `ws://localhost:5003/ws/kibo?token=...`.
To override it manually, pass a tokenized URL such as:
`?ws=ws://localhost:5003/ws/kibo?token=integration-bridge-token`

---

## Embedding Service

```bash
cd server/embedding_service
pip install -r requirements.txt
uvicorn app:app --port 8100
```

---

## Environment Variables Reference

| Variable | Service | Default | Description |
|---|---|---|---|
| `ENGINE_WS_URL` | State Bridge | `ws://chess-engine:8080/ws` | Rust engine WebSocket URL |
| `BRIDGE_URL` | Go Coach | `http://state-bridge:5003` | State bridge base URL |
| `LLM_PROVIDER` | Go Coach / Python Coach | `mock` | `openrouter`, `openai`, `anthropic`, or `mock` |
| `OPENROUTER_API_KEY` | Go Coach | — | Required if `LLM_PROVIDER=openrouter` |
| `ANTHROPIC_API_KEY` | Go Coach | — | Required if `LLM_PROVIDER=anthropic` |
| `EMBEDDING_MODEL` | Embedding Service | `BAAI/bge-m3` | Sentence transformer model |
| `CHROMADB_URL` | Go Coach | `http://chromadb:8000` | ChromaDB HTTP URL |
