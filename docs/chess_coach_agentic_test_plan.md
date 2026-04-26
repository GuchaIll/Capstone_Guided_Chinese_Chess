# Chess Coach Agentic Behavior and Test Plan

This document reviews the intended agent design in
[docs/agents_flow.md](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/docs/agents_flow.md),
compares it with the current `server/chess_coach` implementation, and revises
the testing strategy for all components involved in producing agent-generated
explanations for the React UI.

It is grounded in the current Go graph in
[server/chess_coach/graph.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/graph.go),
the dashboard chat handler in
[server/chess_coach/cmd/main.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/cmd/main.go),
the bridge-backed engine client in
[server/chess_coach/engine/bridge_client.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/engine/bridge_client.go),
and the React chat surface in
[client/Interface/src/components/ChatPanel.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/components/ChatPanel.tsx).

## Executive Summary

The design doc in [docs/agents_flow.md](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/docs/agents_flow.md)
describes a richer coaching pipeline than the code currently implements.

What is already real:
- `ingest -> inspection -> orchestrator -> blunder_detection -> parallel(position_analyst, puzzle_curator) -> coach -> guard -> feedback`
- bridge-backed engine/tool usage
- dashboard chat endpoint used by the React client
- legal-move guardrails around LLM advice
- ChromaDB tool registration and unit tests for collection routing

What is still aspirational in the design doc:
- an explicit `VisualizationAgent`
- active RAG retrieval inside explanation-producing agents
- live agent-state graph integration into the main React experience
- end-to-end proof that agent-generated explanations, not just engine metrics, reach the player UI

The testing strategy therefore needs two layers:

1. implementation-locking tests for the current graph and APIs
2. design-conformance tests for the missing RAG and UI integration behaviors

## Design Doc vs Current Implementation

### Graph Shape

Intended in the design doc:
- `Ingest -> Inspection -> Orchestrator -> Blunder Detection -> Position Analyst || Puzzle Curator -> Coach -> Guard -> Visualization -> Feedback`

Implemented in code:
- `Ingest -> Inspection -> Orchestrator -> Blunder Detection -> Position Analyst || Puzzle Curator -> Coach -> Guard -> Feedback`

Gap:
- there is no `VisualizationAgent` node in
  [server/chess_coach/graph.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/graph.go)
- the design doc treats visualization as a first-class stage; current code folds final formatting into `feedback`

Testing implication:
- current graph tests should assert the real 9-agent graph
- design-conformance tests should explicitly track the missing visualization stage as a future requirement, not silently assume it exists

### Agent Responsibilities

Mostly aligned:
- `ingest`, `inspection`, `orchestrator`, `blunder_detection`, `puzzle_curator`, `guard`, and `feedback` broadly match the design doc

Partially aligned:
- `position_analyst` does engine analysis and tactical feature extraction, but does not actually invoke phase-specific RAG tools despite claiming those capabilities
- `coach` does LLM synthesis, but does not invoke `explain_tactic` or `get_general_advice` tools directly

Mismatch:
- the design doc says RAG can enrich `PositionAnalyst` and `Coach`
- current implementation advertises RAG capability in metadata, but explanation-producing agents do not call RAG tools in `Run()`

Testing implication:
- existing RAG tool tests only prove tool registration and collection routing
- they do not prove that agents use RAG during real explanations

### RAG Usage

The design doc expects these tools to matter to the explanation path:
- `get_opening_plan`
- `get_middlegame_theme`
- `get_endgame_principle`
- `get_general_advice`
- `explain_tactic`
- `explain_puzzle_objective`

Current reality:
- the tools are registered in
  [server/chess_coach/tools/rag_tools.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/rag_tools.go)
- collection/tool mapping is covered by
  [server/chess_coach/tools/rag_tools_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/rag_tools_test.go)
- no current agent test or graph test proves that these tools are invoked by `position_analyst`, `coach`, or `puzzle_curator`

Testing implication:
- the biggest backend gap is not ChromaDB correctness, but agent-to-RAG integration

### React Integration

The design doc implies a coaching-aware UI that can surface the agent pipeline and explanation state.

Current reality:
- [client/Interface/src/App.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/App.tsx)
  triggers chat commentary through `chatPanelRef.current?.sendMoveEvent(...)`
- [client/Interface/src/components/ChatPanel.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/components/ChatPanel.tsx)
  posts to `POST /dashboard/chat`
- the move-triggered request body is still anchored in engine metrics:
  - `"Check: ${isCheck}, score: ${score}. Comment on this move."`
- `AgentStateGraph` exists, but the main app currently keeps:
  - `showAgentGraph = false`
  - `agentGraphData = null`
- there is no live UI integration proving that graph state, RAG retrieval, or orchestrator branch selection is visible to the player

Testing implication:
- the largest product gap is the React-side integration test story
- today the UI is effectively testing "engine-scored move -> chat request -> text response"
- it is not yet testing "agent orchestration -> retrieval-augmented explanation -> rendered coaching state"

## Current Explanation Path

Today’s end-to-end explanation flow is:

