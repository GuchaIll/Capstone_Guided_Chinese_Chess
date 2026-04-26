from __future__ import annotations

import asyncio
import json

from state import STARTING_FEN


ALT_FEN = "9/9/9/9/9/9/9/9/9/9 b - - 0 1"
CV_BASE_FEN = "4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1"
CV_SUCCESS_FEN = "4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2"
AMBIGUOUS_CV_FEN = "9/4k4/9/9/9/9/9/9/R8/4K4 b - - 0 2"
ILLEGAL_CV_FEN = "4k4/9/9/9/9/9/9/9/9/4KR3 b - - 0 2"


def test_health_and_initial_state(client):
    health = client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "ok"
    assert "authoritative_bundle_healthy" in health_body
    assert "relay" in health_body
    assert health_body["snapshot"]["fen"] == STARTING_FEN
    assert health_body["snapshot"]["event_seq"] == 0

    state = client.get("/state")
    assert state.status_code == 200
    assert state.json() == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "game_result": "in_progress",
        "is_check": False,
        "event_seq": 0,
        "last_move": None,
        "move_count": 0,
        "selected_square": None,
        "legal_moves": [],
        "best_move_from": None,
        "best_move_to": None,
        "cv_fen": None,
        "leds_off": False,
    }


async def test_post_engine_fen_updates_state_and_emits_fen_update(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    task = await capture_sse_events()

    response = client.post("/state/fen", json={"fen": ALT_FEN, "source": "engine"})

    assert response.status_code == 200
    assert response.json() == {"status": "FEN updated", "source": "engine"}

    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["type"] == "fen_update"
    assert events[0]["data"]["fen"] == ALT_FEN
    assert events[0]["data"]["source"] == "engine"
    assert events[0]["data"]["side_to_move"] == "black"

    assert state.fen == ALT_FEN
    assert state.side_to_move == "black"
    assert state.cv_fen is None


async def test_post_cv_fen_accepts_valid_move_and_emits_led_resume_then_fen_update_and_best_move(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, relay = bridge_testbed
    state.apply_fen(CV_BASE_FEN, source="engine")
    task = await capture_sse_events(expected=3)

    response = client.post("/state/fen", json={"fen": CV_SUCCESS_FEN, "source": "cv"})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "status": "FEN updated",
        "source": "cv",
        "move": "a0a1",
    }

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["led_command", "fen_update", "best_move"]
    assert events[0]["data"] == {"command": "on"}
    assert events[1]["data"]["fen"] == CV_SUCCESS_FEN
    assert events[1]["data"]["source"] == "cv"
    assert events[2]["data"] == {"from": "b0", "to": "c2"}

    assert state.fen == CV_SUCCESS_FEN
    assert state.cv_fen == CV_SUCCESS_FEN
    assert state.last_move is not None
    assert state.last_move.from_sq == "a0"
    assert state.last_move.to_sq == "a1"
    assert state.best_move_from == "b0"
    assert state.best_move_to == "c2"
    assert state.leds_off is False
    assert relay.calls == [
        ("legal_moves_for_square", CV_BASE_FEN, "a0"),
        ("suggest", CV_SUCCESS_FEN, 5),
        ("ai_move", 4),
    ]


def test_post_cv_fen_ignores_duplicate_capture_within_short_window(client):
    first = client.post("/state/fen", json={"fen": "not a fen", "source": "cv"})
    second = client.post("/state/fen", json={"fen": "not a fen", "source": "cv"})

    assert first.status_code == 400
    assert second.status_code == 200
    assert second.json() == {
        "accepted": True,
        "duplicate": True,
        "source": "cv",
        "status": "Duplicate CV capture ignored",
    }


async def test_post_cv_fen_rejects_malformed_fen_and_emits_validation_error_and_led_restore(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, _ = bridge_testbed
    state.leds_off = True
    task = await capture_sse_events(expected=2)

    response = client.post("/state/fen", json={"fen": "not a fen", "source": "cv"})

    assert response.status_code == 400
    assert response.json() == {
        "accepted": False,
        "source": "cv",
        "reason": "malformed FEN",
    }

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["cv_validation_error", "led_command"]
    assert events[0]["data"]["cv_fen"] == "not a fen"
    assert events[0]["data"]["current_fen"] == STARTING_FEN
    assert events[0]["data"]["reason"] == "malformed FEN"
    assert events[1]["data"] == {"command": "on"}

    assert state.fen == STARTING_FEN
    assert state.cv_fen == "not a fen"
    assert state.leds_off is False


async def test_post_cv_fen_rejects_ambiguous_board_change(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, relay = bridge_testbed
    state.apply_fen(CV_BASE_FEN, source="engine")
    task = await capture_sse_events(expected=2)

    response = client.post("/state/fen", json={"fen": AMBIGUOUS_CV_FEN, "source": "cv"})

    assert response.status_code == 422
    assert "ambiguous board change" in response.json()["reason"]

    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["type"] == "cv_validation_error"
    assert "ambiguous board change" in events[0]["data"]["reason"]
    assert events[1]["type"] == "led_command"
    assert relay.calls == []
    assert state.fen == CV_BASE_FEN
    assert state.cv_fen == AMBIGUOUS_CV_FEN


async def test_post_cv_fen_rejects_illegal_derived_move(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, relay = bridge_testbed
    state.apply_fen(CV_BASE_FEN, source="engine")
    relay.legal_moves_by_square["a0"] = ["a2"]
    task = await capture_sse_events(expected=2)

    response = client.post("/state/fen", json={"fen": ILLEGAL_CV_FEN, "source": "cv"})

    assert response.status_code == 422
    assert response.json() == {
        "accepted": False,
        "source": "cv",
        "reason": "move not in legal moves",
    }

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["cv_validation_error", "led_command"]
    assert events[0]["data"]["reason"] == "move not in legal moves"
    assert relay.calls == [("legal_moves_for_square", CV_BASE_FEN, "a0")]
    assert state.fen == CV_BASE_FEN
    assert state.cv_fen == ILLEGAL_CV_FEN


async def test_post_move_records_state_and_emits_event(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    task = await capture_sse_events()

    response = client.post("/state/move", json={"from_sq": "a0", "to_sq": "a1", "piece": "R"})

    assert response.status_code == 200
    assert response.json() == {"status": "Move recorded"}
    events = await asyncio.wait_for(task, 2.0)

    assert events[0]["type"] == "move_made"
    assert events[0]["data"] == {
        "from": "a0",
        "to": "a1",
        "piece": "R",
        "source": "bridge",
    }
    assert state.last_move is not None
    assert state.last_move.from_sq == "a0"
    assert state.last_move.to_sq == "a1"
    assert state.last_move.piece == "R"
    assert len(state.move_history) == 1


async def test_post_best_move_stores_recommendation_and_emits_event(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    task = await capture_sse_events()

    response = client.post("/state/best-move", json={"from_sq": "b2", "to_sq": "b3"})

    assert response.status_code == 200
    assert response.json() == {"status": "Best move set"}
    events = await asyncio.wait_for(task, 2.0)

    assert events[0]["type"] == "best_move"
    assert events[0]["data"] == {"from": "b2", "to": "b3"}
    assert state.best_move_from == "b2"
    assert state.best_move_to == "b3"


async def test_post_led_command_updates_state_and_emits_event(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    task = await capture_sse_events()

    response = client.post("/state/led-command", json={"command": "off"})

    assert response.status_code == 200
    assert response.json() == {"status": "LED command 'off' published"}
    events = await asyncio.wait_for(task, 2.0)

    assert events[0]["type"] == "led_command"
    assert events[0]["data"] == {"command": "off"}
    assert state.leds_off is True


async def test_select_updates_selection_state_and_emits_piece_selected(client, bridge_testbed, capture_sse_events):
    _, state, _, relay = bridge_testbed
    relay.legal_moves_by_square["e3"] = ["e4", "e5"]
    task = await capture_sse_events()

    response = client.post("/state/select", json={"square": "e3"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "Selection forwarded to engine",
        "targets": ["e4", "e5"],
    }
    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["type"] == "piece_selected"
    assert events[0]["data"] == {"square": "e3", "targets": ["e4", "e5"]}
    assert state.selected_square == "e3"
    assert state.legal_moves == ["e4", "e5"]
    assert relay.calls == [("legal_moves_for_square", STARTING_FEN, "e3")]


def test_engine_passthrough_endpoints_forward_to_relay(client, bridge_testbed):
    _, _, _, relay = bridge_testbed

    move = client.post("/engine/move", json={"move": "a0a1"})
    ai_move = client.post("/engine/ai-move", json={"difficulty": 4})
    set_position = client.post("/engine/set-position", json={"fen": ALT_FEN, "source": "engine"})

    move_body = move.json()
    assert move_body["status"] == "Move forwarded to engine"
    assert isinstance(move_body["command_id"], str)
    assert ai_move.json() == {"status": "AI move requested"}
    assert set_position.json() == {"status": "Position forwarded to engine"}
    assert relay.calls == [
        ("move", "a0a1", move_body["command_id"]),
        ("ai_move", 4),
        ("set_position", ALT_FEN, None),
    ]


def test_engine_move_rejects_duplicate_command_id(client, bridge_testbed):
    _, _, _, relay = bridge_testbed

    first = client.post("/engine/move", json={"move": "a0a1", "command_id": "dup-1"})
    second = client.post("/engine/move", json={"move": "a0a1", "command_id": "dup-1"})

    assert first.status_code == 200
    assert first.json()["command_id"] == "dup-1"
    assert second.status_code == 409
    assert second.json() == {"error": "Duplicate command_id", "command_id": "dup-1"}
    assert relay.calls == [("move", "a0a1", "dup-1")]


def test_bridge_websocket_supports_state_and_helper_commands(client, bridge_testbed):
    _, _, _, relay = bridge_testbed
    relay.legal_moves_by_square["e3"] = ["e4", "e5"]

    with client.websocket_connect("/ws") as ws:
        # Bridge sends initial state snapshot on connect
        initial = ws.receive_json()
        assert initial["type"] == "state"
        assert initial["fen"] == STARTING_FEN

        ws.send_json({"type": "get_state"})
        state_message = ws.receive_json()
        assert state_message["type"] == "state"
        assert state_message["fen"] == STARTING_FEN

        ws.send_json({"type": "legal_moves", "square": "e3"})
        legal_moves = ws.receive_json()
        assert legal_moves == {
            "type": "legal_moves",
            "square": "e3",
            "targets": ["e4", "e5"],
        }

        ws.send_json({"type": "suggest", "difficulty": 4})
        suggestion = ws.receive_json()
        assert suggestion == {
            "type": "suggestion",
            "move": "b0c2",
            "score": 120,
        }

    assert relay.calls == [
        ("legal_moves_for_square", STARTING_FEN, "e3"),
        ("suggest", STARTING_FEN, 4),
    ]


def test_bridge_websocket_forwards_gameplay_and_rejects_duplicate_command_id(client, bridge_testbed):
    _, state, _, relay = bridge_testbed

    with client.websocket_connect("/ws") as ws:
        # Consume initial state snapshot sent on connect
        initial = ws.receive_json()
        assert initial["type"] == "state"

        ws.send_json({"type": "move", "move": "a0a1", "command_id": "ws-dup"})
        move_result = ws.receive_json()
        assert move_result == {
            "type": "move_result",
            "valid": True,
            "move": "a0a1",
            "fen": "fen-after-move",
            "result": "in_progress",
            "is_check": False,
            "command_id": "ws-dup",
        }

        ws.send_json({"type": "move", "move": "a0a1", "command_id": "ws-dup"})
        duplicate = ws.receive_json()
        assert duplicate == {
            "type": "error",
            "message": "Duplicate command_id",
            "command_id": "ws-dup",
        }

        ws.send_json({"type": "reset", "command_id": "ws-reset"})
        reset_result = ws.receive_json()
        assert reset_result == {
            "type": "state",
            "fen": STARTING_FEN,
            "side_to_move": "red",
            "result": "in_progress",
            "is_check": False,
            "seq": 0,
        }

    assert relay.calls == [
        ("move_and_wait", "a0a1", "ws-dup", 15.0),
        ("reset_and_wait", "ws-reset", 15.0),
    ]
    assert state.fen == STARTING_FEN


async def test_engine_reset_restores_starting_state_and_emits_game_reset(client, bridge_testbed, capture_sse_events):
    _, state, _, relay = bridge_testbed
    state.apply_move("a0", "a1", piece="R")
    state.apply_fen(ALT_FEN, source="cv")
    state.set_selection("a0", ["a1", "a2"])
    state.set_best_move("b2", "b3")
    state.leds_off = True

    task = await capture_sse_events()
    response = client.post("/engine/reset")

    assert response.status_code == 200
    response_body = response.json()
    assert response_body["status"] == "Game reset"
    assert isinstance(response_body["command_id"], str)
    events = await asyncio.wait_for(task, 2.0)

    assert relay.calls == [("reset", response_body["command_id"])]
    assert events[0]["type"] == "game_reset"
    assert state.fen == STARTING_FEN
    assert state.last_move is None
    assert state.move_history == []
    assert state.selected_square is None
    assert state.legal_moves == []
    assert state.best_move_from is None
    assert state.best_move_to is None
    assert state.cv_fen is None
    assert state.leds_off is False


async def test_compatibility_endpoints_match_bridge_contracts(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed

    fen_task = await capture_sse_events()
    fen_response = client.post("/fen", json={"fen": ALT_FEN, "source": "engine"})
    assert fen_response.status_code == 200
    fen_events = await asyncio.wait_for(fen_task, 2.0)
    assert fen_events[0]["type"] == "fen_update"
    assert state.fen == ALT_FEN

    move_task = await capture_sse_events()
    opponent_response = client.post(
        "/opponent",
        json={"from_r": 0, "from_c": 1, "to_r": 2, "to_c": 3},
    )
    assert opponent_response.status_code == 200
    move_events = await asyncio.wait_for(move_task, 2.0)
    assert move_events[0]["type"] == "move_made"
    assert move_events[0]["data"]["from"] == "b0"
    assert move_events[0]["data"]["to"] == "d2"
    assert move_events[0]["data"]["source"] == "opponent"


async def test_sse_stream_preserves_event_order_for_single_subscriber(client, capture_sse_events):
    task = await capture_sse_events(expected=3)

    client.post("/state/fen", json={"fen": ALT_FEN, "source": "engine"})
    client.post("/state/best-move", json={"from_sq": "a0", "to_sq": "a1"})
    client.post("/state/led-command", json={"command": "clear"})

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "fen_update",
        "best_move",
        "led_command",
    ]


async def test_two_sse_subscribers_receive_the_same_event(client, capture_sse_events):
    first = await capture_sse_events()
    second = await capture_sse_events()

    client.post("/state/best-move", json={"from_sq": "c3", "to_sq": "c4"})

    first_events = await asyncio.wait_for(first, 2.0)
    second_events = await asyncio.wait_for(second, 2.0)
    assert first_events[0]["type"] == "best_move"
    assert second_events[0]["type"] == "best_move"
    assert first_events[0]["data"] == second_events[0]["data"] == {"from": "c3", "to": "c4"}


async def test_closed_sse_subscriber_does_not_break_later_publish(client, capture_sse_events):
    first = await capture_sse_events()
    client.post("/state/best-move", json={"from_sq": "a0", "to_sq": "a1"})
    await asyncio.wait_for(first, 2.0)

    second = await capture_sse_events()
    client.post("/state/led-command", json={"command": "on"})
    second_events = await asyncio.wait_for(second, 2.0)
    assert second_events[0]["type"] == "led_command"
    assert second_events[0]["data"] == {"command": "on"}


async def test_sse_event_payloads_include_json_shape(client, capture_sse_events):
    task = await capture_sse_events()

    client.post("/state/best-move", json={"from_sq": "d4", "to_sq": "d5"})

    payload = (await asyncio.wait_for(task, 2.0))[0]
    assert payload["type"] == "best_move"
    assert payload["data"] == {"from": "d4", "to": "d5"}
    assert isinstance(payload["ts"], float)
    assert isinstance(payload["seq"], int)


async def test_sse_stream_supports_event_type_filtering(client, bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    class _FilteredRequest:
        query_params = {"types": "move_made"}

        async def is_disconnected(self) -> bool:
            return False

    response = await app_module.sse_events(_FilteredRequest())

    async def _reader():
        events = []
        try:
            async for chunk in response.body_iterator:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if line.startswith("data: "):
                        payload = json.loads(line[6:])
                        events.append(payload)
                        if len(events) >= 1:
                            return events
            return events
        finally:
            await response.body_iterator.aclose()

    task = asyncio.create_task(_reader())
    await asyncio.sleep(0)

    client.post("/state/best-move", json={"from_sq": "a0", "to_sq": "a1"})
    client.post("/state/move", json={"from_sq": "a0", "to_sq": "a1", "piece": "R"})

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["move_made"]
