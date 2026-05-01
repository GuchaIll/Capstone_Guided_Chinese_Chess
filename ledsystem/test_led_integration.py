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
        if path == "/fen-sync":
            board.set_fen(payload["fen"], render=False)
        elif path == "/player-turn":
            best_move = payload.get("best_move")
            normalized_best_move = None
            if isinstance(best_move, dict):
                best_from = best_move.get("from")
                best_to = best_move.get("to")
                normalized_best_move = {
                    "from_r": None if not isinstance(best_from, dict) else best_from.get("row"),
                    "from_c": None if not isinstance(best_from, dict) else best_from.get("col"),
                    "to_r": None if not isinstance(best_to, dict) else best_to.get("row"),
                    "to_c": None if not isinstance(best_to, dict) else best_to.get("col"),
                }
            board.show_player_turn(
                payload.get("selected"),
                payload.get("targets", []),
                normalized_best_move,
            )
        elif path == "/engine-turn":
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

    assert board.board_state[0][1] == "H"
    assert board.board_state[0][2] == "E"
    assert board.board_state[9][1] == "h"
    assert board.board_state[9][2] == "e"

    # 2. Capture flow pauses LEDs, then a selection highlight is queued while
    # CV mode is active and replayed once LEDs resume.
    subscriber.handle_led_command({"command": "off"})
    subscriber.handle_led_player_turn(
        {
            "fen": ENGINE_STYLE_START_FEN,
            "selected_square": "b0",
            "legal_targets": ["a2", "c2"],
            "best_move_from": "b0",
            "best_move_to": "a2",
        }
    )

    assert board.cv_mode is True
    assert board._pending_display == (
        "show_player_turn",
        {
            "selected": {"row": 0, "col": 1},
            "targets": [{"row": 2, "col": 0}, {"row": 2, "col": 2}],
            "best_move": {
                "from_r": 0,
                "from_c": 1,
                "to_r": 2,
                "to_c": 0,
            },
        },
    )

    subscriber.handle_led_command({"command": "on"})

    assert board.cv_mode is False
    assert board._pending_display is None
    assert board.pixels.values[board.pixel_index(0, 1)] == board.RED
    assert board.pixels.values[board.pixel_index(2, 0)] == board.WHITE
    assert board.pixels.values[board.pixel_index(2, 2)] == board.WHITE

    # 3. AI move event refreshes the engine FEN first, then overlays the
    # opponent move highlight.
    subscriber.handle_led_engine_turn(
        {
            "from": "b9",
            "to": "c7",
            "fen": ENGINE_STYLE_AFTER_AI_MOVE_FEN,
        }
    )

    assert subscriber._last_fen == ENGINE_STYLE_AFTER_AI_MOVE_FEN
    assert board.board_state[9][1] == "."
    assert board.board_state[7][2] == "h"
    assert board.pixels.values[board.pixel_index(9, 1)] == board.BLUE
    assert board.pixels.values[board.pixel_index(7, 2)] == board.PURPLE

    assert led_calls == [
        ("/fen-sync", {"fen": ENGINE_STYLE_START_FEN}),
        ("/cv_pause", {}),
        ("/fen-sync", {"fen": ENGINE_STYLE_START_FEN}),
        (
            "/player-turn",
            {
                "fen": ENGINE_STYLE_START_FEN,
                "selected": {"row": 0, "col": 1},
                "targets": [{"row": 2, "col": 0}, {"row": 2, "col": 2}],
                "best_move": {
                    "from": {"row": 0, "col": 1},
                    "to": {"row": 2, "col": 0},
                },
            },
        ),
        ("/cv_resume", {}),
        ("/fen-sync", {"fen": ENGINE_STYLE_AFTER_AI_MOVE_FEN}),
        (
            "/engine-turn",
            {
                "fen": ENGINE_STYLE_AFTER_AI_MOVE_FEN,
                "from_r": 9,
                "from_c": 1,
                "to_r": 7,
                "to_c": 2,
            },
        ),
    ]