1. React move or chat event
2. `ChatPanel` posts to `POST /dashboard/chat`
3. Go chat handler builds graph context
4. agent graph runs
5. engine and puzzle tools are called
6. `coach` may synthesize advice with the LLM on the slow path
7. `guard` validates move references
8. `feedback` returns final text
9. React renders assistant text in the chat panel

This means the current explanation stack is best described as:
- engine-evaluation driven
- tool-enriched
- optionally LLM synthesized
- legality-guarded
- not yet provably retrieval-augmented in live flows

## Revised Testing Strategy

### 1. Design-Conformance Tests

Goal:
- make the design gaps explicit and trackable instead of hiding them inside broad integration tests

Coverage:
- graph topology matches current implementation exactly
- missing `VisualizationAgent` is documented as an intentional gap
- RAG-trigger expectations from the design doc are tracked as pending integration behaviors
- React agent-graph visibility is tracked as pending UI behavior

Recommended outputs:
- one comparison matrix in docs
- one set of `TODO`-style skipped tests or explicit roadmap items for:
  - visualization stage
  - agent-to-RAG invocation
  - live graph state in the app

### 2. Agent Unit Tests

Goal:
- verify each agent’s local behavior and state mutation rules in isolation

Coverage:
- `IngestAgent`
  - extracts `fen`, `move`, and `question`
  - sets `question_only`, `has_move`, and `is_question`
  - supports Xiangqi coordinate move strings like `b0c2`
- `InspectionAgent`
  - passes valid FEN
  - fails invalid FEN
  - skips question-only requests
- `OrchestratorAgent`
  - sets route flags deterministically
  - sets `coach_trigger`
  - records optional intent classification
- `BlunderDetectionAgent`
  - sets `blunder_abort` only when blunders are present
  - preserves downstream routing on non-blunder paths
- `PositionAnalystAgent`
  - stores `engine_metrics`
  - stores `principal_variation`
  - upgrades `coach_trigger` on tactical patterns
  - does not write RAG outputs yet unless RAG integration is implemented
- `PuzzleCuratorAgent`
  - writes puzzle state only when routed
- `CoachAgent`
  - runs only on slow-path trigger
  - builds prompt from engine and puzzle context
  - stores `coaching_advice`
- `GuardAgent`
  - accepts legal advice
  - rejects illegal move references
- `FeedbackAgent`
  - composes correct output for fast path
  - composes correct output for slow path
  - composes blunder-abort output

### 3. RAG-Agent Integration Tests

Goal:
- close the missing test layer between ChromaDB tool correctness and real agent explanation behavior

This is the most important missing backend test category.

Current gap:
- there are ChromaDB and tool-routing tests
- there are no graph or agent integration tests proving that a retrieval result actually influences an explanation

Required coverage once RAG is wired into agents:
- opening position path
  - `position_analyst` or `coach` calls `get_opening_plan`
  - retrieved opening guidance is visible in final advice
- middlegame tactical path
  - a tactical position triggers `get_middlegame_theme` or `explain_tactic`
  - retrieved tactical guidance is included in final explanation
- endgame path
  - endgame phase triggers `get_endgame_principle`
  - advice cites or paraphrases endgame principle output
- question-only path
  - general user question triggers `get_general_advice`
- puzzle path
  - puzzle generation path optionally triggers `explain_puzzle_objective`

Recommended test structure:
- use stub retrievers returning deterministic passages
- register real RAG tools with those stub retrievers
- run either the agent directly or the full graph
- assert:
  - the expected RAG tool was called
  - the query payload matches the intended source from the design doc
  - the final explanation includes retrieved content or a derived phrase

Design note:
- until agents actually invoke the RAG tools, these should be tracked as pending integration tests rather than forced failures

### 4. Tool and Bridge Client Contract Tests

Goal:
- verify the agent-facing contracts to the bridge and engine

Coverage:
- `BridgeClient`
  - `/engine/analyze`
  - `/engine/suggest`
  - `/engine/batch-analyze`
  - `/engine/is-move-legal`
- tool wrappers
  - `analyze_position`
  - `get_principal_variation`
  - `classify_move`
  - `get_position_features`
  - `detect_blunders`
  - `find_tactical_motif`
  - `generate_puzzle`
- RAG tool wrappers
  - confirm arguments used by agents match the design doc query sources

Recommended style:
- `httptest.Server` for bridge-like JSON payloads
- fake retrievers for ChromaDB-backed tools
- assert decoded Go structs and error propagation

### 5. Graph Integration Tests

Goal:
- prove the real `BuildGraph()` pipeline produces coherent explanation state

Coverage:
- question + FEN path
  - graph ends with non-empty `feedback`
  - `engine_metrics` present
  - `coaching_advice` present when trigger is active
- move explanation path
  - `blunder_detection` participates when `move` is provided
- puzzle path
  - `route_puzzle=true` yields `puzzle`, `puzzle_difficulty`, `puzzle_themes`
- fast-path explanation
  - no coach trigger means no `coaching_advice`, but final `feedback` still returns useful analysis
- guard path
  - illegal advice is removed from final response
