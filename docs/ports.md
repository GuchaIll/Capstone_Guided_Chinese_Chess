# Port Mapping & Key Endpoints

## Docker Service Ports

| Service | Host Port | Container Port | Protocol |
|---|---|---|---|
| **chess-engine** | — (internal only) | 8080 | HTTP + WebSocket |
| **state-bridge** | 5003 | 5003 | HTTP + WebSocket (REST + SSE + WS) |
| **go-coaching** | 5002 | 8080 | HTTP |
| **chess-coaching** | 5001 | 5000 | HTTP |
| **chromadb** | 8000 | 8000 | HTTP |
| **embedding** | 8100 | 8100 | HTTP |
| **chess-client** | 3000 / 80 | 3000 | HTTP |
| **kibo-viewer** | 3001 | 3001 | HTTP |
| **led-server** (Pi, external) | 5000 | — | HTTP |

---

## Key Endpoints

| URL | Description |
|---|---|
| `http://localhost:3000` | Main game interface |
| `http://localhost:3000/agents` | Agent pipeline inspector |
| `http://localhost:3001` | Kibo 3D avatar |
| `ws://localhost:5003/ws` | State bridge gameplay WebSocket |
| `http://localhost:5003/state/events` | State bridge SSE stream |
| `http://localhost:5003/health` | State bridge health check |
| `http://localhost:5003/kibo/trigger` | POST — send animation trigger to Kibo |
| `ws://localhost:5003/ws/kibo` | Kibo animation WebSocket |
| `http://localhost:5002/dashboard/` | Go Coach live agent graph UI |
| `http://localhost:5002/dashboard/events` | Real-time SSE of agent execution |
| `http://localhost:5002/coach` | General coaching endpoint |
| `http://localhost:5002/coach/analyze` | Position analysis only |
| `http://localhost:5002/coach/blunder` | Blunder detection on a move sequence |
| `http://localhost:5002/coach/puzzle` | Puzzle generation |
| `http://localhost:5002/health` | Go coach health check |
| `http://localhost:5002/metrics` | Prometheus metrics |
| `http://localhost:5001/health` | Python coach health check |
| `http://localhost:8000` | ChromaDB HTTP API |
| `http://localhost:8100` | Embedding service API |
