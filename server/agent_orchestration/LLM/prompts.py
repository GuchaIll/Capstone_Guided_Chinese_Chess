"""
Prompt Templates
================

Centralized prompt templates for all LLM interactions in the coaching system.

Each template is a function that accepts context variables and returns
a formatted prompt string. This keeps prompt engineering in one place
and makes it easy to iterate on prompts without touching agent logic.

Template Naming Convention:
    {agent}_{action}_prompt
    e.g., coach_blunder_warning_prompt, coach_explain_move_prompt

Variables available to all templates:
    board_fen: Current board FEN
    side_to_move: "red" or "black"
    move_history: Recent moves
    player_skill: "beginner", "intermediate", "advanced"
"""

from __future__ import annotations

from typing import Optional


# ========================
#    SYSTEM PROMPTS
# ========================

SYSTEM_XIANGQI_COACH = (
    "You are a friendly and knowledgeable Xiangqi (Chinese Chess) coach. "
    "You are teaching a player who is new to the game. "
    "Use clear, simple language. Refer to pieces by their English names: "
    "King (General), Advisor (Guard), Elephant (Bishop), Horse (Knight), "
    "Rook (Chariot), Cannon, and Pawn (Soldier). "
    "When explaining board positions, use algebraic notation (a0-i9). "
    "Keep responses concise but informative, ensure you explain all chess terminology."
)

SYSTEM_PUZZLE_MASTER = (
    "You are a Xiangqi puzzle master. You create and explain tactical puzzles "
    "to help players improve. Give hints progressively: first a general "
    "direction, then more specific guidance, and finally the solution. "
    "Celebrate correct answers and encourage players who struggle."
)


# ========================
#    COACH PROMPTS
# ========================

def coach_blunder_warning_prompt(
    player_move: str,
    engine_best: str,
    eval_delta: int,
    fen: str = "",
    rag_context: str = "",
    player_skill: str = "beginner",
) -> str:
    """Prompt for explaining why a player's move was a blunder."""
    skill_instruction = {
        "beginner": "Use simple language and avoid jargon.",
        "intermediate": "You can use standard chess terminology.",
        "advanced": "Be concise and technical.",
    }.get(player_skill, "Use simple language.")

    prompt = (
        f"The player moved {player_move}, but the best move was {engine_best}. "
        f"The evaluation difference is {eval_delta} centipawns "
        f"(higher is worse for the player).\n\n"
    )

    if fen:
        prompt += f"Current position (FEN): {fen}\n\n"

    if rag_context:
        prompt += f"Relevant knowledge:\n{rag_context}\n\n"

    prompt += (
        f"Explain to the player why {engine_best} is better than {player_move}. "
        f"Mention what tactical or positional advantage the better move provides. "
        f"{skill_instruction} "
        f"Keep the response under 3 sentences."
    )

    return prompt


def coach_explain_move_prompt(
    move_str: str,
    side: str,
    fen: str = "",
    rag_context: str = "",
    player_skill: str = "beginner",
) -> str:
    """Prompt for explaining a specific move (AI or player)."""
    prompt = (
        f"The {side} played the move {move_str}.\n\n"
    )

    if fen:
        prompt += f"Position after the move (FEN): {fen}\n\n"

    if rag_context:
        prompt += f"Relevant knowledge:\n{rag_context}\n\n"

    prompt += (
        f"Explain this move briefly to a {player_skill} player. "
        f"Mention the tactical or strategic purpose of the move. "
        f"Keep the response under 2 sentences."
    )

    return prompt


def coach_why_question_prompt(
    user_question: str,
    fen: str = "",
    last_move: str = "",
    rag_context: str = "",
    conversation_context: Optional[list[dict]] = None,
    player_skill: str = "beginner",
) -> str:
    """Prompt for answering a player's 'why' question."""
    prompt = f"The player asks: \"{user_question}\"\n\n"

    if last_move:
        prompt += f"The last move played was: {last_move}\n"
    if fen:
        prompt += f"Current position (FEN): {fen}\n\n"

    if rag_context:
        prompt += f"Relevant Xiangqi knowledge:\n{rag_context}\n\n"

    if conversation_context:
        recent = conversation_context[-3:]
        prompt += "Recent conversation:\n"
        for entry in recent:
            prompt += f"  {entry['role']}: {entry['content'][:100]}\n"
        prompt += "\n"

    prompt += (
        f"Answer the player's question clearly. "
        f"Adjust your explanation for a {player_skill} level player. "
        f"Keep the response under 4 sentences."
    )

    return prompt


