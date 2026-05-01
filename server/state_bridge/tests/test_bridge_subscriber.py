from __future__ import annotations

import io
import itertools
import json

import bridge_subscriber as subscriber


def test_sse_stream_parses_single_and_multiple_messages(monkeypatch):
    payloads = [
        {"type": "best_move", "data": {"from": "a0", "to": "a1"}, "ts": 1.0},
        {"type": "led_command", "data": {"command": "off"}, "ts": 2.0},
    ]
    raw = "".join(f"data: {json.dumps(payload)}\n\n" for payload in payloads).encode()

    def fake_urlopen(_req, timeout=None):
        return io.BytesIO(raw)

    monkeypatch.setattr(subscriber, "urlopen", fake_urlopen)
    stream = subscriber.sse_stream("http://bridge/state/events")

    first, second = list(itertools.islice(stream, 2))
    assert first == payloads[0]
    assert second == payloads[1]


def test_sse_stream_sends_bearer_token_when_configured(monkeypatch):
    seen = {}
    raw = b'data: {"type":"state_sync","data":{"fen":"start"}}\n\n'

    def fake_urlopen(req, timeout=None):
        seen["authorization"] = req.get_header("Authorization")
        return io.BytesIO(raw)

    monkeypatch.setattr(subscriber, "urlopen", fake_urlopen)

    stream = subscriber.sse_stream(
        "http://bridge/state/events",
        bridge_token="integration-bridge-token",
    )
    first = next(stream)

    assert seen["authorization"] == "Bearer integration-bridge-token"
    assert first == {"type": "state_sync", "data": {"fen": "start"}}


