---
name: beginner-coaching
description: >
  Formats coaching advice for beginner-level students. This is a presentation
  skill, not an analysis skill — it controls how output is worded.
  Use this skill whenever the user is identified as a beginner or when
  coaching output needs to be simplified and encouraging.
  Triggers: applied automatically by CoachAgent when generating advice.
---

# Beginner Coaching

## Overview

An LLM formatting skill that tailors coaching output for beginners.
Makes answers concise, explains key turns, and refers to pieces by their
full name (e.g., "the Red Chariot on f3") in addition to color.

## Instructions

1. This skill is a single LLM step with a system prompt.
2. It is used by the CoachAgent to format the final coaching response.
3. Rules enforced by the system prompt:
   - Keep answers concise and easy to understand.
   - Explain key turns and critical moments.
   - Always use full piece names with color (e.g., "the Red Chariot",
     "Black's General") — never abbreviations alone.

## Example

**Without skill:** "Rf3 threatens the c-pawn. Consider Nc7."
**With skill:** "The Red Chariot on f3 is threatening to capture the Black
pawn on c3. Consider moving the Black Horse to c7 to defend it."

## Guidelines

- Never use algebraic abbreviations without the full piece name.
- Keep explanations to 2-3 sentences per point.
- Be encouraging — focus on what the student can do, not just what went wrong.
