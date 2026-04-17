"""
DhtmlXQ Parser
==============

Parses the DhtmlXQ (CC Bridge / Xiangqi viewer) format used by xqinenglish.com
and many other Xiangqi sites.  This format embeds game data inside HTML using
custom tags within ``[DhtmlXQ]...[/DhtmlXQ]`` blocks.

DhtmlXQ Tag Reference
---------------------
::

    [DhtmlXQ_title]       Game title / header
    [DhtmlXQ_red]         Red player name
    [DhtmlXQ_black]       Black player name
    [DhtmlXQ_event]       Tournament / event
    [DhtmlXQ_date]        Date of game
    [DhtmlXQ_result]      Result string
    [DhtmlXQ_open]        Opening name
    [DhtmlXQ_init]        Custom initial position (90 hex chars, rare)
    [DhtmlXQ_binit]       Binary init (alternative encoding)
    [DhtmlXQ_movelist]    Main-line moves as 4-digit coordinate groups
    [DhtmlXQ_comment0]    Comment before first move
    [DhtmlXQ_commentN]    Comment after move N (1-indexed)
    [DhtmlXQ_move_X_Y_Z]  Variation movelist (branch from move Y)
    [DhtmlXQ_comment_X_Y] Variation comment

Move Encoding
-------------
Each move in ``[DhtmlXQ_movelist]`` is four consecutive digits::

    FCFR TCTR

- FC = from-column  0-8  (a=0 .. i=8)
- FR = from-row     0-9  (0 = Black back rank, 9 = Red back rank)
- TC = to-column
- TR = to-row

Conversion to engine algebraic (e.g. ``h2e2``)::

    file  = chr('a' + column)
    rank  = 9 - row
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ========================
#     DATA MODELS
# ========================

@dataclass
class DhtmlXQMove:
    """A single move extracted from DhtmlXQ format."""

    index: int                # 0-based ply index
    from_col: int             # source column 0-8
    from_row: int             # source row 0-9 (DhtmlXQ coord)
    to_col: int               # dest column 0-8
    to_row: int               # dest row 0-9
    commentary: str = ""      # expert commentary (cleaned)

    # ---- derived properties ----

    @property
    def from_file(self) -> str:
        return chr(ord("a") + self.from_col)

    @property
    def from_rank(self) -> int:
        return 9 - self.from_row

    @property
    def to_file(self) -> str:
        return chr(ord("a") + self.to_col)

    @property
    def to_rank(self) -> int:
        return 9 - self.to_row

    @property
    def algebraic(self) -> str:
        """Engine-compatible notation, e.g. ``h2e2``."""
        return f"{self.from_file}{self.from_rank}{self.to_file}{self.to_rank}"

    @property
    def raw_digits(self) -> str:
        """Original 4-digit DhtmlXQ encoding."""
        return f"{self.from_col}{self.from_row}{self.to_col}{self.to_row}"


@dataclass
class DhtmlXQVariation:
    """An alternate move sequence branching from a position in the main line."""

    parent_move_index: int
    branch_number: int
    moves: list[DhtmlXQMove] = field(default_factory=list)


@dataclass
class DhtmlXQGame:
    """A complete game parsed from one ``[DhtmlXQ]`` block."""

    title: str = ""
    red_player: str = ""
    black_player: str = ""
    event: str = ""
    date: str = ""
    result: str = ""
    opening: str = ""
    init_position: str = ""    # raw init/binit string (non-standard start)
    source_url: str = ""

    moves: list[DhtmlXQMove] = field(default_factory=list)
    variations: list[DhtmlXQVariation] = field(default_factory=list)
    opening_comment: str = ""  # comment before the first move

    # ---- helpers ----

    @property
    def total_moves(self) -> int:
        return len(self.moves)

    @property
    def has_commentary(self) -> bool:
        if self.opening_comment:
            return True
        return any(m.commentary for m in self.moves)

    @property
    def commentary_coverage(self) -> float:
        """Fraction of moves that carry commentary (0.0 - 1.0)."""
        if not self.moves:
            return 0.0
        return sum(1 for m in self.moves if m.commentary) / len(self.moves)

    @property
    def commented_move_count(self) -> int:
        return sum(1 for m in self.moves if m.commentary)


# ========================
#     REGEX PATTERNS
# ========================

# Outer block:  [DhtmlXQ]...[/DhtmlXQ]
_BLOCK_RE = re.compile(r"\[DhtmlXQ\](.*?)\[/DhtmlXQ\]", re.DOTALL)

# Closed tags:  [DhtmlXQ_key]value[/DhtmlXQ_key]
_TAG_CLOSED_RE = re.compile(
    r"\[DhtmlXQ_([A-Za-z0-9_]+)\](.*?)\[/DhtmlXQ_\1\]", re.DOTALL
)

# Open tags (fallback — some sites omit closing tags):
#   [DhtmlXQ_key]value   (value ends at the next '[')
_TAG_OPEN_RE = re.compile(
    r"\[DhtmlXQ_([A-Za-z0-9_]+)\]([^\[]*)", re.DOTALL
)


# ========================
#     TAG EXTRACTION
# ========================

def _extract_tags(block: str) -> dict[str, str]:
    """Pull all ``DhtmlXQ_*`` tags from *block* into ``{key: value}``."""

    tags: dict[str, str] = {}

    # 1) Prefer properly closed tags
    for m in _TAG_CLOSED_RE.finditer(block):
        tags[m.group(1).strip()] = m.group(2).strip()

    # 2) Fallback: open-ended tags (fills gaps only)
    for m in _TAG_OPEN_RE.finditer(block):
        key = m.group(1).strip()
        if key not in tags:
            val = m.group(2).strip()
            if val:
                tags[key] = val

    return tags


# ========================
#     MOVELIST PARSER
# ========================

def _parse_movelist(raw: str) -> list[tuple[int, int, int, int]]:
    """Parse a DhtmlXQ movelist string into ``(from_col, from_row, to_col, to_row)`` tuples.

    The string is a sequence of 4-digit groups (non-digit chars stripped).
    """
    digits = re.sub(r"[^0-9]", "", raw)
    moves: list[tuple[int, int, int, int]] = []
    for i in range(0, len(digits) - 3, 4):
        fc, fr, tc, tr = int(digits[i]), int(digits[i + 1]), int(digits[i + 2]), int(digits[i + 3])
        if 0 <= fc <= 8 and 0 <= fr <= 9 and 0 <= tc <= 8 and 0 <= tr <= 9:
            moves.append((fc, fr, tc, tr))
    return moves


# ========================
#     COMMENTARY CLEANER
# ========================

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_XQ_TAG_RE = re.compile(r"\[/?DhtmlXQ[^\]]*\]")

def _clean(text: str) -> str:
    """Strip HTML tags, DhtmlXQ artefacts, and normalise whitespace."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _XQ_TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(".,;: ")
    return text


