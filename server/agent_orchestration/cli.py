"""
Agent Orchestration CLI
========================

Interactive command-line interface for manually testing the agent
orchestration system without running the full web server.

Features:
  - Send text to the orchestrator and see agent responses
  - View/toggle agent states
  - View token usage stats
  - View session state
  - Trigger new game / computer turn
  - All output is printed to terminal AND logged to server/logs/

Usage:
  cd server
  python -m agent_orchestration.cli

Commands:
  (any text)       -> Sent to orchestrator as user input
  /agents          -> List agents and their enabled/disabled status
  /toggle <name>   -> Toggle an agent on/off
  /state           -> Show current session state
  /tokens          -> Show token usage stats
  /budget <n>      -> Set per-session token budget
  /new             -> Start a new game
  /computer        -> Trigger computer turn
  /difficulty <n>  -> Set AI search depth
  /logs            -> Tail the last 10 agent_state.log entries
  /help            -> Show this help
  /quit            -> Exit

Environment:
  Reads from server/.env automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Ensure server/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agent_orchestration.services.orchestrator import Orchestrator
from agent_orchestration.tools.engine_client import EngineClient
from agent_orchestration.tools.rag_retriever import RAGRetriever
from agent_orchestration.tools.llm_client import LLMClient
from agent_orchestration.LLM.LLMRegistry import LLMRegistry

# ========================
#     LOGGING SETUP
# ========================

LOG_LEVEL = os.environ.get("LOG_LEVEL", "WARNING")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.WARNING),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ========================
#     CLI COMMANDS
# ========================

HELP_TEXT = """
Agent Orchestration CLI
========================
Commands:
  (any text)        Send to orchestrator as user input
  /agents           List agents and their enabled/disabled status
  /toggle <name>    Toggle an agent on/off
  /state            Show current session state
  /tokens           Show token usage stats
  /budget <n>       Set per-session token budget
  /new              Start a new game
  /computer         Trigger computer turn
  /difficulty <n>   Set AI search depth (1-8)
  /logs             Show last 10 agent_state.log entries
  /help             Show this help
  /quit             Exit
