---
name: detect-blunders
description: >
  Detects blunders in a move sequence using the engine's batch feature analysis
  with built-in move classification. Use this skill when the user asks to review
  a game, find mistakes, check for blunders, or analyze a sequence of moves.
  Triggers: "find blunders", "review my game", "what mistakes did I make",
  "check moves", move sequence provided.
---

# Detect Blunders

## Overview

Analyzes a sequence of moves via batch engine analysis. Each move is classified
(brilliant/good/inaccuracy/mistake/blunder) with centipawn loss and better
alternatives. An LLM step then explains each blunder constructively.

## Instructions

1. Requires `fen` (starting position) and `moves` (space-separated move sequence).
2. Pipeline:
   - **find_blunders** — `detect_blunders` tool. Uses `BatchAnalyze()` to classify
     every move in one engine call. Returns blunders with `category`, `centipawn_loss`,
     `score_delta`, and `alternatives`.
   - **explain_blunders** — LLM step that explains each blunder: why it's bad,
     what was better, and the positional consequence.
3. Blunders with centipawn loss exceeding the threshold (default 150) are flagged.
4. If blunders are found, sets `route_puzzle = true` for downstream puzzle generation.

## Example

**User:** "Review these moves from the starting position: h2e2 h9g7 h0g2 i9h9"

→ Batch analysis classifies each move → LLM explains:
> Move 3 (h0g2) is an inaccuracy (centipawn loss: 85). Moving the knight to g2
> blocks the chariot's development. Better: e0d1 (developing the advisor, score +12).

## Guidelines

- Use the engine's classification categories, not manual eval-delta heuristics.
- Always cite the better alternatives with their scores.
- Be constructive — frame blunders as learning opportunities.