# ========================
#     BLOCK → GAME
# ========================

def _pick_init(tags: dict[str, str]) -> str:
    """Select the best initial-position tag.

    Prefers ``binit`` (actual board layout) over ``init`` (which sometimes
    contains viewport dimensions like ``500,350`` instead of board data).
    """
    binit = tags.get("binit", "").strip()
    if binit and len(binit) == 64 and all(c in "0123456789" for c in binit):
        return binit

    init = tags.get("init", "").strip()
    # Filter out viewport-dimension strings like "500,350"
    if init and "," not in init and len(init) >= 64:
        return init

    # If binit exists but didn't match the 64-digit check, still use it
    if binit:
        return binit

    return ""


def parse_dhtmlxq_block(block: str, source_url: str = "") -> Optional[DhtmlXQGame]:
    """Parse one ``[DhtmlXQ]`` block into a :class:`DhtmlXQGame`.

    Returns ``None`` if the block has no movelist.
    """
    tags = _extract_tags(block)
    if not tags:
        return None

    movelist_raw = tags.get("movelist", "")
    if not movelist_raw:
        return None

    game = DhtmlXQGame(
        title=_clean(tags.get("title", "")),
        red_player=_clean(tags.get("red", "")),
        black_player=_clean(tags.get("black", "")),
        event=_clean(tags.get("event", "")),
        date=_clean(tags.get("date", "")),
        result=_clean(tags.get("result", "")),
        opening=_clean(tags.get("open", tags.get("opening", ""))),
        init_position=_pick_init(tags),
        source_url=source_url,
        opening_comment=_clean(tags.get("comment0", "")),
    )

    # ---- main-line moves + comments ----
    raw_moves = _parse_movelist(movelist_raw)
    for idx, (fc, fr, tc, tr) in enumerate(raw_moves):
        # DhtmlXQ comment indexing is 1-based in most sites;
        # try both 1-based and 0-based keys.
        commentary = ""
        for key in (f"comment{idx + 1}", f"comment{idx}"):
            if key in tags and key != "comment0":
                commentary = _clean(tags[key])
                break

        game.moves.append(DhtmlXQMove(
            index=idx,
            from_col=fc, from_row=fr,
            to_col=tc, to_row=tr,
            commentary=commentary,
        ))

    # ---- variations ----
    for key, val in tags.items():
        m = re.match(r"move_(\d+)_(\d+)_(\d+)", key)
        if not m:
            continue
        _parent, branch_at, branch_no = int(m.group(1)), int(m.group(2)), int(m.group(3))
        var_raw = _parse_movelist(val)
        var_moves: list[DhtmlXQMove] = []
        for vi, (fc, fr, tc, tr) in enumerate(var_raw):
            vc_key = f"comment{_parent}_{branch_at + vi}_{branch_no}"
            var_moves.append(DhtmlXQMove(
                index=branch_at + vi,
                from_col=fc, from_row=fr,
                to_col=tc, to_row=tr,
                commentary=_clean(tags.get(vc_key, "")),
            ))
        if var_moves:
            game.variations.append(DhtmlXQVariation(
                parent_move_index=branch_at,
                branch_number=branch_no,
                moves=var_moves,
            ))

    return game


