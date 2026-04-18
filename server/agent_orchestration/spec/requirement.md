# Requirements - Agent Orchestration
# =====================================

## User Stories

### US-1: Move Explanation
As a beginner player, I want to understand why a move is good or bad,
so I can learn from my mistakes and the computer's moves.
- Acceptance: After AI moves, a brief explanation is shown in the chat panel.
- Acceptance: Player can ask "why" and receive a contextual answer.

### US-2: Blunder Detection
As a player, I want to be warned when I make a serious mistake,
so I can learn to avoid common errors.
- Acceptance: Moves losing >= 200 centipawns trigger a warning.
- Acceptance: Warning includes the better move and a brief explanation.

### US-3: Progressive Hints
As a player, I want to ask for hints that get progressively more specific,
so I can try to find the answer myself first.
- Acceptance: 3 hint levels (vague, moderate, specific).
- Acceptance: Hints use RAG knowledge for contextual relevance.

### US-4: Puzzle Mode
As a learner, I want to solve tactical puzzles generated from game positions,
so I can practice pattern recognition.
- Acceptance: Puzzles are created from positions with large eval swings.
- Acceptance: Solutions are validated against engine analysis.
- Acceptance: Progressive hints are available during puzzles.

### US-5: Mini-Lessons
As a beginner, I want to request lessons on specific topics,
so I can learn at my own pace.
- Acceptance: Player can say "teach me about cannons" and get a lesson.
- Acceptance: Lessons use RAG-retrieved domain knowledge.
- Acceptance: Previously taught topics are not repeated.

### US-6: Adaptive Coaching
As a player, I want the coach to adapt its verbosity and content to my level,
so explanations are neither too simple nor too complex.
- Acceptance: Skill level is estimated from mistake rate and puzzle performance.
- Acceptance: Coach adjusts language complexity based on skill level.

### US-7: Multi-Modal Output
As a user of the physical chess board, I want coaching feedback
displayed on the LED board, spoken via TTS, and shown in the UI,
so I can learn without looking at a screen.
- Acceptance: LED highlights show suggested/legal moves.
- Acceptance: TTS reads coaching messages aloud.
- Acceptance: UI chat panel shows formatted messages.

## Business Rules

- Only the human player receives coaching (not the AI).
- The coach never moves pieces on behalf of the player.
- Puzzle mode pauses normal gameplay until exited.
- Player profile persists across sessions.
- The system works offline (mock LLM fallback) with degraded quality.