def test_handle_fen_update_updates_cached_fen_and_posts_to_led_server(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._last_fen = ""

    subscriber.handle_fen_update({"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "source": "engine"})

    assert subscriber._last_fen == "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
    assert calls == [
        ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
    ]


def test_handle_state_sync_runs_startup_sequence_once(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._cancel_startup_timer()
    subscriber._startup_completed = False
    subscriber._last_fen = ""

    try:
        # First state_sync should fen-sync then render /zones and start the
        # 20s hold timer. Snapshot overlay fields are intentionally ignored.
        subscriber.handle_state_sync(
            {
                "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                "source": "engine",
                "side_to_move": "red",
                "selected_square": "b2",
                "legal_moves": ["b3"],
                "best_move_from": "a0",
                "best_move_to": "a1",
            }
        )
        # A subsequent state_sync (e.g. SSE reconnect) syncs FEN only —
        # the startup zones display is one-shot per process.
        subscriber.handle_state_sync(
            {
                "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                "source": "engine",
                "side_to_move": "red",
            }
        )

        assert calls == [
            ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
            ("/zones", {}),
            ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
        ]
    finally:
        subscriber._cancel_startup_timer()


def test_handle_state_sync_does_not_synthesize_overlay_from_snapshot(monkeypatch):
    """Per docs/led_flow.md §1: startup must not derive a player- or
    engine-turn overlay from the state_sync snapshot. The bridge will
    publish the real led_player_turn / led_engine_turn event when the
    next real action happens.
    """
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._cancel_startup_timer()
    subscriber._startup_completed = False
    subscriber._last_fen = ""

    try:
        subscriber.handle_state_sync(
            {
                "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
                "source": "engine",
                "side_to_move": "black",
                "last_move": {"from": "c3", "to": "d4"},
            }
        )

        assert calls == [
            ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1"}),
            ("/zones", {}),
        ]
    finally:
        subscriber._cancel_startup_timer()


def test_led_player_turn_cancels_startup_zones_hold(monkeypatch):
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: True)
    subscriber._cancel_startup_timer()
    subscriber._startup_completed = False
    subscriber._last_fen = ""

    try:
        subscriber.handle_state_sync(
            {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "side_to_move": "red"}
        )
        assert subscriber._startup_timer is not None

        subscriber.handle_led_player_turn(
            {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}
        )
        assert subscriber._startup_timer is None
    finally:
        subscriber._cancel_startup_timer()


def test_led_engine_turn_cancels_startup_zones_hold(monkeypatch):
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: True)
    subscriber._cancel_startup_timer()
    subscriber._startup_completed = False
    subscriber._last_fen = ""

    try:
        subscriber.handle_state_sync(
            {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "side_to_move": "red"}
        )
        assert subscriber._startup_timer is not None

        subscriber.handle_led_engine_turn(
            {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "from": "c3", "to": "d4"}
        )
        assert subscriber._startup_timer is None
    finally:
        subscriber._cancel_startup_timer()


def test_handle_led_player_turn_posts_explicit_overlay_to_led_server(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._last_fen = ""

    subscriber.handle_led_player_turn(
        {
            "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
            "selected_square": "b2",
            "legal_targets": ["b3", "c4"],
            "best_move_from": "a0",
            "best_move_to": "a1",
        }
    )

    assert subscriber._last_fen == "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
    assert calls == [
        ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
        (
            "/player-turn",
            {
                "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                "selected": {"row": 2, "col": 1},
                "targets": [{"row": 3, "col": 1}, {"row": 4, "col": 2}],
                "best_move": {
                    "from": {"row": 0, "col": 0},
                    "to": {"row": 1, "col": 0},
                },
            },
        ),
    ]


def test_handle_move_made_refreshes_fen_without_displaying_engine_overlay(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._last_fen = ""

    subscriber.handle_move_made(
        {
            "source": "ai",
            "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
        }
    )

    assert calls == [
        ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
    ]


def test_handle_led_engine_turn_posts_explicit_engine_overlay(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._last_fen = ""

    subscriber.handle_led_engine_turn(
        {
            "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
            "from": "c3",
            "to": "d4",
        }
    )

    assert calls == [
        ("/fen-sync", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
        (
            "/engine-turn",
            {
                "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                "from_r": 3,
                "from_c": 2,
                "to_r": 4,
                "to_c": 3,
            },
        ),
    ]


def test_handle_led_command_clears_and_restores_board(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)

    subscriber.handle_led_command({"command": "off"})
    subscriber.handle_led_command({"command": "clear"})
    subscriber.handle_led_command({"command": "on"})

    assert calls == [
        ("/cv_pause", {}),
        ("/cv_pause", {}),
        ("/cv_resume", {}),
    ]


def test_handle_led_command_ignores_bridge_direct_http_capture_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)

    subscriber.handle_led_command({"command": "off", "source": "bridge_direct_http"})
    subscriber.handle_led_command({"command": "on", "source": "bridge_direct_http"})

    assert calls == []


def test_handle_led_game_result_and_reset(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    cancelled = []
    monkeypatch.setattr(subscriber, "_cancel_startup_timer", lambda reason="": cancelled.append(reason) or False)
    started = []
    monkeypatch.setattr(subscriber, "_start_zones_hold", lambda reason: started.append(reason))

    subscriber.handle_led_game_result({"result": "red_wins", "winner": "red"})
    subscriber.handle_led_game_result({"result": "draw"})
    subscriber.handle_led_reset({"reason": "game_over"})
    subscriber.handle_led_reset({"reason": "engine_reset"})

    assert calls == [
        ("/win", {"side": "red"}),
        ("/draw", {}),
        ("/clear", {}),
    ]
    assert cancelled == ["game_over"]
    assert started == ["engine_reset"]


def test_game_reset_then_led_reset_restarts_startup_zones_hold(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    started = []
    monkeypatch.setattr(subscriber, "_start_zones_hold", lambda reason: started.append(reason))

    subscriber._last_fen = ""

    subscriber.handle_game_reset({})
    subscriber.handle_led_reset({"reason": "engine_reset"})

    assert calls == [
        ("/fen-sync", {"fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"}),
    ]
    assert started == ["engine_reset"]


def test_event_dispatch_maps_explicit_led_flows():
    assert subscriber.EVENT_HANDLERS["state_sync"] is subscriber.handle_state_sync
    assert subscriber.EVENT_HANDLERS["led_player_turn"] is subscriber.handle_led_player_turn
    assert subscriber.EVENT_HANDLERS["led_engine_turn"] is subscriber.handle_led_engine_turn
