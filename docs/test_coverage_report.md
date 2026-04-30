# Test Coverage Report — Guided Chinese Chess

**Run date:** 2026-04-29
**Branch:** `main`
**Scope:** unit + integration test suites across Python, Go, Rust, and React

---

## 1. Headline numbers

| Suite | Language | Tests run | Pass | Fail / Error | Line / Statement coverage |
|---|---|---:|---:|---:|---:|
| `server/state_bridge/tests` | Python | 47 | 36 | 1 fail, 10 errors† | **63%** |
| `server/agent_orchestration/tests` | Python | 65 | 65 | 0 | **39%** |
| `integration_tests/` (compose-backed) | Python | 15 | 14 | 1 error | n/a (process-level)‡ |
| `server/chess_coach` | Go | 35 | 35 | 0 | **29.1%** |
| `server/go_agent_framework` | Go | 75 | 75 | 0 | **21.5%** |
| `Engine` (Rust) | Rust | 109 | 97 | 4 fail, 8 ignored | not measured§ |
| `client/Interface` (Vitest) | TS / React | 15 | 14 | 1 fail | **7.0%** statements (7.0% lines, 38.9% funcs, 60.2% branches) |

† `test_engine_relay.py` errors are infra-side: `websockets` 14.x removed `ping_interval` from `serve()`, breaking the in-test relay fixture. Tests do not assert against any of the bridge code paths now blocked from running.
‡ Python integration suite drives the live Docker compose stack; `pytest --cov` is intentionally not enabled because the code under test executes in containers, not the test process. One scenario reset failure recorded below.
§ Rust `cargo test` produces no built-in coverage. Add `cargo-llvm-cov` or `cargo-tarpaulin` if a percentage is required.

---

## 2. Python — `server/state_bridge`

Command:

```bash
python -m pytest -c server/state_bridge/pytest.ini server/state_bridge/tests \
  --cov=server/state_bridge --cov-report=term
```

| Module | Stmts | Miss | Cover |
|---|---:|---:|---:|
| `app.py` | 502 | 159 | **68%** |
| `cv_validation.py` | 74 | 8 | **89%** |
| `engine_relay.py` | 317 | 221 | **30%** |
| `events.py` | 68 | 5 | **93%** |
| `state.py` | 66 | 0 | **100%** |
| `_smoke_test.py` | 130 | 130 | 0% (manual smoke script — not under unit test) |
| **Package total (incl. tests)** | **1923** | **712** | **63%** |

Test results: **36 passed, 1 failed, 10 errors** in 20.8s.

- **Failure** — `test_engine_reset_restores_starting_state_and_emits_game_reset`: relay now calls `reset_and_wait(...)` instead of `reset(...)`; assertion on `relay.calls` is stale. Code change vs. test drift, not a regression of bridge contract.
- **Errors (10)** — all in `test_engine_relay.py`, traced to `websockets.serve(..., ping_interval=...)` in the test fixture; the installed `websockets` 14.2 dropped that kwarg. These tests never started, so the engine_relay coverage of 30% reflects only the indirect coverage from the contract suite.

---

## 3. Python — `server/agent_orchestration`

Command:

```bash
python -m pytest -c server/pytest.ini agent_orchestration/tests
```

`pytest.ini` enforces `--cov=agent_orchestration --cov=app --cov-fail-under=75`. Current run is **below the threshold**.

| Top modules under test | Stmts | Miss | Cover |
|---|---:|---:|---:|
| `agents/intent_classifier.py` | 41 | 3 | **93%** |
| `agents/token_limiter_agent.py` | 110 | 3 | **97%** |
| `agents/base_agent.py` | 70 | 8 | **89%** |
| `services/session_state.py` | 72 | 6 | **92%** |
| `services/state_tracker.py` | 91 | 21 | **77%** |
| `agents/onboarding_agent.py` | 57 | 10 | **82%** |
| `agents/retrieval_request.py` | 35 | 7 | **80%** |
| `agents/rag_manager_agent.py` | 91 | 32 | **65%** |
| `agents/coach_agent.py` | 136 | 54 | **60%** |
| `agents/output_agent.py` | 81 | 33 | **59%** |
| `agents/memory_agent.py` | 159 | 70 | **56%** |
| `agents/puzzle_master_agent.py` | 119 | 69 | **42%** |
| `agents/game_engine_agent.py` | 98 | 65 | **34%** |
| `services/orchestrator.py` | 354 | 262 | **26%** |
| `tools/llm_client.py` | 141 | 124 | **12%** |
| `tools/rag_retriever.py` | 126 | 107 | **15%** |
| `tools/engine_client.py` | 115 | 92 | **20%** |
| `LLM/prompts.py` | 119 | 105 | **12%** |
| `Inference/pipeline.py` | 103 | 103 | **0%** |
| `cli.py` / `__main__.py` | 167 | 167 | **0%** (entrypoints) |
| `tools/preprocess_commentary.py` | 269 | 269 | **0%** (data tooling) |
| `tools/generate_training_data.py` | 336 | 336 | **0%** (data tooling) |
| **Total** | **3486** | **2110** | **39.47%** |

