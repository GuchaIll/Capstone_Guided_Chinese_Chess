"""
Guided Chinese Chess - Python Server
=====================================

FastAPI application that serves as the agent orchestration layer
between the React frontend and the Rust game engine.

Endpoints:
  - WS  /ws/chat    Agent-mediated coaching interactions
  - GET /health     Health check
  - GET /agents     List registered agents and their status
  - POST /agents/{name}/toggle  Enable/disable an agent

The Rust engine at ws://localhost:8080/ws handles direct game
interactions (moves, legal_moves, ai_move). This server handles
coaching, explanations, puzzles, and adaptive learning.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Set

from dotenv import load_dotenv
load_dotenv()  # Load .env before reading any os.environ

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# ========================
#     CONFIGURATION
# ========================

ENGINE_WS_URL = os.environ.get("ENGINE_WS_URL", "ws://localhost:8080/ws")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "5000"))
RAG_BACKEND = os.environ.get("RAG_BACKEND", "mock")
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "./chroma_db")
PROFILE_DIR = os.environ.get("PROFILE_DIR", "./agent_orchestration/.agent/profiles")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ========================
#     LOGGING SETUP
# ========================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")

from agent_orchestration.services.orchestrator import Orchestrator
from agent_orchestration.services.session_state import SessionState
from agent_orchestration.services.state_tracker import state_tracker
from agent_orchestration.tools.engine_client import EngineClient
from agent_orchestration.tools.rag_retriever import RAGRetriever
from agent_orchestration.tools.llm_client import LLMClient
from agent_orchestration.tools.kibo_detector import detect_animation
from agent_orchestration.LLM.LLMRegistry import LLMRegistry

# ========================
#     APP FACTORY
# ========================

orchestrator: Orchestrator = None  # Initialized on startup

# Connected Kibo 3D viewers — commands are broadcast to all
kibo_viewers: Set[object] = set()


def create_app():
    """Create and configure the FastAPI application."""
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        logger.error(
            "FastAPI not installed. Run: pip install fastapi uvicorn websockets"
        )
        sys.exit(1)

    app = FastAPI(
        title="Guided Chinese Chess - Coaching Server",
        description="Agent orchestration for Xiangqi coaching",
        version="0.1.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Startup / Shutdown ----

    @app.on_event("startup")
    async def startup():
        global orchestrator

        logger.info("Starting coaching server...")

        # Initialize tools
        engine_client = EngineClient(url=ENGINE_WS_URL)
        rag_retriever = RAGRetriever(backend=RAG_BACKEND, chroma_path=CHROMA_DB_PATH)
        llm_registry = LLMRegistry.from_env()
        llm_client = LLMClient(
            registry=llm_registry,
            default_provider=llm_registry._default_provider,
        )

        # Log LLM provider setup
        logger.info(
            f"LLM provider: {llm_registry._default_provider}, "
            f"registered: {llm_registry.list_providers()}, "
            f"API key set: {bool(os.environ.get('OPENROUTER_API_KEY', '').strip())}"
        )

        # Initialize RAG
        await rag_retriever.initialize()

        # Load knowledge base into ChromaDB if using chromadb backend
        if RAG_BACKEND == "chromadb":
            try:
                from agent_orchestration.tools.knowledge_loader import KnowledgeLoader
                loader = KnowledgeLoader(
                    chroma_path=CHROMA_DB_PATH,
                    model_name=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
                )
                results = loader.load_all(force=False)
                total = sum(results.values())
                if total > 0:
                    logger.info(f"Loaded {total} knowledge docs into ChromaDB")
                else:
                    logger.info("Knowledge base already populated in ChromaDB")
            except Exception as e:
                logger.warning(f"Knowledge loading failed (non-fatal): {e}")

        # Initialize orchestrator with profile directory from env
        orchestrator = Orchestrator(
            engine_client=engine_client,
            rag_retriever=rag_retriever,
            llm_client=llm_client,
        )
        orchestrator.memory_agent._profile_dir = PROFILE_DIR
        await orchestrator.initialize()

        # Try connecting to engine (non-blocking if unavailable)
        connected = await engine_client.connect()
        if connected:
            logger.info(f"Connected to engine at {ENGINE_WS_URL}")
        else:
            logger.warning(
                f"Engine not available at {ENGINE_WS_URL}. "
                "Coaching will work with stubs."
            )

        # LLM gateway smoke test
        llm_status = await orchestrator.smoke_test_llm()
        if llm_status["ok"]:
            mock_tag = " (MOCK)" if llm_status.get("is_mock") else ""
            logger.info(
                f"LLM smoke test PASSED{mock_tag}: provider={llm_status['provider']}, "
                f"latency={llm_status['latency_ms']}ms, "
                f"response={llm_status['response_preview']!r}"
            )
        else:
            logger.warning(
                f"LLM smoke test FAILED: provider={llm_status['provider']}, "
                f"error={llm_status['error']}"
            )

        logger.info(f"Coaching server ready at http://{SERVER_HOST}:{SERVER_PORT}")

    @app.on_event("shutdown")
    async def shutdown():
        if orchestrator:
            await orchestrator.shutdown()
        logger.info("Coaching server stopped")

    # ---- WebSocket: /ws/chat ----

    @app.websocket("/ws/chat")
    async def chat_websocket(websocket: WebSocket):
        """Agent-mediated coaching WebSocket endpoint.

        Client sends:
            { "type": "chat", "message": "why did you move there?" }
            { "type": "new_game" }
            { "type": "set_difficulty", "level": 4 }

        Server responds:
            { "type": "coach_response", "message": "...", "data": {...} }
            { "type": "error", "message": "..." }
        """
        await websocket.accept()
        logger.info("[WS/chat] Client connected")

        # LLM smoke test — notify client of gateway status
        try:
            llm_status = await orchestrator.smoke_test_llm()
            await websocket.send_json({
                "type": "system",
                "message": (
                    f"LLM gateway: {'connected' if llm_status['ok'] and not llm_status.get('is_mock') else 'using mock responses'} "
                    f"(provider: {llm_status['provider']}, "
                    f"latency: {llm_status['latency_ms']}ms)"
                ),
                "data": {"llm_status": llm_status},
            })
        except Exception as e:
            logger.error(f"[WS/chat] LLM smoke test failed: {e}")

        # Send onboarding prompt only if not already completed this session
        if not orchestrator.state.onboarding_complete:
            try:
                onboarding_response = await orchestrator.start_onboarding()
                await websocket.send_json({
                    "type": "onboarding",
                    "source": onboarding_response.source,
                    "message": onboarding_response.message,
                    "data": onboarding_response.data,
                })
            except Exception as e:
                logger.error(f"[WS/chat] Failed to send onboarding: {e}")
        else:
            logger.info("[WS/chat] Onboarding already complete, skipping")

        try:
            while True:
                raw = await websocket.receive_text()
                logger.info(f"[WS/chat] <<< {raw[:120]}")

                try:
                    data = json.loads(raw)
                    msg_type = data.get("type", "")

                    if msg_type == "chat":
                        message = data.get("message", "")

                        # Scan user message for Kibo animation keywords
                        kibo_cmd = detect_animation(message)
                        if kibo_cmd:
                            logger.info(f"[WS/chat] Kibo animation detected: {kibo_cmd}")
                            await broadcast_to_kibo(kibo_cmd)

                        response = await orchestrator.process_input(message)

                        # Also scan coach response for animation keywords
                        coach_kibo_cmd = detect_animation(response.message)
                        if coach_kibo_cmd and coach_kibo_cmd != kibo_cmd:
                            logger.info(f"[WS/chat] Kibo animation from coach: {coach_kibo_cmd}")
                            await broadcast_to_kibo(coach_kibo_cmd)

                        await websocket.send_json({
                            "type": "coach_response",
                            "source": response.source,
                            "response_type": response.response_type.value,
                            "message": response.message,
                            "data": response.data,
                        })

                    elif msg_type == "onboarding_answer":
                        selection = data.get("selection", "")
                        response = await orchestrator.process_input(selection)
                        # Extract onboarding data from OutputAgent wrapper
                        inner_data = response.data.get("outputs", {}).get("ui_text", {}).get("data", {})
                        onboarding_data = inner_data if inner_data.get("step") else response.data
                        await websocket.send_json({
                            "type": "onboarding",
                            "source": response.source,
                            "message": response.message,
                            "data": onboarding_data,
                        })

                    elif msg_type == "new_game":
                        await orchestrator.new_game()
                        # Re-run onboarding for the new session
                        ob_resp = await orchestrator.start_onboarding()
                        await websocket.send_json({
                            "type": "onboarding",
                            "source": ob_resp.source,
                            "message": ob_resp.message,
                            "data": ob_resp.data,
                        })

                    elif msg_type == "set_difficulty":
                        level = data.get("level", 4)
                        orchestrator.state.difficulty = level
                        await websocket.send_json({
                            "type": "system",
                            "message": f"Difficulty set to {level}.",
                        })

                    elif msg_type == "get_state":
                        await websocket.send_json({
                            "type": "session_state",
                            "data": orchestrator.state.to_dict(),
                        })

                    elif msg_type == "get_agents":
                        agents_info = {
                            name: {
                                "enabled": agent.is_enabled,
                                "name": agent.name,
                            }
                            for name, agent in orchestrator._agents.items()
                        }
                        await websocket.send_json({
                            "type": "agents",
                            "data": agents_info,
                        })

                    elif msg_type == "move_event":
                        # Frontend notifies us after a move is confirmed by the engine
                        # This triggers coaching analysis WITHOUT re-applying the move
                        move_str = data.get("move", "")
                        fen = data.get("fen", "")
                        side = data.get("side", "red")
                        result = data.get("result", "in_progress")
                        is_check = data.get("is_check", False)
                        score = data.get("score", 0)

                        logger.info(
                            f"[WS/chat] move_event: {side} {move_str} "
                            f"(result={result}, check={is_check})"
                        )

                        coaching_response = await orchestrator.analyze_move_event(
                            move_str=move_str,
                            fen=fen,
                            side=side,
                            result=result,
                            is_check=is_check,
                            score=score,
                        )

                        if coaching_response:
                            await websocket.send_json({
                                "type": "coach_response",
                                "source": coaching_response.source,
                                "response_type": coaching_response.response_type.value,
                                "message": coaching_response.message,
                                "data": coaching_response.data,
                            })

                    elif msg_type == "get_agent_graph":
                        await websocket.send_json({
                            "type": "agent_state_graph",
                            "data": state_tracker.get_graph_state(),
                        })

                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Unknown message type: {msg_type}",
                        })

                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON",
                    })
                except Exception as e:
                    logger.exception(f"[WS/chat] Error processing message: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })

        except WebSocketDisconnect:
            logger.info("[WS/chat] Client disconnected")
        except Exception as e:
            logger.error(f"[WS/chat] Connection error: {e}")

    # ---- Helper: broadcast command to Kibo viewers ----

    async def broadcast_to_kibo(command: dict) -> None:
        """Send an animation command to all connected Kibo 3D viewers."""
        if not kibo_viewers:
            return
        payload = json.dumps(command)
        dead: list = []
        for ws in kibo_viewers:
            try:
                await ws.send_text(payload)  # type: ignore[attr-defined]
            except Exception:
                dead.append(ws)
        for ws in dead:
            kibo_viewers.discard(ws)

    # ---- WebSocket: /ws/kibo ----

    @app.websocket("/ws/kibo")
    async def kibo_websocket(websocket: WebSocket):
        """Kibo 3D viewer WebSocket — receives animation commands.

        The server pushes KiboCommand JSON to the viewer whenever
        keyword detection triggers an animation.  The viewer can
        also send {"type": "getStatus"} to request its own status.
        """
        await websocket.accept()
        kibo_viewers.add(websocket)
        logger.info(f"[WS/kibo] Viewer connected ({len(kibo_viewers)} total)")

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                    msg_type = data.get("type", "")

                    if msg_type == "getStatus":
                        await websocket.send_json({
                            "type": "status",
                            "kibo_viewers": len(kibo_viewers),
                        })
                    else:
                        logger.debug(f"[WS/kibo] Unknown message: {msg_type}")
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"[WS/kibo] Error: {e}")
        finally:
            kibo_viewers.discard(websocket)
            logger.info(f"[WS/kibo] Viewer disconnected ({len(kibo_viewers)} total)")

    # ---- REST Endpoints ----

    from pydantic import BaseModel

    class ChatRequest(BaseModel):
        message: str
        state: str = ""
        history: str = ""

    @app.post("/chat")
    async def chat_rest(req: ChatRequest):
        """REST endpoint for chat."""
        if not orchestrator:
            return {"response": "Server not initialized"}
        try:
            response = await orchestrator.process_input(req.message)
            return {"response": response.message}
        except Exception as e:
            logger.exception("Chat request failed")
            return {"response": f"Error: {e}"}

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        engine_connected = (
            orchestrator.engine_agent._engine.is_connected
            if orchestrator and orchestrator.engine_agent._engine
            else False
        )
        return {
            "status": "ok",
            "engine_connected": engine_connected,
            "agents_count": len(orchestrator._agents) if orchestrator else 0,
        }

    @app.get("/health/llm")
    async def health_llm():
        """LLM gateway smoke test endpoint."""
        if not orchestrator:
            return {"ok": False, "error": "Server not initialized"}
        return await orchestrator.smoke_test_llm()

    @app.get("/agents")
    async def list_agents():
        """List all registered agents and their status."""
        if not orchestrator:
            return {"error": "Server not initialized"}
        return {
            name: {
                "enabled": agent.is_enabled,
                "name": agent.name,
            }
            for name, agent in orchestrator._agents.items()
        }

    @app.post("/agents/{agent_name}/toggle")
    async def toggle_agent(agent_name: str, enable: bool = True):
        """Enable or disable a specific agent."""
        if not orchestrator:
            return {"error": "Server not initialized"}
        if enable:
            success = orchestrator.enable_agent(agent_name)
        else:
            success = orchestrator.disable_agent(agent_name)
        return {"agent": agent_name, "enabled": enable, "success": success}

    # ---- Agent State Visualization Endpoints ----

    @app.get("/agent-state/graph")
    async def get_agent_graph():
        """Get the current agent state graph for visualization.

        Returns nodes (agents) with their current status and
        edges (transitions) with activation state.
        """
        return state_tracker.get_graph_state()

    @app.get("/agent-state/log")
    async def get_agent_state_log(last_n: int = 50):
        """Get recent state transition log entries for debugging."""
        return {"transitions": state_tracker.get_session_log(last_n=last_n)}

    return app


# ========================
#     ENTRY POINT
# ========================

app = create_app()

if __name__ == "__main__":
    try:
        import uvicorn
        uvicorn.run(
            "app:app",
            host=SERVER_HOST,
            port=SERVER_PORT,
            reload=True,
            log_level="info",
        )
    except ImportError:
        logger.error("uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)
