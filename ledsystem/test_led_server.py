from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types


def test_led_server_source_keeps_player_turn_and_drops_legacy_move_route():
    source = Path("ledsystem/led_server.py").read_text()

    assert source.count('@app.route("/player-turn", methods=["POST"])') == 1
    assert source.count('@app.route("/fen-sync", methods=["POST"])') == 1
    assert source.count('@app.route("/draw", methods=["POST"])') == 1
    assert source.count('@app.route("/engine-turn", methods=["POST"])') == 1
    assert '@app.route("/move", methods=["POST"])' not in source
    assert "led.set_fen(fen, render=False)" in source
    assert "led.show_player_turn(selected, targets, normalized_best_move)" in source


def test_led_server_falls_back_to_mock_board_when_hardware_init_fails():
    failing_led_board = types.ModuleType("led_board")

    class FailingLEDBoard:
        def __init__(self):
            raise RuntimeError("hardware init failed")

    failing_led_board.LEDBoard = FailingLEDBoard
    sys.modules["led_board"] = failing_led_board
    sys.modules.pop("led_server", None)

    try:
        led_server = importlib.import_module("led_server")
        assert isinstance(led_server.led, led_server.MockLEDBoard)
    finally:
        sys.modules.pop("led_server", None)
        sys.modules.pop("led_board", None)