def parse_all_games(html: str, source_url: str = "") -> list[DhtmlXQGame]:
    """Extract **every** ``[DhtmlXQ]`` game from an HTML page.

    Handles three page layouts:

    1. Standard ``[DhtmlXQ]...[/DhtmlXQ]`` wrapper blocks.
    2. ``[DhtmlXQiFrame]``-delimited sections (no outer wrapper).
       Each section contains its own movelist, binit, title, etc.
    3. Bare tags in the HTML (single-game fallback).
    """

    games: list[DhtmlXQGame] = []

    # ---- Layout 1: proper [DhtmlXQ]...[/DhtmlXQ] blocks ----
    for m in _BLOCK_RE.finditer(html):
        g = parse_dhtmlxq_block(m.group(1), source_url)
        if g and g.moves:
            games.append(g)

    if games:
        return games

    # ---- Layout 2: [DhtmlXQiFrame]-delimited sections ----
    if "[DhtmlXQiFrame]" in html and html.count("[DhtmlXQ_movelist]") > 1:
        segments = re.split(r"\[DhtmlXQiFrame\]", html)
        for seg in segments:
            if "[DhtmlXQ_movelist]" not in seg:
                continue
            g = parse_dhtmlxq_block(seg, source_url)
            if g and g.moves:
                games.append(g)
        if games:
            return games

    # ---- Layout 3: single-game fallback ----
    if "[DhtmlXQ_movelist]" in html:
        g = parse_dhtmlxq_block(html, source_url)
        if g and g.moves:
            games.append(g)

    return games


# ========================
#     FEN GENERATION
# ========================

# Standard starting position — 10 rows x 9 columns
# Row 0 = Black back rank (rank 9); Row 9 = Red back rank (rank 0)
_START_BOARD: list[list[str]] = [
    list("rnbakabnr"),   # row 0 — rank 9
    list("........."),
    list(".c.....c."),
    list("p.p.p.p.p"),
    list("........."),
    list("........."),   # row 5 — river
    list("P.P.P.P.P"),
    list(".C.....C."),
    list("........."),
    list("RNBAKABNR"),   # row 9 — rank 0
]


def _board_to_fen(board: list[list[str]], side: str = "w") -> str:
    rows: list[str] = []
    for row in board:
        fen_row = ""
        empty = 0
        for ch in row:
            if ch == ".":
                empty += 1
            else:
                if empty:
                    fen_row += str(empty)
                    empty = 0
                fen_row += ch
        if empty:
            fen_row += str(empty)
        rows.append(fen_row)
    return f"{'/'.join(rows)} {side} - - 0 1"


def _copy_board(board: list[list[str]]) -> list[list[str]]:
    return [row[:] for row in board]


def _parse_init_position(init_str: str) -> list[list[str]]:
    """Decode a ``[DhtmlXQ_binit]`` or ``[DhtmlXQ_init]`` string.

    The **binit** format is 64 decimal digits encoding 32 piece positions.
    Each piece = 2 decimal digits for its square (``col * 10 + row``),
    or ``99`` if the piece is off the board.

    Piece order (indices 0-15 = Red, 16-31 = Black)::

        R R N N B B A A K C C P P P P P  |  r r n n b b a a k c c p p p p p

    Square encoding: ``sq = col * 10 + row`` where col ∈ [0,8], row ∈ [0,9].
    Row 0 = Black back rank (rank 9), Row 9 = Red back rank (rank 0).

    Falls back to the standard starting position on any parse failure.
    """
    if not init_str or not init_str.strip():
        return _copy_board(_START_BOARD)

    init_str = init_str.strip()

    # --- 64-digit decimal "binit" format (32 pieces × 2 decimal digits) ---
    if len(init_str) == 64 and all(c in "0123456789" for c in init_str):
        return _parse_binit(init_str)

    # --- 90-char format (one char per square, row-major) ---
    if len(init_str) >= 90:
        return _parse_init_90(init_str[:90])

    return _copy_board(_START_BOARD)