"""


async def run_cli():
    """Main CLI loop."""
    print("=" * 60)
    print("  Guided Chinese Chess - Agent Orchestration CLI")
    print("=" * 60)
    print("Initializing...")

    # ---- Build orchestrator ----
    engine_url = os.environ.get("ENGINE_WS_URL", "ws://localhost:8080/ws")
    rag_backend = os.environ.get("RAG_BACKEND", "mock")
    chroma_path = os.environ.get("CHROMA_DB_PATH", "./chroma_db")

    engine_client = EngineClient(url=engine_url)
    rag_retriever = RAGRetriever(backend=rag_backend, chroma_path=chroma_path)
    llm_registry = LLMRegistry.from_env()
    llm_client = LLMClient(
        registry=llm_registry,
        default_provider=llm_registry._default_provider,
    )

    await rag_retriever.initialize()

    orchestrator = Orchestrator(
        engine_client=engine_client,
        rag_retriever=rag_retriever,
        llm_client=llm_client,
    )
    await orchestrator.initialize()

    # Try engine connection (non-blocking)
    connected = await engine_client.connect()
    if connected:
        print(f"[OK] Engine connected at {engine_url}")
    else:
        print(f"[--] Engine not available at {engine_url} (using stubs)")

    print(f"[OK] LLM provider: {llm_registry._default_provider}")
    print(f"[OK] Agents: {len(orchestrator._agents)}")
    print(f"\nType /help for commands, or type text to chat.\n")

    # ---- Main loop ----
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not user_input:
            continue

        # ---- Command dispatch ----
        if user_input.lower() == "/quit":
            print("Exiting...")
            break

        elif user_input.lower() == "/help":
            print(HELP_TEXT)

        elif user_input.lower() == "/agents":
            await cmd_agents(orchestrator)

        elif user_input.lower().startswith("/toggle "):
            agent_name = user_input[8:].strip()
            await cmd_toggle(orchestrator, agent_name)

        elif user_input.lower() == "/state":
            await cmd_state(orchestrator)

        elif user_input.lower() == "/tokens":
            await cmd_tokens(orchestrator)

        elif user_input.lower().startswith("/budget "):
            try:
                n = int(user_input[8:].strip())
                await cmd_set_budget(orchestrator, n)
            except ValueError:
                print("Usage: /budget <number>")

        elif user_input.lower() == "/new":
            await orchestrator.new_game()
            print("[OK] New game started.")

        elif user_input.lower() == "/computer":
            await cmd_computer_turn(orchestrator)

        elif user_input.lower().startswith("/difficulty "):
            try:
                d = int(user_input[12:].strip())
                orchestrator.state.difficulty = max(1, min(d, 8))
                print(f"[OK] Difficulty set to {orchestrator.state.difficulty}")
            except ValueError:
                print("Usage: /difficulty <1-8>")

        elif user_input.lower() == "/logs":
            cmd_tail_logs()

        elif user_input.startswith("/"):
            print(f"Unknown command: {user_input}. Type /help for commands.")

        else:
            # ---- Send to orchestrator ----
            await cmd_chat(orchestrator, user_input)

    # ---- Cleanup ----
    await orchestrator.shutdown()
    await engine_client.disconnect()


# ========================
#    COMMAND HANDLERS
# ========================

async def cmd_chat(orchestrator: Orchestrator, user_input: str):
    """Send text through the orchestrator pipeline and print the result."""
    response = await orchestrator.process_input(user_input)
    print()
    print(f"[{response.source}] ({response.response_type.value})")
    print(f"  {response.message}")
    if response.data:
        # Print non-empty interesting data fields
        skip_keys = {"outputs", "original_source", "original_type"}
        data_display = {
            k: v for k, v in response.data.items()
            if k not in skip_keys and v
        }
        if data_display:
            print(f"  data: {json.dumps(data_display, indent=2, default=str)[:500]}")
    print()


async def cmd_agents(orchestrator: Orchestrator):
    """List all agents and their status."""
    print("\n  Registered Agents:")
    print("  " + "-" * 40)
    for name, agent in orchestrator._agents.items():
        status = "ON " if agent.is_enabled else "OFF"
        print(f"  [{status}] {name}")
    print()


async def cmd_toggle(orchestrator: Orchestrator, agent_name: str):
    """Toggle an agent on/off."""
    agent = orchestrator.get_agent(agent_name)
    if agent is None:
        print(f"  Unknown agent: {agent_name}")
        print(f"  Available: {', '.join(orchestrator._agents.keys())}")
        return
    if agent.is_enabled:
        orchestrator.disable_agent(agent_name)
        print(f"  [OFF] {agent_name} disabled")
    else:
        orchestrator.enable_agent(agent_name)
        print(f"  [ON ] {agent_name} enabled")


async def cmd_state(orchestrator: Orchestrator):
    """Show session state."""
    state = orchestrator.state.to_dict()
    print("\n  Session State:")
    print("  " + "-" * 40)
    for k, v in state.items():
        print(f"  {k:25s}: {v}")
    print()


async def cmd_tokens(orchestrator: Orchestrator):
    """Show token usage stats."""
    limiter = orchestrator.token_limiter
    response = await limiter.safe_handle(
        orchestrator.state, token_action="stats",
    )
    print(f"\n  {response.message}")
    if response.data.get("budget"):
        b = response.data["budget"]
        print(f"  Budget: per_request={b['per_request']}, "
              f"per_session={b['per_session']}, daily={b['daily']}")
    print()


async def cmd_set_budget(orchestrator: Orchestrator, per_session: int):
    """Set per-session token budget."""
    await orchestrator.token_limiter.safe_handle(
        orchestrator.state,
        token_action="set_budget",
        per_session=per_session,
    )
    print(f"  [OK] Per-session budget set to {per_session}")


async def cmd_computer_turn(orchestrator: Orchestrator):
    """Trigger computer turn."""
    response = await orchestrator.process_computer_turn()
    print(f"\n  [{response.source}] ({response.response_type.value})")
    print(f"  {response.message}")
    if response.data.get("move"):
        print(f"  Move: {response.data['move']}")
    print()


def cmd_tail_logs():
    """Tail the last 10 entries of agent_state.log."""
    log_path = os.path.join(
        os.path.dirname(__file__), "..", "logs", "agent_state.log",
    )
    if not os.path.exists(log_path):
        print("  No log file yet (agent_state.log)")
        return
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    last_10 = lines[-10:] if len(lines) >= 10 else lines
    print("\n  Last agent_state.log entries:")
    print("  " + "-" * 50)
    for line in last_10:
        try:
            entry = json.loads(line.strip())
            print(f"  {entry.get('ts', '?')} | {entry.get('event', '?')} | "
                  f"{entry.get('agent', entry.get('target_agent', '?'))} | "
                  f"{entry.get('action', entry.get('intent', '?'))}")
        except json.JSONDecodeError:
            print(f"  {line.strip()}")
    print()


# ========================
#     ENTRY POINT
# ========================

def main():
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
