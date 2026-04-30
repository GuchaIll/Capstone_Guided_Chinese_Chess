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
        ("/fen", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
    ]


def test_handle_piece_selected_posts_selected_square_to_led_server(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)

    subscriber.handle_piece_selected({"square": "b2", "targets": ["b3", "c4"]})

    assert calls == [
        ("/move", {"row": 2, "col": 1}),
    ]


def test_handle_move_made_refreshes_fen_and_highlights_opponent_move(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)
    subscriber._last_fen = ""

    subscriber.handle_move_made(
        {
            "from": "a0",
            "to": "b1",
            "source": "ai",
            "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
        }
    )

    assert subscriber._last_fen == "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
    assert calls == [
        ("/fen", {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}),
        (
            "/opponent",
            {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 1},
        ),
    ]


def test_handle_best_move_highlights_from_square(monkeypatch):
    calls = []
    monkeypatch.setattr(subscriber, "_led_post", lambda path, body=None: calls.append((path, body)) or True)

    subscriber.handle_best_move({"from": "c3", "to": "d4"})

    assert calls == [
        ("/move", {"row": 3, "col": 2}),
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


def test_event_dispatch_maps_cv_capture_to_fen_update():
    assert subscriber.EVENT_HANDLERS["cv_capture"] is subscriber.EVENT_HANDLERS["fen_update"]
