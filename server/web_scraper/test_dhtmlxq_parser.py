"""
Tests for the DhtmlXQ parser — coordinate conversion, movelist parsing,
FEN generation, commentary extraction, and edge cases.
"""

import json
import pytest
from pipeline.loaders.dhtmlxq_parser import (
    DhtmlXQMove,
    DhtmlXQGame,
    _parse_movelist,
    _extract_tags,
    _board_to_fen,
    _copy_board,
    _START_BOARD,
    parse_dhtmlxq_block,
    parse_all_games,
    generate_fens_for_game,
    game_to_training_entries,
)


# ========================
#     COORDINATE CONVERSION
# ========================

class TestCoordinateConversion:

    def test_central_cannon_opening(self):
        """7747 = Red cannon h2 -> e2."""
        mv = DhtmlXQMove(index=0, from_col=7, from_row=7, to_col=4, to_row=7)
        assert mv.algebraic == "h2e2"
        assert mv.raw_digits == "7747"

    def test_horse_defense(self):
        """1022 = Black horse b9 -> c7."""
        mv = DhtmlXQMove(index=1, from_col=1, from_row=0, to_col=2, to_row=2)
        assert mv.algebraic == "b9c7"

    def test_red_back_rank(self):
        """Row 9 in DhtmlXQ = rank 0 (Red back rank)."""
        mv = DhtmlXQMove(index=0, from_col=4, from_row=9, to_col=4, to_row=8)
        assert mv.from_rank == 0
        assert mv.to_rank == 1
        assert mv.algebraic == "e0e1"

    def test_black_back_rank(self):
        """Row 0 in DhtmlXQ = rank 9 (Black back rank)."""
        mv = DhtmlXQMove(index=0, from_col=4, from_row=0, to_col=4, to_row=1)
        assert mv.from_rank == 9
        assert mv.to_rank == 8
        assert mv.algebraic == "e9e8"

    def test_all_corners(self):
        # a0 = col 0, row 9
        mv = DhtmlXQMove(index=0, from_col=0, from_row=9, to_col=0, to_row=9)
        assert mv.from_file == "a" and mv.from_rank == 0

        # i0 = col 8, row 9
        mv = DhtmlXQMove(index=0, from_col=8, from_row=9, to_col=0, to_row=0)
        assert mv.from_file == "i" and mv.from_rank == 0

        # a9 = col 0, row 0
        mv = DhtmlXQMove(index=0, from_col=0, from_row=0, to_col=0, to_row=0)
        assert mv.from_file == "a" and mv.from_rank == 9

        # i9 = col 8, row 0
        mv = DhtmlXQMove(index=0, from_col=8, from_row=0, to_col=0, to_row=0)
        assert mv.from_file == "i" and mv.from_rank == 9


# ========================
#     MOVELIST PARSING
# ========================

class TestMovelistParsing:

    def test_basic(self):
        moves = _parse_movelist("7747102279271927")
        assert len(moves) == 4
        assert moves[0] == (7, 7, 4, 7)

    def test_empty(self):
        assert _parse_movelist("") == []
        assert _parse_movelist("   ") == []

    def test_whitespace_stripped(self):
        assert len(_parse_movelist("77 47\n10 22")) == 2

    def test_short_ignored(self):
        assert _parse_movelist("774") == []

    def test_trailing_digits(self):
        assert len(_parse_movelist("77471")) == 1

    def test_invalid_coords_filtered(self):
        assert _parse_movelist("9947") == []


# ========================
#     TAG EXTRACTION
# ========================

class TestTagExtraction:

    def test_closed_tags(self):
        block = (
            "[DhtmlXQ_title]Test[/DhtmlXQ_title]"
            "[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]"
        )
        tags = _extract_tags(block)
        assert tags["title"] == "Test"
        assert tags["movelist"] == "7747"

    def test_open_tags_fallback(self):
        block = "[DhtmlXQ_title]Test\n[DhtmlXQ_movelist]7747\n"
        tags = _extract_tags(block)
        assert "title" in tags
        assert "movelist" in tags

    def test_comment_tags(self):
        block = (
            "[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]"
            "[DhtmlXQ_comment0]Intro[/DhtmlXQ_comment0]"
            "[DhtmlXQ_comment1]Move 1[/DhtmlXQ_comment1]"
        )
        tags = _extract_tags(block)
        assert tags["comment0"] == "Intro"
        assert tags["comment1"] == "Move 1"


# ========================
#     GAME PARSING
# ========================

