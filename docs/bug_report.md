# Bug Report and Remediation

## Scope

This report tracks the current coaching, dashboard, and voice-control defects in the Xiangqi stack, with emphasis on the explanation path:

- React client
- Go `chess_coach`
- Go agent dashboard / observability
- voice / VAD / STT path

## 1. Excessive token counts and repeated long explanations

### Symptom

- Dashboard shows token totals growing by ~2500 per message even though LLM output is capped at 256 tokens.
- Coaching responses contain repeated RAG passages and very long raw knowledge dumps.

### Root cause

There were three separate issues:

1. Dashboard token totals are **prompt-size estimates**, not completion caps.
   - In [server/go_agent_framework/observability/llm.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/observability/llm.go), token counts are estimated from character length of the full prompt and completion.
   - `max_tokens=256` limits only completion length, not prompt size.

2. `/dashboard/chat` reused session state without clearing transient analysis fields.
   - Old `rag_context`, `engine_metrics`, `feedback`, `blunder_analysis`, and puzzle state could leak into later chat runs in the same `session_id`.

3. RAG text was injected too literally.
   - Multiple long retrieved chunks were appended into prompt/state.
   - Fast-path feedback rendered raw RAG text back to the user.

### Implemented fixes

Patched:

- [server/chess_coach/cmd/main.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/cmd/main.go)
  - added `resetTransientChatState(...)` before each `/dashboard/chat` graph run
  - preserves session continuity for `fen`/`move`, while clearing transient outputs

- [server/chess_coach/agents/rag_support.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/rag_support.go)
  - deduplicates repeated RAG chunks
  - caps retrieved text to 2 chunks
  - truncates stored RAG context to ~1200 chars

- [server/chess_coach/agents/coach.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/coach.go)
  - instructs LLM to keep advice under 100 words
  - explicitly forbids large knowledge-block quoting

- [server/chess_coach/agents/feedback.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/feedback.go)
  - no longer dumps raw full RAG passages in user feedback
  - now emits only a compact one-line guidance snippet on fast path
  - truncates approved coaching advice to 100 words

### Result

- repeated context accumulation is removed
- prompt size is materially reduced
- fast-path responses are shorter and safer
- dashboard token counters may still look “high” because they measure full prompt volume, but they should now drop significantly

### Follow-up recommendation

If exact token accounting is required, replace character-based estimation in
[server/go_agent_framework/observability/llm.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/observability/llm.go)
with provider-reported token usage when available.

## 2. Chat orchestration runs twice around turn handling

### Symptom

- A move explanation may be triggered more than expected around `End My Turn` and `End Engine's Turn`.

### Current understanding

The intended product behavior is:

1. one coaching run when the human commits their turn
2. one coaching run when the engine/opponent turn is acknowledged

The likely duplication risk comes from overlapping sources:

- bridge command responses
- bridge SSE `move_made` events
- client-side `sendMoveEvent(...)` calls

### Implemented fix

Patched:

- [client/Interface/src/App.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/App.tsx)
  - keeps deduping across bridge command WS and SSE via `lastAppliedMoveSignatureRef`
  - defers engine-move coaching until the player clicks `End Engine's Turn`
  - stores AI/opponent move commentary as a pending acknowledgement event instead of sending it immediately on arrival

- [client/Interface/src/App.test.tsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/App.test.tsx)
  - proves bridge AI move events do not trigger coaching before acknowledgement
  - proves command WS + SSE duplicates still produce only one coaching event after acknowledgement

### Result

- player move commentary still fires once on committed turn end
- engine move commentary now fires once on acknowledged turn end
- duplicate bridge command + SSE AI updates no longer create duplicate coaching messages

### Remaining work

- add an explicit regression for:
  - zero coaching calls for take-back
  - zero coaching calls for rejected second move

## 3. Explanations should stay under 320 words

### Requirement

- coaching output should be concise enough to avoid cognitive overload

### Implemented fix

Applied in:

- [server/chess_coach/agents/coach.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/coach.go)
- [server/chess_coach/agents/feedback.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/feedback.go)

### Additional hardening

Added regression coverage in:

- [server/chess_coach/agents/agent_behaviors_test.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/agent_behaviors_test.go)

That test now proves `FeedbackAgent` caps rendered coaching advice to 320 words.

### Remaining risk

This is still enforced primarily at render time.
For stronger guarantees, add a dedicated compression step before storing
`coaching_advice` in graph state.

## 4. Dashboard lacks clear fast-path / slow-path and tool-skill visibility

### Symptom

- current dashboard does not clearly show:
  - fast path vs slow path
  - which tools were used
  - which skills were used
  - whether RAG was used and from which collection

### Desired behavior

- visible boxes for active tool/skill usage
- 2-second delay to make transitions legible
- side log panel instead of chat panel
- explicit fast/slow track labeling
- explicit RAG collection labeling

### Implemented fix

Patched:

- [server/go_agent_framework/dashboard/src/App.jsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/dashboard/src/App.jsx)
  - tracks fast vs slow path from coach thought events
  - shows temporary tool/skill subprocess boxes for 2 seconds
  - annotates RAG tools with collection metadata

- [server/go_agent_framework/dashboard/src/AgentNode.jsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/dashboard/src/AgentNode.jsx)
  - renders fast/slow badges
  - renders temporary tool/skill boxes with description and collection

- [server/go_agent_framework/dashboard/src/ChatRoom.jsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/dashboard/src/ChatRoom.jsx)
  - replaced the side chat-room behavior with an execution-log panel
  - groups entries by agent state
  - lists tool usage, skill usage, thought messages, and RAG collection markers
  - now waits for the live SSE source to appear before subscribing, fixing the empty "Waiting for orchestration events" panel

