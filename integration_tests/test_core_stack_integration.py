from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from conftest import (
    BLACK_TO_MOVE_FEN,
    STARTING_FEN,
    get_json,
    get_text,
    post_json,
    read_sse_events,
)

ILLEGAL_CV_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/R8/9/P1P1P1P1P/1C5C1/9/1NBAKABNR b - - 0 2"


async def recv_type(ws, expected_type: str, *, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(f"Timed out waiting for WS message type {expected_type!r}")
        raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))
        payload = json.loads(raw)
        if payload.get("type") == expected_type:
            return payload


async def play_move_via_engine_ws(move: str, *, reset_first: bool = False) -> dict:
    async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
        await recv_type(ws, "state")
        if reset_first:
            await ws.send(json.dumps({"type": "reset"}))
            await recv_type(ws, "state")
        await ws.send(json.dumps({"type": "move", "move": move}))
        return await recv_type(ws, "move_result")


def test_core_services_health_and_basic_contracts(core_stack: dict[str, bool]) -> None:
    status, engine = get_json("http://127.0.0.1:8080/health")
    assert status == 200
    assert engine["status"] == "ok"

    status, bridge = get_json("http://127.0.0.1:5003/health")
    assert status == 200
    assert bridge["status"] == "ok"

    status, chromadb = get_json("http://127.0.0.1:8000/api/v1/heartbeat")
    assert status == 200
    assert chromadb.get("nanosecond heartbeat")

    status, embedding = get_json("http://127.0.0.1:8100/health")
    assert status == 200
    assert embedding["status"] == "ok"

    status, go_coaching = get_json("http://127.0.0.1:5002/health")
    assert status == 200
    assert go_coaching["status"] == "ok"

    status, coaching = get_json("http://127.0.0.1:5001/health")
    assert status == 200
    assert coaching["status"] == "ok"
    assert isinstance(coaching["engine_connected"], bool)
    assert coaching["agents_count"] > 0

    status, metrics = get_text("http://127.0.0.1:5002/metrics")
    assert status == 200
    assert "go_" in metrics or "process_" in metrics or "http_" in metrics


def test_embedding_service_returns_vectors(core_stack: dict[str, bool]) -> None:
    status, body = post_json(
        "http://127.0.0.1:8100/embed",
        {"texts": ["central cannon opening", "horse develops with tempo"]},
        timeout=60.0,
    )
    assert status == 200, body
    embeddings = body["embeddings"]
    assert len(embeddings) == 2
    assert all(isinstance(vector, list) and len(vector) > 8 for vector in embeddings)
    assert all(isinstance(vector[0], (int, float)) for vector in embeddings)


