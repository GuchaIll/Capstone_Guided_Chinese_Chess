---
name: evaluate-position
description: >
  Full position evaluation using the xiangqi engine's feature extraction pipeline.
  Use this skill when the user asks to evaluate, assess, or analyze a board position.
  Triggers: "evaluate", "assess", "what's the position like", "who is better",
  "analyze position", FEN string provided without a specific move question.
---

# Evaluate Position

## Overview

Runs the engine's deep analysis on a FEN position, extracts structured features
(material, mobility, king safety, hanging pieces, forks, pins, cannon screens),
and produces a natural-language coaching assessment via LLM.

## Instructions

1. Requires `fen` in context state. Optionally accepts `depth` (default 20).
2. Pipeline:
   - **run_analysis** — `analyze_position` tool at the specified depth.
   - **get_features** — `get_position_features` tool with sections:
     `material, mobility, king_safety, hanging_pieces, forks, pins, cannon_screens`.
   - **interpret** — LLM step that synthesizes a structured assessment covering
     material balance, king safety, tactical threats, mobility, and a recommended plan.
3. Output is stored in `ctx.State["engine_metrics"]` (raw) and the LLM assessment
   is returned as the skill result.

## Example

**User:** "Evaluate this position: rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

→ Runs engine analysis → Extracts features → LLM produces:
> Material is equal. Both kings are safely behind their advisors and elephants.
> No hanging pieces or active tactical threats. Red has slightly better mobility
> due to centralized cannons. Recommended plan: develop chariots to open files.

## Guidelines

- Always reference specific pieces and squares from the feature data.
- Cover all five assessment areas: material, king safety, threats, mobility, plan.
- If the engine returns a checkmate or stalemate flag, lead with that.
