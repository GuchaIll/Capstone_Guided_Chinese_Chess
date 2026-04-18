---
name: endgame-principle
description: >
  Retrieves and summarizes endgame principles and techniques from the
  endgames knowledge base. Use this skill when the user asks about endgame
  play, king activity, pawn promotion, or piece coordination in simplified
  positions.
  Triggers: "endgame", "few pieces left", "how to win this ending",
  "pawn promotion", "king activity", "Chariot vs Horse endgame".
---

# Endgame Principle

## Overview

Queries the `endgames` RAG collection for endgame principles. An LLM
explains king activity, pawn promotion paths, piece coordination, and
winning techniques in simplified positions.

## Instructions

1. Requires `question` in context state.
2. Pipeline:
   - **retrieve_endgames** — RAG query against the `endgames` collection (top 5).
   - **summarize** — LLM explains relevant endgame principles: king activity,
     promotion paths, piece coordination, and concrete winning techniques.

## Example

**User:** "How do I win with a Chariot against a Horse?"
→ RAG retrieves: Chariot vs Horse endgame theory
→ LLM: "The Chariot is stronger than the Horse in open positions. Push the
  opponent's General to the edge, then use your Chariot to cut off escape squares."

## Guidelines

- Cover king (General) activity as a priority — it's critical in xiangqi endgames.
- Explain specific piece matchups when asked (Chariot vs Horse, Cannon vs Horse, etc.).
- Include concrete piece placement advice, not just principles.