def coach_hint_prompt(
    fen: str,
    best_move: str,
    hint_level: int,
    player_skill: str = "beginner",
) -> str:
    """Prompt for generating progressive hints."""
    level_instruction = {
        1: (
            f"Give a VAGUE hint about where to look on the board. "
            f"Do NOT mention any specific squares or pieces. "
            f"Just give a general direction (e.g., 'look at your attack')."
        ),
        2: (
            f"Give a MODERATE hint. You may mention the TYPE of piece to move "
            f"(e.g., 'your rook can create a threat') but do NOT reveal "
            f"the exact square."
        ),
        3: (
            f"Give the SPECIFIC hint. Reveal the piece and the general area "
            f"of the board. The player should be able to find it from here."
        ),
    }.get(hint_level, "Reveal the move directly.")

    prompt = (
        f"Position (FEN): {fen}\n"
        f"The best move is: {best_move}\n\n"
        f"{level_instruction}\n"
        f"Keep the hint to 1-2 sentences."
    )

    return prompt


def coach_teach_prompt(
    topic: str,
    rag_context: str = "",
    concepts_already_taught: Optional[list[str]] = None,
    player_skill: str = "beginner",
) -> str:
    """Prompt for delivering a mini-lesson."""
    prompt = f"Teach the player about: {topic}\n\n"

    if rag_context:
        prompt += f"Reference material:\n{rag_context}\n\n"

    if concepts_already_taught:
        prompt += (
            f"The player has already learned about: "
            f"{', '.join(concepts_already_taught)}\n"
            f"Avoid repeating these concepts.\n\n"
        )

    prompt += (
        f"Deliver a short, engaging lesson for a {player_skill} player. "
        f"Include one practical tip they can apply immediately. "
        f"Keep the lesson under 5 sentences."
    )

    return prompt


# ========================
#   PUZZLE PROMPTS
# ========================

def puzzle_create_prompt(
    fen: str,
    best_move: str,
    puzzle_type: str = "tactical",
) -> str:
    """Prompt for generating a puzzle description."""
    prompt = (
        f"Position (FEN): {fen}\n"
        f"The key move is: {best_move}\n"
        f"Puzzle type: {puzzle_type}\n\n"
        f"Write a one-sentence puzzle instruction for the player. "
        f"Do NOT reveal the answer. "
        f"Example: 'Find the move that wins material.' "
        f"or 'Your opponent's king is exposed. Find the checkmate.'"
    )

    return prompt


def puzzle_feedback_correct_prompt(
    move_str: str,
    attempts: int,
) -> str:
    """Prompt for congratulating a correct puzzle solution."""
    prompt = (
        f"The player found the correct move: {move_str} "
        f"in {attempts} attempt(s).\n\n"
        f"Write a short congratulatory message (1-2 sentences). "
        f"If they solved it in 1 attempt, be extra enthusiastic."
    )

    return prompt


def puzzle_feedback_incorrect_prompt(
    player_move: str,
    attempts: int,
) -> str:
    """Prompt for encouraging the player after an incorrect attempt."""
    prompt = (
        f"The player tried {player_move} but it's not the best move. "
        f"This is attempt #{attempts}.\n\n"
        f"Write a short encouraging message (1 sentence) that nudges "
        f"them to try again without revealing the answer."
    )

    return prompt


# ========================
#   GENERAL CHAT PROMPTS
# ========================

def general_chat_prompt(
    user_input: str,
    fen: str = "",
    side_to_move: str = "",
    conversation_context: Optional[list[dict]] = None,
) -> str:
    """Prompt for general conversation with the player."""
    prompt = f"The player says: \"{user_input}\"\n\n"

    if fen:
        prompt += f"Current game position (FEN): {fen}\n"
    if side_to_move:
        prompt += f"It is {side_to_move}'s turn.\n\n"

    if conversation_context:
        recent = conversation_context[-3:]
        prompt += "Recent conversation:\n"
        for entry in recent:
            prompt += f"  {entry['role']}: {entry['content'][:100]}\n"
        prompt += "\n"

    prompt += (
        "Respond naturally as a friendly Xiangqi coach. "
        "If the player's message relates to the game, weave in "
        "relevant chess knowledge. Keep it conversational and brief."
    )

    return prompt


