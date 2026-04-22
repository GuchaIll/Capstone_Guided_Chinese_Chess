# Guided Chinese Chess (象棋) — Capstone Project

An intelligent, interactive Xiangqi (Chinese Chess) learning platform that combines a high-performance game engine, a multi-agent AI coaching system, a 3D animated coach avatar, and a voice-controlled React interface

**Team:** Charlie Ai · Claire Lee · Yoyo Zhong

---

## Vision

Most Xiangqi learners have no access to real-time, personalized coaching. This is an ongoign capstone project bridges that gap by pairing every game with an AI coach (Kibo) that detects blunders, explains moves, generates tactical puzzles, and teaches domain knowledge — adapting its depth and tone to each player's skill level. The long-term vision includes physical board integration via Raspberry Pi LED guidance and a computer-vision board-state detector.

---

## Features

### Gameplay
- Full Xiangqi rule enforcement (legal moves, flying general, perpetual check/chase, stalemate)
- Alpha-Beta minimax AI opponent with configurable difficulty
- Drag-and-drop or click-to-move piece interaction on an authentic 9×10 board
- Real-time bi-directional game state sync over WebSocket

### AI Coaching (Multi-Agent Pipeline)
| Agent | Responsibility |
|---|---|
| **IntentClassifier** | Routes player input (move / why / hint / teach / puzzle) |
| **GameEngine** | Proxies moves to the Rust engine, validates results |
| **Coach** | Blunder detection, move explanation, "why" Q&A |
| **PuzzleMaster** | Generates and validates tactical puzzles from game positions |
| **RAGManager** | Retrieves Xiangqi knowledge from ChromaDB vector store |
| **Memory** | Tracks player profile, mistake history, skill progression |
| **TokenLimiter** | Enforces daily LLM token budgets |
| **Output** | Formats responses for chat UI / TTS / LED |
| **Onboarding** | 5-step new-player questionnaire to calibrate coaching |

### Kibo — 3D Coach Avatar
Kibo is a digital avatar that transforms chess gameplay into a personalized, interactive experience and reflects on your progress over time, surfacing insights about your growth as a player
Makes every game feel like a coaching session

- Three.js GLTF character with full animation state machine
- States: Idle · Cheer · Dance  · Dance · Knocked down
- Emotes: Wave · Jump · Head Shake · Head Nod · ThumbsUp
- Keyword-driven: coaching server broadcasts animation commands in real time when the LLM response contains action keywords (e.g. "great move!" → ThumbsUp)

### Voice Interaction
- Wake-word detection: **"Kibo"** (also accepts: Kibble, Kimbo, Kiko, Kido)
- Web Speech API STT / TTS — fully in-browser, no external service required
- Continuous recognition; only forwards speech after wakeword is detected

### Agent Pipeline Inspector
- Live React Flow graph showing active agents, transitions, and data flow
- Polling log of all agent-to-agent transitions with intent, latency, and LLM output
- Enable / disable individual agents from the UI
- Accessible at `http://localhost:3000/agents`


### LLM Flexibility
- Pluggable provider registry: OpenRouter · OpenAI · Anthropic · Mock (offline fallback)
- Mock provider ships by default — the app works fully without an API key
- Switch providers via environment variables, no code changes needed

---

## Project Structure

```
Capstone_Guided_Chinese_Chess/
├── Engine/                  # Rust — game logic, AI, WebSocket server
│   └── src/
│       ├── main.rs          # Warp HTTP/WS server
│       ├── Game.rs          # Xiangqi rules and board
│       ├── GameState.rs     # Position, history, scoring
│       └── AI/
│           └── AlphaBetaMinMax.rs
│
├── server/                  # Python — agent orchestration, RAG, LLM
│   ├── app.py               # FastAPI entry point
│   └── agent_orchestration/
│       ├── agents/          # All agent implementations
│       ├── services/        # Orchestrator, session state, state tracker
│       ├── tools/           # Engine client, RAG retriever, LLM client
│       └── LLM/             # Provider registry and prompt templates
│
├── client/Interface/        # React + TypeScript — board UI, chat, agent inspector
│   └── src/
│       ├── components/      # Board, ChatPanel, AgentStateGraph, VoiceControl …
│       ├── hooks/           # useChessVoiceCommands, useChessWebSocket …
│       └── pages/           # GamePage, AgentsPage
│
├── Kibo/                    # Three.js — Kibo 3D character viewer
│   └── src/
│       ├── KiboCharacter.ts # GLTF model loader + animation mixer
│       ├── KiboAPI.ts       # JS control surface + WebSocket receiver
│       └── main.ts          # Entry point, auto-connect to /ws/kibo
│
└── docker-compose.yml       # Five-service orchestration
```

