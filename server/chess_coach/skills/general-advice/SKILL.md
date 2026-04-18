---
name: general-advice
description: >
  Retrieves and formats general xiangqi advice for beginners from the
  beginner_principles knowledge base. Use this skill for broad coaching
  questions that don't fit a specific analysis, tactic, or phase category.
  Triggers: "general advice", "tips", "how to improve", "what should I learn",
  "beginner tips", "common mistakes".
---

# General Advice

## Overview

Queries the `beginner_principles` RAG collection for fundamental chess
wisdom. An LLM formats it into clear, encouraging advice using simple
language and concrete examples.

## Instructions

1. Requires `question` in context state.
2. Pipeline:
   - **retrieve_principles** — RAG query against `beginner_principles` (top 5).
   - **format** — LLM produces friendly, encouraging advice in simple language
     with concrete examples from the retrieved principles.

## Example

**User:** "Any tips for a beginner?"
→ RAG retrieves: piece development, king safety, material counting
→ LLM: "Three key tips: 1) Develop your Chariots early — they're your strongest
  pieces. 2) Keep your General safe behind Advisors and Elephants.
  3) Don't trade pieces when you're ahead in material — simplify to win."

## Guidelines

- Use simple, beginner-friendly language.
- Be encouraging and constructive.
- Provide concrete, actionable advice (not abstract principles).
