"""
Orchestrator
=============

Main orchestration loop for the agent-based coaching system.

Flow:
  1. Receive user input (text, move, or system event)
  2. Route through IntentClassifierAgent to determine intent
  3. Dispatch to the appropriate agent(s) based on intent
  4. Aggregate responses and update session state
  5. Format output via OutputAgent and deliver to client

Turn Phases:
  Computer Turn: Engine generates move -> Coach explains -> Output
  Player Turn:   Intent classify -> GameEngine / Coach / Puzzle -> Output
  Puzzle Mode:   Validate solutions -> Hints -> Output

The Orchestrator holds references to all agents and the shared SessionState.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .session_state import SessionState, TurnPhase
from .agent_logger import agent_state_logger
from .state_tracker import state_tracker

from ..agents.base_agent import AgentBase, AgentResponse, ResponseType
from ..agents.intent_classifier import IntentClassifierAgent, Intent
from ..agents.game_engine_agent import GameEngineAgent
from ..agents.coach_agent import CoachAgent
from ..agents.puzzle_master_agent import PuzzleMasterAgent
from ..agents.rag_manager_agent import RAGManagerAgent
from ..agents.memory_agent import MemoryAgent
from ..agents.output_agent import OutputAgent
from ..agents.token_limiter_agent import TokenLimiterAgent
from ..agents.onboarding_agent import OnboardingAgent, OnboardingStep
from ..tools.go_client import GoCoachingClient


# ========================
#     ORCHESTRATOR
# ========================

class Orchestrator:
    """Central coordinator for the multi-agent coaching system.

    Manages agent lifecycle, routes messages, and maintains session state.

    Usage:
        orchestrator = Orchestrator()
        await orchestrator.initialize()
        response = await orchestrator.process_input("e3e4")
    """

    def __init__(
        self,
        engine_client: Any = None,
        rag_retriever: Any = None,
        llm_client: Any = None,
        go_coaching_url: str | None = None,
    ):
        self.logger = logging.getLogger("orchestrator")
        self.state = SessionState()
        self._llm_client = llm_client  # Stored for smoke testing

        # ---- Go Coaching Bridge ----
        self._go_client = GoCoachingClient(base_url=go_coaching_url)
        self._go_available: bool | None = None  # Lazy-checked on first request

        # ---- Initialize Agents ----
        self.memory_agent = MemoryAgent()
        self.rag_agent = RAGManagerAgent(retriever=rag_retriever)
        self.engine_agent = GameEngineAgent(engine_client=engine_client)
        self.coach_agent = CoachAgent(
            rag_agent=self.rag_agent,
            llm_client=llm_client,
            memory_agent=self.memory_agent,
        )
        self.puzzle_agent = PuzzleMasterAgent(
            engine_agent=self.engine_agent,
            memory_agent=self.memory_agent,
        )
        self.intent_agent = IntentClassifierAgent(llm_client=llm_client)
        self.output_agent = OutputAgent()
        self.token_limiter = TokenLimiterAgent()
        self.onboarding_agent = OnboardingAgent(memory_agent=self.memory_agent)

        # Agent registry for dynamic dispatch
        self._agents: dict[str, AgentBase] = {
            "IntentClassifierAgent": self.intent_agent,
            "GameEngineAgent": self.engine_agent,
            "CoachAgent": self.coach_agent,
            "PuzzleMasterAgent": self.puzzle_agent,
            "RAGManagerAgent": self.rag_agent,
            "MemoryAgent": self.memory_agent,
            "OutputAgent": self.output_agent,
            "TokenLimiterAgent": self.token_limiter,
            "OnboardingAgent": self.onboarding_agent,
        }

        # State tracker for visualization
        self.state_tracker = state_tracker

    # ---- Lifecycle ----

    async def initialize(self) -> None:
        """Initialize all agents (session-based, no profile persistence)."""
        self.logger.info("Orchestrator initializing...")
        # Fresh session every time — no profile loading from disk
        self.memory_agent._profile = __import__(
            'agent_orchestration.agents.memory_agent', fromlist=['PlayerProfile']
        ).PlayerProfile()
        self.memory_agent._session_data.clear()

        self.logger.info(
            f"Agents ready: {[name for name, a in self._agents.items() if a.is_enabled]}"
        )

    async def smoke_test_llm(self) -> dict:
        """Send a minimal probe to the LLM gateway and return status.

        Returns:
            dict with keys: ok (bool), provider (str), latency_ms (float),
            response_preview (str), error (str|None)
        """
        if not self._llm_client:
            return {"ok": False, "provider": "none", "latency_ms": 0,
                    "response_preview": "", "error": "No LLM client configured"}

        provider = getattr(self._llm_client, '_default_provider', 'unknown')
        t0 = time.perf_counter()
        try:
            response = await self._llm_client.generate(
                prompt="Reply with exactly: OK",
                max_tokens=8,
                temperature=0.0,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            is_mock = response == self._llm_client._mock_generate("Reply with exactly: OK")
            return {
                "ok": True,
                "provider": provider,
                "is_mock": is_mock,
                "latency_ms": round(elapsed, 1),
                "response_preview": response[:80],
                "error": None,
            }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "ok": False,
                "provider": provider,
                "is_mock": False,
                "latency_ms": round(elapsed, 1),
                "response_preview": "",
                "error": str(e),
            }

    async def shutdown(self) -> None:
        """Gracefully shut down all agents."""
        self.logger.info("Orchestrator shutting down...")
        await self._go_client.close()
        for name, agent in self._agents.items():
            try:
                await agent.on_game_end(self.state.game_result)
            except Exception as e:
                self.logger.error(f"Error shutting down {name}: {e}")

    # ---- Main Processing Loop ----

    async def process_input(self, user_input: str) -> AgentResponse:
        """Process user input through the agent pipeline.

        This is the main entry point for all user interactions.

        Args:
            user_input: Raw text from the user (move, question, command).

        Returns:
            Final AgentResponse formatted by OutputAgent.
        """
        self.logger.info(f"Processing input: '{user_input[:80]}'")

        # Begin tracking this request
        self.state_tracker.begin_request(user_input)

        # Record user input in conversation
        self.state.add_conversation("user", user_input)

        # ---- Onboarding Intercept ----
        # If onboarding is not complete, route to OnboardingAgent
        if not self.state.onboarding_complete:
            return await self._handle_onboarding(user_input)

        # ---- Go Coaching Bridge ----
        # Try the Go service first; fall back to the Python pipeline if
        # the Go service is unavailable or returns an error.
        go_response = await self._try_go_coaching(user_input)
        if go_response is not None:
            self.state.add_conversation(
                go_response.source, go_response.message,
                response_type=go_response.response_type.value,
            )
            self.state_tracker.end_request(go_response.message)
            return go_response

        # Step 1: Classify intent
        self.state_tracker.transition(
            "UserInput", "IntentClassifierAgent", "classify",
            user_input_preview=user_input[:80],
        )
        intent_response = await self.intent_agent.safe_handle(
            self.state, user_input=user_input
        )
        intent = intent_response.data.get("intent", Intent.UNKNOWN)
        target_agent_name = intent_response.follow_up_agent or "CoachAgent"

        self.logger.info(
            f"Intent: {intent}, Target: {target_agent_name}"
        )

        # Log dispatch decision
        agent_state_logger.log_dispatch(
            intent=str(intent),
            target_agent=target_agent_name,
            user_input=user_input,
        )

        self.state_tracker.transition(
            "IntentClassifierAgent", target_agent_name, "intent_route",
            intent=str(intent),
        )

        # Step 2: Handle puzzle mode intercept
        if self.state.puzzle_mode and intent == Intent.MOVE:
            return await self._handle_puzzle_move(user_input)

        # Step 3: Dispatch to target agent
        response = await self._dispatch(
            target_agent_name, intent, user_input
        )

        # Step 4: Follow-up chain (if agent requests it)
        max_chain = 3  # Prevent infinite loops
        chain_count = 0
        while response.follow_up_agent and chain_count < max_chain:
            chain_count += 1
            self.logger.debug(
                f"Follow-up chain -> {response.follow_up_agent} "
                f"(step {chain_count})"
            )
            prev_agent = response.source
            self.state_tracker.transition(
                prev_agent, response.follow_up_agent, "follow_up",
                metadata={"chain_step": chain_count},
            )
            response = await self._dispatch_agent(
                response.follow_up_agent,
                agent_response=response,
                user_input=user_input,
            )

        # Step 5: Update session state from response
        self._update_state_from_response(response)

        # Step 6: Record agent response in conversation
        self.state.add_conversation(
            response.source, response.message,
            response_type=response.response_type.value,
        )

        # Step 7: Format output
        self.state_tracker.transition(
            response.source, "OutputAgent", "format",
            response_type=response.response_type.value,
        )
        output = await self.output_agent.safe_handle(
            self.state, agent_response=response
        )

        # Track LLM output if present
        if response.message:
            self.state_tracker.set_llm_output(
                response.source,
                output=response.message,
                reasoning=response.data.get("reasoning", ""),
            )

        self.state_tracker.end_request(output.message)

        return output

    # ---- Go Coaching Bridge ----

    async def _try_go_coaching(self, user_input: str) -> AgentResponse | None:
        """Attempt to delegate to the Go coaching service.

        Returns an AgentResponse on success, or None if the Go service
        is unavailable / returned an error (triggering Python fallback).
        """
        # Lazy health-check: probe once, then cache result for this session
        if self._go_available is None:
            self._go_available = await self._go_client.is_available()
            if self._go_available:
                self.logger.info("Go coaching service is available — using as primary")
            else:
                self.logger.info("Go coaching service unavailable — using Python fallback")

        if not self._go_available:
            return None

        try:
            resp = await self._go_client.coach(
                fen=self.state.board_fen,
                user_input=user_input,
                move_history=list(self.state.move_history),
                difficulty=self.state.difficulty,
            )
            if resp.response_type == ResponseType.ERROR:
                self.logger.warning(
                    "Go service returned error, falling back to Python: %s",
                    resp.message,
                )
                return None
            return resp
        except Exception as exc:
            self.logger.warning("Go coaching bridge failed: %s", exc)
            self._go_available = False  # Stop retrying this session
            return None

    # ---- Turn Phase Handlers ----

    async def process_computer_turn(self) -> AgentResponse:
        """Execute the computer's turn.

        Called by the game loop when it's the AI's turn.
        1. Engine generates a move
        2. Coach optionally explains the move
        3. Puzzle Master checks for puzzle opportunities
        """
        self.state.turn_phase = TurnPhase.COMPUTER_TURN
        self.logger.info("Computer turn starting...")

        # Step 1: AI generates and applies a move
        ai_response = await self.engine_agent.safe_handle(
            self.state,
            action="ai_move",
            difficulty=self.state.difficulty,
        )

        if ai_response.response_type == ResponseType.ERROR:
            return ai_response

        # Step 2: Update state
        self._update_state_from_response(ai_response)

        # Step 3: Coach explains the AI's move
        move_str = ai_response.data.get("move", "")
        coach_response = await self.coach_agent.safe_handle(
            self.state,
            coaching_action="explain_move",
            move_str=move_str,
            side="computer",
        )

        # Step 4: Check for puzzle opportunity
        eval_delta = abs(ai_response.data.get("score", 0) - self.state.last_eval)
        if self.puzzle_agent.should_create_puzzle(eval_delta, self.state.move_number):
            puzzle_response = await self.puzzle_agent.safe_handle(
                self.state,
                puzzle_action="create",
                fen=self.state.board_fen,
            )
            if puzzle_response.response_type == ResponseType.PUZZLE:
                self.state.puzzle_mode = True
                return puzzle_response

        # Combine AI move + coach explanation
        combined_message = ai_response.message
        if coach_response.message:
            combined_message += f"\n{coach_response.message}"

        return AgentResponse(
            source="Orchestrator",
            response_type=ResponseType.BOARD_ACTION,
            message=combined_message,
            data={
                **ai_response.data,
                "coach_message": coach_response.message,
            },
        )

    async def process_player_move(self, move_str: str) -> AgentResponse:
        """Process a player's move through the full pipeline.

        1. Engine validates and applies the move
        2. Coach checks for blunders
        3. State updates
        """
        self.state.turn_phase = TurnPhase.PLAYER_TURN

        # Step 1: Apply move via engine
        engine_response = await self.engine_agent.safe_handle(
            self.state, action="move", move_str=move_str,
        )

        if engine_response.response_type == ResponseType.ERROR:
            return engine_response

        # Step 2: Update state
        self._update_state_from_response(engine_response)

        # Step 3: Check for blunders
        analysis = engine_response.data.get("analysis", {})
        if analysis.get("is_blunder"):
            self.state.warning_state = True
            coach_response = await self.coach_agent.safe_handle(
                self.state,
                coaching_action="blunder_warning",
                move_analysis=analysis,
            )
            # Return combined response
            return AgentResponse(
                source="Orchestrator",
                response_type=ResponseType.WARNING,
                message=coach_response.message,
                data={
                    "move_result": engine_response.data.get("move_result"),
                    "analysis": analysis,
                    "warning": coach_response.message,
                },
            )

        return engine_response

    # ---- Puzzle Mode ----

    async def _handle_puzzle_move(self, user_input: str) -> AgentResponse:
        """Route a move attempt to the puzzle master when in puzzle mode."""
        # Extract move from input
        move_str = user_input.strip()

        response = await self.puzzle_agent.safe_handle(
            self.state,
            puzzle_action="validate",
            player_move=move_str,
        )

        # If puzzle solved, exit puzzle mode
        if response.data.get("result") == "correct":
            self.state.puzzle_mode = False

        return response

    # ---- Onboarding ----

    async def start_onboarding(self) -> AgentResponse:
        """Trigger the onboarding welcome message (called on every connection).

        Always starts fresh — onboarding is session-based.
        """
        # Reset onboarding state for a fresh session
        self.state.onboarding_complete = False
        self.onboarding_agent._current_step = OnboardingStep.WELCOME
        self.memory_agent._session_data.clear()

        response = await self.onboarding_agent.safe_handle(
            self.state, onboarding_action="start"
        )
        return response

    async def _handle_onboarding(self, user_input: str) -> AgentResponse:
        """Route user input to the onboarding agent during onboarding phase.

        The user_input is treated as a button selection value.
        """
        self.state_tracker.transition(
            "UserInput", "OnboardingAgent", "onboarding_answer",
            user_input_preview=user_input[:40],
            metadata={"selection": user_input[:40]},
        )

        response = await self.onboarding_agent.safe_handle(
            self.state,
            onboarding_action="answer",
            selection=user_input.strip().lower(),
        )

        # If onboarding just completed, update session state (no disk persistence)
        if response.data.get("onboarding_complete"):
            self.state.onboarding_complete = True

            # Apply preferences to in-memory profile for this session
            prefs = response.data.get("preferences", {})
            if prefs.get("skill_level"):
                self.memory_agent._profile.skill_level = prefs["skill_level"]
            if prefs.get("board_game_exposure"):
                self.memory_agent._profile.board_game_exposure = prefs["board_game_exposure"]
            if prefs.get("play_style"):
                self.memory_agent._profile.play_style = prefs["play_style"]
            if prefs.get("coaching_verbosity"):
                self.memory_agent._profile.coaching_verbosity = prefs["coaching_verbosity"]
                self.output_agent.set_verbosity(prefs["coaching_verbosity"])

            self.logger.info("Onboarding complete (session-only)")

            # Append opening discussion to engage user immediately
            skill = prefs.get("skill_level", "beginner")
            opening_msg = self._opening_discussion_intro(skill)
            response = AgentResponse(
                source=response.source,
                response_type=response.response_type,
                message=response.message + "\n\n" + opening_msg,
                data=response.data,
            )

        # Record in conversation
        self.state.add_conversation(
            response.source, response.message,
            response_type=response.response_type.value,
        )

        # Format through OutputAgent
        output = await self.output_agent.safe_handle(
            self.state, agent_response=response
        )

        self.state_tracker.end_request(output.message)
        return output

    # ---- Opening Discussion ----

    @staticmethod
    def _opening_discussion_intro(skill_level: str) -> str:
        """Return skill-appropriate opening guidance to start the game discussion."""
        skill = skill_level.lower() if skill_level else "beginner"
        if skill == "beginner":
            return (
                "Let's start with some opening principles!\n\n"
                "In Xiangqi, Red moves first. Here are the most popular openings:\n"
                "• **Central Cannon (中炮)** — Move your cannon to the center column. "
                "This is the most common and aggressive opening.\n"
                "• **Elephant Opening (飛象局)** — Develop your elephants for a solid, "
                "defensive start.\n\n"
                "Try moving your cannon to the center — I'll guide you through the game!"
            )
        if skill == "intermediate":
            return (
                "You have the initiative as Red. Consider opening with:\n"
                "• **Central Cannon** for direct aggression\n"
                "• **Elephant Opening** for flexible development\n\n"
                "Make your first move and I'll provide analysis!"
            )
        return "You have the tempo as Red. Make your opening move and I'll discuss the theory."

    # ---- Internal Dispatch ----

    async def _dispatch(
        self,
        agent_name: str,
        intent: Intent,
        user_input: str,
    ) -> AgentResponse:
        """Dispatch to the appropriate agent based on intent and target."""

        # Build kwargs based on intent
        kwargs: dict[str, Any] = {"user_input": user_input}

        if intent == Intent.MOVE:
            kwargs["action"] = "move"
            kwargs["move_str"] = user_input.strip()
        elif intent == Intent.WHY_QUESTION:
            kwargs["coaching_action"] = "why_question"
        elif intent == Intent.HINT_REQUEST:
            kwargs["coaching_action"] = "hint"
        elif intent == Intent.TEACH_ME:
            kwargs["coaching_action"] = "teach"
            kwargs["topic"] = user_input
        elif intent == Intent.UNDO:
            kwargs["action"] = "undo"
        elif intent == Intent.RESIGN:
            kwargs["action"] = "resign"
        elif intent == Intent.GENERAL_CHAT:
            kwargs["coaching_action"] = "general_chat"

        return await self._dispatch_agent(agent_name, **kwargs)

    async def _dispatch_agent(
        self,
        agent_name: str,
        **kwargs: Any,
    ) -> AgentResponse:
        """Invoke a specific agent by name."""
        agent = self._agents.get(agent_name)
        if agent is None:
            self.logger.error(f"Unknown agent: {agent_name}")
            return AgentResponse.from_error(
                "Orchestrator", f"Unknown agent: {agent_name}"
            )

        t0 = time.perf_counter()
        response = await agent.safe_handle(self.state, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        agent_state_logger.log_handle(
            agent_name=agent_name,
            action=str(kwargs.get("action", kwargs.get("coaching_action", kwargs.get("token_action", "handle")))),
            result="error" if response.response_type == ResponseType.ERROR else "ok",
            response_type=response.response_type.value,
            duration_ms=elapsed_ms,
            error=response.error,
        )

        return response

    # ---- State Updates ----

    def _update_state_from_response(self, response: AgentResponse) -> None:
        """Update session state based on an agent response."""
        data = response.data

        # Board state updates
        if "fen" in data:
            self.state.board_fen = data["fen"]
        if "side_to_move" in data:
            self.state.side_to_move = data["side_to_move"]
        if "result" in data:
            self.state.game_result = data["result"]
        if "is_check" in data:
            self.state.is_check = data["is_check"]

        # Eval tracking
        if "score" in data:
            self.state.last_eval = data["score"]

        # Move tracking
        if response.response_type == ResponseType.BOARD_ACTION:
            if data.get("move") or data.get("move_result", {}).get("move"):
                self.state.move_number += 1
                self.state.last_move = (
                    data.get("move") or
                    data.get("move_result", {}).get("move", "")
                )

        # Puzzle mode
        if "puzzle_mode" in data:
            self.state.puzzle_mode = data["puzzle_mode"]

        # Game over check
        if self.state.is_game_over():
            self.state.turn_phase = TurnPhase.IDLE

    # ---- Agent Management ----

    def get_agent(self, name: str) -> Optional[AgentBase]:
        """Get an agent by name."""
        return self._agents.get(name)

    def enable_agent(self, name: str) -> bool:
        """Enable a specific agent."""
        agent = self._agents.get(name)
        if agent:
            agent.enable()
            return True
        return False

    def disable_agent(self, name: str) -> bool:
        """Disable a specific agent."""
        agent = self._agents.get(name)
        if agent:
            agent.disable()
            return True
        return False

    # ---- Move Event Analysis (called AFTER engine processes the move) ----

    async def analyze_move_event(
        self,
        move_str: str,
        fen: str,
        side: str,
        result: str = "in_progress",
        is_check: bool = False,
        score: int = 0,
    ) -> Optional[AgentResponse]:
        """Analyze a move that was already applied by the engine.

        This is the bridge between the Rust engine (which handles board
        state) and the coaching pipeline. The frontend sends move events
        here AFTER the engine confirms the move.

        Does NOT re-apply the move. Instead:
          1. Updates orchestrator session state from the event
          2. For player moves: checks for blunders, provides coaching
          3. For AI moves: explains the move
          4. Proactively teaches based on game phase

        Args:
            move_str: The move in coordinate notation (e.g., "e3e4")
            fen: Board FEN after the move
            side: Which side made the move ("red" or "black")
            result: Game result after move ("in_progress", "red_wins", etc.)
            is_check: Whether the move gives check
            score: Engine evaluation (centipawns) if available

        Returns:
            AgentResponse with coaching commentary, or None if nothing to say.
        """
        self.logger.info(
            f"[MoveEvent] {side} played {move_str}, fen={fen[:30]}..., "
            f"result={result}, check={is_check}"
        )

        # Update session state from move event
        prev_eval = self.state.last_eval
        self.state.board_fen = fen
        self.state.last_move = move_str
        self.state.move_number += 1
        self.state.is_check = is_check
        self.state.game_result = result
        self.state.side_to_move = "black" if side == "red" else "red"
        if score != 0:
            self.state.last_eval = score

        # Determine game phase for coaching decisions
        game_phase = self.coach_agent._detect_game_phase(self.state)
        player_side = self.state.player_side  # typically "red"
        is_player_move = (side == player_side)

        responses: list[str] = []
        response_data: dict = {
            "move": move_str,
            "side": side,
            "game_phase": game_phase,
            "move_number": self.state.move_number,
        }

        if is_player_move:
            # ---- PLAYER MOVE ANALYSIS ----
            self.state.turn_phase = TurnPhase.PLAYER_TURN

            # Get engine suggestion to compare (blunder detection)
            # Only if engine is connected and we can get a suggestion
            if self.engine_agent._engine and self.engine_agent._engine.is_connected:
                try:
                    suggestion = await self.engine_agent._engine.get_suggestion(
                        difficulty=self.state.difficulty
                    )
                    if suggestion and suggestion.get("move"):
                        engine_best = suggestion["move"]
                        engine_eval = suggestion.get("score", 0)
                        eval_delta = abs(engine_eval - prev_eval)

                        response_data["engine_best"] = engine_best
                        response_data["eval_delta"] = eval_delta

                        from ..agents.game_engine_agent import MoveAnalysis
                        analysis = MoveAnalysis(
                            player_move=move_str,
                            engine_best_move=engine_best,
                            player_eval=score,
                            engine_eval=engine_eval,
                        )

                        if analysis.is_blunder:
                            coach_resp = await self.coach_agent.safe_handle(
                                self.state,
                                coaching_action="blunder_warning",
                                move_analysis=analysis.to_dict(),
                            )
                            responses.append(coach_resp.message)
                            response_data["severity"] = "blunder"
                        elif analysis.is_mistake:
                            coach_resp = await self.coach_agent.safe_handle(
                                self.state,
                                coaching_action="blunder_warning",
                                move_analysis=analysis.to_dict(),
                            )
                            responses.append(coach_resp.message)
                            response_data["severity"] = "mistake"
                except Exception as e:
                    self.logger.error(f"[MoveEvent] Blunder analysis failed: {e}")

            # Proactive coaching: opening guidance (moves 1-8)
            if game_phase == "opening" and self.state.move_number <= 8:
                try:
                    from ..agents.retrieval_request import RetrievalRequest
                    request = RetrievalRequest(
                        query_text=f"Xiangqi opening move {move_str} early game principles",
                        user_intent="proactive_coaching",
                        game_phase="opening",
                        player_skill=self.coach_agent._coaching_mode,
                        top_k=2,
                    )
                    rag_resp = await self.rag_agent.safe_handle(
                        self.state, retrieval_request=request,
                    )
                    docs = rag_resp.data.get("documents", [])
                    if docs and not responses:
                        # Only provide opening tips if no blunder warning
                        tip = await self._generate_proactive_tip(
                            game_phase, move_str, side, docs
                        )
                        if tip:
                            responses.append(tip)
                            response_data["coaching_type"] = "opening_guidance"
                except Exception as e:
                    self.logger.debug(f"[MoveEvent] Opening coaching failed: {e}")

        else:
            # ---- AI MOVE EXPLANATION ----
            self.state.turn_phase = TurnPhase.COMPUTER_TURN

            coach_resp = await self.coach_agent.safe_handle(
                self.state,
                coaching_action="explain_move",
                move_str=move_str,
                side="computer",
            )
            if coach_resp.message:
                responses.append(coach_resp.message)
                response_data["coaching_type"] = "move_explanation"

        # Proactive endgame coaching (moves 40+)
        if game_phase == "endgame" and self.state.move_number % 5 == 0:
            try:
                from ..agents.retrieval_request import RetrievalRequest
                request = RetrievalRequest(
                    query_text="Xiangqi endgame checkmate technique",
                    user_intent="proactive_coaching",
                    game_phase="endgame",
                    player_skill=self.coach_agent._coaching_mode,
                    top_k=2,
                )
                rag_resp = await self.rag_agent.safe_handle(
                    self.state, retrieval_request=request,
                )
                docs = rag_resp.data.get("documents", [])
                if docs:
                    tip = await self._generate_proactive_tip(
                        game_phase, move_str, side, docs
                    )
                    if tip:
                        responses.append(tip)
                        response_data["coaching_type"] = "endgame_guidance"
            except Exception as e:
                self.logger.debug(f"[MoveEvent] Endgame coaching failed: {e}")

        # Game over message
        if result != "in_progress":
            responses.append(f"Game over: {result}.")
            response_data["game_over"] = True

        if not responses:
            return None

        combined = "\n\n".join(responses)
        self.state.add_conversation("CoachAgent", combined, response_type="coaching")

        return AgentResponse(
            source="CoachAgent",
            response_type=ResponseType.TEXT,
            message=combined,
            data=response_data,
        )

    async def _generate_proactive_tip(
        self,
        game_phase: str,
        move_str: str,
        side: str,
        rag_docs: list[str],
    ) -> str:
        """Generate a proactive coaching tip using RAG context and LLM."""
        rag_context = "\n".join(rag_docs[:2])

        if self.coach_agent._llm:
            phase_instruction = {
                "opening": (
                    f"The game is in the opening phase. {side} just played {move_str}. "
                    f"Based on this knowledge, give a brief opening tip or identify "
                    f"the opening being played. Keep it to 1-2 sentences."
                ),
                "endgame": (
                    f"The game is in the endgame. {side} just played {move_str}. "
                    f"Give a brief endgame tip or checkmate strategy hint. "
                    f"Keep it to 1-2 sentences."
                ),
                "middlegame": (
                    f"The game is in the middlegame. {side} just played {move_str}. "
                    f"Give a brief positional or tactical tip. "
                    f"Keep it to 1-2 sentences."
                ),
            }.get(game_phase, "")

            prompt = (
                f"You are a Xiangqi coach. {phase_instruction}\n\n"
                f"Relevant knowledge:\n{rag_context}\n\n"
                f"Provide a concise, helpful coaching tip."
            )
            try:
                return await self.coach_agent._generate_llm_response(prompt)
            except Exception:
                pass

        # Fallback: return first RAG doc excerpt
        if rag_docs:
            return rag_docs[0][:150] + "..."
        return ""

    async def new_game(self) -> None:
        """Reset state and notify all agents of a new game.

        Resets onboarding so the user goes through setup again.
        """
        self.state.reset()
        self.state.onboarding_complete = False
        self.onboarding_agent._current_step = OnboardingStep.WELCOME
        self.memory_agent._session_data.clear()
        self.memory_agent._profile = __import__(
            'agent_orchestration.agents.memory_agent', fromlist=['PlayerProfile']
        ).PlayerProfile()
        self.state_tracker.reset()
        for agent in self._agents.values():
            await agent.on_game_start()
        self.logger.info("New game started (onboarding reset)")
