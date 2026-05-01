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


def load_led_board_module():
    fake_board = types.SimpleNamespace(D18="D18")
    fake_neopixel = types.SimpleNamespace(GRBW="GRBW", NeoPixel=FakePixels)
    sys.modules["board"] = fake_board
    sys.modules["neopixel"] = fake_neopixel
    sys.modules.pop("led_board", None)
    return importlib.import_module("led_board")


def test_set_fen_normalizes_engine_notation_and_renders_board():
    led_board = load_led_board_module()
    board = led_board.LEDBoard()

    board.set_fen("4n4/9/9/9/9/9/9/9/9/4B4 w - - 0 1")

    assert board.board_state[0][4] == "E"
    assert board.board_state[9][4] == "h"
    assert board.pixels.show_calls >= 1
    assert board.pixels.values[board.pixel_index(0, 4)] == board.RED
    assert board.pixels.values[board.pixel_index(9, 4)] == board.BLUE


def test_cv_resume_replays_pending_player_turn_overlay():
    led_board = load_led_board_module()
    board = led_board.LEDBoard()
    board.set_fen("9/9/9/9/9/9/9/9/9/R8 w - - 0 1")

    board.cv_pause()
    board.show_player_turn(
        {"row": 0, "col": 0},
        [{"row": 1, "col": 0}],
        {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
    )

    assert board._pending_display == (
        "show_player_turn",
        {
            "selected": {"row": 0, "col": 0},
            "targets": [{"row": 1, "col": 0}],
            "best_move": {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
        },
    )

    board.cv_resume()

    assert board._pending_display is None
    assert board.pixels.values[board.pixel_index(0, 0)] == board.RED
    assert board.pixels.values[board.pixel_index(1, 0)] == board.WHITE


def test_show_player_turn_without_selection_highlights_only_best_piece():
    led_board = load_led_board_module()
    board = led_board.LEDBoard()
    board.set_fen("9/9/9/9/9/9/9/9/9/R8 w - - 0 1", render=False)

    board.show_player_turn(
        None,
        [{"row": 1, "col": 0}],
        {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
    )

    assert board.pixels.values[board.pixel_index(0, 0)] == board.GREEN
    assert board.pixels.values[board.pixel_index(1, 0)] == board.OFF


def test_show_player_turn_with_selection_highlights_selected_and_targets_only():
    led_board = load_led_board_module()
    board = led_board.LEDBoard()
    board.set_fen("9/9/9/9/9/9/9/9/9/R8 w - - 0 1", render=False)

    board.show_player_turn(
        {"row": 0, "col": 0},
        [{"row": 1, "col": 0}],
        {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
    )

    assert board.pixels.values[board.pixel_index(0, 0)] == board.RED
    assert board.pixels.values[board.pixel_index(1, 0)] == board.WHITE


def test_show_player_turn_colors_capture_target_orange_on_asymmetric_board():
    led_board = load_led_board_module()
    board = led_board.LEDBoard()
    board.set_fen("9/9/9/9/9/9/9/9/p8/R8 w - - 0 1", render=False)

    board.show_player_turn(
        {"row": 0, "col": 0},
        [{"row": 1, "col": 0}],
        {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0},
    )

    assert board.board_state[0][0] == "R"
    assert board.board_state[1][0] == "p"
    assert board.pixels.values[board.pixel_index(1, 0)] == board.ORANGE