---

## Port Mapping

| Service | Container Port | Host Port | Description |
|---|---|---|---|
| **chess-engine** | 8080 | 8080 | Rust game engine (HTTP health + WS) |
| **chess-coaching** | 5000 | **5001** | Python coaching server (FastAPI) |
| **chess-client** | 3000 | 3000 / 80 | React board UI (nginx) |
| **kibo-viewer** | 3001 | 3001 | Kibo 3D avatar viewer (nginx) |
| **go-coaching** | 8080 | **5002** | Go coaching service (agent framework + dashboard) |

> **Note:** The coaching server's host port is **5001** (not 5000) because macOS Monterey+ reserves port 5000 for AirPlay Receiver. All internal Docker networking still uses port 5000.

### Key Endpoints

| URL | Description |
|---|---|
| `http://localhost:3000` | Main game interface |
| `http://localhost:3000/agents` | Agent pipeline inspector |
| `http://localhost:3001` | Kibo 3D avatar viewer |
| `ws://localhost:8080/ws` | Rust engine WebSocket |
| `http://localhost:5001/health` | Coaching server health check |
| `http://localhost:5001/agent-state/graph` | Live agent graph (JSON) |
| `http://localhost:5001/agents` | Agent registry (JSON) |
| `http://localhost:5002/dashboard/` | Go Agent Framework dashboard (live agent graph UI) |
| `http://localhost:5002/dashboard/events` | Real-time SSE stream of agent execution |
| `http://localhost:5002/dashboard/graph` | Agent graph structure (JSON) |
| `http://localhost:5002/dashboard/stats` | LLM token usage statistics |
| `http://localhost:5002/coach` | Go coaching pipeline API |
| `http://localhost:5002/health` | Go coaching health check |
| `http://localhost:5002/metrics` | Prometheus metrics |

---

## Setup Guide

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (v24+)
- Git

### 1. Clone the Repository
```bash
git clone <repo-url>
cd Capstone_Guided_Chinese_Chess
```

### 2. Configure Environment (Optional)
Copy the template and add your LLM API key to enable real AI responses. Without a key the system runs in mock mode, which still demonstrates the full pipeline.

```bash
cp .env.example .env   # if it exists, otherwise create .env manually
```

```dotenv
# .env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemma-3-12b-it:free

# OR use OpenAI / Anthropic instead:
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# Embedding model for RAG (default works offline)
EMBEDDING_MODEL=BAAI/bge-m3
```

### 3. Build and Start
```bash
docker compose up --build
```

First build takes ~5 minutes (Rust compilation + Python ML library downloads). Subsequent starts use cached layers and are much faster.

### 4. Open the App
- **Game:** http://localhost:3000
- **Kibo:** http://localhost:3001
- **Agent Inspector:** http://localhost:3000/agents

### Stopping
```bash
docker compose down
```

---

## Local Development (Without Docker)

### Rust Engine
```bash
cd Engine
cargo run --release
# Runs at http://localhost:8080
```

### Python Coaching Server
```bash
cd server
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 5000 --reload
```

### React Client
```bash
cd client/Interface
npm install
npm run dev
# Runs at http://localhost:3000 (proxies WS to localhost:8080 and localhost:5000)
```

### Kibo Viewer
```bash
cd Kibo
npm install
npm run dev
# Runs at http://localhost:3001 (proxies /ws/kibo to localhost:5000)
```

---

## Future Improvements

### Physical Board Integration
- Raspberry Pi LED strip driver for move highlighting
- Computer vision (OpenCV) for automatic board-state detection from a camera
- Serial/GPIO output from OutputAgent already stubbed in the pipeline

### LLM & RAG
- Fine-tuned Xiangqi model (Xiangqi-GPT) replacing generic LLM prompting
- Populate ChromaDB with opening theory, endgame tables, and annotated games
- Cross-session memory persistence (SQLite → cloud sync)

### Kibo Avatar
- Replace placeholder RobotExpressive model with a custom Kibo character asset
- Facial expression blendshapes driven by sentiment analysis of LLM output
- Lip-sync TTS using phoneme timing data

### Gameplay
- Game replay and annotated PGN export
- Opening explorer with ECO-style Xiangqi opening database
- Puzzle library with difficulty ratings and spaced repetition

### Infrastructure
- Replace polling-based agent state inspector with WebSocket push
- Redis pub/sub for multi-session agent isolation
- Prometheus metrics + Grafana dashboard for LLM latency and token usage
- Mobile-responsive board layout for iPhone / iPad play
