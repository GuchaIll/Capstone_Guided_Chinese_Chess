---
name: explain-tactic
description: >
  Explains a tactical concept using RAG context and move validation.
  Use this skill when the user asks "what is a fork", "explain this pin",
  "how does a cannon screen work", or wants a concept explained with
  a concrete position example.
  Triggers: "explain tactic", "what is a fork", "how does a pin work",
  "cannon screen explained", tactical concept name + position.
---

# Explain Tactic

## Overview

Combines RAG-retrieved tactical knowledge with move validation to explain
why a specific tactic works, what the threat is, and how to recognize
similar patterns in future games.

## Instructions

1. Requires `question` in context state. Optionally `fen` and `move` for
   position-specific validation.
2. Pipeline:
   - **retrieve_context** — RAG query against `beginner_principles` (top 3).
   - **validate_move** — `validate_move_legality` tool. Confirms the discussed
     move is legal in the position (if FEN and move provided).
   - **explain** — LLM uses retrieved context and move analysis to explain
     why the tactic works, what the concrete threat is, and how to recognize
     similar patterns.

## Example

**User:** "Explain why h7e7 is a fork in this position."
→ RAG retrieves: fork definition, Horse fork patterns
→ Move validated as legal
→ LLM: "H7e7 moves the Horse to e7, where it simultaneously attacks the
  General on e9 and the Chariot on c6. This is a knight fork — the opponent
  can only save one piece."

## Guidelines

- Always explain the mechanism of the tactic, not just the name.
- If a position is provided, validate the move first.
- Show how to recognize similar patterns in future games.
