---
name: find-tactical-motif
description: >
  Detects tactical motifs (forks, pins, cannon screens, hanging pieces) in a
  position using the engine's feature extraction. Use this skill when the user
  asks about tactics, threats, patterns, or "what can I exploit" in a position.
  Triggers: "find tactics", "any threats", "tactical motifs", "what patterns",
  "is there a fork", "cannon screen".
---

# Find Tactical Motif

## Overview

Uses the engine's position analysis to identify concrete tactical patterns:
forks (with attacker type and targets), pins (pinner, pinned piece, pinned-to),
cannon screens (with target pieces), and hanging pieces. An LLM step describes
each pattern and how to exploit or defend.

## Instructions

1. Requires `fen` in context state.
2. Pipeline:
   - **get_patterns** — `get_tactical_patterns` tool. Returns structured data:
     forks, pins, cannon_screens, hanging_pieces, and `has_tactics` boolean.
   - **detect_motifs** — `find_tactical_motif` tool. Augments with PV and
     best-move context from the engine.
   - **describe_motifs** — LLM step that describes each pattern: pieces involved,
     squares, the concrete threat, and exploitation/defense advice.
3. Results stored in `ctx.State["tactical_motifs"]` and `ctx.State["tactical_patterns"]`.

## Example

**User:** "Are there any tactical patterns in this position?"

→ Engine finds: fork (Horse at e5 attacks General and Chariot), hanging Cannon at c7.
→ LLM: "Red can play Horse to e5, forking the Black General on e9 and the
  Chariot on g4. Also, the Black Cannon on c7 is undefended — consider capturing it."

## Guidelines

- Name the specific pattern type (fork, pin, cannon screen, hanging piece).
- Always cite the pieces and squares involved.
- If `has_tactics` is false, report "positional" and suggest strategic ideas instead.
