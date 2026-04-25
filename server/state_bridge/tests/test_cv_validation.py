from __future__ import annotations

import pytest

from cv_validation import FenDiffError, derive_move_from_fen_diff


QUIET_PREV = "4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1"
QUIET_FEN = "4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2"
CAPTURE_PREV = "4k4/9/9/9/4p4/4P4/9/9/9/4K4 b - - 0 1"
CAPTURE_FEN = "4k4/9/9/9/9/4p4/9/9/9/4K4 w - - 0 2"
OWN_CAPTURE_PREV = "4k4/9/9/9/4p4/4r4/9/9/9/4K4 b - - 0 1"
OWN_CAPTURE_FEN = "4k4/9/9/9/9/4p4/9/9/9/4K4 w - - 0 2"
SIDE_MISMATCH_FEN = "9/4k4/9/9/9/9/9/9/9/R3K4 b - - 0 2"
MULTI_CHANGE_FEN = "9/4k4/9/9/9/9/9/9/R8/4K4 b - - 0 2"


def test_derive_move_from_single_quiet_move():
    move = derive_move_from_fen_diff(QUIET_PREV, QUIET_FEN)

    assert move.from_sq == "a0"
    assert move.to_sq == "a1"
    assert move.move == "a0a1"
    assert move.piece == "R"
    assert move.captured_piece is None


def test_derive_move_from_capture():
    move = derive_move_from_fen_diff(CAPTURE_PREV, CAPTURE_FEN)

    assert move.from_sq == "e5"
    assert move.to_sq == "e4"
    assert move.move == "e5e4"
    assert move.piece == "p"
    assert move.captured_piece == "P"


@pytest.mark.parametrize(
    ("current_fen", "cv_fen", "message"),
    [
        (QUIET_PREV, QUIET_PREV, "no board change detected"),
        (QUIET_PREV, MULTI_CHANGE_FEN, "ambiguous board change"),
        (OWN_CAPTURE_PREV, OWN_CAPTURE_FEN, "captures a piece of the moving side"),
        (QUIET_PREV, SIDE_MISMATCH_FEN, "could not isolate a single move"),
    ],
)
def test_derive_move_rejects_invalid_board_diffs(current_fen: str, cv_fen: str, message: str):
    with pytest.raises(FenDiffError, match=message):
        derive_move_from_fen_diff(current_fen, cv_fen)
