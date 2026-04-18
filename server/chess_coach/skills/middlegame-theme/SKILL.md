---
name: middlegame-theme
description: >
  Retrieves and summarizes middlegame themes and tactical patterns from the
  tactics knowledge base. Use this skill when the user asks about middlegame
  strategy, piece coordination, attacking plans, or pawn breaks.
  Triggers: "middlegame", "attacking plan", "piece coordination", "pawn break",
  "how to attack", "strategy in the middle".
---

# Middlegame Theme

## Overview

Queries the `tactics` RAG collection for middlegame strategic and tactical
content. An LLM synthesizes it into concrete advice about piece coordination,
pawn breaks, and attacking plans.

## Instructions

1. Requires `question` in context state.
2. Pipeline:
   - **retrieve_tactics** — RAG query against the `tactics` collection (top 5).
   - **summarize** — LLM formats into actionable middlegame advice: piece
     coordination, pawn breaks, attacking plans, and key principles.

## Example

**User:** "How should I attack in the middlegame with cannons?"
→ RAG retrieves: Cannon coordination patterns, double-cannon tactics
→ LLM: "Coordinate your Cannons on open files. The 'Double Cannon' formation
  creates threats along the bottom rank. Support with a Chariot on the same file."

## Guidelines

- Be specific about piece coordination and tactical patterns.
- Include concrete examples when the RAG context provides them.
- Distinguish between attacking and defensive middlegame themes.
