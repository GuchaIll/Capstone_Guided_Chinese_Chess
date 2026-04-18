"""
Output Agent
=============

Formats agent responses for multi-modal delivery.

Output Channels:
  - UI Text: Formatted messages for the React frontend chat panel
  - TTS Payload: Text prepared for text-to-speech synthesis
  - LED Commands: Board highlight instructions for the physical LED board

Responsibilities:
  - Convert AgentResponse objects into channel-specific formats
  - Manage verbosity level preference (brief / normal / detailed)
  - Aggregate multiple agent responses into a single user-facing output
  - Handle i18n preparation (Chinese + English bilingual support)

.. deprecated::
    Replaced by FeedbackAgent in the Go coaching service (server/chess_coach/).
    Retained as fallback only. See AGENTS.md.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "OutputAgent is deprecated — use Go FeedbackAgent instead.",
    DeprecationWarning, stacklevel=2,
)

from enum import Enum
from typing import Any

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#    VERBOSITY LEVELS
# ========================

class Verbosity(str, Enum):
    BRIEF = "brief"       # Short, one-line responses
    NORMAL = "normal"     # Standard coaching detail
    DETAILED = "detailed" # Full explanations with examples


# ========================
#    OUTPUT CHANNELS
# ========================

class OutputChannel(str, Enum):
    UI_TEXT = "ui_text"
    TTS = "tts"
    LED = "led"


# ========================
#     OUTPUT AGENT
# ========================

class OutputAgent(AgentBase):
    """Formats and delivers responses across UI, TTS, and LED channels.

    Transforms raw AgentResponse objects into structured payloads
    suitable for each output channel.
    """

    def __init__(
        self,
        verbosity: Verbosity = Verbosity.NORMAL,
        enabled_channels: list[OutputChannel] | None = None,
        enabled: bool = True,
    ):
        super().__init__(name="OutputAgent", enabled=enabled)
        self._verbosity = verbosity
        self._channels = enabled_channels or [
            OutputChannel.UI_TEXT,
            OutputChannel.LED,
        ]

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Format an agent response for delivery.

        Expected kwargs:
            agent_response (AgentResponse): The response to format.
            channels (list[str]): Override which channels to target.

        Returns:
            AgentResponse with formatted payloads in data.outputs.
        """
        source_response: AgentResponse = kwargs.get("agent_response")
        if source_response is None:
            return AgentResponse.from_error(
                self.name, "No agent_response provided to format"
            )

        channels = kwargs.get("channels", self._channels)
        outputs = {}

        for channel in channels:
            if channel == OutputChannel.UI_TEXT or channel == "ui_text":
                outputs["ui_text"] = self._format_ui_text(source_response)
            elif channel == OutputChannel.TTS or channel == "tts":
                outputs["tts"] = self._format_tts(source_response)
            elif channel == OutputChannel.LED or channel == "led":
                outputs["led"] = self._format_led(source_response)

        return AgentResponse(
            source=self.name,
            response_type=source_response.response_type,
            message=source_response.message,
            data={
                "outputs": outputs,
                "original_source": source_response.source,
                "original_type": source_response.response_type.value,
            },
        )

    # ---- Channel Formatters ----

    def _format_ui_text(self, response: AgentResponse) -> dict:
        """Format for the React frontend chat panel.

        Returns a dict with:
            text: The message to display
            type: Message styling hint (info, warning, success, error)
            data: Additional structured data for UI rendering
        """
        type_map = {
            ResponseType.WARNING: "warning",
            ResponseType.ERROR: "error",
            ResponseType.SUGGESTION: "info",
            ResponseType.PUZZLE: "puzzle",
            ResponseType.LESSON: "lesson",
            ResponseType.TEXT: "info",
            ResponseType.BOARD_ACTION: "success",
            ResponseType.ONBOARDING: "onboarding",
        }

        message = response.message
        if self._verbosity == Verbosity.BRIEF and len(message) > 100:
            message = message[:97] + "..."
        elif self._verbosity == Verbosity.DETAILED:
            # Append any extra context from data
            if response.data.get("rag_context"):
                message += f"\n\nAdditional context: {response.data['rag_context']}"

        return {
            "text": message,
            "type": type_map.get(response.response_type, "info"),
            "data": response.data,
        }

    def _format_tts(self, response: AgentResponse) -> dict:
        """Format for text-to-speech output.

        Simplifies the message: removes technical details, coordinates,
        and formats for natural speech.
        """
        text = response.message

        # Clean up for speech: remove coordinate notation
        # e.g., "e3e4" -> "E3 to E4"
        import re
        text = re.sub(
            r"\b([a-i])(\d)([a-i])(\d)\b",
            lambda m: f"{m.group(1).upper()}{m.group(2)} to {m.group(3).upper()}{m.group(4)}",
            text,
        )

        # Truncate for speech if too long
        if len(text) > 300:
            text = text[:297] + "..."

        return {
            "text": text,
            "language": "en",
            "speed": 1.0,
        }

    def _format_led(self, response: AgentResponse) -> dict:
        """Format LED board highlight commands.

        Extracts square coordinates from the response data and
        maps them to LED color commands.

        LED Colors:
            green: Best/suggested move destination
            yellow: Legal move targets
            red: Warning (blunder square)
            blue: Puzzle-related highlights
        """
        led_commands = []

        data = response.data

        # Suggestion highlights
        if response.response_type == ResponseType.SUGGESTION:
            if data.get("from"):
                led_commands.append({
                    "square": data["from"],
                    "color": "green",
                    "action": "highlight",
                })
            if data.get("to"):
                led_commands.append({
                    "square": data["to"],
                    "color": "green",
                    "action": "highlight",
                })

        # Legal move highlights
        if data.get("targets"):
            for target in data["targets"]:
                led_commands.append({
                    "square": target,
                    "color": "yellow",
                    "action": "highlight",
                })

        # Warning highlights
        if response.response_type == ResponseType.WARNING:
            if data.get("player_move"):
                move = data["player_move"]
                if len(move) >= 4:
                    led_commands.append({
                        "square": move[2:4],
                        "color": "red",
                        "action": "highlight",
                    })
            if data.get("engine_best"):
                best = data["engine_best"]
                if len(best) >= 4:
                    led_commands.append({
                        "square": best[2:4],
                        "color": "green",
                        "action": "highlight",
                    })

        # Board action: clear all LEDs first, then highlight
        if response.response_type == ResponseType.BOARD_ACTION:
            led_commands.insert(0, {"action": "clear_all"})

        return {
            "commands": led_commands,
            "count": len(led_commands),
        }

    # ---- Configuration ----

    def set_verbosity(self, level: str) -> None:
        """Set the verbosity level for output formatting."""
        try:
            self._verbosity = Verbosity(level)
            self.logger.info(f"Verbosity set to: {level}")
        except ValueError:
            self.logger.warning(f"Invalid verbosity level: {level}")

    def set_channels(self, channels: list[str]) -> None:
        """Set which output channels are active."""
        self._channels = [OutputChannel(c) for c in channels if c in OutputChannel.__members__]
        self.logger.info(f"Active channels: {self._channels}")
