from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from conftest import TEST_BRIDGE_TOKEN
from state import STARTING_FEN


ALT_FEN = "9/9/9/9/9/9/9/9/9/9 b - - 0 1"
CV_BASE_FEN = "4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1"
CV_SUCCESS_FEN = "4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2"
CV_ALT_NOTATION_FEN = "rheagaehr/9/1c5c1/s1s1s1s1s/9/4S4/S1S3S1S/1C5C1/9/RHEAGAEHR w - - 0 1"
CV_NORMALIZED_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR w - - 0 1"
AMBIGUOUS_CV_FEN = "9/4k4/9/9/9/9/9/9/R8/4K4 b - - 0 2"
ILLEGAL_CV_FEN = "4k4/9/9/9/9/9/9/9/9/4KR3 b - - 0 2"


def test_health_endpoint_is_unauthenticated(bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    with TestClient(app_module.app) as anonymous_client:
        response = anonymous_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unauthenticated_request_to_gated_route_rejected(bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    with TestClient(app_module.app) as anonymous_client:
        response = anonymous_client.get("/state")
    assert response.status_code == 401
    assert response.json() == {"error": "Unauthorized"}


def test_request_authenticated_via_query_token(bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    with TestClient(app_module.app) as anonymous_client:
        response = anonymous_client.get(f"/state?token={TEST_BRIDGE_TOKEN}")
    assert response.status_code == 200
    assert response.json()["fen"] == STARTING_FEN


def test_health_and_initial_state(client):
    health = client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "ok"
    assert "authoritative_bundle_healthy" in health_body
    assert "cv_service_healthy" in health_body
    assert "cv_service" in health_body
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


async def test_post_cv_fen_accepts_valid_move_and_emits_led_resume_then_cv_capture_and_best_move(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, relay = bridge_testbed
    state.apply_fen(CV_BASE_FEN, source="engine")
    relay.make_move_results[(CV_BASE_FEN, "a0a1")] = {
        "type": "move_result",
        "valid": True,
        "move": "a0a1",
        "fen": CV_SUCCESS_FEN,
        "result": "in_progress",
        "is_check": False,
    }
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
    assert [event["type"] for event in events] == ["led_command", "cv_capture", "best_move"]
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
        ("make_move", CV_BASE_FEN, "a0a1"),
        ("suggest", CV_SUCCESS_FEN, 5),
        ("ai_move", 4),
    ]


async def test_post_cv_fen_normalizes_cv_piece_symbols_before_validation_and_state_update(
    client,
    bridge_testbed,
    capture_sse_events,
):
    _, state, _, relay = bridge_testbed
    relay.legal_moves_by_square["e3"] = ["e4"]
    relay.make_move_results[(STARTING_FEN, "e3e4")] = {
        "type": "move_result",
        "valid": True,
        "move": "e3e4",
        "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 2",
        "result": "in_progress",
        "is_check": False,
    }
    task = await capture_sse_events(expected=3)

    response = client.post("/state/fen", json={"fen": CV_ALT_NOTATION_FEN, "source": "cv"})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "status": "FEN updated",
        "source": "cv",
        "move": "e3e4",
    }

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["led_command", "cv_capture", "best_move"]
    assert events[1]["data"]["fen"] == "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 2"
    assert state.fen == "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 2"
    assert state.cv_fen == "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 2"
    assert state.side_to_move == "black"
    assert relay.calls == [
        ("legal_moves_for_square", STARTING_FEN, "e3"),
        ("make_move", STARTING_FEN, "e3e4"),
        ("suggest", "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 2", 5),
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


async def test_capture_endpoint_proxies_cv_capture_result(client, monkeypatch, capture_sse_events):
    task = await capture_sse_events(expected=4)
    led_calls: list[str] = []

    async def fake_capture():
        return 200, {
            "status": "ok",
            "fen": CV_SUCCESS_FEN,
            "image_path": "cv/output/http_capture.jpg",
            "image_mime": "image/jpeg",
            "image_base64": "ZmFrZQ==",
            "capture_id": 3,
        }

    async def fake_led_call(path: str) -> bool:
        led_calls.append(path)
        return True

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", fake_led_call)

    response = client.post("/capture")

    assert response.status_code == 200
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "led_command",
        "cv_capture_requested",
        "cv_capture_result",
        "led_command",
    ]
    assert events[0]["data"] == {"command": "off", "source": "bridge_direct_http"}
    assert events[1]["data"]["endpoint"] == "/capture"
    assert events[2]["data"]["fen"] == CV_SUCCESS_FEN
    assert events[3]["data"] == {"command": "on", "source": "bridge_direct_http"}
    assert led_calls == ["/cv_pause", "/cv_resume"]
    assert response.json() == {
        "status": "ok",
        "fen": CV_SUCCESS_FEN,
        "issues": [],
        "image_path": "cv/output/http_capture.jpg",
        "image_mime": "image/jpeg",
        "capture_id": 3,
    }


async def test_capture_endpoint_accepts_float_captured_at_from_cv(client, monkeypatch, capture_sse_events):
    task = await capture_sse_events(expected=4)

    async def fake_capture():
        return 200, {
            "status": "ok",
            "fen": CV_SUCCESS_FEN,
            "image_path": "cv/output/http_capture.jpg",
            "image_mime": "image/jpeg",
            "capture_id": 3,
            "captured_at": 1777597478.1658082,
        }

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", lambda path: asyncio.sleep(0, result=True))

    response = client.post("/capture")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["fen"] == CV_SUCCESS_FEN
    assert isinstance(body["captured_at"], str)
    assert body["captured_at"].startswith("2026-")

    events = await asyncio.wait_for(task, 2.0)
    assert events[2]["type"] == "cv_capture_result"
    assert isinstance(events[2]["data"]["captured_at"], str)


def test_engine_validate_fen_accepts_cv_piece_notation_and_normalizes_before_relay(client, bridge_testbed):
    _, _, _, relay = bridge_testbed

    response = client.post("/engine/validate-fen", json={"fen": CV_ALT_NOTATION_FEN})

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert relay.calls == [("validate_fen", CV_NORMALIZED_FEN)]


def test_resolve_led_server_url_prefers_explicit_url(bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    resolved = app_module._resolve_led_server_url(
        {
            "LED_SERVER_URL": "http://led-host:5000/",
            "RASPBERRY_PI_IP": "192.168.1.55",
            "LED_SERVER_PORT": "5001",
        }
    )

    assert resolved == "http://led-host:5000"


def test_resolve_led_server_url_derives_from_raspberry_pi_ip(bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    resolved = app_module._resolve_led_server_url(
        {
            "RASPBERRY_PI_IP": "192.168.1.55",
            "LED_SERVER_PORT": "5001",
        }
    )

    assert resolved == "http://192.168.1.55:5001"


def test_resolve_led_server_url_accepts_legacy_raspbery_pi_ip_spelling(bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    resolved = app_module._resolve_led_server_url(
        {
            "RASPBERY_PI_IP": "192.168.1.77",
        }
    )

    assert resolved == "http://192.168.1.77:5000"


def test_event_from_model_rejects_malformed_payload():
    """Publishing through Event.from_model must validate at the boundary."""
    import pytest as _pytest
    from event_models import LedCommandData
    from events import Event, EventType

    # `command` is a required string; passing a bool fails validation
    # at the model boundary rather than emitting a malformed wire frame.
    with _pytest.raises(Exception):
        Event.from_model(EventType.LED_COMMAND, LedCommandData(command=False))  # type: ignore[arg-type]


async def test_capture_endpoint_rejects_malformed_cv_payload(client, monkeypatch, capture_sse_events):
    task = await capture_sse_events(expected=4)

    async def fake_capture():
        # `fen` should be string-or-null; sending a list breaks the contract
        # and the bridge should refuse to republish it as an authoritative
        # event rather than passing the malformed shape through.
        return 200, {"status": "ok", "fen": ["not-a-fen"]}

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", lambda path: asyncio.sleep(0, result=True))

    response = client.post("/capture")

    assert response.status_code == 502
    assert response.json() == {"error": "CV service returned an unexpected payload shape"}
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "led_command",
        "cv_capture_requested",
        "cv_capture_result",
        "led_command",
    ]
    assert events[0]["data"] == {"command": "off", "source": "bridge_direct_http"}
    assert events[2]["data"]["status"] == "malformed"
    assert events[3]["data"] == {"command": "on", "source": "bridge_direct_http"}
    # Outbound payloads omit None-valued optional fields, so `fen` simply
    # isn't present rather than `null` on the wire.
    assert events[2]["data"].get("fen") is None


async def test_capture_endpoint_returns_503_when_cv_service_is_unavailable(client, monkeypatch, capture_sse_events):
    task = await capture_sse_events(expected=4)

    async def fake_capture():
        raise OSError("camera offline")

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", lambda path: asyncio.sleep(0, result=True))

    response = client.post("/capture")

    assert response.status_code == 503
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "led_command",
        "cv_capture_requested",
        "cv_capture_result",
        "led_command",
    ]
    assert events[0]["data"] == {"command": "off", "source": "bridge_direct_http"}
    assert events[2]["data"]["status"] == "unavailable"
    assert events[3]["data"] == {"command": "on", "source": "bridge_direct_http"}
    assert response.json()["error"] == "CV capture service unavailable"


async def test_capture_endpoint_waits_for_blackout_timer_before_led_resume(client, monkeypatch, capture_sse_events):
    task = await capture_sse_events(expected=4)
    monkeypatch.setattr("app.CV_LED_BLACKOUT_SECONDS", 0.05)
    led_calls: list[str] = []

    async def fake_capture():
        return 200, {"status": "ok", "fen": CV_SUCCESS_FEN}

    async def fake_led_call(path: str) -> bool:
        led_calls.append(path)
        return True

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", fake_led_call)

    started = asyncio.get_running_loop().time()
    response = client.post("/capture")
    elapsed = asyncio.get_running_loop().time() - started

    assert response.status_code == 200
    assert elapsed >= 0.045
    assert led_calls == ["/cv_pause", "/cv_resume"]

    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["data"] == {"command": "off", "source": "bridge_direct_http"}
    assert events[3]["data"] == {"command": "on", "source": "bridge_direct_http"}


async def test_capture_endpoint_still_publishes_blackout_events_when_direct_led_control_is_unavailable(
    client,
    monkeypatch,
    capture_sse_events,
):
    task = await capture_sse_events(expected=4)
    led_calls: list[str] = []

    async def fake_capture():
        return 200, {"status": "ok", "fen": CV_SUCCESS_FEN}

    async def fake_led_call(path: str) -> bool:
        led_calls.append(path)
        return False

    monkeypatch.setattr("app._request_cv_capture", fake_capture)
    monkeypatch.setattr("app._call_led_server", fake_led_call)

    response = client.post("/capture")

    assert response.status_code == 200
    assert led_calls == ["/cv_pause"]

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "led_command",
        "cv_capture_requested",
        "cv_capture_result",
        "led_command",
    ]
    assert events[0]["data"] == {"command": "off", "source": "event_bus_fallback"}
    assert events[3]["data"] == {"command": "on", "source": "event_bus_fallback"}


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


async def test_post_best_move_also_emits_explicit_led_player_turn_event(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    state.set_selection("e3", ["e4"])
    task = await capture_sse_events(expected=2)

    response = client.post("/state/best-move", json={"from_sq": "b2", "to_sq": "b3"})

    assert response.status_code == 200
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["best_move", "led_player_turn"]
    assert events[1]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "selected_square": "e3",
        "legal_targets": ["e4"],
        "best_move_from": "b2",
        "best_move_to": "b3",
    }


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


async def test_select_also_emits_explicit_led_player_turn_event(client, bridge_testbed, capture_sse_events):
    _, _, _, relay = bridge_testbed
    relay.legal_moves_by_square["e3"] = ["e4", "e5"]
    task = await capture_sse_events(expected=2)

    response = client.post("/state/select", json={"square": "e3"})

    assert response.status_code == 200
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["piece_selected", "led_player_turn"]
    assert events[1]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "selected_square": "e3",
        "legal_targets": ["e4", "e5"],
    }


async def test_deselect_clears_selection_and_emits_led_player_turn(client, bridge_testbed, capture_sse_events):
    _, state, _, _ = bridge_testbed
    state.set_selection("e3", ["e4", "e5"])
    state.set_best_move("b2", "b3")
    task = await capture_sse_events()

    response = client.post("/state/deselect", json={})

    assert response.status_code == 200
    assert response.json() == {"status": "Selection cleared"}
    events = await asyncio.wait_for(task, 2.0)
    assert events[0]["type"] == "led_player_turn"
    assert events[0]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "legal_targets": [],
        "best_move_from": "b2",
        "best_move_to": "b3",
    }
    assert state.selected_square is None
    assert state.legal_moves == []


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


