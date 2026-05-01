from __future__ import annotations

import sys
from pathlib import Path

import cv2

from conftest import STARTING_FEN


REPO_ROOT = Path(__file__).resolve().parents[1]
CV_ROOT = REPO_ROOT / "cv"
STATE_BRIDGE_ROOT = REPO_ROOT / "server" / "state_bridge"

for path in (str(CV_ROOT), str(STATE_BRIDGE_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


import board_pipeline_yolo8 as cv_pipeline  # noqa: E402
import app as bridge_app  # noqa: E402
from cv_validation import derive_move_from_fen_diff  # noqa: E402


EXPECTED_CAPTURE_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR w - - 0 1"


def test_saved_http_capture_normalizes_to_engine_fen() -> None:
    cv_pipeline.load_grid_calibration()
    model = cv_pipeline.load_model(cv_pipeline.MODEL_PATH)
    image = cv2.imread(str(REPO_ROOT / "cv" / "output" / "http_capture.jpg"))
    assert image is not None

    board_corners = cv_pipeline.get_board_corners_for_grid()
    board_left, board_right, board_top, board_bottom = cv_pipeline.board_corners_to_bounds(board_corners)
    grid = cv_pipeline.generate_grid_points(
        board_left,
        board_top,
        board_right,
        board_bottom,
        cols=cv_pipeline.GRID_COLS,
        rows=cv_pipeline.GRID_ROWS,
    )

    detections = cv_pipeline.run_yolo_on_warped(model, image)
    mapped = cv_pipeline.map_detections_to_grid(detections, grid)
    assigned = cv_pipeline.resolve_grid_conflicts(mapped)
    board, unknown_classes = cv_pipeline.assigned_to_board(assigned)
    issues = cv_pipeline.sanity_check_board(board)
    capture_fen = cv_pipeline.board_to_fen(board)

    assert len(detections) >= 32
    assert len(mapped) >= 32
    assert len(assigned) == 32
    assert unknown_classes == []
    assert issues == []
    assert capture_fen == EXPECTED_CAPTURE_FEN
    assert bridge_app._looks_like_xiangqi_fen(capture_fen) is True

    derived_move = derive_move_from_fen_diff(STARTING_FEN, capture_fen)
    assert derived_move.move == "e3e4"
