# Project Structure

```
Capstone_Guided_Chinese_Chess/
├── Engine/                       # Rust — game logic, AI, WebSocket server
│   └── src/
│       ├── api.rs                # Warp HTTP/WS handlers
│       ├── Game.rs               # Xiangqi rules and board
│       ├── GameState.rs          # Position, history, scoring
│       └── AI/
│           └── alpha_beta.rs
│
├── server/
│   ├── state_bridge/             # Python FastAPI — central event hub
│   │   ├── app.py                # REST + SSE + WS endpoints
│   │   ├── engine_relay.py       # Persistent WS relay to Rust engine
│   │   ├── events.py             # EventBus (SSE + WS broadcast)
│   │   └── cv_validation.py      # CV FEN validation helpers
│   │
│   ├── chess_coach/              # Go — 9-agent coaching pipeline
│   │   ├── cmd/main.go           # HTTP server, tool registry, graph wiring
│   │   ├── graph.go              # Agent graph definition
│   │   ├── agents/               # All 9 agent implementations
│   │   ├── engine/               # BridgeClient, WSClient, MockEngine
│   │   ├── tools/                # Engine tools, RAG tools, puzzle tools
│   │   └── skills/               # Coaching skill definitions (JSON)
│   │
│   ├── go_agent_framework/       # Git submodule — reusable Go agent runtime
│   │   ├── core/                 # Agent graph engine, node lifecycle, SSE bus
│   │   ├── contrib/              # Optional integrations (LLM adapters, RAG helpers)
│   │   ├── dashboard/            # Embedded web dashboard (agent graph visualizer)
│   │   ├── observability/        # Prometheus metrics and tracing helpers
│   │   └── examples/             # Standalone usage examples
│   │
│   ├── agent_orchestration/      # Python — LLM orchestration, session memory
│   │   ├── agents/               # Specialist agent implementations
│   │   └── tools/                # Engine client, RAG retriever, LLM client
│   │
│   └── embedding_service/        # Python — sentence transformer API (BAAI/bge-m3)
│
├── ledsystem/                    # Raspberry Pi — LED board driver
│   ├── led_board.py              # NeoPixel hardware layer + BOARD_LED_MAP
│   ├── led_server.py             # Flask REST API (:5000)
│   └── bridge_subscriber.py      # SSE → LED event handler
│
├── cv/                           # Computer vision — board state detection
│   └── board_pipeline_yolo8.py  # YOLO v8 + ArUco perspective warp + FEN export
│
├── client/Interface/             # React + TypeScript — board UI
│   └── src/
│       ├── components/           # Board, ChatPanel, GameOverModal, VoiceControl
│       ├── hooks/                # useGameState, useWebSocket, useVoiceCommands
│       └── pages/                # GamePage, AgentsPage
│
├── Kibo/                         # Three.js — Kibo 3D character viewer (:3001)
│   ├── src/
│   │   ├── main.ts               # Entry point — loads model, animations, WS
│   │   ├── scene.ts              # Camera, lights, OrbitControls
│   │   ├── KiboCharacter.ts      # FBXLoader, AnimationMixer, root-motion strip
│   │   ├── KiboAPI.ts            # WebSocket command handler
│   │   ├── animationMap.ts       # Trigger → weighted-random animation map
│   │   └── types.ts              # FbxAnimation, KiboTrigger, KiboCommand types
│   └── public/models/            # Kibo1.fbx + Mixamo FBX animation clips
│
├── finetunning/                  # LoRA fine-tuning pipeline (Qwen2.5-7B)
│   └── game_commentary_LoRA.ipynb
│
├── integration_tests/            # Cross-service integration tests
│   └── test_core_stack_integration.py
│
├── docs/                         # Architecture and operational docs
├── img/                          # README images
└── docker-compose.yml            # 9-service container orchestration
```

---

## Key Entry Points

| What you want to change | File |
|---|---|
| Game rules / AI depth | `Engine/src/Game.rs`, `Engine/src/AI/` |
| State bridge events & endpoints | `server/state_bridge/app.py`, `events.py` |
| Agent pipeline routing | `server/chess_coach/graph.go` |
| Agent implementations | `server/chess_coach/agents/` |
| Kibo animations | `Kibo/src/KiboCharacter.ts`, `Kibo/src/animationMap.ts` |
| Board UI components | `client/Interface/src/components/` |
| LED color logic | `ledsystem/led_board.py` |
| CV piece detection | `cv/board_pipeline_yolo8.py` |