SAMPLE = (
    "[DhtmlXQ_title]2024 Championship[/DhtmlXQ_title]"
    "[DhtmlXQ_red]Wang Tianyi[/DhtmlXQ_red]"
    "[DhtmlXQ_black]Zheng Weitong[/DhtmlXQ_black]"
    "[DhtmlXQ_result]1-0[/DhtmlXQ_result]"
    "[DhtmlXQ_movelist]77471022[/DhtmlXQ_movelist]"
    "[DhtmlXQ_comment0]Classic duel[/DhtmlXQ_comment0]"
    "[DhtmlXQ_comment1]Central cannon[/DhtmlXQ_comment1]"
    "[DhtmlXQ_comment2]Screen horse[/DhtmlXQ_comment2]"
)


class TestGameParsing:

    def test_basic(self):
        g = parse_dhtmlxq_block(SAMPLE, "http://test")
        assert g is not None
        assert g.title == "2024 Championship"
        assert g.red_player == "Wang Tianyi"
        assert g.total_moves == 2

    def test_commentary(self):
        g = parse_dhtmlxq_block(SAMPLE)
        assert g.opening_comment == "Classic duel"
        assert g.moves[0].commentary == "Central cannon"
        assert g.moves[1].commentary == "Screen horse"
        assert g.commentary_coverage == 1.0

    def test_no_movelist(self):
        assert parse_dhtmlxq_block("[DhtmlXQ_title]X[/DhtmlXQ_title]") is None

    def test_no_commentary(self):
        g = parse_dhtmlxq_block("[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]")
        assert g is not None
        assert not g.has_commentary

    def test_html_block(self):
        html = f"<html><body>[DhtmlXQ]{SAMPLE}[/DhtmlXQ]</body></html>"
        games = parse_all_games(html, "http://test")
        assert len(games) == 1

    def test_multiple_games(self):
        b1 = "[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]"
        b2 = "[DhtmlXQ_movelist]1022[/DhtmlXQ_movelist]"
        html = f"[DhtmlXQ]{b1}[/DhtmlXQ] [DhtmlXQ]{b2}[/DhtmlXQ]"
        assert len(parse_all_games(html)) == 2

    def test_html_cleaned(self):
        block = (
            "[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]"
            "[DhtmlXQ_comment1]<b>Bold</b> <br/>text[/DhtmlXQ_comment1]"
        )
        g = parse_dhtmlxq_block(block)
        assert g.moves[0].commentary == "Bold text"


# ========================
#     FEN GENERATION
# ========================

class TestFEN:

    def test_starting_fen(self):
        fen = _board_to_fen(_copy_board(_START_BOARD), "w")
        expected = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
        assert fen == expected

    def test_central_cannon(self):
        g = parse_dhtmlxq_block("[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]")
        fens = generate_fens_for_game(g)
        assert len(fens) == 1
        assert fens[0]["move_str"] == "h2e2"
        assert fens[0]["side"] == "red"
        # FEN before move = starting position
        assert fens[0]["fen"].startswith("rnbakabnr")

    def test_two_moves(self):
        g = parse_dhtmlxq_block("[DhtmlXQ_movelist]77471022[/DhtmlXQ_movelist]")
        fens = generate_fens_for_game(g)
        assert len(fens) == 2
        assert fens[0]["side"] == "red"
        assert fens[1]["side"] == "black"
        assert fens[1]["move_str"] == "b9c7"
        # Second FEN (before Black's move) should show cannon moved to e2
        assert "1C2C" in fens[1]["fen"]


# ========================
#     TRAINING EXPORT
# ========================

class TestExport:

    def test_entries(self):
        g = parse_dhtmlxq_block(
            "[DhtmlXQ_title]Test[/DhtmlXQ_title]"
            "[DhtmlXQ_red]Red[/DhtmlXQ_red]"
            "[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]"
            "[DhtmlXQ_comment1]Central cannon[/DhtmlXQ_comment1]",
            "http://test",
        )
        entries = game_to_training_entries(g)
        assert len(entries) == 1
        assert entries[0]["move_str"] == "h2e2"
        assert entries[0]["expert_commentary"] == "Central cannon"
        assert entries[0]["game_title"] == "Test"

    def test_json_serializable(self):
        g = parse_dhtmlxq_block("[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]")
        for e in game_to_training_entries(g):
            line = json.dumps(e, ensure_ascii=False)
            parsed = json.loads(line)
            assert parsed["fen"]
            assert parsed["move_str"]

    def test_no_commentary_is_none(self):
        g = parse_dhtmlxq_block("[DhtmlXQ_movelist]7747[/DhtmlXQ_movelist]")
        entries = game_to_training_entries(g)
        assert entries[0]["expert_commentary"] is None


