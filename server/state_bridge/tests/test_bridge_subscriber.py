from __future__ import annotations

import io
import json
import itertools

import pytest

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


def test_handle_fen_update_refreshes_board_and_redraws(monkeypatch):
    seen = []

    def fake_parse(fen):
        seen.append(("parse", fen))
        return [["K"]]

    def fake_show(board_state, selected=None, moves=None, best_move=None):
        seen.append(("show", board_state, selected, moves, best_move))

    monkeypatch.setattr(subscriber, "parse_xiangqi_fen", fake_parse)
    monkeypatch.setattr(subscriber, "show_position", fake_show)
    subscriber._board_state = []

    subscriber.handle_fen_update({"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "source": "engine"})

    assert subscriber._board_state == [["K"]]
    assert seen[0] == ("parse", "9/9/9/9/9/9/9/9/9/9 w - - 0 1")
    assert seen[1] == ("show", [["K"]], None, None, None)


def test_handle_piece_selected_converts_targets_and_highlights(monkeypatch):
    calls = []
    subscriber._board_state = [["."] * 9 for _ in range(10)]

    monkeypatch.setattr(subscriber, "best_move_for_piece", lambda board, r, c, moves: (2, 2))
    monkeypatch.setattr(
        subscriber,
        "show_position",
        lambda board_state, selected=None, moves=None, best_move=None: calls.append(
            (board_state, selected, moves, best_move)
        ),
    )

    subscriber.handle_piece_selected({"square": "b2", "targets": ["b3", "c4"]})

    assert calls == [
        (subscriber._board_state, (2, 1), [(3, 1), (4, 2)], (2, 2)),
    ]


def test_handle_move_made_highlights_opponent_move_and_refreshes_fen(monkeypatch):
    calls = []
    subscriber._board_state = [["."] * 9 for _ in range(10)]
    monkeypatch.setattr(subscriber, "HAS_LED", False)
    monkeypatch.setattr(subscriber, "clear", lambda: calls.append(("clear",)))
    monkeypatch.setattr(subscriber, "set_square", lambda r, c, color: calls.append(("set_square", r, c, color)))
    monkeypatch.setattr(subscriber, "parse_xiangqi_fen", lambda fen: [["X"]])
    monkeypatch.setattr(
        subscriber,
        "show_position",
        lambda board_state, selected=None, moves=None, best_move=None: calls.append(
            ("show_position", board_state, selected, moves, best_move)
        ),
    )

    subscriber.handle_move_made(
        {
            "from": "a0",
            "to": "b1",
            "source": "ai",
            "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
        }
    )

    assert calls[:3] == [
        ("clear",),
        ("set_square", 0, 0, subscriber.BLUE),
        ("set_square", 1, 1, subscriber.PURPLE),
    ]
    assert calls[3] == ("show_position", [["X"]], None, None, None)
    assert subscriber._board_state == [["X"]]


def test_handle_best_move_highlights_recommended_squares(monkeypatch):
    calls = []
    subscriber._board_state = [["."] * 9 for _ in range(10)]
    monkeypatch.setattr(subscriber, "HAS_LED", False)
    monkeypatch.setattr(
        subscriber,
        "show_position",
        lambda board_state, selected=None, moves=None, best_move=None: calls.append(
            ("show_position", board_state, selected, moves, best_move)
        ),
    )
    monkeypatch.setattr(subscriber, "set_square", lambda r, c, color: calls.append(("set_square", r, c, color)))

    subscriber.handle_best_move({"from": "c3", "to": "d4"})

    assert calls == [
        ("show_position", subscriber._board_state, None, None, None),
        ("set_square", 4, 3, subscriber.GREEN),
        ("set_square", 3, 2, subscriber.RED),
    ]


def test_handle_led_command_clears_and_restores_board(monkeypatch):
    calls = []
    subscriber._board_state = [["."]]
    monkeypatch.setattr(subscriber, "clear", lambda: calls.append(("clear",)))
    monkeypatch.setattr(
        subscriber,
        "show_position",
        lambda board_state, selected=None, moves=None, best_move=None: calls.append(
            ("show_position", board_state)
        ),
    )

    subscriber.handle_led_command({"command": "off"})
    subscriber.handle_led_command({"command": "clear"})
    subscriber.handle_led_command({"command": "on"})

    assert calls == [
        ("clear",),
        ("clear",),
        ("show_position", [["."]]),
    ]


def test_event_dispatch_maps_cv_capture_to_fen_update(monkeypatch):
    assert subscriber.EVENT_HANDLERS["cv_capture"] is subscriber.EVENT_HANDLERS["fen_update"]
