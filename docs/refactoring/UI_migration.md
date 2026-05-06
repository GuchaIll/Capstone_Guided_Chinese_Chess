# UI Migration Plan

This document tracks the Inkstone UI migration in the order we want to execute it:

1. Integrate the engine first for move generation, legal moves, and win/loss state.
2. Replace local hint generation with engine-backed suggestions.
3. Wire coaching into the rules/guidance side experience.
4. Replace local move state with engine-backed state once the UI is visually stable.
5. Replace placeholder guidance with agent-orchestrated LLM feedback.

The current visual source of truth is:

- [client/InkstoneInterface/src/App.tsx](../../client/InkstoneInterface/src/App.tsx)
- [client/InkstoneInterface/src/views/LandingPage.tsx](../../client/InkstoneInterface/src/views/LandingPage.tsx)

The current integration surfaces we will reattach incrementally are:

- [client/InkstoneInterface/src/services/bridgeClient.ts](../../client/InkstoneInterface/src/services/bridgeClient.ts)
- [client/InkstoneInterface/src/hooks/useWebSocket.ts](../../client/InkstoneInterface/src/hooks/useWebSocket.ts)
- [client/InkstoneInterface/src/hooks/useBridgeEventStream.ts](../../client/InkstoneInterface/src/hooks/useBridgeEventStream.ts)
- [client/InkstoneInterface/src/types/bridgeProtocol.ts](../../client/InkstoneInterface/src/types/bridgeProtocol.ts)
- [client/InkstoneInterface/src/components/ChatPanel.tsx](../../client/InkstoneInterface/src/components/ChatPanel.tsx)

## Phase 1: Engine-Backed Core Play

Goal: keep the current Remix-style Inkstone UI, but stop using local rules as the source of truth for move generation, legal moves, and terminal game state.

### Scope

Replace these local-only responsibilities in [client/InkstoneInterface/src/App.tsx](../../client/InkstoneInterface/src/App.tsx):

- local legal move generation via `getLegalMoves(...)`
- local move application into `board`
- local turn switching
- local win/loss state assumptions

Do not change yet:

- landing page
- board visuals and animations
- drag interactions
- rules panel UX
- guide panel UX

### Target Behavior

The UI should continue to look and feel the same, but:

- legal targets come from the engine/bridge
- completed moves are validated by the engine
- board state is refreshed from engine-backed FEN/state
- game end conditions come from engine/bridge result fields, not local inference

### Files to Introduce or Refactor

- `src/hooks/useInkstoneEngineGame.ts`
  - new orchestration hook for engine-backed board state
- `src/App.tsx`
  - keep presentation, remove local game truth
- `src/lib/xiangqiRules.ts`
  - keep only as temporary fallback during migration
- `src/services/bridgeClient.ts`
  - use existing BFF bridge routes
- `src/hooks/useWebSocket.ts`
  - use existing WS ticket flow
- `src/hooks/useBridgeEventStream.ts`
  - use SSE updates for state reconciliation
- `src/types/bridgeProtocol.ts`
  - consume `state`, `legal_moves`, `move_result`, `suggestion`, `ai_move`, and SSE move/state events

### Step-by-Step Plan

#### Step 1: Add board/FEN conversion helpers

Create an adapter that converts engine-backed state into the current UI board model used by `App.tsx`.

Needed helpers:

- `fenToInkstoneBoard(fen: string): Board`
- optional `inkstoneBoardToFen(...)` only if needed for temporary fallback/debugging
- `moveStringToSquares("b2e2") -> { from: [row, col], to: [row, col] }`

This should live in a small adapter module, for example:

- `src/utils/engineBoardAdapter.ts`

Acceptance:

- given an engine FEN, the current board UI can render the same position without changing the JSX layout

#### Step 2: Build `useInkstoneEngineGame`

Create a controller hook that owns:

- current FEN
- current UI board
- selected square
- legal moves for selected square
- current side to move
- game result
- hint state
- loading/error state for bridge failures

This hook should become the single place that talks to:

- `bridgeFetch`
- `useWebSocket`
- `useBridgeEventStream`

Acceptance:

- `App.tsx` reads game state from this hook instead of mutating local board state directly

#### Step 3: Replace local legal move generation

Current local path:

- selecting a piece
- calling `getLegalMoves(board, row, col)`

New path:

1. on select, map selected UI square to engine algebraic notation
2. send `select` through WS
3. wait for `legal_moves`
4. render returned legal targets in the existing ink-wash legal move UI

Acceptance:

- clicking a piece still shows the same legal target overlay
- targets are now driven by the engine

#### Step 4: Replace local move application

Current local path:

- local validation
- local board mutation
- local capture tally update
- local turn flip

New path:

1. on drop/click destination, send move intent through WS
2. wait for `move_result` or SSE `move_made`
3. rebuild board from returned FEN
4. trigger existing move/capture animation from the confirmed move
5. derive new turn from engine result/state

Important rule:

- do not permanently mutate the board before engine confirmation
- if desired, keep a temporary "pending move" animation layer later, but the committed board should remain engine-backed

Acceptance:

