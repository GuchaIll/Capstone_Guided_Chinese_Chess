"""Helpers for validating CV-detected Xiangqi board states."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivedMove:
    from_sq: str
    to_sq: str
    piece: str
    captured_piece: str | None = None

    @property
    def move(self) -> str:
        return f"{self.from_sq}{self.to_sq}"


class FenDiffError(ValueError):
    """Raised when a CV FEN cannot be mapped to one legal board move."""


def _normalize_piece(piece: str | None) -> str | None:
    if piece is None:
        return None
    mapping = {
        "H": "N",
        "h": "n",
        "E": "B",
        "e": "b",
        "G": "K",
        "g": "k",
        "S": "P",
        "s": "p",
    }
    return mapping.get(piece, piece)


def _parse_board(fen: str) -> list[list[str | None]]:
    parts = fen.strip().split()
    if len(parts) < 2:
        raise FenDiffError("FEN is missing side-to-move information")

    ranks = parts[0].split("/")
    if len(ranks) != 10:
        raise FenDiffError("FEN must contain 10 ranks")

    board: list[list[str | None]] = [[None for _ in range(10)] for _ in range(9)]
    for rank_idx, rank_text in enumerate(ranks):
        rank = 9 - rank_idx
        file = 0
        for ch in rank_text:
            if ch.isdigit():
                file += int(ch)
                continue
            if file >= 9:
                raise FenDiffError("FEN rank overflows board width")
            board[file][rank] = _normalize_piece(ch)
            file += 1
        if file != 9:
            raise FenDiffError("FEN rank does not span 9 files")
    return board


def _square_name(file: int, rank: int) -> str:
    return f"{chr(ord('a') + file)}{rank}"


def _moving_side_token(fen: str) -> str:
    parts = fen.strip().split()
    if len(parts) < 2:
        raise FenDiffError("FEN is missing side-to-move information")
    token = parts[1].lower()
    if token not in {"w", "b"}:
        raise FenDiffError("FEN side-to-move must be 'w' or 'b'")
    return token


def _is_side_piece(piece: str | None, side_token: str) -> bool:
    if not piece:
        return False
    return piece.isupper() if side_token == "w" else piece.islower()


def derive_move_from_fen_diff(current_fen: str, cv_fen: str) -> DerivedMove:
    """Derive exactly one move by the side-to-move from board placement diff."""

    current_board = _parse_board(current_fen)
    cv_board = _parse_board(cv_fen)
    side_token = _moving_side_token(current_fen)

    deltas: list[tuple[str, str | None, str | None]] = []
    for file in range(9):
        for rank in range(10):
            before = current_board[file][rank]
            after = cv_board[file][rank]
            if before != after:
                deltas.append((_square_name(file, rank), before, after))

    if not deltas:
        raise FenDiffError("no board change detected")
    if len(deltas) != 2:
        raise FenDiffError(f"ambiguous board change: expected 2 changed squares, found {len(deltas)}")

    from_delta = next(
        (
            (square, before, after)
            for square, before, after in deltas
            if before is not None and _is_side_piece(before, side_token) and after is None
        ),
        None,
    )
    to_delta = next(
        (
            (square, before, after)
            for square, before, after in deltas
            if after is not None and _is_side_piece(after, side_token) and after != before
        ),
        None,
    )

    if from_delta is None or to_delta is None:
        raise FenDiffError("could not isolate a single move by the side to move")

    from_sq, moving_piece, _ = from_delta
    to_sq, captured_piece, landed_piece = to_delta

    if landed_piece != moving_piece:
        raise FenDiffError("detected board change does not preserve the moving piece")
    if captured_piece is not None and _is_side_piece(captured_piece, side_token):
        raise FenDiffError("detected board change captures a piece of the moving side")

    return DerivedMove(
        from_sq=from_sq,
        to_sq=to_sq,
        piece=moving_piece or "",
        captured_piece=captured_piece,
    )
