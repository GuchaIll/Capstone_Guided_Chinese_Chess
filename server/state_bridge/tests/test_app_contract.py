from __future__ import annotations

from state import STARTING_FEN


ALT_FEN = "9/9/9/9/9/9/9/9/9/9 b - - 0 1"
NEXT_FEN = "9/9/9/9/9/9/9/9/9/9 w - - 0 1"


def test_health_and_initial_state(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    state = client.get("/state")
    assert state.status_code == 200
    assert state.json() == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "game_result": "in_progress",
        "is_check": False,
        "last_move": None,
        "move_count": 0,
        "selected_square": None,
        "legal_moves": [],
        "best_move_from": None,
        "best_move_to": None,
        "cv_fen": None,
        "leds_off": False,
    }


import asyncio


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
    assert isinstance(events[0]["ts"], float)

    assert state.fen == ALT_FEN
    assert state.side_to_move == "black"
    assert state.cv_fen is None


async def test_post_cv_fen_updates_cv_fen_only_and_emits_cv_capture(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    task = await capture_sse_events()

    response = client.post("/state/fen", json={"fen": NEXT_FEN, "source": "cv"})

    assert response.status_code == 200
    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["type"] == "cv_capture"
    assert events[0]["data"] == {"fen": NEXT_FEN, "source": "cv"}

    assert state.fen == STARTING_FEN
    assert state.cv_fen == NEXT_FEN


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


def test_select_forwards_to_relay_without_mutating_selection(client, bridge_testbed):
    _, state, _, relay = bridge_testbed

    response = client.post("/state/select", json={"square": "e3"})

    assert response.status_code == 200
    assert response.json() == {"status": "Selection forwarded to engine"}
    assert relay.calls == [("legal_moves", "e3")]
    assert state.selected_square is None
    assert state.legal_moves == []


def test_engine_passthrough_endpoints_forward_to_relay(client, bridge_testbed):
    _, _, _, relay = bridge_testbed

    move = client.post("/engine/move", json={"move": "a0a1"})
    ai_move = client.post("/engine/ai-move", json={"difficulty": 4})
    set_position = client.post("/engine/set-position", json={"fen": ALT_FEN, "source": "engine"})

    assert move.json() == {"status": "Move forwarded to engine"}
    assert ai_move.json() == {"status": "AI move requested"}
    assert set_position.json() == {"status": "Position forwarded to engine"}
    assert relay.calls == [
        ("move", "a0a1"),
        ("ai_move", 4),
        ("set_position", ALT_FEN),
    ]


async def test_engine_reset_clears_overlay_state_and_emits_game_reset(client, bridge_testbed, capture_sse_events):
    _, state, _, relay = bridge_testbed
    state.apply_move("a0", "a1", piece="R")
    state.set_selection("a0", ["a1", "a2"])
    state.set_best_move("b2", "b3")

    task = await capture_sse_events()
    response = client.post("/engine/reset")

    assert response.status_code == 200
    assert response.json() == {"status": "Game reset"}
    events = await asyncio.wait_for(task, 2.0)

    assert relay.calls == [("reset",)]
    assert events[0]["type"] == "game_reset"
    assert state.last_move is None
    assert state.move_history == []
    assert state.selected_square is None
    assert state.legal_moves == []
    assert state.best_move_from is None
    assert state.best_move_to is None


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
