"""fen_features.py — Lightweight FEN feature extractor for Xiangqi positions.

Produces a concise natural-language description of the board state from a
FEN string, suitable for inclusion in LLM training prompts.

Features extracted (curated subset — NOT the dense engine PositionAnalysis):
  - Material summary (piece counts per side + balance)
  - Palace occupancy (advisors + elephants still in palace)
  - King position (center-file vs off-center)
  - Crossed-river pieces (infiltrating pieces with square)
  - Game phase (inferred from total piece count)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ========================
#   PIECE DEFINITIONS
# ========================

# Uppercase = Red, lowercase = Black
# R=Rook, N=Knight, B=Elephant, A=Advisor, K=King, C=Cannon, P=Pawn

PIECE_VALUES: dict[str, int] = {
    "R": 900, "N": 400, "B": 200, "A": 200, "C": 450, "P": 100, "K": 0,
    "r": 900, "n": 400, "b": 200, "a": 200, "c": 450, "p": 100, "k": 0,
}

_PIECE_LABEL: dict[str, str] = {
    "R": "Rk", "r": "Rk",
    "N": "Kn", "n": "Kn",
    "B": "El", "b": "El",
    "A": "Ad", "a": "Ad",
    "C": "Cn", "c": "Cn",
    "P": "Pw", "p": "Pw",
    "K": "Kg", "k": "Kg",
}

_PIECE_NAME: dict[str, str] = {
    "R": "red_chariot",   "r": "black_chariot",
    "N": "red_horse",     "n": "black_horse",
    "B": "red_elephant",  "b": "black_elephant",
    "A": "red_advisor",   "a": "black_advisor",
    "K": "red_general",   "k": "black_general",
    "C": "red_cannon",    "c": "black_cannon",
    "P": "red_pawn",      "p": "black_pawn",
}

# Palace squares (row, col) in board representation
# Board: row 0 = rank 9 (Black back rank), row 9 = rank 0 (Red back rank)
# Palace cols: 3-5 (files d-f)
_RED_PALACE_ROWS: frozenset[int] = frozenset({7, 8, 9})    # rows 7-9 → ranks 0-2
_BLACK_PALACE_ROWS: frozenset[int] = frozenset({0, 1, 2})  # rows 0-2 → ranks 7-9
_PALACE_COLS: frozenset[int] = frozenset({3, 4, 5})         # files d, e, f


# ========================
#   FEN PARSING
# ========================

def parse_fen_board(fen: str) -> list[list[str]]:
    """Parse the board part of a FEN string into a 10×9 grid.

    Row 0 = rank 9 (Black back rank).
    Row 9 = rank 0 (Red back rank).
    Empty squares are represented as '.'.
    """
    board_part = fen.split()[0]
    rows_raw = board_part.split("/")

    board: list[list[str]] = []
    for row_str in rows_raw:
        row: list[str] = []
        for ch in row_str:
            if ch.isdigit():
                row.extend(["."] * int(ch))
            else:
                row.append(ch)
        # Normalise to exactly 9 columns
        while len(row) < 9:
            row.append(".")
        board.append(row[:9])

    # Normalise to exactly 10 rows
    while len(board) < 10:
        board.append(["."] * 9)
    return board[:10]


def _piece_list(board: list[list[str]]) -> list[tuple[str, int, int]]:
    """Return (piece_char, row, col) for every non-empty square."""
    return [
        (board[r][c], r, c)
        for r in range(10)
        for c in range(9)
        if board[r][c] != "."
    ]


def _alg(row: int, col: int) -> str:
    """Convert (row, col) board coordinates to algebraic notation (e.g. 'e0')."""
    return f"{chr(ord('a') + col)}{9 - row}"


# ========================
#   FEATURE DATACLASS
# ========================

@dataclass
class FenFeatures:
    side_to_move: str = "red"
    phase: str = "middlegame"       # "opening" | "middlegame" | "endgame"
    total_pieces: int = 0

    # Material: piece_char → count (uppercase=Red, lowercase=Black)
    red_material: dict[str, int] = field(default_factory=dict)
    black_material: dict[str, int] = field(default_factory=dict)
    material_balance: int = 0       # positive = Red advantage (centipawns)

    # Palace occupancy
    red_palace_advisors: int = 0
    red_palace_elephants: int = 0
    black_palace_advisors: int = 0
    black_palace_elephants: int = 0

    # King positions
    red_king_square: Optional[str] = None
    black_king_square: Optional[str] = None
    red_king_on_center: bool = True
    black_king_on_center: bool = True

    # Crossed-river pieces: list of (piece_char, algebraic_square)
    red_crossed: list[tuple[str, str]] = field(default_factory=list)
    black_crossed: list[tuple[str, str]] = field(default_factory=list)


# ========================
#   EXTRACTION
# ========================

def extract_features(fen: str) -> FenFeatures:
    """Extract board features from a FEN string."""
    board = parse_fen_board(fen)
    pieces = _piece_list(board)

    parts = fen.split()
    side_token = parts[1] if len(parts) > 1 else "w"
    side = "red" if side_token.lower() == "w" else "black"

    feat = FenFeatures(side_to_move=side, total_pieces=len(pieces))

    # --- Game phase ---
    if feat.total_pieces >= 28:
        feat.phase = "opening"
    elif feat.total_pieces >= 16:
        feat.phase = "middlegame"
    else:
        feat.phase = "endgame"

    # --- Material, palace, king, crossed-river ---
    red_val = 0
    black_val = 0

    for (ch, row, col) in pieces:
        sq = _alg(row, col)

        if ch.isupper():  # Red piece
            feat.red_material[ch] = feat.red_material.get(ch, 0) + 1
            red_val += PIECE_VALUES.get(ch, 0)
        else:             # Black piece
            feat.black_material[ch] = feat.black_material.get(ch, 0) + 1
            black_val += PIECE_VALUES.get(ch, 0)

        # King squares
        if ch == "K":
            feat.red_king_square = sq
            feat.red_king_on_center = (col == 4)
        elif ch == "k":
            feat.black_king_square = sq
            feat.black_king_on_center = (col == 4)

        # Palace occupancy
        if ch == "A" and row in _RED_PALACE_ROWS and col in _PALACE_COLS:
            feat.red_palace_advisors += 1
        elif ch == "a" and row in _BLACK_PALACE_ROWS and col in _PALACE_COLS:
            feat.black_palace_advisors += 1
        elif ch == "B" and row in _RED_PALACE_ROWS and col in _PALACE_COLS:
            feat.red_palace_elephants += 1
        elif ch == "b" and row in _BLACK_PALACE_ROWS and col in _PALACE_COLS:
            feat.black_palace_elephants += 1

        # Crossed-river pieces (not kings)
        # Red crosses river when row < 5 (into ranks 5-9, Black's half)
        # Black crosses river when row >= 5 (into ranks 0-4, Red's half)
        if ch.isupper() and ch != "K" and row < 5:
            feat.red_crossed.append((ch, sq))
        elif ch.islower() and ch != "k" and row >= 5:
            feat.black_crossed.append((ch, sq))

    feat.material_balance = red_val - black_val
    return feat


# ========================
#   NATURAL LANGUAGE
# ========================

def _material_str(mat: dict[str, int], uppercase: bool) -> str:
    """Format piece counts as a compact string like '1Rk 2Kn 1Cn 3Pw'."""
    order = (
        ["R", "N", "C", "B", "A", "P"] if uppercase
        else ["r", "n", "c", "b", "a", "p"]
    )
    parts = [f"{mat[k]}{_PIECE_LABEL[k]}" for k in order if mat.get(k, 0) > 0]
    return " ".join(parts) if parts else "—"


def features_to_text(feat: FenFeatures) -> str:
    """Render extracted features as a compact natural-language block."""
    lines: list[str] = []

    lines.append(f"Phase: {feat.phase} ({feat.total_pieces} pieces on board)")
    lines.append(f"To move: {feat.side_to_move}")

    red_mat = _material_str(feat.red_material, uppercase=True)
    blk_mat = _material_str(feat.black_material, uppercase=False)
    lines.append(f"Material — Red: {red_mat} | Black: {blk_mat}")

    if feat.material_balance > 0:
        lines.append(f"Material edge: Red (+{feat.material_balance} cp)")
    elif feat.material_balance < 0:
        lines.append(f"Material edge: Black (+{-feat.material_balance} cp)")
    else:
        lines.append("Material: equal")

    r_pal = f"{feat.red_palace_advisors}Ad {feat.red_palace_elephants}El"
    b_pal = f"{feat.black_palace_advisors}Ad {feat.black_palace_elephants}El"
    lines.append(f"Palace defense — Red: {r_pal} | Black: {b_pal}")

    if feat.red_king_square:
        ctr = "center file" if feat.red_king_on_center else "off-center"
        lines.append(f"Red king: {feat.red_king_square} ({ctr})")
    if feat.black_king_square:
        ctr = "center file" if feat.black_king_on_center else "off-center"
        lines.append(f"Black king: {feat.black_king_square} ({ctr})")

    if feat.red_crossed:
        crossed = ", ".join(
            f"{_PIECE_LABEL[ch]}@{sq}" for ch, sq in feat.red_crossed
        )
        lines.append(f"Red crossed river: {crossed}")
    if feat.black_crossed:
        crossed = ", ".join(
            f"{_PIECE_LABEL[ch]}@{sq}" for ch, sq in feat.black_crossed
        )
        lines.append(f"Black crossed river: {crossed}")

    return "\n".join(lines)


def enrich_fen(fen: str) -> str:
    """Return a formatted string combining the FEN with extracted features."""
    feat = extract_features(fen)
    return f"FEN: {fen}\n{features_to_text(feat)}"


# ========================
#   RELATIONAL HELPERS
# ========================

def _pieces_between(
    board: list[list[str]], r1: int, c1: int, r2: int, c2: int
) -> int:
    """Count pieces strictly between two squares on the same rank or file."""
    count = 0
    if r1 == r2:
        for c in range(min(c1, c2) + 1, max(c1, c2)):
            if board[r1][c] != ".":
                count += 1
    elif c1 == c2:
        for r in range(min(r1, r2) + 1, max(r1, r2)):
            if board[r][c1] != ".":
                count += 1
    return count


def _rook_attacks(
    board: list[list[str]], row: int, col: int
) -> list[tuple[str, int, int]]:
    """Return (piece_char, row, col) for the first piece hit in each of 4 directions."""
    results: list[tuple[str, int, int]] = []
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        r, c = row + dr, col + dc
        while 0 <= r < 10 and 0 <= c < 9:
            if board[r][c] != ".":
                results.append((board[r][c], r, c))
                break
            r += dr
            c += dc
    return results


def _cannon_attacks(
    board: list[list[str]], row: int, col: int
) -> list[tuple[str, int, int, str, int, int]]:
    """Return (target_ch, tr, tc, screen_ch, sr, sc) for all cannon capture lines."""
    results: list[tuple[str, int, int, str, int, int]] = []
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        r, c = row + dr, col + dc
        screen_ch: Optional[str] = None
        sr, sc = -1, -1
        while 0 <= r < 10 and 0 <= c < 9:
            if board[r][c] != ".":
                if screen_ch is None:
                    screen_ch, sr, sc = board[r][c], r, c
                else:
                    results.append((board[r][c], r, c, screen_ch, sr, sc))
                    break
            r += dr
            c += dc
    return results


def _knight_attacks(
    board: list[list[str]], row: int, col: int
) -> list[tuple[str, int, int]]:
    """Return (piece_at_dest, dest_row, dest_col) for all reachable knight destinations.

    Respects the horse's-leg blocking rule.
    """
    results: list[tuple[str, int, int]] = []
    for leg_dr, leg_dc, end_dr, end_dc in [
        (-1,  0, -1, -1), (-1,  0, -1,  1),
        ( 1,  0,  1, -1), ( 1,  0,  1,  1),
        ( 0, -1, -1, -1), ( 0, -1,  1, -1),
        ( 0,  1, -1,  1), ( 0,  1,  1,  1),
    ]:
        lr, lc = row + leg_dr, col + leg_dc
        if not (0 <= lr < 10 and 0 <= lc < 9):
            continue
        if board[lr][lc] != ".":        # horse's leg blocked
            continue
        dr, dc = lr + end_dr, lc + end_dc
        if 0 <= dr < 10 and 0 <= dc < 9:
            results.append((board[dr][dc], dr, dc))
    return results


# ========================
#   RELATIONAL FEATURES
# ========================

def compute_relations(fen: str) -> list[str]:
    """Compute explicit relational features from a FEN position.

    Returns a list of relation strings covering attacks, cannon screens,
    knight forks, flying general threats, pins, pawn structure, and king
    exposure.
    """
    board = parse_fen_board(fen)
    pieces = _piece_list(board)
    relations: list[str] = []

    # Locate kings up-front (needed for pins / flying-general / king-exposure)
    red_king: Optional[tuple[int, int]] = None
    black_king: Optional[tuple[int, int]] = None
    for ch, r, c in pieces:
        if ch == "K":
            red_king = (r, c)
        elif ch == "k":
            black_king = (r, c)

    for ch, row, col in pieces:
        sq = _alg(row, col)
        name = _PIECE_NAME.get(ch, ch)
        is_red = ch.isupper()
        enemy_king_ch = "k" if is_red else "K"

        # ---- Chariot attacks + pins ----
        if ch in ("R", "r"):
            for tch, tr, tc in _rook_attacks(board, row, col):
                if is_red == tch.isupper():
                    continue  # friendly piece
                tsq = _alg(tr, tc)
                tname = _PIECE_NAME.get(tch, tch)
                line = "open_file" if col == tc else "open_rank"
                dist = abs(tr - row) + abs(tc - col)
                relations.append(
                    f"attack({name}@{sq}, {tname}@{tsq},"
                    f" distance={dist}, line={line})"
                )
                # Pin: enemy king directly behind the attacked piece?
                if tch not in ("K", "k"):
                    dr = 0 if row == tr else (1 if tr > row else -1)
                    dc = 0 if col == tc else (1 if tc > col else -1)
                    rr, cc = tr + dr, tc + dc
                    while 0 <= rr < 10 and 0 <= cc < 9:
                        sq_behind = board[rr][cc]
                        if sq_behind == enemy_king_ch:
                            ksq = _alg(rr, cc)
                            kname = _PIECE_NAME[enemy_king_ch]
                            relations.append(
                                f"pin({name}@{sq}, pinned={tname}@{tsq},"
                                f" behind={kname}@{ksq})"
                            )
                            break
                        if sq_behind != ".":
                            break
                        rr += dr
                        cc += dc

        # ---- Cannon screens ----
        elif ch in ("C", "c"):
            for tch, tr, tc, sch, sr, sc in _cannon_attacks(board, row, col):
                if is_red == tch.isupper():
                    continue  # cannon cannot capture friendly
                tsq = _alg(tr, tc)
                ssq = _alg(sr, sc)
                tname = _PIECE_NAME.get(tch, tch)
                sname = _PIECE_NAME.get(sch, sch)
                relations.append(
                    f"cannon_screen({name}@{sq}, screen={sname}@{ssq},"
                    f" target={tname}@{tsq})"
                )

        # ---- Knight forks and single attacks ----
        elif ch in ("N", "n"):
            targets = [
                (tch, tr, tc)
                for tch, tr, tc in _knight_attacks(board, row, col)
                if tch != "." and (is_red != tch.isupper())
            ]
            if len(targets) >= 2:
                t_str = ", ".join(
                    f"{_PIECE_NAME.get(t[0], t[0])}@{_alg(t[1], t[2])}"
                    for t in targets
                )
                relations.append(f"fork({name}@{sq}, targets=[{t_str}])")
            elif len(targets) == 1:
                tch, tr, tc = targets[0]
                relations.append(
                    f"attack({name}@{sq},"
                    f" {_PIECE_NAME.get(tch, tch)}@{_alg(tr, tc)})"
                )

        # ---- Pawn structure ----
        elif ch in ("P", "p"):
            crossed = (is_red and row < 5) or (not is_red and row >= 5)
            # Center-file pressure
            if crossed and col in _PALACE_COLS:
                depth = (4 - row) if is_red else (row - 5)
                relations.append(
                    f"pawn_center_pressure({name}@{sq},"
                    f" file={chr(ord('a') + col)}, depth={depth})"
                )
            # Diagonal pairs (only emit for lower-col pawn to avoid duplicates)
            if crossed and col + 1 < 9 and board[row][col + 1] == ch:
                nsq = _alg(row, col + 1)
                relations.append(
                    f"pawn_diagonal_pair({name}@{sq},"
                    f" {_PIECE_NAME[ch]}@{nsq}, mutual_defense=True)"
                )

    # ---- Flying general ----
    if red_king and black_king and red_king[1] == black_king[1]:
        between = _pieces_between(
            board, red_king[0], red_king[1], black_king[0], black_king[1]
        )
        if between == 0:
            file_letter = chr(ord("a") + red_king[1])
            rksq = _alg(*red_king)
            bksq = _alg(*black_king)
            relations.append(
                f"flying_general_threat(red_general@{rksq},"
                f" black_general@{bksq}, file={file_letter})"
            )

    # ---- King exposure ----
    for king_ch, king_label in (("K", "red_general"), ("k", "black_general")):
        king_pos = red_king if king_ch == "K" else black_king
        if king_pos is None:
            continue
        kr, kc = king_pos
        ksq = _alg(kr, kc)
        is_red_king = king_ch == "K"
        # Open file: king's column has no other pieces
        open_col = all(board[r][kc] in (".", king_ch) for r in range(10))
        # Nearby enemy pieces in the 3×3 neighbourhood
        nearby = sum(
            1
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if not (dr == 0 and dc == 0)
            and 0 <= kr + dr < 10
            and 0 <= kc + dc < 9
            and board[kr + dr][kc + dc] != "."
            and (is_red_king != board[kr + dr][kc + dc].isupper())
        )
        if open_col or nearby >= 2:
            parts: list[str] = []
            if open_col:
                parts.append(f"open_file={chr(ord('a') + kc)}")
            if nearby >= 2:
                parts.append(f"nearby_threats={nearby}")
            relations.append(
                f"king_exposure({king_label}@{ksq}, {', '.join(parts)})"
            )

    return relations


def relations_to_text(fen: str) -> str:
    """Return relational features as a bullet-point string (or '(none)' if empty)."""
    rels = compute_relations(fen)
    return "\n".join(f"- {r}" for r in rels) if rels else "(none)"


# ========================
#   QUICK SELF-TEST
# ========================

if __name__ == "__main__":
    start_fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
    print("=== Starting Position ===")
    print(enrich_fen(start_fen))
    print("\n[RELATIONS]")
    print(relations_to_text(start_fen))
    print()

    sample_fen = "2bak4/1C2a1n2/2R1br3/4p4/9/2P6/9/2C1B4/4A4/4KAB1c w"
    print("=== Sample Tactical Position ===")
    print(enrich_fen(sample_fen))
    print("\n[RELATIONS]")
    print(relations_to_text(sample_fen))