# DhtmlXQ binit piece order: Red pieces then Black pieces
# Positions 0-8: Red back rank left-to-right (R N B A K A B N R)
# Positions 9-10: Red cannons (left, right)
# Positions 11-15: Red pawns (a, c, e, g, i files)
# Positions 16-24: Black back rank left-to-right (r n b a k a b n r)
# Positions 25-26: Black cannons (left, right)
# Positions 27-31: Black pawns (a, c, e, g, i files)
_BINIT_PIECES = [
    # Red (indices 0-15)
    "R", "N", "B", "A", "K", "A", "B", "N", "R", "C", "C",
    "P", "P", "P", "P", "P",
    # Black (indices 16-31)
    "r", "n", "b", "a", "k", "a", "b", "n", "r", "c", "c",
    "p", "p", "p", "p", "p",
]


def _parse_binit(binit_str: str) -> list[list[str]]:
    """Parse the 64-digit decimal ``binit`` encoding.

    Square index = ``col * 10 + row``  (col 0-8, row 0-9).
    ``99`` means the piece is not on the board.
    """
    board = [list(".........") for _ in range(10)]

    for i, piece_char in enumerate(_BINIT_PIECES):
        pair = binit_str[i * 2: i * 2 + 2]
        if pair == "99":
            continue  # piece not on board
        try:
            sq = int(pair)
        except ValueError:
            continue
        col = sq // 10
        row = sq % 10
        if 0 <= col <= 8 and 0 <= row <= 9:
            board[row][col] = piece_char
    return board


def _parse_init_90(init_str: str) -> list[list[str]]:
    """Parse the 90-char-per-square init format."""
    _MAP = {
        "0": ".", "1": "K", "2": "A", "3": "B", "4": "N",
        "5": "R", "6": "C", "7": "P",
        "8": "k", "9": "a", "a": "b", "b": "n",
        "c": "r", "d": "c", "e": "p",
    }
    board: list[list[str]] = []
    for r in range(10):
        row: list[str] = []
        for c in range(9):
            ch = init_str[r * 9 + c].lower()
            row.append(_MAP.get(ch, "."))
        board.append(row)
    return board


def generate_fens_for_game(game: DhtmlXQGame) -> list[dict]:
    """Replay the game and produce a FEN + metadata dict for every ply.

    Each dict contains:
        ``fen``          FEN **before** the move
        ``move_str``     algebraic notation (``h2e2``)
        ``move_index``   0-based ply index
        ``commentary``   expert commentary (may be empty)
        ``side``         ``"red"`` or ``"black"``
        ``raw_digits``   original 4-digit DhtmlXQ encoding
    """
    board = (
        _parse_init_position(game.init_position)
        if game.init_position
        else _copy_board(_START_BOARD)
    )

    results: list[dict] = []
    side = "w"  # Red moves first

    for mv in game.moves:
        fen = _board_to_fen(board, side)
        results.append({
            "fen": fen,
            "move_str": mv.algebraic,
            "move_index": mv.index,
            "commentary": mv.commentary,
            "side": "red" if side == "w" else "black",
            "raw_digits": mv.raw_digits,
        })

        # Apply move on the 10x9 array
        board[mv.to_row][mv.to_col] = board[mv.from_row][mv.from_col]
        board[mv.from_row][mv.from_col] = "."

        side = "b" if side == "w" else "w"

    return results


# ========================
#     TRAINING EXPORT
# ========================

def game_to_training_entries(game: DhtmlXQGame) -> list[dict]:
    """Convert a :class:`DhtmlXQGame` to JSONL-compatible training dicts.

    Compatible with ``generate_training_data.py`` input format.
    """
    fens = generate_fens_for_game(game)
    entries: list[dict] = []

    for entry in fens:
        entries.append({
            "fen": entry["fen"],
            "move_str": entry["move_str"],
            "expert_commentary": entry["commentary"] or None,
            "move_index": entry["move_index"],
            "side": entry["side"],
            "game_title": game.title,
            "red_player": game.red_player,
            "black_player": game.black_player,
            "event": game.event,
            "result": game.result,
            "source_url": game.source_url,
        })

    return entries
