# Test Suites

## Run Commands

### Rust engine
```bash
cd Engine && cargo test
```

### Go chess coach
```bash
cd server/chess_coach && GOCACHE=/tmp/go-build-chess-coach go test ./...
```

### Go agent framework
```bash
cd server/go_agent_framework && GOCACHE=/tmp/go-build-goaf go test ./...
```

### Python agent orchestration
```bash
python -m pytest -c server/pytest.ini server/agent_orchestration/tests
```

### State bridge
```bash
python -m pytest -c server/state_bridge/pytest.ini server/state_bridge/tests
```

### Compose-backed integration
```bash
python -m pytest -c integration_tests/pytest.ini integration_tests -q
```

### React client
```bash
cd client/Interface && npm test
```

### React targeted coaching tests
```bash
cd client/Interface && npm test -- App.test.tsx ChatPanel.test.tsx
```

### Frontend build check
```bash
cd client/Interface && npm run build
```

## Agent + LLM File Tree

```text
client/Interface/src/
├── App.tsx — main game UI; forwards move events into coaching chat flow.
├── App.test.tsx — tests move-event -> coaching wiring.
├── hooks/
│   └── useWebSocket.ts — shared websocket hook used by interactive UI flows.
├── components/
│   ├── ChatPanel.tsx — posts to /dashboard/chat and renders agent responses.
│   ├── ChatPanel.test.tsx — tests chat payloads and rendered coaching output.
│   └── AgentStateGraph.tsx — visualizes agent/graph state when wired in.
└── pages/
    └── AgentsPage.tsx — agent dashboard page for graph/chat inspection.

server/chess_coach/
├── cmd/
│   └── main.go — boots coach service, dashboard chat handler, graph, LLM models.
├── graph.go — wires the Go coaching graph and agent execution order.
├── agents/
│   ├── ingest.go — extracts FEN, move, and question from requests.
│   ├── inspection.go — validates/normalizes position input.
│   ├── orchestrator.go — decides routing; optional LLM intent classification.
│   ├── blunder_detection.go — checks whether the move is a blunder.
│   ├── position_analyst.go — engine analysis + phase-based RAG retrieval.
│   ├── puzzle_curator.go — puzzle generation + puzzle-objective RAG retrieval.
│   ├── rag_support.go — shared helpers for invoking RAG tools and storing context.
│   ├── coach.go — slow-path LLM synthesis using engine and RAG context.
│   ├── guard.go — strips illegal or unsafe move references from advice.
│   ├── feedback.go — assembles the final user-visible explanation.
│   ├── analysis.go — compact analysis agent used by auxiliary flows.
│   └── strategy.go — strategic LLM advice agent for position coaching.
├── engine/
│   ├── bridge_client.go — bridge-backed engine HTTP client used by agents/tools.
│   ├── client.go — engine client contracts/helpers.
│   └── features.go — feature/result structures consumed by coach agents.
└── tools/
    ├── tools.go — base tool registration for coach graph.
    ├── feature_tools.go — engine feature/classification tool wrappers.
    ├── rag_tools.go — registers RAG tools used by live explanations.
    ├── chromadb_retriever.go — ChromaDB retrieval backend.
    ├── puzzle_tools.go — puzzle generation tool wrappers.
    ├── puzzle_detector_tools.go — tactical/puzzle detection helpers.
    ├── pgn_tools.go — PGN/game text helpers.
    └── visualize_tools.go — visualization-oriented helper tools.

server/go_agent_framework/
├── core/
│   ├── graph.go — generic graph runtime used by chess_coach.
│   ├── context.go — execution context and shared graph state carrier.
│   ├── tool.go — tool interfaces and registry.
│   ├── skill.go — skill registry and step metadata.
│   ├── rag.go — framework-level RAG abstractions.
│   ├── handler.go — graph request execution entrypoint.
│   ├── worker.go — async worker/runtime helpers.
│   └── workflow.go — workflow composition primitives.
├── contrib/llm/
│   ├── client.go — LLM client interface used by Go agents.
│   ├── openrouter.go — OpenRouter implementation.
│   └── mock.go — test/mock LLM implementation.
└── observability/
    ├── dashboard.go — dashboard mux and chat integration surface.
    ├── llm.go — LLM call instrumentation.
    └── publish.go — event publishing for graph/agent state.

server/agent_orchestration/
├── LLM/
│   ├── prompts.py — centralized prompt templates for Python coaching flows.
│   └── LLMRegistry.py — provider/model registry.
├── Inference/
│   └── pipeline.py — RAG -> prompt -> LLM inference pipeline.
├── tools/
│   ├── llm_client.py — provider-agnostic Python LLM client.
│   ├── rag_retriever.py — Python RAG retrieval adapter.
│   ├── engine_client.py — Python engine access layer.
│   └── go_client.py — Python -> Go service bridge client.
├── services/
│   ├── orchestrator.py — Python orchestration service and chat/proactive flows.
│   ├── session_state.py — session memory and conversation continuity.
│   ├── state_tracker.py — tracks agent/LLM outputs for inspection.
│   └── agent_logger.py — logs tool, RAG, and LLM activity.
└── agents/
    ├── base_agent.py — base Python agent contract.
    ├── coach_agent.py — Python coach agent using prompts + LLM.
    ├── rag_manager_agent.py — retrieval coordination agent.
    ├── game_engine_agent.py — engine-analysis agent.
    ├── intent_classifier.py — intent routing/classification.
    ├── output_agent.py — final response shaping.
    ├── memory_agent.py — memory/context agent.
    ├── puzzle_master_agent.py — puzzle coaching flow.
    ├── onboarding_agent.py — onboarding/help responses.
    ├── retrieval_request.py — retrieval routing presets by task.
    └── token_limiter_agent.py — token-budget guard before LLM calls.
```