- future RAG path
  - when implemented, final `feedback` reflects retrieval-enriched content

### 6. HTTP Integration Tests for the Coaching Surface

Goal:
- test the actual backend APIs the UI and dashboard use

Coverage:
- `POST /dashboard/chat`
  - returns `{ session_id, response, state }`
  - response contains graph-generated explanation
- `POST /coach/analyze`
  - returns explanation plus metrics
- `POST /coach/features`
  - returns feature subsets
- `POST /coach/classify-move`
  - returns classification payload
- `GET /health`
  - returns service health
- `GET /dashboard/graph`
  - returns graph metadata for UI graph rendering

Important addition:
- add handler-level tests that verify `state` includes enough information for future UI graph integration, even if the current React app does not render it yet

### 7. React Integration Test Strategy

Goal:
- explicitly test how agent-generated explanations reach the player, not just how engine metrics are displayed

This is currently the biggest gap.

#### 7.1 What the current UI really does

Today the main app behavior is:
- game events in `App.tsx` call `chatPanelRef.current?.sendMoveEvent(...)`
- `sendMoveEvent()` builds a message that includes engine-native signals like:
  - move string
  - side
  - `Check`
  - `score`
- `ChatPanel` posts that payload to `/dashboard/chat`
- assistant text is rendered in the chat panel

So the current UI is still primarily hooked to engine-generated evaluation metrics, with the agent graph acting behind the endpoint rather than as an explicit UI-visible system.

#### 7.2 Required React integration coverage

1. `ChatPanel` request contract
- user chat request posts to `/dashboard/chat`
- move-triggered explanation request posts:
  - `message`
  - `fen`
  - `move`
  - `session_id`
- response text is rendered

2. `App -> ChatPanel` move explanation wiring
- accepted player move triggers `sendMoveEvent`
- accepted AI move triggers `sendMoveEvent`
- rejected or rolled-back moves do not trigger coaching requests

3. Agent-generated explanation rendering
- when backend returns retrieval-enriched or coach-generated text, the UI displays that text without stripping structure
- explanation rendering should not depend on local engine score labels being present in the UI

4. Graph-state integration plan
- once `GET /dashboard/graph` or a state payload is wired into the app:
  - `AgentStateGraph` renders active/completed nodes
  - graph state updates after a chat or move-triggered request
- current status:
  - this is not yet wired in the main app
  - testing should mark this as pending rather than pretending it exists

5. Error handling
- failed `/dashboard/chat` request shows fallback copy
- partial coaching payloads still render usable assistant text

#### 7.3 Recommended React test layers

Immediate tests:
- keep `ChatPanel` tests for request/response behavior
- add `App` tests that mock the board/game event path and assert `sendMoveEvent` is called for:
  - player move accepted
  - AI move accepted
  - no call on failed move or take-back

Next-phase tests:
- mount `App` with mocked `/dashboard/chat`
- simulate a real move flow
- assert the returned explanation appears in the sidebar chat
- verify the text shown is backend-generated coaching content, not a local score label

Future tests after graph wiring:
- assert `AgentStateGraph` updates from backend graph state
- assert active agent transitions can be surfaced to users during a coaching request

### 8. Compose-Backed End-to-End Tests

Goal:
- validate the full explanation stack with live services running

Coverage:
- React-style chat request -> Go coach -> bridge -> engine -> LLM -> response
- move event generated from UI -> explanation returned to chat
- bridge-backed evaluation endpoints used by Go coach remain healthy
- future RAG path:
  - ChromaDB enabled
  - agent invokes retrieval
  - final response reflects retrieved coaching context

Recommended first end-to-end milestones:
- backend-only compose test for `/dashboard/chat` with live bridge + engine
- browserless UI contract test for move-triggered commentary
- later full browser integration if the app begins showing graph state and richer coaching panels

## Initial Setup Already Implemented

This repo already has the first round of agentic test scaffolding:

- Go agent helper setup:
  - [server/chess_coach/agents/test_helpers_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/test_helpers_test.go)
- agent behavior unit tests:
  - [server/chess_coach/agents/agent_behaviors_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/agent_behaviors_test.go)
- graph integration test:
  - [server/chess_coach/graph_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/graph_test.go)
- dashboard chat handler test:
  - [server/chess_coach/cmd/main_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/cmd/main_test.go)
- React chat contract test:
  - [client/Interface/src/components/ChatPanel.test.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/components/ChatPanel.test.tsx)

## Recommended Next Implementation Steps

1. Add `BridgeClient` contract tests with `httptest.Server`.
2. Add handler tests for `/coach/analyze`, `/coach/features`, and `/coach/classify-move`.
3. Add `App`-level React tests for move-triggered explanation flow.
4. Add pending or skipped graph tests that define expected RAG-agent integration behavior.
5. Wire at least one real RAG tool into `position_analyst` or `coach`, then promote the pending RAG integration tests to required tests.
6. If the main app is meant to expose agent state, wire `/dashboard/graph` or returned graph state into `AgentStateGraph`, then add UI tests around it.
  

