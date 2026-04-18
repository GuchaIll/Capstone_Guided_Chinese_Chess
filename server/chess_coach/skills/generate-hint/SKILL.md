---
name: generate-hint
description: >
  Generates a progressive hint for a xiangqi puzzle using engine features
  and coaching LLM. Use this skill when the user is stuck on a puzzle and
  asks for a hint, clue, or nudge without wanting the full answer.
  Triggers: "give me a hint", "I'm stuck", "clue", "help with this puzzle",
  hint_level provided.
---

# Generate Hint

## Overview

Combines the position's tactical features (hanging pieces, forks, pins,
cannon screens) with a shallow engine search to produce an encouraging hint
that guides the student without revealing the exact solution.

## Instructions

1. Requires `fen` in context state. Optionally `hint_level` (1=vague, 2=moderate,
   3=specific; default 1).
2. Pipeline:
   - **get_features** — `get_position_features` with
     `hanging_pieces, forks, pins, cannon_screens`.
   - **shallow_search** — `generate_hint` tool. Uses `Suggest()` for
     a lightweight best-move query.
   - **format_hint** — LLM step that crafts the hint using tactical features.
     If there's a hanging piece, hints about vulnerability. If there's a fork,
     hints about a multi-target attack. Does not reveal the exact move.
3. Progressive hints: level 1 = general area, level 2 = piece type + region,
   level 3 = partial move notation.

## Example

**User:** "I'm stuck, give me a hint" (hint_level 1)
→ Features: fork opportunity with Horse
→ LLM: "Look carefully at what your Horse can threaten — there might be more
  than one target!"

## Guidelines

- Never reveal the exact move at hint levels 1 or 2.
- Use tactical features to ground hints in real position data.
- Be encouraging — the goal is to help the student discover the answer.
