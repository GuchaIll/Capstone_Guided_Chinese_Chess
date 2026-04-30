from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
import uuid

import pytest
import websockets

from conftest import (
    BLACK_TO_MOVE_FEN,
    STARTING_FEN,
    get_json,
    get_text,
    post_json,
    read_sse_events,
    read_sse_events_for_duration,
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
    async with websockets.connect("ws://127.0.0.1:5003/ws") as ws:
        await recv_type(ws, "state")
        if reset_first:
            await ws.send(json.dumps({"type": "reset"}))
            await recv_type(ws, "state")
        await ws.send(json.dumps({"type": "move", "move": move}))
        return await recv_type(ws, "move_result")


def test_core_services_health_and_basic_contracts(core_stack: dict[str, bool]) -> None:
    status, bridge = get_json("http://127.0.0.1:5003/health")
    assert status == 200
    assert bridge["status"] == "ok"
    assert bridge["authoritative_bundle_healthy"] is True

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


def test_bridge_observes_bridge_websocket_move_via_sse(reset_bridge_state: dict[str, object]) -> None:
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
        "cv_capture",
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
async def test_bridge_websocket_protocol(reset_bridge_state: dict[str, object]) -> None:
    async with websockets.connect("ws://127.0.0.1:5003/ws") as ws:
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


# ─── Architectural-revision acceptance criteria ────────────────────────────────


def test_helper_requests_produce_no_gameplay_sse_events(reset_bridge_state: dict[str, object]) -> None:
    """Architecture: helper call via command channel → observer sees zero gameplay events.

    Calls every stateless helper endpoint (validate-fen, legal-moves, suggest,
    make-move-on-snapshot) and asserts that none of them emit a gameplay SSE event
    (move_made, game_reset, fen_update, ai_move) to observers.
    """
    helper_calls = [
        ("http://127.0.0.1:5003/engine/validate-fen", {"fen": STARTING_FEN}),
        ("http://127.0.0.1:5003/engine/legal-moves", {"fen": STARTING_FEN, "square": "b0"}),
        ("http://127.0.0.1:5003/engine/suggest", {"fen": STARTING_FEN, "depth": 1}),
        ("http://127.0.0.1:5003/engine/make-move", {"fen": STARTING_FEN, "move": "b0c2"}),
        ("http://127.0.0.1:5003/engine/analyze", {"fen": STARTING_FEN, "depth": 1}),
    ]

    # Start SSE reader in background before calling helpers.
    events: list[dict] = []
    ready = threading.Event()

    def _subscribe() -> None:
        import urllib.request as _ur

        req = _ur.Request(
            "http://127.0.0.1:5003/state/events",
            headers={"Accept": "text/event-stream"},
        )
        data_lines: list[str] = []
        try:
            with _ur.urlopen(req, timeout=12.0) as resp:
                ready.set()
                deadline = time.time() + 10.0
                while time.time() < deadline:
                    try:
                        raw = resp.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    text = raw.decode("utf-8").strip()
                    if not text:
                        if data_lines:
                            events.append(json.loads("\n".join(data_lines)))
                            data_lines.clear()
                    elif text.startswith("data: "):
                        data_lines.append(text[6:])
        except Exception:
            pass
        finally:
            ready.set()

    t = threading.Thread(target=_subscribe, daemon=True)
    t.start()
    ready.wait(timeout=5.0)

    for url, body in helper_calls:
        status, resp = post_json(url, body, timeout=30.0)
        assert status == 200, f"Helper call failed: {url} → {resp}"

    # Allow a brief window for any spurious events to arrive.
    time.sleep(1.5)

    gameplay_types = {"move_made", "game_reset", "fen_update", "ai_move"}
    gameplay_events = [e for e in events if e.get("type") in gameplay_types]
    assert gameplay_events == [], (
        f"Helper calls unexpectedly emitted gameplay SSE events: {gameplay_events}"
    )


@pytest.mark.asyncio
async def test_bridge_rejects_duplicate_command_id_integration(
    reset_bridge_state: dict[str, object],
) -> None:
    """Architecture: duplicate command_id is rejected within the live bridge session.

    First move with an explicit command_id must succeed; an immediate retry with
    the same command_id (which may be a network retry scenario) must be rejected
    with an error response before any second state mutation occurs.
    """
    cmd_id = uuid.uuid4().hex

    async with websockets.connect("ws://127.0.0.1:5003/ws") as ws:
        await recv_type(ws, "state")

        # First submission — must succeed.
        await ws.send(json.dumps({"type": "move", "move": "b0c2", "command_id": cmd_id}))
        result1 = await recv_type(ws, "move_result", timeout=20.0)
        assert result1["valid"] is True, f"First move should succeed: {result1}"
        assert result1.get("command_id") == cmd_id

        # Retry with same command_id — must be rejected as a duplicate.
        await ws.send(json.dumps({"type": "move", "move": "b0c2", "command_id": cmd_id}))
        result2 = await recv_type(ws, "error", timeout=10.0)
        assert result2["message"] == "Duplicate command_id", (
            f"Expected duplicate rejection, got: {result2}"
        )
        assert result2.get("command_id") == cmd_id


def test_two_sse_subscribers_see_identical_move_event(
    reset_bridge_state: dict[str, object],
) -> None:
    """Architecture: React-like client sends move → LED-like observer sees same event.

    Two independent SSE subscribers both open before a single WS move is issued.
    Both must receive the same move_made payload, proving fan-out symmetry.
    """
    events_a: list[dict] = []
    events_b: list[dict] = []
    ready_a = threading.Event()
    ready_b = threading.Event()

    def _sub(collector: list, ready: threading.Event) -> None:
        import urllib.request as _ur

        req = _ur.Request(
            "http://127.0.0.1:5003/state/events",
            headers={"Accept": "text/event-stream"},
        )
        data_lines: list[str] = []
        try:
            with _ur.urlopen(req, timeout=35.0) as resp:
                ready.set()
                deadline = time.time() + 30.0
                while time.time() < deadline and len(collector) < 2:
                    try:
                        raw = resp.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    text = raw.decode("utf-8").strip()
                    if not text:
                        if data_lines:
                            collector.append(json.loads("\n".join(data_lines)))
                            data_lines.clear()
                    elif text.startswith("data: "):
                        data_lines.append(text[6:])
        except Exception:
            pass
        finally:
            ready.set()

    ta = threading.Thread(target=_sub, args=(events_a, ready_a), daemon=True)
    tb = threading.Thread(target=_sub, args=(events_b, ready_b), daemon=True)
    ta.start()
    tb.start()

    # Wait for both connections to be established before triggering the move.
    ready_a.wait(timeout=8.0)
    ready_b.wait(timeout=8.0)
    time.sleep(0.2)

    # Trigger a move via bridge WS.
    result = asyncio.run(play_move_via_engine_ws("b0c2"))
    assert result["valid"] is True

    ta.join(timeout=35.0)
    tb.join(timeout=35.0)

    assert len(events_a) >= 2, f"Subscriber A received too few events: {events_a}"
    assert len(events_b) >= 2, f"Subscriber B received too few events: {events_b}"

    move_a = next((e for e in events_a if e.get("type") == "move_made"), None)
    move_b = next((e for e in events_b if e.get("type") == "move_made"), None)

    assert move_a is not None, f"Subscriber A never saw move_made: {events_a}"
    assert move_b is not None, f"Subscriber B never saw move_made: {events_b}"
    assert move_a["data"]["from"] == move_b["data"]["from"], (
        f"Fan-out mismatch: A={move_a}, B={move_b}"
    )
    assert move_a["data"]["to"] == move_b["data"]["to"], (
        f"Fan-out mismatch: A={move_a}, B={move_b}"
    )
    assert move_a["data"]["fen"] == move_b["data"]["fen"], (
        f"FEN mismatch between subscribers: A={move_a}, B={move_b}"
    )


@pytest.mark.asyncio
async def test_concurrent_moves_from_two_clients_are_serialized(
    reset_bridge_state: dict[str, object],
) -> None:
    """Architecture: concurrent move attempts serialized by FIFO queue; state deterministic.

    Two WebSocket clients both connect to a freshly reset board and immediately
    send a different (but both individually legal) red opening move near-simultaneously.
    The bridge FIFO queue must serialize them: exactly one succeeds and one fails
    (the second arrives after the board is already advanced to black's turn).
    """

    async def _connect_and_move(move: str) -> dict:
        async with websockets.connect("ws://127.0.0.1:5003/ws") as ws:
            await recv_type(ws, "state", timeout=10.0)
            await ws.send(json.dumps({"type": "move", "move": move}))
            return await recv_type(ws, "move_result", timeout=20.0)

    def _run(move: str) -> dict:
        return asyncio.run(_connect_and_move(move))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_run, "b0c2")   # left-side red knight
        f2 = pool.submit(_run, "h0g2")   # right-side red knight
        results = [f1.result(timeout=35.0), f2.result(timeout=35.0)]

    valid_results = [r for r in results if r["valid"]]
    invalid_results = [r for r in results if not r["valid"]]

    assert len(valid_results) == 1, (
        f"Expected exactly 1 valid move, got {len(valid_results)}: {results}"
    )
    assert len(invalid_results) == 1, (
        f"Expected exactly 1 invalid move, got {len(invalid_results)}: {results}"
    )

    # Both clients must report *some* FEN — state was not corrupted.
    winning_fen = valid_results[0].get("fen", "")
    assert winning_fen, f"Winning move result missing fen: {valid_results[0]}"

    # The final bridge snapshot must agree with the winner's FEN.
    from conftest import get_json as _get_json

    status, snapshot = _get_json("http://127.0.0.1:5003/state", timeout=10.0)
    assert status == 200
    assert snapshot["fen"] == winning_fen, (
        f"Bridge snapshot FEN {snapshot['fen']!r} does not match "
        f"winning move FEN {winning_fen!r}"
    )