async def test_bridge_websocket_supports_state_and_helper_commands(client, bridge_testbed, capture_sse_events):
    _, state, _, relay = bridge_testbed
    relay.legal_moves_by_square["e3"] = ["e4", "e5"]
    task = await capture_sse_events(expected=5)

    with client.websocket_connect("/ws") as ws:
        # Bridge sends initial state snapshot on connect
        initial = ws.receive_json()
        assert initial["type"] == "state"
        assert initial["fen"] == STARTING_FEN

        ws.send_json({"type": "get_state"})
        state_message = ws.receive_json()
        assert state_message["type"] == "state"
        assert state_message["fen"] == STARTING_FEN

        ws.send_json({"type": "select", "square": "e3"})
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
            "from": "b0",
            "to": "c2",
            "move": "b0c2",
            "score": 120,
        }

        ws.send_json({"type": "deselect"})
        assert ws.receive_json() == {"type": "selection_cleared"}

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "piece_selected",
        "led_player_turn",
        "best_move",
        "led_player_turn",
        "led_player_turn",
    ]
    assert events[1]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "selected_square": "e3",
        "legal_targets": ["e4", "e5"],
    }
    assert events[3]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "selected_square": "e3",
        "legal_targets": ["e4", "e5"],
        "best_move_from": "b0",
        "best_move_to": "c2",
    }
    assert events[4]["data"] == {
        "fen": STARTING_FEN,
        "side_to_move": "red",
        "legal_targets": [],
        "best_move_from": "b0",
        "best_move_to": "c2",
    }
    assert state.selected_square is None
    assert state.best_move_from == "b0"
    assert state.best_move_to == "c2"

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

    assert relay.calls == [("reset_and_wait", response_body["command_id"], 15.0)]
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


async def test_engine_reset_also_emits_led_reset_event(client, bridge_testbed, capture_sse_events):
    _, _, _, _ = bridge_testbed
    task = await capture_sse_events(expected=2)

    response = client.post("/engine/reset")

    assert response.status_code == 200
    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == ["game_reset", "led_reset"]
    assert events[1]["data"] == {"reason": "engine_reset"}


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
    task = await capture_sse_events(expected=4)

    client.post("/state/fen", json={"fen": ALT_FEN, "source": "engine"})
    client.post("/state/best-move", json={"from_sq": "a0", "to_sq": "a1"})
    client.post("/state/led-command", json={"command": "clear"})

    events = await asyncio.wait_for(task, 2.0)
    assert [event["type"] for event in events] == [
        "fen_update",
        "best_move",
        "led_player_turn",
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