Test results: **65 passed** in 4.0s. Coverage gate (`--cov-fail-under=75`) **fails**.

Most of the deficit lives in three areas:
1. **Service layer** — `orchestrator.py` exercises the LLM-in-the-loop chat and proactive flows, neither of which is reachable without the live Go coaching and LLM clients.
2. **Tooling/inference** — `Inference/pipeline.py`, `tools/llm_client.py`, `tools/rag_retriever.py`, `tools/engine_client.py` are network/RAG adapters with no in-process test fakes.
3. **Data/bootstrap scripts** — `cli.py`, `preprocess_commentary.py`, `generate_training_data.py`. These are operator tools and a likely candidate for explicit coverage exclusion rather than added tests.

The whole `agent_orchestration` package is also flagged by deprecation warnings indicating intended migration to the Go coaching service; adjust the gate scope accordingly.

---

## 4. Python — `integration_tests/`

Command:

```bash
python -m pytest -c integration_tests/pytest.ini integration_tests -q
```

Test results: **14 passed, 1 error** in 52.8s.

- The one error is in `test_bridge_select_flow_emits_piece_selected_for_led_overlay` — bridge state did not return to the starting FEN within the polling window after `/engine/reset`. Looks like residual state bleed from the prior scenario rather than a regression in the select flow itself.
- Suite drives the running Docker stack (state-bridge, engine, coaching). Process-level coverage is not collected here because the code under test runs out-of-process; rely on the unit suites for line coverage.

Covered scenarios (per `docs/state_bridge_test_report.md`): bridge REST contracts, SSE ordering, CV-driven physical-board success and failure flows, engine relay round-trip, LED bridge subscriber HTTP adapter, Go coaching `/coach/features`, `/coach/classify-move`, `/dashboard/chat`, Python coaching `/health`, `/agents`, `/agent-state/graph`.

---

## 5. Go — `server/chess_coach`

Command:

```bash
GOCACHE=/tmp/go-build-chess-coach go test -coverprofile=/tmp/coach_cov.out ./...
```

| Package | Tests | Coverage |
|---|---:|---:|
| `chess_coach` (root: graph wiring) | 9 | **4.3%** |
| `chess_coach/agents` | 9 | **48.2%** |
| `chess_coach/cmd` | 5 | **31.0%** |
| `chess_coach/engine` | 3 | **64.8%** |
| `chess_coach/tools` | 9 | **8.7%** |
| **Module total** | **35** | **29.1%** |

All 35 tests pass. Hot spots:
- `chess_coach` root coverage is low because `graph.go` is mostly compile-time wiring; runtime coverage is exercised through `cmd` handlers.
- `tools/` (puzzle, PGN, visualization, ChromaDB retriever) is dominated by network-bound adapters with little in-process test fakes — only `rag_tools.go` and a couple of helpers are exercised.

---

## 6. Go — `server/go_agent_framework`

Command:

```bash
GOCACHE=/tmp/go-build-goaf go test -coverprofile=/tmp/goaf_cov.out ./...
```

| Package | Tests | Coverage |
|---|---:|---:|
| `contrib/cache` | 4 | **100.0%** |
| `contrib/llm` | 1 | 2.3% (`mock.go` only) |
| `contrib/queue` | 2 | 32.7% |
| `contrib/vector` | 5 | **100.0%** |
| `core` | 38 | **51.2%** |
| `observability` | 25 | 29.8% |
| `contrib/embedding`, `contrib/envutil`, `contrib/skills`, `contrib/store`, `contrib/tools`, `examples/*` | 0 | 0% |
| **Module total** | **75** | **21.5%** |

The dilution to 21.5% is driven entirely by the `examples/` and unused `contrib/*` directories. Excluding `examples/...` from the profile (`go test ./core/... ./contrib/cache ./contrib/queue ./contrib/vector ./contrib/llm ./observability`) puts the meaningful surface near 50%+.

---

## 7. Rust — `Engine`

Command:

```bash
cd Engine && cargo test
```

Test results: **97 passed, 4 failed, 8 ignored** (109 declared).

By file (declared `#[test]` count):

| File | Tests |
|---|---:|
| `src/Game.rs` | 15 |
| `src/GameState.rs` | 16 |
| `src/api.rs` | 2 |
| `src/session.rs` | 4 |
| `src/AI/AlphaBetaMinMax.rs` | 43 |
| `src/AI/feature_extractor.rs` | 4 |
| `src/AI/position_analyzer.rs` | 8 |
| `src/AI/piece_square_tables.rs` | 7 |
| `src/AI/explainability_gen.rs` | 4 |
| `src/AI/puzzle_detector.rs` | 5 |

