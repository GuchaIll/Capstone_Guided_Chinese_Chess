"""
State Tracker
=============

Singleton that tracks live agent pipeline state for the React Flow
graph visualizer (GET /agent-state/graph) and transition log
(GET /agent-state/log).

Thread-safe via a simple lock; all writes are in-process (async-friendly).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional


# ================================
#   NODE / EDGE TOPOLOGY
# ================================

_ALL_NODES = [
    {"id": "UserInput",             "label": "User Input",         "type": "input",      "group": "io"},
    {"id": "IntentClassifierAgent", "label": "Intent Classifier",  "type": "classifier", "group": "core"},
    {"id": "GameEngineAgent",       "label": "Game Engine",        "type": "agent",      "group": "core"},
    {"id": "CoachAgent",            "label": "Coach",              "type": "agent",      "group": "core"},
    {"id": "PuzzleMasterAgent",     "label": "Puzzle Master",      "type": "agent",      "group": "core"},
    {"id": "RAGManagerAgent",       "label": "RAG Manager",        "type": "agent",      "group": "support"},
    {"id": "MemoryAgent",           "label": "Memory",             "type": "agent",      "group": "support"},
    {"id": "TokenLimiterAgent",     "label": "Token Limiter",      "type": "agent",      "group": "support"},
    {"id": "OutputAgent",           "label": "Output",             "type": "output",     "group": "io"},
    {"id": "OnboardingAgent",       "label": "Onboarding",         "type": "agent",      "group": "core"},
]

_ALL_NODE_IDS = {n["id"] for n in _ALL_NODES}

_MAX_LOG = 500  # Maximum transitions retained in memory


# ================================
#   STATE TRACKER
# ================================

class StateTracker:
    """Tracks live agent transitions and exposes graph/log snapshots.

    Designed as a module-level singleton (``state_tracker``).

    Usage::

        state_tracker.begin_request(user_input)
        state_tracker.transition("UserInput", "IntentClassifierAgent", "classify")
        state_tracker.end_request(output_text)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Current request context
        self._request_id: Optional[str] = None
        self._request_start: float = 0.0
        self._active_agent: Optional[str] = None

        # Node runtime state: node_id -> status/visited flags
        self._node_status: Dict[str, str] = {n["id"]: "idle" for n in _ALL_NODES}
        self._node_visited: Dict[str, bool] = {n["id"]: False for n in _ALL_NODES}

        # Last active edge(s) this request
        self._active_edges: set[tuple[str, str]] = set()

        # LLM output attached to the most recent active agent
        self._llm_output: Optional[str] = None
        self._llm_reasoning: Optional[str] = None

        # Transition log (ring buffer)
        self._log: Deque[Dict[str, Any]] = deque(maxlen=_MAX_LOG)

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def begin_request(self, user_input: str) -> None:
        """Mark the start of a new request cycle."""
        with self._lock:
            self._request_id = str(uuid.uuid4())[:8]
            self._request_start = time.monotonic()
            self._active_agent = "UserInput"
            self._active_edges = set()
            self._llm_output = None
            self._llm_reasoning = None
            # Reset all nodes to idle/unvisited for this request
            for node_id in self._node_status:
                self._node_status[node_id] = "idle"
                self._node_visited[node_id] = False
            self._node_visited["UserInput"] = True
            self._node_status["UserInput"] = "active"

    def transition(
        self,
        from_agent: str,
        to_agent: str,
        trigger: str,
        *,
        intent: str = "",
        response_type: str = "",
        user_input_preview: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Record a transition between two agents."""
        with self._lock:
            now = time.monotonic()
            duration_ms = round((now - self._request_start) * 1000, 1)

            # Update node states
            if from_agent in _ALL_NODE_IDS:
                if self._node_status.get(from_agent) == "active":
                    self._node_status[from_agent] = "completed"
                self._node_visited[from_agent] = True

            if to_agent in _ALL_NODE_IDS:
                self._node_status[to_agent] = "active"
                self._node_visited[to_agent] = True
                self._active_agent = to_agent

            # Mark the edge as active
            self._active_edges = {(from_agent, to_agent)}

            # Build transition record
            record: Dict[str, Any] = {
                "id": f"{self._request_id}-{len(self._log)}",
                "from_agent": from_agent,
                "to_agent": to_agent,
                "trigger": trigger,
                "timestamp": time.time(),
                "duration_ms": duration_ms,
                "intent": intent,
                "response_type": response_type,
                "user_input_preview": user_input_preview,
                "metadata": metadata or {},
            }
            # Absorb any extra kwargs into metadata
            if kwargs:
                record["metadata"].update(kwargs)

            self._log.append(record)

    def set_llm_output(
        self,
        source: str,
        output: str = "",
        reasoning: str = "",
    ) -> None:
        """Attach LLM output to the most recent transition record."""
        with self._lock:
            self._llm_output = output
            self._llm_reasoning = reasoning
            if self._log:
                last = self._log[-1]
                last["llm_output"] = output[:500] if output else ""
                last["reasoning"] = reasoning[:300] if reasoning else ""

    def end_request(self, output_message: str = "") -> None:
        """Mark the end of a request cycle and mark OutputAgent completed."""
        with self._lock:
            if "OutputAgent" in _ALL_NODE_IDS:
                self._node_visited["OutputAgent"] = True
                self._node_status["OutputAgent"] = "completed"

            self._active_agent = None
            self._active_edges = set()

    def reset(self) -> None:
        """Reset all state (e.g. on new game/session)."""
        with self._lock:
            self._request_id = None
            self._active_agent = None
            self._active_edges = set()
            self._log.clear()
            for node_id in self._node_status:
                self._node_status[node_id] = "idle"
                self._node_visited[node_id] = False

    # ------------------------------------------------------------------
    # SNAPSHOT API  (read by FastAPI endpoints)
    # ------------------------------------------------------------------

    def get_graph_state(self) -> Dict[str, Any]:
        """Return a snapshot dict matching the AgentGraphState TypeScript type."""
        with self._lock:
            active_edges = set(self._active_edges)
            node_status = dict(self._node_status)
            node_visited = dict(self._node_visited)
            active_agent = self._active_agent
            request_id = self._request_id
            transitions = list(self._log)[-20:]  # last 20 for polling

        nodes = [
            {
                "id": n["id"],
                "label": n["label"],
                "status": node_status.get(n["id"], "idle"),
                "visited": node_visited.get(n["id"], False),
                "group": n["group"],
                "type": n["type"],
            }
            for n in _ALL_NODES
        ]

        edges = [
            {
                "source": n["id"],
                "target": m["id"],
                "label": "",
                "active": (n["id"], m["id"]) in active_edges,
            }
            for n in _ALL_NODES
            for m in _ALL_NODES
            if (n["id"], m["id"]) in active_edges
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "transitions": transitions,
            "active_agent": active_agent,
            "request_id": request_id,
        }

    def get_session_log(self, last_n: int = 200) -> List[Dict[str, Any]]:
        """Return the last *last_n* transition records."""
        with self._lock:
            entries = list(self._log)
        return entries[-last_n:]


# ================================
#   MODULE-LEVEL SINGLETON
# ================================

state_tracker = StateTracker()