def test_state_bridge_rest_sse_and_compat_endpoints(reset_bridge_state: dict[str, object]) -> None:
    def trigger() -> None:
        for url, payload in [
            ("http://127.0.0.1:5003/state/fen", {"fen": BLACK_TO_MOVE_FEN, "source": "engine"}),
            ("http://127.0.0.1:5003/state/best-move", {"from_sq": "b0", "to_sq": "c2"}),
            ("http://127.0.0.1:5003/state/led-command", {"command": "off"}),
            (
                "http://127.0.0.1:5003/opponent",
                {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
            ),
        ]:
            status, body = post_json(url, payload, timeout=20.0)
            assert status == 200, body

    events = read_sse_events("http://127.0.0.1:5003/state/events", 5, trigger=trigger)
    assert [event["type"] for event in events] == [
        "state_sync",
        "fen_update",
        "best_move",
        "led_command",
        "move_made",
    ]

    assert events[0]["data"]["fen"] == STARTING_FEN
    assert events[1]["data"]["fen"] == BLACK_TO_MOVE_FEN
    assert events[2]["data"] == {"from": "b0", "to": "c2"}
    assert events[3]["data"] == {"command": "off"}
    assert events[4]["data"]["from"] == "a0"
    assert events[4]["data"]["to"] == "a1"
    assert events[4]["data"]["source"] == "opponent"

    status, snapshot = get_json("http://127.0.0.1:5003/state")
    assert status == 200
    assert snapshot["fen"] == BLACK_TO_MOVE_FEN
    assert snapshot["side_to_move"] == "black"
    assert snapshot["best_move_from"] == "b0"
    assert snapshot["best_move_to"] == "c2"
    assert snapshot["leds_off"] is True
    assert snapshot["last_move"]["from"] == "a0"
    assert snapshot["last_move"]["to"] == "a1"
    assert snapshot["move_count"] >= 1

    status, body = post_json("http://127.0.0.1:5003/fen", {"fen": STARTING_FEN, "source": "engine"})
    assert status == 200
    assert body["status"] == "FEN updated"


def test_bridge_select_flow_emits_piece_selected_for_led_overlay(reset_bridge_state: dict[str, object]) -> None:
    def trigger() -> None:
        status, body = post_json(
            "http://127.0.0.1:5003/state/select",
            {"square": "b0"},
            timeout=30.0,
        )
        assert status == 200, body
        assert "c2" in body["targets"]

    events = read_sse_events("http://127.0.0.1:5003/state/events", 2, trigger=trigger)
    assert events[0]["type"] == "state_sync"
    assert events[1]["type"] == "piece_selected"
    assert events[1]["data"]["square"] == "b0"
    assert "c2" in events[1]["data"]["targets"]

    status, snapshot = get_json("http://127.0.0.1:5003/state")
    assert status == 200, snapshot
    assert snapshot["selected_square"] == "b0"
    assert "c2" in snapshot["legal_moves"]


@pytest.mark.xfail(
    reason=(
        "The Rust engine WebSocket currently responds per-client and does not "
        "broadcast direct move events to the bridge relay connection."
    ),
    strict=False,
)
def test_bridge_observes_direct_engine_move_via_sse(reset_bridge_state: dict[str, object]) -> None:
    def trigger() -> None:
        result = asyncio.run(play_move_via_engine_ws("b0c2", reset_first=False))
        assert result["valid"] is True

    events = read_sse_events("http://127.0.0.1:5003/state/events", 2, trigger=trigger, timeout=30.0)
    assert events[0]["type"] == "state_sync"
    assert events[1]["type"] == "move_made"
    assert events[1]["data"]["source"] == "player"
    assert events[1]["data"]["from"] == "b0"
    assert events[1]["data"]["to"] == "c2"
    assert "fen" in events[1]["data"]


def test_physical_board_end_turn_success_flow(reset_bridge_state: dict[str, object]) -> None:
    accepted_fen: str | None = None

    def trigger() -> None:
        nonlocal accepted_fen
        status, body = post_json(
            "http://127.0.0.1:5003/state/led-command",
            {"command": "off"},
            timeout=20.0,
        )
        assert status == 200, body

        status, move_result = post_json(
            "http://127.0.0.1:5003/engine/make-move",
            {"fen": STARTING_FEN, "move": "b0c2"},
            timeout=30.0,
        )
        assert status == 200, move_result
        assert move_result["valid"] is True
        accepted_fen = move_result["fen"]

        status, body = post_json(
            "http://127.0.0.1:5003/state/fen",
            {"fen": accepted_fen, "source": "cv"},
            timeout=45.0,
        )
        assert status == 200, body
        assert body["accepted"] is True
        assert body["move"] == "b0c2"

    events = read_sse_events("http://127.0.0.1:5003/state/events", 6, trigger=trigger, timeout=60.0)
    assert [event["type"] for event in events] == [
        "state_sync",
        "led_command",
        "led_command",
        "fen_update",
        "best_move",
        "move_made",
    ]
    assert events[1]["data"] == {"command": "off"}
    assert events[2]["data"] == {"command": "on"}
    assert events[3]["data"]["source"] == "cv"
    assert events[3]["data"]["fen"] == accepted_fen
    assert events[4]["data"]["from"]
    assert events[4]["data"]["to"]
    assert events[5]["data"]["source"] == "ai"
    assert events[5]["data"]["fen"]

    status, snapshot = get_json("http://127.0.0.1:5003/state")
    assert status == 200, snapshot
    assert snapshot["cv_fen"] == accepted_fen
    assert snapshot["fen"] == events[5]["data"]["fen"]
    assert snapshot["best_move_from"] == events[4]["data"]["from"]
    assert snapshot["best_move_to"] == events[4]["data"]["to"]
    assert snapshot["leds_off"] is False
    assert snapshot["move_count"] >= 2


def test_physical_board_end_turn_failure_flow_keeps_state_frozen(reset_bridge_state: dict[str, object]) -> None:
    def trigger() -> None:
        status, body = post_json(
            "http://127.0.0.1:5003/state/led-command",
            {"command": "off"},
            timeout=20.0,
        )
        assert status == 200, body

        status, body = post_json(
            "http://127.0.0.1:5003/state/fen",
            {"fen": ILLEGAL_CV_FEN, "source": "cv"},
            timeout=30.0,
        )
        assert status == 422, body
        assert body["accepted"] is False
        assert body["reason"] == "move not in legal moves"

    events = read_sse_events("http://127.0.0.1:5003/state/events", 4, trigger=trigger, timeout=45.0)
    assert [event["type"] for event in events] == [
        "state_sync",
        "led_command",
        "cv_validation_error",
        "led_command",
    ]
    assert events[1]["data"] == {"command": "off"}
    assert events[2]["data"]["reason"] == "move not in legal moves"
    assert events[2]["data"]["current_fen"] == STARTING_FEN
    assert events[3]["data"] == {"command": "on"}

    status, snapshot = get_json("http://127.0.0.1:5003/state")
    assert status == 200, snapshot
    assert snapshot["fen"] == STARTING_FEN
    assert snapshot["cv_fen"] == ILLEGAL_CV_FEN
    assert snapshot["move_count"] == 0
    assert snapshot["last_move"] is None
    assert snapshot["leds_off"] is False


@pytest.mark.asyncio
async def test_engine_websocket_protocol(reset_bridge_state: dict[str, object]) -> None:
    async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
        initial = await recv_type(ws, "state")
        assert "fen" in initial
        assert initial["side_to_move"] in {"red", "black"}

        await ws.send(json.dumps({"type": "reset"}))
        reset_state = await recv_type(ws, "state")
        assert reset_state["side_to_move"] == "red"

        await ws.send(json.dumps({"type": "get_state"}))
        state = await recv_type(ws, "state")
        assert state["fen"] == STARTING_FEN

        await ws.send(json.dumps({"type": "move", "move": "b0c2"}))
        legal = await recv_type(ws, "move_result")
        assert legal["valid"] is True
        assert legal["move"] == "b0c2"

        await ws.send(json.dumps({"type": "move", "move": "a9a5"}))
        illegal = await recv_type(ws, "move_result")
        assert illegal["valid"] is False
        assert illegal["reason"]

        await ws.send(json.dumps({"type": "ai_move", "difficulty": 1}))
        ai_move = await recv_type(ws, "ai_move")
        assert len(ai_move["move"]) >= 4
        assert "fen" in ai_move


def test_state_bridge_engine_proxy_endpoints(reset_bridge_state: dict[str, object]) -> None:
    status, body = post_json("http://127.0.0.1:5003/engine/validate-fen", {"fen": STARTING_FEN}, timeout=30.0)
    assert status == 200, body
    assert body["valid"] is True

    status, body = post_json("http://127.0.0.1:5003/engine/validate-fen", {"fen": "not a fen"}, timeout=30.0)
    assert status == 200, body
    assert body["valid"] is False

    status, body = post_json(
        "http://127.0.0.1:5003/engine/legal-moves",
        {"fen": STARTING_FEN, "square": "b0"},
        timeout=30.0,
    )
    assert status == 200, body
    assert body["type"] == "legal_moves"
    assert body["square"] == "b0"
    assert "c2" in body["targets"]

    status, body = post_json(
        "http://127.0.0.1:5003/engine/is-move-legal",
        {"fen": STARTING_FEN, "move": "b0c2"},
        timeout=30.0,
    )
    assert status == 200, body
    assert body["legal"] is True
    assert "c2" in body["targets"]

    status, body = post_json(
        "http://127.0.0.1:5003/engine/is-move-legal",
        {"fen": STARTING_FEN, "move": "a9a5"},
        timeout=30.0,
    )
    assert status == 200, body
    assert body["legal"] is False

    status, body = post_json(
        "http://127.0.0.1:5003/engine/make-move",
        {"fen": STARTING_FEN, "move": "b0c2"},
        timeout=30.0,
    )
    assert status == 200, body
    assert body["type"] == "move_result"
    assert body["valid"] is True
    assert body["move"] == "b0c2"

    status, body = post_json(
        "http://127.0.0.1:5003/engine/analyze",
        {"fen": STARTING_FEN, "depth": 2},
        timeout=60.0,
    )
    assert status == 200, body
    assert body["fen"] == STARTING_FEN
    assert body["side_to_move"] in {"red", "black"}
    assert isinstance(body["move_features"], dict)
    assert isinstance(body["search_score"], int)

    status, body = post_json(
        "http://127.0.0.1:5003/engine/batch-analyze",
        {"moves": [{"fen": STARTING_FEN, "move_str": "b0c2"}]},
        timeout=60.0,
    )
    assert status == 200, body
    assert len(body) == 1
    assert body[0]["move_metadata"]["move_str"] == "b0c2"
    assert "classification" in body[0]
    assert "search_metrics" in body[0]

    status, body = post_json(
        "http://127.0.0.1:5003/engine/suggest",
        {"fen": STARTING_FEN, "depth": 2},
        timeout=60.0,
    )
    assert status == 200, body
    assert body["type"] == "suggestion"
    assert len(body["move"]) >= 4


def test_go_coaching_bridge_backed_endpoints(reset_bridge_state: dict[str, object]) -> None:
    status, body = post_json(
        "http://127.0.0.1:5002/coach/features",
        {"fen": STARTING_FEN, "features": "material,mobility,king_safety"},
        timeout=90.0,
    )
    assert status == 200, body
    assert body["fen"] == STARTING_FEN
    assert body["side_to_move"] in {"red", "black"}
    assert "material" in body
    assert "mobility" in body
    assert "red_king_safety" in body
    assert "black_king_safety" in body

    status, body = post_json(
        "http://127.0.0.1:5002/coach/classify-move",
        {"fen": STARTING_FEN, "move": "b0c2"},
        timeout=90.0,
    )
    assert status == 200, body
    assert body["move"] == "b0c2"
    assert body["classification"]["category"]
    assert isinstance(body["alternatives"], list)
    assert isinstance(body["centipawn_loss"], int)

    status, body = post_json(
        "http://127.0.0.1:5002/dashboard/chat",
        {
            "message": "Give one concise strategic tip for this Xiangqi position.",
            "session_id": "integration-suite",
            "fen": STARTING_FEN,
            "move": "b0c2",
        },
        timeout=90.0,
    )
    assert status == 200, body
    assert body["session_id"] == "integration-suite"
    assert isinstance(body["response"], str)
    assert body["response"].strip()


def test_python_coaching_http_contracts(core_stack: dict[str, bool]) -> None:
    status, body = get_json("http://127.0.0.1:5001/health/llm", timeout=30.0)
    assert status == 200, body
    assert "ok" in body
    assert "provider" in body

    status, body = get_json("http://127.0.0.1:5001/agents", timeout=30.0)
    assert status == 200, body
    assert isinstance(body, dict)
    assert body

    status, body = get_json("http://127.0.0.1:5001/agent-state/graph", timeout=30.0)
    assert status == 200, body
    assert "nodes" in body
    assert "edges" in body
