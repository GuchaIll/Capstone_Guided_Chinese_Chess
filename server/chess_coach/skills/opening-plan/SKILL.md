---
name: opening-plan
description: >
  Retrieves and summarizes opening plans from the openings knowledge base
  using RAG. Use this skill when the user asks about opening theory, first
  moves, development plans, or a specific opening system name.
  Triggers: "opening", "first moves", "how to start", "development plan",
  specific opening names (e.g., "Central Cannon", "Screen Horse Defence").
---

# Opening Plan

## Overview

Queries the `openings` RAG collection for relevant opening theory and
has an LLM synthesize it into an actionable plan with key moves, typical
pawn structures, and strategic ideas.

## Instructions

1. Requires `question` in context state (the user's opening query).
2. Pipeline:
   - **retrieve_openings** — RAG query against the `openings` collection (top 5).
   - **summarize** — LLM formats retrieved theory into a clear plan: key moves,
     pawn structures, strategic ideas, and common continuations.

## Example

**User:** "What's the plan for the Central Cannon opening?"
→ RAG retrieves: Central Cannon theory documents
→ LLM: "The Central Cannon aims to control the center file. Key moves: 1. C2=5...
  Typical structure: Cannon on e-file supported by Chariots on the flanks."

## Guidelines

- Always include specific move sequences when available.
- Mention both the plan's strengths and what the opponent typically does.
- Use piece full names for clarity (Chariot, Cannon, Horse, not C/R/H).
