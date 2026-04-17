//! Piece-Square Tables (PSTs) for Xiangqi Position Evaluation
//!
//! PSTs assign positional bonuses/penalties based on where a piece sits on the board.
//! Values are in centipawns. Two phases: opening/midgame and endgame.
//! Tables are defined for RED pieces (bottom of board, ranks 0-4 = own territory).
//! BLACK values are mirrored vertically at lookup time.
//!
//! Board uses 11×14 mailbox (154 squares). Only the 90 valid squares
//! (file 0-8, rank 0-9) have meaningful values; all others are 0.

use crate::Game::{
    Board, PIECE_TYPE, PIECE_COLOR,
    RED, EMPTY, OFFBOARD,
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,
};

// ========================
//     9×10 RAW TABLES
// ========================
// Indexed as [rank][file] where rank 0 = Red's back rank, rank 9 = Black's back rank.
// Values for RED pieces — higher = better position for that piece.

/// Pawn PST (Opening/Midgame)
/// Pawns are worth more after crossing the river (rank 5+) and on central files.
const PAWN_TABLE_MG: [[i32; 9]; 10] = [
    // rank 0 (Red back rank) — pawns can't be here normally
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    // rank 1
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    // rank 2
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    // rank 3 (starting pawn rank for Red)
    [  0,  0,  0,  2,  4,  2,  0,  0,  0],
    // rank 4
    [  2,  0,  4,  6, 10,  6,  4,  0,  2],
    // rank 5 (river — crossed)
    [ 10, 12, 18, 30, 36, 30, 18, 12, 10],
    // rank 6
    [ 20, 24, 32, 40, 48, 40, 32, 24, 20],
    // rank 7
    [ 20, 30, 40, 50, 58, 50, 40, 30, 20],
    // rank 8
    [ 20, 30, 40, 50, 58, 50, 40, 30, 20],
    // rank 9 (Black back rank)
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Pawn PST (Endgame) — pawns even more valuable deep in enemy territory
const PAWN_TABLE_EG: [[i32; 9]; 10] = [
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  4,  6,  4,  0,  0,  0],
    [  4,  2,  6, 10, 14, 10,  6,  2,  4],
    [ 14, 18, 24, 36, 44, 36, 24, 18, 14],
    [ 30, 34, 42, 52, 60, 52, 42, 34, 30],
    [ 40, 44, 52, 62, 70, 62, 52, 44, 40],
    [ 40, 44, 52, 62, 70, 62, 52, 44, 40],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Advisor PST — prefer center of palace
const ADVISOR_TABLE: [[i32; 9]; 10] = [
    [  0,  0,  0, 10,  0, 10,  0,  0,  0], // rank 0
    [  0,  0,  0,  0, 15,  0,  0,  0,  0], // rank 1 — center is best
    [  0,  0,  0, 10,  0, 10,  0,  0,  0], // rank 2
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Elephant PST — prefer standard defensive positions, penalize edge
const ELEPHANT_TABLE: [[i32; 9]; 10] = [
    [  0,  0,  8,  0,  0,  0,  8,  0,  0], // rank 0
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 10,  0,  0,  0, 14,  0,  0,  0, 10], // rank 2 — c2/g2 strong, e2 ideal
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0, 10,  0,  0,  0, 10,  0,  0], // rank 4 — c4/g4 forward elephants
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Knight/Horse PST (Opening/Midgame) — center control, avoid edges
const KNIGHT_TABLE_MG: [[i32; 9]; 10] = [
    [ -8,  0,  0,  0,  0,  0,  0,  0, -8], // rank 0
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ -4,  6, 10, 12, 12, 12, 10,  6, -4], // rank 2
    [  2,  8, 14, 16, 18, 16, 14,  8,  2],
    [  4, 10, 16, 22, 24, 22, 16, 10,  4],
    [  6, 14, 20, 26, 28, 26, 20, 14,  6], // rank 5 (river)
    [  6, 14, 20, 26, 28, 26, 20, 14,  6],
    [  4, 10, 16, 22, 24, 22, 16, 10,  4],
    [  2,  8, 10, 12, 14, 12, 10,  8,  2],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Knight/Horse PST (Endgame) — similar but slightly different weighting
const KNIGHT_TABLE_EG: [[i32; 9]; 10] = [
    [ -6,  0,  0,  0,  0,  0,  0,  0, -6],
    [  0,  2,  4,  6,  6,  6,  4,  2,  0],
    [  0,  6, 10, 14, 14, 14, 10,  6,  0],
    [  2, 10, 16, 20, 22, 20, 16, 10,  2],
    [  4, 12, 18, 24, 26, 24, 18, 12,  4],
    [  6, 14, 20, 26, 28, 26, 20, 14,  6],
    [  6, 14, 20, 26, 28, 26, 20, 14,  6],
    [  4, 12, 18, 24, 26, 24, 18, 12,  4],
    [  2, 10, 14, 16, 18, 16, 14, 10,  2],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Cannon PST (Opening/Midgame) — central files, good rank placement
const CANNON_TABLE_MG: [[i32; 9]; 10] = [
    [  0,  0,  2,  4,  8,  4,  2,  0,  0], // rank 0
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  2,  4,  6, 10, 14, 10,  6,  4,  2], // rank 2 (starting rank for cannons)
    [  2,  4,  8, 12, 14, 12,  8,  4,  2],
    [  4,  6, 10, 14, 18, 14, 10,  6,  4],
    [  6,  8, 12, 16, 20, 16, 12,  8,  6], // rank 5
    [  4,  6, 10, 14, 18, 14, 10,  6,  4],
    [  2,  4,  8, 10, 14, 10,  8,  4,  2],
    [  0,  0,  2,  4,  6,  4,  2,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Cannon PST (Endgame) — less valuable without screens
const CANNON_TABLE_EG: [[i32; 9]; 10] = [
    [  0,  0,  0,  2,  4,  2,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  2,  4,  6,  8,  6,  4,  2,  0],
    [  0,  2,  4,  6,  8,  6,  4,  2,  0],
    [  2,  4,  6,  8, 10,  8,  6,  4,  2],
    [  2,  4,  6,  8, 10,  8,  6,  4,  2],
    [  2,  4,  6,  8, 10,  8,  6,  4,  2],
    [  0,  2,  4,  6,  8,  6,  4,  2,  0],
    [  0,  0,  2,  4,  6,  4,  2,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

/// Rook/Chariot PST (Opening/Midgame) — open files, active positions
const ROOK_TABLE_MG: [[i32; 9]; 10] = [
    [  0,  0,  2,  4,  6,  4,  2,  0,  0], // rank 0
    [  0,  0,  2,  6,  8,  6,  2,  0,  0],
    [  2,  4,  6,  8, 10,  8,  6,  4,  2],
    [  4,  6,  8, 12, 14, 12,  8,  6,  4],
    [  6,  8, 10, 14, 16, 14, 10,  8,  6],
    [ 10, 12, 14, 18, 20, 18, 14, 12, 10], // rank 5 (across river!)
    [ 14, 16, 18, 22, 24, 22, 18, 16, 14],
    [ 16, 18, 22, 26, 28, 26, 22, 18, 16],
    [ 16, 18, 22, 26, 28, 26, 22, 18, 16],
    [  8, 10, 14, 16, 18, 16, 14, 10,  8],
];

/// Rook/Chariot PST (Endgame) — even more valuable when active
const ROOK_TABLE_EG: [[i32; 9]; 10] = [
    [  0,  0,  2,  4,  6,  4,  2,  0,  0],
    [  0,  2,  4,  6,  8,  6,  4,  2,  0],
    [  4,  6,  8, 10, 12, 10,  8,  6,  4],
    [  6,  8, 10, 14, 16, 14, 10,  8,  6],
    [  8, 10, 14, 18, 20, 18, 14, 10,  8],
    [ 12, 14, 18, 22, 24, 22, 18, 14, 12],
    [ 16, 18, 22, 26, 28, 26, 22, 18, 16],
    [ 18, 20, 24, 28, 30, 28, 24, 20, 18],
    [ 18, 20, 24, 28, 30, 28, 24, 20, 18],
    [ 10, 12, 16, 18, 20, 18, 16, 12, 10],
];

/// King PST — prefer center of palace, penalize edges
const KING_TABLE: [[i32; 9]; 10] = [
    [  0,  0,  0,  4,  8,  4,  0,  0,  0], // rank 0
    [  0,  0,  0,  6, 12,  6,  0,  0,  0], // rank 1 (center best)
    [  0,  0,  0,  2,  4,  2,  0,  0,  0], // rank 2
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
    [  0,  0,  0,  0,  0,  0,  0,  0,  0],
];

// ========================
//     LOOKUP FUNCTIONS
// ========================

/// Convert a mailbox square index (0-153) to (file, rank) for table lookup.
/// Returns None for OFFBOARD squares.
fn square_to_file_rank(square: usize) -> Option<(usize, usize)> {
    if square >= 154 {
        return None;
    }
    let row = square / 11;
    let col = square % 11;
    // Valid rows are 2-11 (ranks 9 down to 0), valid cols are 1-9 (files 0-8)
    if row < 2 || row > 11 || col < 1 || col > 9 {
        return None;
    }
    let file = col - 1;       // 0-8
    let rank = 11 - row;      // rank 9 (top) to rank 0 (bottom)
    Some((file, rank))
}

/// Look up a raw 9×10 table value for a given square.
/// For BLACK pieces, the rank is mirrored (rank -> 9 - rank) so that
/// Black's back rank (rank 9) maps to the same row as Red's back rank (rank 0).
fn table_lookup(table: &[[i32; 9]; 10], square: usize, side: u8) -> i32 {
    match square_to_file_rank(square) {
        Some((file, rank)) => {
            let effective_rank = if side == RED { rank } else { 9 - rank };
            table[effective_rank][file]
        }
        None => 0,
    }
}

/// Interpolate between midgame and endgame table values.
/// `phase` is 0.0 (pure endgame) to 1.0 (pure opening/midgame).
fn interpolate(mg: i32, eg: i32, phase: f32) -> i32 {
    ((mg as f32 * phase) + (eg as f32 * (1.0 - phase))) as i32
}

/// Get the PST bonus for a piece on a square, interpolated by game phase.
///
/// - `piece`: piece ID (1-14, the actual board value)
/// - `square`: mailbox index (0-153)
/// - `phase`: 0.0 = endgame, 1.0 = opening/midgame
///
/// Returns a signed centipawn bonus (positive = good for the piece's side).
pub fn pst_score(piece: u8, square: usize, phase: f32) -> i32 {
    let piece_type = PIECE_TYPE[piece as usize];
    let side = PIECE_COLOR[piece as usize];

    match piece_type {
        PAWN => {
            let mg = table_lookup(&PAWN_TABLE_MG, square, side);
            let eg = table_lookup(&PAWN_TABLE_EG, square, side);
            interpolate(mg, eg, phase)
        }
        ADVISOR => table_lookup(&ADVISOR_TABLE, square, side),
        ELEPHANT => table_lookup(&ELEPHANT_TABLE, square, side),
        KNIGHT => {
            let mg = table_lookup(&KNIGHT_TABLE_MG, square, side);
            let eg = table_lookup(&KNIGHT_TABLE_EG, square, side);
            interpolate(mg, eg, phase)
        }
        CANNON => {
            let mg = table_lookup(&CANNON_TABLE_MG, square, side);
            let eg = table_lookup(&CANNON_TABLE_EG, square, side);
            interpolate(mg, eg, phase)
        }
        ROOK => {
            let mg = table_lookup(&ROOK_TABLE_MG, square, side);
            let eg = table_lookup(&ROOK_TABLE_EG, square, side);
            interpolate(mg, eg, phase)
        }
        KING => table_lookup(&KING_TABLE, square, side),
        _ => 0,
    }
}

/// Compute the total PST bonus for all pieces on the board.
/// Returns (red_pst_total, black_pst_total).
pub fn total_pst_score(board: &Board, phase: f32) -> (i32, i32) {
    let mut red_total = 0i32;
    let mut black_total = 0i32;

    for sq in 0..154 {
        let piece = board.board[sq];
        if piece == EMPTY || piece == OFFBOARD {
            continue;
        }
        let bonus = pst_score(piece, sq, phase);
        let side = PIECE_COLOR[piece as usize];
        if side == RED {
            red_total += bonus;
        } else {
            black_total += bonus;
        }
    }

    (red_total, black_total)
}

// ========================
//     GAME PHASE
// ========================

/// Maximum non-pawn, non-king material for one side (centipawns):
/// 2 Advisors (200*2) + 2 Elephants (200*2) + 2 Knights (400*2) + 2 Cannons (450*2) + 2 Rooks (900*2) = 4300
const MAX_PHASE_MATERIAL: i32 = 4300;

/// Piece values for phase calculation (non-pawn, non-king pieces only)
fn phase_piece_value(piece_type: u8) -> i32 {
    match piece_type {
        ADVISOR  => 200,
        ELEPHANT => 200,
        KNIGHT   => 400,
        CANNON   => 450,
        ROOK     => 900,
        _ => 0,
    }
}

/// Compute game phase as a float: 1.0 = opening/midgame, 0.0 = pure endgame.
/// Based on total non-pawn, non-king material remaining on the board.
pub fn compute_game_phase(board: &Board) -> f32 {
    let mut total_material = 0i32;

    for sq in 0..154 {
        let piece = board.board[sq];
        if piece == EMPTY || piece == OFFBOARD {
            continue;
        }
        let pt = PIECE_TYPE[piece as usize];
        total_material += phase_piece_value(pt);
    }

    // Both sides' max = 2 * MAX_PHASE_MATERIAL
    let max_total = 2 * MAX_PHASE_MATERIAL;
    (total_material as f32 / max_total as f32).clamp(0.0, 1.0)
}

/// Game phase classification
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GamePhase {
    Opening,
    Midgame,
    Endgame,
}

impl GamePhase {
    pub fn as_str(&self) -> &'static str {
        match self {
            GamePhase::Opening => "opening",
            GamePhase::Midgame => "midgame",
            GamePhase::Endgame => "endgame",
        }
    }
}

/// Classify the game phase from the phase float.
pub fn classify_phase(phase: f32) -> GamePhase {
    if phase > 0.70 {
        GamePhase::Opening
    } else if phase > 0.35 {
        GamePhase::Midgame
    } else {
        GamePhase::Endgame
    }
}

// ========================
//     TESTS
// ========================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Game::{RED_PAWN, RED_ROOK, BLACK_PAWN, START_FEN};

    #[test]
    fn test_square_to_file_rank() {
        // a9 = index 23, should be file 0, rank 9
        assert_eq!(square_to_file_rank(23), Some((0, 9)));
        // e0 = index 126, should be file 4, rank 0
        assert_eq!(square_to_file_rank(126), Some((4, 0)));
        // offboard
        assert_eq!(square_to_file_rank(0), None);
        assert_eq!(square_to_file_rank(11), None);
    }

    #[test]
    fn test_pst_score_pawn() {
        // Red pawn on rank 3 (starting), center file e (file 4)
        let e3 = Board::square_from_file_rank(4, 3);
        let score = pst_score(RED_PAWN, e3, 1.0);
        assert!(score > 0, "Central pawn should have positive PST, got {}", score);

        // Red pawn deep in enemy territory (rank 7, center)
        let e7 = Board::square_from_file_rank(4, 7);
        let score_deep = pst_score(RED_PAWN, e7, 1.0);
        assert!(score_deep > score, "Deep pawn should have higher PST: {} vs {}", score_deep, score);
    }

    #[test]
    fn test_pst_score_rook() {
        // Rook on rank 7 (deep in enemy territory) should be higher than rank 0
        let e0 = Board::square_from_file_rank(4, 0);
        let e7 = Board::square_from_file_rank(4, 7);
        let score_back = pst_score(RED_ROOK, e0, 1.0);
        let score_active = pst_score(RED_ROOK, e7, 1.0);
        assert!(score_active > score_back,
            "Active rook should have higher PST: {} vs {}", score_active, score_back);
    }

    #[test]
    fn test_phase_computation() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);
        let phase = compute_game_phase(&board);
        assert!(phase > 0.9, "Starting position should be near 1.0, got {}", phase);
        assert_eq!(classify_phase(phase), GamePhase::Opening);
    }

    #[test]
    fn test_phase_endgame() {
        let mut board = Board::new();
        // King + Rook vs King — very low material
        board.set_board_from_fen("4k4/9/9/9/9/9/9/9/9/4K3R w - - 0 1");
        let phase = compute_game_phase(&board);
        assert!(phase < 0.2, "K+R vs K should be endgame phase, got {}", phase);
        assert_eq!(classify_phase(phase), GamePhase::Endgame);
    }

    #[test]
    fn test_black_mirror() {
        // Black pawn at rank 6 (crossed river from Black's perspective)
        // should get the same PST as Red pawn at rank 3 (mirrored: 9-6=3)
        let e3_red = Board::square_from_file_rank(4, 3);
        let e6_black = Board::square_from_file_rank(4, 6);
        let red_score = pst_score(RED_PAWN, e3_red, 1.0);
        let black_score = pst_score(BLACK_PAWN, e6_black, 1.0);
        assert_eq!(red_score, black_score,
            "Mirrored pawn positions should have same PST: red={}, black={}", red_score, black_score);
    }

    #[test]
    fn test_total_pst_starting() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);
        let (red, black) = total_pst_score(&board, 1.0);
        // Starting position is symmetric, so totals should be equal
        assert_eq!(red, black,
            "Starting position PSTs should be equal: red={}, black={}", red, black);
    }
}
