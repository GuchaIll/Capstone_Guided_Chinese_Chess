"""In-memory game state shared across the bridge."""

from __future__ import annotations

from dataclasses import dataclass, field


STARTING_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


def _fen_side_to_xiangqi(token: str) -> str:
    """Map FEN side token ('w'/'b') to Xiangqi convention ('red'/'black')."""
    return {"w": "red", "b": "black"}.get(token.lower(), token)


@dataclass
class MoveRecord:
    from_sq: str          # e.g. "e3"
    to_sq: str            # e.g. "e4"
    piece: str = ""       # e.g. "R" (optional)
    fen_after: str = ""   # FEN after the move


@dataclass
class GameStateBridge:
    """Central state object for the bridge.  All fields are plain data so
    they can be serialised to JSON trivially."""

    fen: str = STARTING_FEN
    side_to_move: str = "red"
    game_result: str = "in_progress"
    is_check: bool = False

    # Last move applied by the engine
    last_move: MoveRecord | None = None
    move_history: list[MoveRecord] = field(default_factory=list)

    # Piece selection / legal-move overlay
    selected_square: str | None = None   # e.g. "e3"
    legal_moves: list[str] = field(default_factory=list)  # target squares

    # Coaching recommendation
    best_move_from: str | None = None
    best_move_to: str | None = None

    # CV camera reading (advisory, may differ from engine FEN)
    cv_fen: str | None = None

    # LED control flag (True = LEDs turned off for camera capture)
    leds_off: bool = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def apply_fen(self, fen: str, source: str = "engine") -> None:
        """Update FEN.  *source* is 'engine' or 'cv'."""
        if source == "cv":
            self.cv_fen = fen
        else:
            self.fen = fen
            parts = fen.split()
            if len(parts) >= 2:
                self.side_to_move = _fen_side_to_xiangqi(parts[1])

    def apply_move(self, from_sq: str, to_sq: str, piece: str = "",
                   fen_after: str = "") -> MoveRecord:
        rec = MoveRecord(from_sq=from_sq, to_sq=to_sq, piece=piece,
                         fen_after=fen_after)
        self.last_move = rec
        self.move_history.append(rec)
        if fen_after:
            self.apply_fen(fen_after)
        return rec

    def set_selection(self, square: str | None, targets: list[str] | None = None) -> None:
        self.selected_square = square
        self.legal_moves = targets or []

    def set_best_move(self, from_sq: str, to_sq: str) -> None:
        self.best_move_from = from_sq
        self.best_move_to = to_sq

    def to_dict(self) -> dict:
        return {
            "fen": self.fen,
            "side_to_move": self.side_to_move,
            "game_result": self.game_result,
            "is_check": self.is_check,
            "last_move": _move_dict(self.last_move),
            "move_count": len(self.move_history),
            "selected_square": self.selected_square,
            "legal_moves": self.legal_moves,
            "best_move_from": self.best_move_from,
            "best_move_to": self.best_move_to,
            "cv_fen": self.cv_fen,
            "leds_off": self.leds_off,
        }


def _move_dict(m: MoveRecord | None) -> dict | None:
    if m is None:
        return None
    return {"from": m.from_sq, "to": m.to_sq, "piece": m.piece,
            "fen_after": m.fen_after}