Failing tests (need attention):
- `AI::puzzle_detector::tests::test_detect_starting_position` — starting position scored 100, expected non-puzzle-worthy. Looks like a heuristic regression after recent puzzle-detector changes.
- `GameState::tests::test_game_state_fullmove_counter` — fullmove counter off by one.
- `GameState::tests::test_game_state_halfmove_clock_reset_on_capture` — halfmove clock not reset to 0 on capture.
- `GameState::tests::test_game_state_captured_pieces` — captured-piece tracking returned empty list.

Line-coverage % is not currently produced by `cargo test`. To add it: `cargo install cargo-llvm-cov && cargo llvm-cov --html`.

---

## 8. React — `client/Interface`

Command:

```bash
cd client/Interface && npm test -- --coverage
```

Test results: **14 passed, 1 failed** (15 total in 3 files).

- `src/utils/fenMoveDiff.test.ts`: 5/5 passed.
- `src/components/ChatPanel.test.tsx`: 3/3 passed.
- `src/App.test.tsx`: 6/7 passed; one assertion times out waiting for `/cv unavailable; engine move acknowledged/` text. Likely a timing/contract drift between the test mock and the current `App.tsx` failure-flow rendering.

Coverage (passing files only — vitest does not produce a coverage report when any test fails on the same run, so the App.tsx execution paths exercised by the failing run are excluded below):

| Area | Stmts | Lines | Funcs | Branches |
|---|---:|---:|---:|---:|
| `src/utils/fenMoveDiff.ts` | **89.2%** | 89.2% | 100% | 74.4% |
| `src/components/ChatPanel.tsx` | **57.0%** | 57.0% | 71.4% | 65.6% |
| `src/types/index.ts` | 71.4% | 71.4% | 0% | 100% |
| `src/App.tsx` | 0% | 0% | 0% | 0% |
| `src/components/{AgentNode,AgentStateGraph,ChessBoard,FlipTurnButton,GameInfo,GameOverModal,Piece,VoiceControl}.tsx` | 0% | 0% | 0% | 0% |
| `src/hooks/{useGameState,useVoiceCommands,useWebSocket}.ts` | 0% | 0% | 0% | 0% |
| `src/pages/{AgentsPage,HardwarePage}.tsx` | 0% | 0% | 0% | 0% |
| `src/services/speech/SpeechService.ts` | 0% | — | 100% | 100% |
| **All files (passing run)** | **7.0%** | **7.0%** | **38.9%** | **60.2%** |
| Totals | 269 / 3837 stmts | — | 14 / 36 funcs | 56 / 93 branches |

Two clear gaps:
- The bulk of the UI (board, hooks, agent dashboard, hardware page, voice control) has no Vitest coverage.
- Once `App.test.tsx` is fixed, the App-level integration test will lift `App.tsx` and indirectly the components/hooks it renders, materially raising the floor.

---

## 9. Cross-suite gaps (not run by any CI gate above)

Test files present but not wired into the documented suites in `docs/test_suites.md`:

| File | Notes |
|---|---|
| `cv/board_pipeline_*.py` | No automated CV tests. Validation is the manual checklist in `docs/test_strategy.md` §5. |
| `ledsystem/test_led_board.py`, `ledsystem/test_manual.py` | Hardware-in-the-loop, run on the Pi only. |
| `server/web_scraper/test_dhtmlxq_parser.py` | Standalone parser test, not in any pytest config. |
| `finetunning/test_strategy_dictionary_*.py` | Fine-tuning helpers, runnable but not gated. |
| `Kibo/`, `chess_coach/` (top-level Rust dir) | No automated tests. |

Folding these into `docs/test_suites.md` would close the audit gap.

---

## 10. Action items, ranked

1. **Fix the four Rust failures in `Engine/src/{GameState,puzzle_detector}.rs`** — these block the engine `cargo test` gate.
2. **Restore `server/state_bridge` engine_relay tests.** Pin `websockets<14` in the test environment, or update the test fixture to drop the `ping_interval=` kwarg.
3. **Patch `App.test.tsx` CV-failure assertion** to match the current "engine move acknowledged" copy. That single fix unblocks the React coverage from 7% → ~40%+ since the App test exercises the full game loop.
4. **Lift the `agent_orchestration` coverage gate or shrink its scope.** The current `--cov-fail-under=75` will keep failing until either `Inference/pipeline.py` is covered or `cli.py` / `tools/preprocess_commentary.py` / `tools/generate_training_data.py` are excluded with `[tool.coverage.run] omit = …`.
5. **Tighten the Go framework coverage view** by excluding `examples/...` from the default profile so the published number reflects the runtime surface.
6. **Adopt `cargo-llvm-cov`** for the Rust engine so all four suites carry an actual %.
7. **Stabilize integration `select` flow** — investigate why `/engine/reset` doesn't restore the starting FEN in time after the prior scenario; likely a teardown ordering bug rather than a select-flow bug.