# ========================
#     GAME MODEL
# ========================

class TestGameModel:

    def test_properties(self):
        g = DhtmlXQGame(
            title="Test",
            moves=[
                DhtmlXQMove(0, 7, 7, 4, 7, commentary="C1"),
                DhtmlXQMove(1, 1, 0, 2, 2),
                DhtmlXQMove(2, 7, 9, 2, 7, commentary="C2"),
            ],
        )
        assert g.total_moves == 3
        assert g.has_commentary
        assert g.commented_move_count == 2
        assert abs(g.commentary_coverage - 2 / 3) < 0.01

    def test_opening_comment_counts(self):
        g = DhtmlXQGame(
            opening_comment="Intro",
            moves=[DhtmlXQMove(0, 7, 7, 4, 7)],
        )
        assert g.has_commentary


# ========================
#     BINIT PARSING
# ========================

class TestBinit:

    def test_standard_starting_position(self):
        """binit encoding of the standard starting position must decode to
        the canonical FEN."""
        from pipeline.loaders.dhtmlxq_parser import (
            _parse_binit, _board_to_fen, _copy_board, _START_BOARD,
        )
        binit = "0919293949596979891777062646668600102030405060708012720323436383"
        board = _parse_binit(binit)
        fen = _board_to_fen(board, "w")
        expected = _board_to_fen(_copy_board(_START_BOARD), "w")
        assert fen == expected

    def test_endgame_position(self):
        """binit for an endgame (K+R vs k+n+p+2a) decodes correctly."""
        from pipeline.loaders.dhtmlxq_parser import _parse_binit, _board_to_fen
        # Practical Endgames 175: Red K at d0, R at i0; Black k at d9, a at e8, a+n at d7/f7, p at d3
        binit = "8999999939999999999999999999999999529932304199999999993699999999"
        board = _parse_binit(binit)
        fen = _board_to_fen(board, "w")
        # Red pieces
        assert board[9][3] == "K"  # King at d0
        assert board[9][8] == "R"  # Rook at i0
        # Black pieces
        assert board[0][3] == "k"  # King at d9
        # Piece at i0 (row 9, col 8) should be Red Rook — first move i0i9 is valid
        assert board[9][8] == "R"

    def test_off_board_pieces(self):
        """Pairs of '99' must not place pieces on the board."""
        from pipeline.loaders.dhtmlxq_parser import _parse_binit
        # All pieces off board
        binit = "99" * 32
        board = _parse_binit(binit)
        for row in board:
            assert all(c == "." for c in row)

    def test_pick_init_prefers_binit_over_viewport(self):
        """init=500,350 (viewport) must be ignored in favour of binit."""
        from pipeline.loaders.dhtmlxq_parser import _pick_init
        tags = {
            "init": "500,350",
            "binit": "0919293949596979891777062646668600102030405060708012720323436383",
        }
        result = _pick_init(tags)
        assert len(result) == 64
        assert "," not in result


# ========================
#   UNWRAPPED MULTI-GAME
# ========================

class TestUnwrappedMultiGame:

    def test_iframe_delimited(self):
        """Multiple games separated by [DhtmlXQiFrame] tags."""
        page = (
            "[DhtmlXQiFrame]"
            "[DhtmlXQ_title]Game A[/DhtmlXQ_title]"
            "[DhtmlXQ_movelist]77474737[/DhtmlXQ_movelist]"
            "[DhtmlXQiFrame]"
            "[DhtmlXQ_title]Game B[/DhtmlXQ_title]"
            "[DhtmlXQ_movelist]00091909[/DhtmlXQ_movelist]"
        )
        games = parse_all_games(page)
        assert len(games) == 2
        assert games[0].title == "Game A"
        assert games[1].title == "Game B"

    def test_binit_per_game(self):
        """Each unwrapped game gets its own binit, not the first one."""
        binit_start = "0919293949596979891777062646668600102030405060708012720323436383"
        binit_endgame = "8999999939999999999999999999999999529932304199999999993699999999"
        page = (
            "[DhtmlXQiFrame]"
            "[DhtmlXQ_binit]" + binit_start + "[/DhtmlXQ_binit]"
            "[DhtmlXQ_movelist]77474737[/DhtmlXQ_movelist]"
            "[DhtmlXQiFrame]"
            "[DhtmlXQ_binit]" + binit_endgame + "[/DhtmlXQ_binit]"
            "[DhtmlXQ_movelist]89800908[/DhtmlXQ_movelist]"
        )
        games = parse_all_games(page)
        assert len(games) == 2
        assert games[0].init_position == binit_start
        assert games[1].init_position == binit_endgame


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
