from __future__ import annotations

import importlib
import sys
import types


class FakePixels:
    def __init__(self, _pin, count, **_kwargs):
        self.values = [(0, 0, 0, 0)] * count
        self.show_calls = 0

    def __setitem__(self, index, value):
        self.values[index] = value

    def fill(self, value):
        self.values = [value] * len(self.values)

    def show(self):
        self.show_calls += 1


def load_led_modules():
    fake_board = types.SimpleNamespace(D18="D18")
    fake_neopixel = types.SimpleNamespace(GRBW="GRBW", NeoPixel=FakePixels)
    sys.modules["board"] = fake_board
    sys.modules["neopixel"] = fake_neopixel
    sys.modules.pop("led_board", None)
    sys.modules.pop("bridge_subscriber", None)
    led_board = importlib.import_module("led_board")
    bridge_subscriber = importlib.import_module("bridge_subscriber")
    return led_board, bridge_subscriber


ENGINE_STYLE_START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
ENGINE_STYLE_AFTER_AI_MOVE_FEN = "r1bakabnr/9/1cn4c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2"


def test_engine_event_sequence_drives_led_board_with_normalized_fen(monkeypatch):
    led_board, subscriber = load_led_modules()
    board = led_board.LEDBoard()
    led_calls: list[tuple[str, dict | None]] = []

    def dispatch_led_post(path: str, body: dict | None = None) -> bool:
        payload = body or {}
        led_calls.append((path, body))
        if path == "/fen":
            board.set_fen(payload["fen"])
        elif path == "/move":
            board.show_moves("", payload["row"], payload["col"])
        elif path == "/opponent":
            board.show_opponent_move(
                payload["from_r"],
                payload["from_c"],
                payload["to_r"],
                payload["to_c"],
            )
        elif path == "/cv_pause":
            board.cv_pause()
        elif path == "/cv_resume":
            board.cv_resume()
        else:
            raise AssertionError(f"Unhandled LED path in test: {path}")
        return True

    monkeypatch.setattr(subscriber, "_led_post", dispatch_led_post)
    subscriber._last_fen = ""

    # 1. Engine publishes the starting board using chess-style N/B letters.
    subscriber.handle_fen_update({"fen": ENGINE_STYLE_START_FEN, "source": "engine"})

    assert board.board_state[0][1] == "h"
    assert board.board_state[0][2] == "e"
    assert board.board_state[9][1] == "H"
    assert board.board_state[9][2] == "E"

    # 2. Capture flow pauses LEDs, then a selection highlight is queued while
    # CV mode is active and replayed once LEDs resume.
    subscriber.handle_led_command({"command": "off"})
    subscriber.handle_piece_selected({"square": "b9", "targets": ["a7", "c7"]})

    assert board.cv_mode is True
    assert board._pending_display == ("show_moves", {"row": 9, "col": 1})

    subscriber.handle_led_command({"command": "on"})

    assert board.cv_mode is False
    assert board._pending_display is None
    assert board.pixels.values[board.BOARD_LED_MAP[9][1]] == board.RED
    # The horse at b9 has legal moves to a7 and c7 from the starting position;
    # show_moves marks the first legal move green as the "best" hint.
    assert board.pixels.values[board.BOARD_LED_MAP[7][0]] == board.GREEN
    assert board.pixels.values[board.BOARD_LED_MAP[7][2]] == board.WHITE

    # 3. AI move event refreshes the engine FEN first, then overlays the
    # opponent move highlight.
    subscriber.handle_move_made(
        {
            "from": "b0",
            "to": "c2",
            "source": "ai",
            "fen": ENGINE_STYLE_AFTER_AI_MOVE_FEN,
        }
    )

    assert subscriber._last_fen == ENGINE_STYLE_AFTER_AI_MOVE_FEN
    assert board.board_state[0][1] == "."
    assert board.board_state[2][2] == "h"
    assert board.pixels.values[board.BOARD_LED_MAP[0][1]] == board.BLUE
    assert board.pixels.values[board.BOARD_LED_MAP[2][2]] == board.PURPLE

    assert led_calls == [
        ("/fen", {"fen": ENGINE_STYLE_START_FEN}),
        ("/cv_pause", {}),
        ("/move", {"row": 9, "col": 1}),
        ("/cv_resume", {}),
        ("/fen", {"fen": ENGINE_STYLE_AFTER_AI_MOVE_FEN}),
        (
            "/opponent",
            {"from_r": 0, "from_c": 1, "to_r": 2, "to_c": 2},
        ),
    ]