- illegal moves are rejected by the engine and do not corrupt local board state
- successful moves keep the same UI feel, but state comes from returned FEN

#### Step 5: Replace local win/loss conditions

Current local MVP does not have authoritative terminal-state handling.

New path:

- consume `result` from:
  - WS `state`
  - WS `move_result`
  - WS `ai_move`
  - SSE `fen_update` / `state_sync` / `move_made`

Normalize into:

- `in_progress`
- `red_wins`
- `black_wins`
- `draw`

Then drive:

- game-over overlay or modal
- disabling further move interaction
- end-of-game guidance later

Acceptance:

- checkmate/stalemate/terminal engine states are reflected in the UI without any local rule guesswork

#### Step 6: Keep local rules as temporary fallback only

[client/InkstoneInterface/src/lib/xiangqiRules.ts](../../client/InkstoneInterface/src/lib/xiangqiRules.ts) should remain temporarily for:

- offline fallback during migration
- non-blocking hint fallback if bridge suggestion fails

But it should no longer be the primary source for:

- legal moves
- move validity
- turn state
- game result

### Acceptance Criteria for Phase 1

- board visuals remain unchanged
- drag and click interactions still work
- legal move highlights are engine-backed
- moves are engine-validated
- board state is restored from engine FEN/state
- win/loss/draw comes from engine result fields
- local rules are no longer the main game authority

## Phase 2: Replace Local Hint Generation

Goal: keep the current `提示` UX, but replace local `getHintMove(...)` with engine-backed suggestion output.

### Plan

1. Reuse the engine controller hook from Phase 1.
2. On `提示`, send `suggest` through WS or use the bridge endpoint if that path is cleaner.
3. Consume `suggestion` from [src/types/bridgeProtocol.ts](../../client/InkstoneInterface/src/types/bridgeProtocol.ts).
4. Map returned algebraic squares into the current hint overlay format.
5. Keep local `getHintMove(...)` only as fallback during transition.

Acceptance:

- the hint overlay still animates exactly as it does now
- the move source is the engine, not local greedy rules

## Phase 3: Wire Coaching into Rules and Guidance Side Experience

Goal: use the existing coach service for contextual guidance, while keeping static piece rules deterministic.

### Rules Panel

Keep rules local and deterministic.

Do not LLM-generate piece movement rules.

Use the current static rule cards in `App.tsx` as the long-term behavior.

### Guide Panel

Replace placeholder guidance in [client/InkstoneInterface/src/App.tsx](../../client/InkstoneInterface/src/App.tsx):

- `PLACEHOLDER_STRATEGIES`
- `"AI-generated guidance (placeholder)"`

with coaching-backed guidance.

### Plan

1. Extract the guide panel into `src/components/GuidancePanel.tsx`.
2. Add a small `guidanceClient` or hook that reuses the same coach path pattern as [ChatPanel.tsx](../../client/InkstoneInterface/src/components/ChatPanel.tsx).
3. Pass:
   - current FEN
   - side to move
   - selected language
   - optional recent moves
4. Ask for a structured output matching the current UI:
   - title
   - short description
   - 2-4 move ideas
   - optional highlight sequences
5. Preserve placeholder strategies as fallback if the coach fails.

Acceptance:

- clicking `导引` shows position-aware guidance from the coaching service
- highlight buttons still illuminate the board squares using the current UI behavior

## Phase 4: Engine-Backed Full Move State

Goal: once the board is visually stable and hints/guidance are attached, fully remove the remaining local board authority.

### Plan

1. Remove local board mutation as the primary path.
2. Derive capture tally from move stream or board diff.
3. Drive turn indicator from engine state only.
4. Reconcile all board updates through:
   - WS command responses
   - SSE state syncs
5. Keep the current UI animation layers as presentation-only overlays on top of engine-backed truth.

Acceptance:

- a reload can restore the current game from bridge state
- UI and engine no longer drift apart

## Phase 5: Agent-Orchestrated LLM Guidance

Goal: replace the guide panel’s simple coached text with structured orchestrated feedback.

### Plan

1. Introduce a dedicated backend guidance route, for example `/api/coach/guidance`.
2. Combine:
   - engine suggestion
   - board features
   - move history
   - coaching persona/instruction
3. Return structured JSON rather than raw prose.
4. Render that JSON directly into the current guide panel layout.

Suggested response shape:

- `openingIdeas[]`
- `defensiveIdeas[]`
- `midgameIdeas[]`
- `recommendedLine[]`
- `highlightSquares[]`
- `summary`

Acceptance:

- the guide panel is no longer placeholder text
- guidance is position-specific and can drive board highlights directly

## Recommended Implementation Order

1. Engine-backed legal moves
2. Engine-backed move submission and board refresh
3. Engine-backed win/loss/draw handling
4. Engine-backed hint generation
5. Coaching-backed guide panel
6. Agent-orchestrated structured guidance

## Immediate Next Task

Start with the engine-backed move layer:

1. add `engineBoardAdapter.ts`
2. add `useInkstoneEngineGame.ts`
3. swap piece-selection legal move generation off `getLegalMoves(...)`
4. swap move commit flow off local board mutation
5. read terminal state from engine `result`