# ========================
#   FULL COACHING PROMPT
# ========================

def build_full_coaching_prompt(
    action: str,
    user_query: str = "",
    fen: str = "",
    game_phase: str = "",
    side_to_move: str = "",
    move_history: Optional[list[str]] = None,
    engine_analysis: Optional[dict] = None,
    rag_documents: Optional[list[dict]] = None,
    player_skill: str = "beginner",
    conversation_context: Optional[list[dict]] = None,
) -> str:
    """Build a comprehensive coaching prompt per the RAG specification.

    Assembles: Game State + Move History + Engine Analysis +
    Retrieved Knowledge + Player Context + User Query + Instructions.
    """
    sections = []

    # 1. Game State
    if fen or game_phase or side_to_move:
        state_lines = ["## Game State"]
        if fen:
            state_lines.append(f"Position (FEN): {fen}")
        if game_phase:
            state_lines.append(f"Phase: {game_phase}")
        if side_to_move:
            state_lines.append(f"Side to move: {side_to_move}")
        sections.append("\n".join(state_lines))

    # 2. Move History
    if move_history:
        recent = move_history[-10:]
        sections.append(
            "## Recent Moves\n" + ", ".join(recent)
        )

    # 3. Engine Analysis
    if engine_analysis:
        analysis_lines = ["## Engine Analysis"]
        if "eval" in engine_analysis:
            analysis_lines.append(f"Evaluation: {engine_analysis['eval']} cp")
        if "best_move" in engine_analysis:
            analysis_lines.append(f"Best move: {engine_analysis['best_move']}")
        if "player_move" in engine_analysis:
            analysis_lines.append(f"Player move: {engine_analysis['player_move']}")
        if "eval_delta" in engine_analysis:
            analysis_lines.append(
                f"Eval difference: {engine_analysis['eval_delta']} cp"
            )
        sections.append("\n".join(analysis_lines))

    # 4. Retrieved Knowledge
    if rag_documents:
        knowledge_lines = ["## Retrieved Knowledge"]
        for i, doc in enumerate(rag_documents[:5], 1):
            content = doc if isinstance(doc, str) else doc.get("content", "")
            score = doc.get("score", "") if isinstance(doc, dict) else ""
            score_str = f" (relevance: {score:.2f})" if score else ""
            knowledge_lines.append(f"{i}. {content}{score_str}")
        sections.append("\n".join(knowledge_lines))

    # 5. Player Context
    skill_instruction = {
        "beginner": "Use simple language and avoid jargon. Explain piece names.",
        "intermediate": "You can use standard chess terminology.",
        "advanced": "Be concise and technical.",
    }.get(player_skill, "Use simple language.")
    sections.append(f"## Player Level: {player_skill}\n{skill_instruction}")

    # 6. Conversation Context
    if conversation_context:
        recent = conversation_context[-3:]
        conv_lines = ["## Recent Conversation"]
        for entry in recent:
            conv_lines.append(
                f"  {entry['role']}: {entry['content'][:100]}"
            )
        sections.append("\n".join(conv_lines))

    # 7. User Query
    if user_query:
        sections.append(f"## User Query\n{user_query}")

    # 8. Action-specific instructions
    instructions = {
        "blunder_warning": (
            "Explain why the player's move was a mistake and why the "
            "engine's move is better. Be encouraging, not harsh."
        ),
        "explain_move": (
            "Explain the tactical or strategic purpose of this move."
        ),
        "why_question": (
            "Answer the player's question using the retrieved knowledge. "
            "Be conversational and helpful."
        ),
        "hint": (
            "Give a hint without revealing the answer directly."
        ),
        "teach": (
            "Deliver a short, engaging lesson on the topic. "
            "Include one practical tip the player can apply immediately."
        ),
        "general_chat": (
            "Respond naturally as a friendly Xiangqi coach."
        ),
    }
    instruction = instructions.get(action, instructions["general_chat"])
    sections.append(f"## Instructions\n{instruction}\nKeep the response concise.")

    return "\n\n".join(sections)
