# RAG Implementation for Live Chess Coach Explanations

This document translates the RAG design into the current
`server/chess_coach` architecture and closes the gap where RAG tools were
registered but not actually invoked by the live explanation agents.

## Goal

Make retrieval part of the real explanation path, not just the tool layer.

After this implementation:
- `position_analyst` retrieves phase-specific knowledge during analysis
- `puzzle_curator` retrieves puzzle-objective guidance when a puzzle is generated
- `coach` retrieves general/tactical guidance and injects retrieved text into the LLM prompt
- `feedback` surfaces retrieved guidance on the fast path when no LLM coaching runs

## Canonical Collection Mapping

The product-level design talks about:
- `openings`
- `midgame`
- `endgame`
- `principles`

The current populated and code-level collection names remain:
- `openings`
- `tactics`
- `endgames`
- `beginner_principles`

Use this mapping:

| Conceptual name | Runtime collection |
|---|---|
| opening | `openings` |
| midgame | `tactics` |
| endgame | `endgames` |
| principles | `beginner_principles` |

This keeps the runtime aligned with:
- [server/chess_coach/tools/rag_tools.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/rag_tools.go)
- [server/chess_coach/tools/chromadb_retriever.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/chromadb_retriever.go)
- [server/web_scraper/knowledge/json/knowledge_base.json](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/web_scraper/knowledge/json/knowledge_base.json)

## Live Invocation Plan

### 1. PositionAnalystAgent

Purpose:
- retrieve phase-specific guidance during normal position analysis

Invocation rules:
- opening phase -> `get_opening_plan`
- middlegame phase -> `get_middlegame_theme`
- endgame phase -> `get_endgame_principle`

Query strategy:
- opening: question + best move + opening principles keywords
- middlegame: question + tactical features like forks, pins, hanging pieces
- endgame: question + material balance + endgame keywords

State written:
- `rag_context[opening|middlegame|endgame]`
- `rag_queries[opening|middlegame|endgame]`

### 2. PuzzleCuratorAgent

Purpose:
- retrieve explanatory guidance for generated puzzles

Invocation rule:
- if puzzle generation succeeds and `explain_puzzle_objective` exists, call it

Query strategy:
- puzzle themes + tactical motifs + starting FEN context

State written:
- `rag_context["puzzle"]`
- `rag_queries["puzzle"]`

### 3. CoachAgent

Purpose:
- enrich the slow-path prompt with both previously retrieved context and
  additional direct retrieval

Invocation rules:
- question-only or general advice request -> `get_general_advice`
- move-specific explanation request -> `explain_tactic`

Prompt injection:
- all stored `rag_context` sections are appended to the prompt before the final
  generation request

### 4. FeedbackAgent

Purpose:
- keep the fast path retrieval-augmented even when the LLM is skipped

Behavior:
- if approved `coaching_advice` is absent, emit retrieved `rag_context` as a
  `Knowledge guidance` section
- if approved coaching exists, rely on the coach prompt to absorb the RAG text
  and avoid noisy duplication

## State Contract

The shared graph state stores retrieval output in:

- `rag_context`
  - `map[string]map[string]interface{}`
  - section -> `{ tool, query, text }`
- `rag_queries`
  - `map[string]string`
  - section -> query string

Example:

```json
{
  "rag_context": {
    "opening": {
      "tool": "get_opening_plan",
      "query": "opening principles develop pieces control the center",
      "text": "Things to do: Try to move your major pieces..."
    },
    "tactic": {
      "tool": "explain_tactic",
      "query": "Why is b0c2 strong? b0c2",
      "text": "Context:\nControl the center..."
    }
  }
}
```

## Testing Strategy

### 1. Agent/Graph Integration with Real Corpus

Use the real
[server/web_scraper/knowledge/json/knowledge_base.json](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/web_scraper/knowledge/json/knowledge_base.json)
as the retrieval corpus in tests instead of mocked chunk strings.

That gives us:
- real collection boundaries
- real source text
- real tool execution
- deterministic offline tests

### 2. What the integration tests must prove

Fast path:
- graph runs without LLM coaching
- `position_analyst` invokes a live RAG tool
- `feedback` contains retrieved guidance from the real corpus

Slow path:
- graph invokes the coach LLM
- the LLM prompt includes retrieved RAG text from the real corpus

Puzzle path:
- `puzzle_curator` can populate `rag_context["puzzle"]`

### 3. Why not depend on live ChromaDB in unit/integration tests

The runtime system uses live ChromaDB through `CHROMADB_URL`, but local loopback
HTTP is not always available in constrained test environments.

Therefore:
- production path = real ChromaDB retrievers
- automated integration tests = real corpus + real RAG tools + offline retriever

This still tests agent-to-RAG integration without reducing the suite to mocks.

## Implementation Summary

1. Add shared RAG helper functions for agents.
2. Invoke RAG tools from `position_analyst`.
3. Invoke RAG tools from `coach`.
4. Invoke puzzle-objective retrieval from `puzzle_curator`.
5. Inject retrieved text into the coach prompt.
6. Surface retrieved guidance in `feedback` on fast-path runs.
7. Add real-corpus integration tests.
