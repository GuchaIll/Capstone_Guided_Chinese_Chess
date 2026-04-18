"""
Agent Logger
=============

File-based logger that writes agent state transitions, tool invocations,
and token usage to rotating log files under the logs/ directory.

Log Files:
  logs/agent_state.log   - Agent handle() calls, state transitions, enable/disable
  logs/tool_usage.log    - EngineClient, RAGRetriever, LLMClient invocations
  logs/token_usage.log   - Token budget checks, usage records, rejections

Each entry is a JSON line for easy parsing by monitoring tools.
"""

from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Optional


# ========================
#     LOG DIRECTORY
# ========================

DEFAULT_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
)


# ========================
#   LOGGER SETUP
# ========================

def _create_file_logger(
    name: str,
    filename: str,
    log_dir: str,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
) -> logging.Logger:
    """Create a rotating file logger that writes JSON lines."""
    os.makedirs(log_dir, exist_ok=True)
    filepath = os.path.join(log_dir, filename)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Don't propagate to root logger

    # Avoid adding duplicate handlers on reimport
    if not logger.handlers:
        handler = RotatingFileHandler(
            filepath,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(message)s")  # Raw JSON lines
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# ========================
#   AGENT STATE LOGGER
# ========================

class AgentStateLogger:
    """Logs agent state transitions, handle() invocations, and responses.

    Writes JSON-line entries to logs/agent_state.log.

    Usage:
        from agent_orchestration.services.agent_logger import agent_state_logger
        agent_state_logger.log_handle("CoachAgent", "coaching_action=hint", "success")
    """

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = log_dir or DEFAULT_LOG_DIR
        self._logger = _create_file_logger(
            "agent_state_file", "agent_state.log", self._log_dir,
        )

    def log_handle(
        self,
        agent_name: str,
        action: str,
        result: str,
        response_type: str = "",
        duration_ms: float = 0.0,
        error: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Log an agent handle() invocation."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "agent_handle",
            "agent": agent_name,
            "action": action,
            "result": result,
            "response_type": response_type,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            entry["error"] = error
        if extra:
            entry.update(extra)
        self._logger.info(json.dumps(entry))

    def log_state_change(
        self,
        agent_name: str,
        change_type: str,
        details: str = "",
    ) -> None:
        """Log an agent state change (enable/disable, game start/end)."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "state_change",
            "agent": agent_name,
            "change": change_type,
            "details": details,
        }
        self._logger.info(json.dumps(entry))

    def log_dispatch(
        self,
        intent: str,
        target_agent: str,
        user_input: str,
    ) -> None:
        """Log orchestrator dispatch decision."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "dispatch",
            "intent": intent,
            "target_agent": target_agent,
            "input_preview": user_input[:80],
        }
        self._logger.info(json.dumps(entry))


# ========================
#   TOOL USAGE LOGGER
# ========================

class ToolUsageLogger:
    """Logs tool invocations (EngineClient, RAGRetriever, LLMClient).

    Writes JSON-line entries to logs/tool_usage.log.

    Usage:
        tool_logger.log_call("EngineClient", "send_move", {"move": "e3e4"}, 15.2)
    """

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = log_dir or DEFAULT_LOG_DIR
        self._logger = _create_file_logger(
            "tool_usage_file", "tool_usage.log", self._log_dir,
        )

    def log_call(
        self,
        tool_name: str,
        method: str,
        params: Optional[dict] = None,
        duration_ms: float = 0.0,
        success: bool = True,
        error: Optional[str] = None,
        response_preview: str = "",
    ) -> None:
        """Log a tool invocation."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "tool_call",
            "tool": tool_name,
            "method": method,
            "params": _truncate_dict(params) if params else {},
            "duration_ms": round(duration_ms, 2),
            "success": success,
        }
        if error:
            entry["error"] = error
        if response_preview:
            entry["response_preview"] = response_preview[:200]
        self._logger.info(json.dumps(entry))


# ========================
#   TOKEN USAGE LOGGER
# ========================

class TokenUsageLogger:
    """Logs token budget checks, usage records, and rejections.

    Writes JSON-line entries to logs/token_usage.log.
    """

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = log_dir or DEFAULT_LOG_DIR
        self._logger = _create_file_logger(
            "token_usage_file", "token_usage.log", self._log_dir,
        )

    def log_check(
        self,
        agent_name: str,
        estimated_tokens: int,
        allowed: bool,
        reason: str,
        session_total: int = 0,
        daily_total: int = 0,
    ) -> None:
        """Log a token budget check."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "token_check",
            "agent": agent_name,
            "estimated": estimated_tokens,
            "allowed": allowed,
            "reason": reason,
            "session_total": session_total,
            "daily_total": daily_total,
        }
        self._logger.info(json.dumps(entry))

    def log_usage(
        self,
        agent_name: str,
        tokens: int,
        provider: str = "unknown",
        session_total: int = 0,
        daily_total: int = 0,
    ) -> None:
        """Log actual token consumption."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "token_usage",
            "agent": agent_name,
            "tokens": tokens,
            "provider": provider,
            "session_total": session_total,
            "daily_total": daily_total,
        }
        self._logger.info(json.dumps(entry))


# ========================
#     HELPERS
# ========================

def _truncate_dict(d: dict, max_str_len: int = 100) -> dict:
    """Truncate string values in a dict for logging."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > max_str_len:
            result[k] = v[:max_str_len] + "..."
        elif isinstance(v, dict):
            result[k] = _truncate_dict(v, max_str_len)
        else:
            result[k] = v
    return result


# ========================
#   SINGLETON INSTANCES
# ========================

agent_state_logger = AgentStateLogger()
tool_logger = ToolUsageLogger()
token_logger = TokenUsageLogger()
