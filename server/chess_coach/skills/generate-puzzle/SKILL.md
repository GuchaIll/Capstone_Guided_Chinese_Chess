---
name: generate-puzzle
description: >
  Generates a complete tactical puzzle from a position: detects patterns,
  builds a solution with batch-validated moves, rates difficulty, and tags
  themes. Use this skill when the user asks for a puzzle, practice problem,
  exercise, or when blunder detection flags a teachable position.
  Triggers: "give me a puzzle", "practice problem", "tactical exercise",
  "create a drill", route_puzzle flag set by blunder detection.
---

# Generate Puzzle

## Overview

Full puzzle generation pipeline: discovers tactical patterns in the position,
builds a forced winning line using the engine, rates the puzzle's difficulty
based on depth and piece count, and tags it with tactical themes.

## Instructions

1. Requires `fen` in context state.
2. Pipeline:
   - **get_patterns** — `get_tactical_patterns` tool. Identifies forks, pins,
     cannon screens, hanging pieces to determine if the position is tactical.
   - **find_motif** — `find_tactical_motif` tool. Augments with PV and engine eval.
   - **create_puzzle** — `generate_puzzle` tool. Builds a 3-move solution using
     `Suggest()` with scored steps.
   - **rate** — `rate_difficulty` tool. Estimates difficulty (beginner/intermediate/
     advanced/expert) based on solution depth and piece count.
   - **tag** — `tag_puzzle_themes` tool. Tags with themes: combination, one_move,
     middlegame, endgame, tactical.
3. Results stored in `ctx.State["puzzle"]`, `ctx.State["puzzle_difficulty"]`,
   `ctx.State["puzzle_themes"]`.

## Example

**User:** "Give me a practice puzzle from this position."

→ Tactical patterns found: hanging Chariot → Puzzle: 3-move forced win
→ Difficulty: intermediate (1200) → Themes: combination, middlegame

## Guidelines

- Only generate puzzles from positions with `has_tactics: true`.
- Solution must be a forced winning line validated by the engine.
- Always include difficulty rating and themes for the student.