- [server/chess_coach/agents/position_analyst.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/position_analyst.go)
  - reduced aggressive slow-path escalation
  - `tactical_pattern` now requires forks, pins, or at least two hanging pieces instead of any single tactical hint

### Result

- dashboard now distinguishes fast vs slow track
- active tool/skill usage is visible on the graph
- side panel is now oriented toward execution debugging rather than chat
- execution log now renders as a continuous chronological stream instead of grouped state cards
- fast path is more likely to remain visible instead of being constantly upgraded to slow path

### Remaining work

- add dashboard UI tests for:
  - fast-path badge rendering
  - slow-path badge rendering
  - transient tool box appearance
  - log-panel RAG collection display
- decide whether the dashboard should keep a separate manual chat trigger elsewhere

## 5. Microphone / VAD / STT instability

### Symptom

- mic button flashes on/off
- VAD does not reliably pick up wake word
- STT does not transcribe reliably

### Implemented fix

Patched:

- [client/Interface/src/hooks/useChessVoiceCommands.ts](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/client/Interface/src/hooks/useChessVoiceCommands.ts)
  - requests microphone permission up front before starting wake-word detection
  - tracks whether speech recognition is already running to avoid restart churn
  - handles `not-allowed`, `service-not-allowed`, and `audio-capture` by cleanly resetting to idle
  - treats `processing` as an active listening state so the mic button no longer flashes off between wakeword detection and send

### Result

- microphone state is more stable
- wake-word detection is less likely to thrash on repeated restarts
- STT failures now surface clearer idle/error transitions instead of silent flicker

### Remaining work

1. add a visible voice debug panel for:
   - mic permission
   - recognition running
   - wake-word detected
   - STT request pending / failed
2. add component tests around voice-state transitions
3. tune wake-word mis-transcription patterns and timeout windows with live browser testing

## 6. Slow path lock-in, repeated mock advice, and missing blunder/puzzle escalation

### Symptom

- move commentary requests were staying on the fast path
- when slow path did run under mock LLMs, advice could still collapse into repetitive generic text
- hanging-piece positions could still show `detect_blunders -> no blunders`
- `puzzle_curator` was skipped on blunder turns because `blunder_abort` prevented it from running

### Root cause

There were four linked issues:

1. `OrchestratorAgent` only escalated slow-path coaching on move-count or score-shift triggers.
   - explicit requests like `Comment on this move` or `Why was this good?` were not treated as coaching intents

2. `PositionAnalystAgent` had become too conservative.
   - a single hanging piece no longer counted as a tactical escalation signal

3. `BlunderDetectionAgent` relied too heavily on batch engine classification.
   - if the engine did not classify the move as a blunder, there was no fallback using tactical-pattern evidence already available from the position

4. `PuzzleCuratorAgent` skipped whenever `blunder_abort=true`.
   - that prevented follow-up puzzle generation exactly on the turns where a teaching puzzle was most useful

### Implemented fix

Patched:

- [server/chess_coach/agents/orchestrator.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/orchestrator.go)
  - explicit move-commentary and explanation-style requests now force `coach_trigger=explicit`

- [server/chess_coach/agents/position_analyst.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/position_analyst.go)
  - a single hanging piece now counts as a tactical escalation signal again

- [server/chess_coach/agents/coach.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/coach.go)
  - when the runtime LLM is the instrumented mock provider, the coach now emits a deterministic, state-driven explanation instead of the same canned sentence
  - fallback advice now references engine score, best move, tactical warnings, and summarized knowledge guidance

- [server/go_agent_framework/observability/llm.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/observability/llm.go)
  - instrumented LLM wrappers now expose provider/model metadata, so the coach can detect mock mode safely

- [server/chess_coach/agents/blunder_detection.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/blunder_detection.go)
  - added fallback blunder synthesis from `get_tactical_patterns`
  - hanging pieces, forks, and pins can now trigger blunder handling even when `detect_blunders` returns empty

- [server/chess_coach/agents/puzzle_curator.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/agents/puzzle_curator.go)
  - now generates a follow-up puzzle even on blunder-abort turns, as long as `route_puzzle=true`

- [server/go_agent_framework/dashboard/src/ChatRoom.jsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/dashboard/src/ChatRoom.jsx)
  - execution log now renders event-by-event streaming lines instead of grouped agent-state blocks

- [server/go_agent_framework/dashboard/src/App.jsx](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/go_agent_framework/dashboard/src/App.jsx)
  - pipeline-track state is now updated immediately, reducing badge races between coach thought events and `agent_end`

### Result

- move commentary requests can reach the slow path again
- mock-mode coaching is no longer a single repeated canned answer
- hanging-piece positions now have a tactical fallback into blunder handling
- follow-up puzzle generation runs on blunder turns
- dashboard execution logs read like a live stream instead of per-agent state cards

## Verification

Verified after the patch:

```bash
cd server/chess_coach && GOCACHE=/tmp/go-build-chess-coach go test ./...
```

Result:

- `ok chess_coach`
- `ok chess_coach/agents`
- `ok chess_coach/cmd`
- `ok chess_coach/engine`
- `ok chess_coach/tools`

## Summary

Shipped now:

- transient chat-state reset
- RAG dedupe + truncation
- concise coach prompt
- concise user-facing feedback rendering

Still pending:

- take-back / rejected-move orchestration regression tests
- dashboard UI test coverage
- deeper live-browser tuning for microphone / VAD / STT

6.Execution Log is empty and displays wiating for orechestration events
increase the token limit to 320 words, slow track is always run, it does not appear that the engine is running fast track
