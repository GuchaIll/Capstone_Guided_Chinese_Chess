---
name: explain-move
description: >
  Classifies and explains a specific move using engine feature analysis.
  Use this skill when the user asks "was this move good?", "explain this move",
  "why is X better than Y", or provides a FEN + move and wants feedback.
  Triggers: "explain move", "was this good", "why is this bad", "rate my move",
  specific move provided with a position.
---

# Explain Move

## Overview

Uses the engine's `classify_move` tool to get a move's classification
(brilliant/good/inaccuracy/mistake/blunder), centipawn loss, and better
alternatives. Adds positional context via `get_position_features`, then
an LLM explains the move quality educationally.

## Instructions

1. Requires `fen` and `move` in context state.
2. Pipeline:
   - **classify** — `classify_move` tool. Returns classification category,
     centipawn loss, and top alternative moves with scores.
   - **get_context** — `get_position_features` with `material, hanging_pieces,
     forks, pins` to provide tactical context.
   - **explain** — LLM step covering: was the move good/bad (using classification),
     better alternatives (with scores), and the tactical context that made
     this move important.
3. Output is the LLM's educational explanation.

## Example

**User:** "Was h2e2 a good move in this position?"

→ Engine classifies: inaccuracy (centipawn loss: 45)
→ Alternatives: c0e2 (+15), a0a1 (+8)
→ LLM: "Moving Cannon from h2 to e2 is a slight inaccuracy. While it centralizes
  the Cannon, it blocks the Elephant's development. Better was c0e2, developing
  the Elephant to protect the General."

## Guidelines

- Always state the classification category explicitly.
- For bad moves, always cite at least one better alternative with its score.
- Relate the explanation to the position's tactical features when relevant.
