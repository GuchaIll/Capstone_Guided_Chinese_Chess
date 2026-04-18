---
name: get-best-move
description: >
  Quick engine recommendation for the best move at limited depth.
  Use this skill when the user asks "what should I play", "best move",
  "what's the engine suggestion", or wants a fast recommendation without
  full analysis.
  Triggers: "best move", "what to play", "suggest a move", "engine recommendation".
---

# Get Best Move

## Overview

Runs a shallow engine analysis (depth 10) to quickly return the recommended
best move for the current position. Lightweight alternative to full
`evaluate_position` when only the move suggestion is needed.

## Instructions

1. Requires `fen` in context state.
2. Single step: `analyze_position` tool at depth 10.
3. Returns the engine's best move and evaluation score.

## Example

**User:** "What should Red play here?"
→ Engine at depth 10: best move h2e2, score +35.

## Guidelines

- Use this for quick suggestions, not deep analysis.
- For detailed assessments, use `evaluate_position` instead.
- The shallow depth means the suggestion may differ from deeper analysis.
