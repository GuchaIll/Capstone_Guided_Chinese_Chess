//Engine references https://github.com/maksimKorzh/wukong-xiangqi/blob/main/integration/engine/wukong.js

use std::collections::HashMap;

// ========================
//     SIDE CONSTANTS
// ========================
pub const RED: u8 = 0;
pub const BLACK: u8 = 1;
pub const NO_COLOR: u8 = 2;

// ========================
//     PIECE ENCODINGS
// ========================
pub const EMPTY: u8 = 0;
pub const RED_PAWN: u8 = 1;
pub const RED_ADVISOR: u8 = 2;
pub const RED_ELEPHANT: u8 = 3;
pub const RED_KNIGHT: u8 = 4;
pub const RED_CANNON: u8 = 5;
pub const RED_ROOK: u8 = 6;
pub const RED_KING: u8 = 7;
pub const BLACK_PAWN: u8 = 8;
pub const BLACK_ADVISOR: u8 = 9;
pub const BLACK_ELEPHANT: u8 = 10;
pub const BLACK_KNIGHT: u8 = 11;
pub const BLACK_CANNON: u8 = 12;
pub const BLACK_ROOK: u8 = 13;
pub const BLACK_KING: u8 = 14;
pub const OFFBOARD: u8 = 15;

// ========================
//     PIECE TYPES
// ========================
pub const PAWN: u8 = 16;
pub const ADVISOR: u8 = 17;
pub const ELEPHANT: u8 = 18;
pub const KNIGHT: u8 = 19;
pub const CANNON: u8 = 20;
pub const ROOK: u8 = 21;
pub const KING: u8 = 22;

// Map piece to type
pub const PIECE_TYPE: [u8; 15] = [
    0, // EMPTY
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,        // RED pieces
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,        // BLACK pieces
];

// Map piece to color
pub const PIECE_COLOR: [u8; 15] = [
    NO_COLOR, // EMPTY
    RED, RED, RED, RED, RED, RED, RED,          // RED pieces
    BLACK, BLACK, BLACK, BLACK, BLACK, BLACK, BLACK,  // BLACK pieces
];

pub const FILES: i32 = 9;
pub const RANKS: i32 = 10;

//Starting position FEN (Xiangqi)
pub const START_FEN: &str =
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";

pub const BOARD_ENCODING: [&str; 154] = [
    "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx",
    "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx",
    "xx", "a9", "b9", "c9", "d9", "e9", "f9", "g9", "h9", "i9", "xx",
    "xx", "a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8", "i8", "xx",
    "xx", "a7", "b7", "c7", "d7", "e7", "f7", "g7", "h7", "i7", "xx",
    "xx", "a6", "b6", "c6", "d6", "e6", "f6", "g6", "h6", "i6", "xx",
    "xx", "a5", "b5", "c5", "d5", "e5", "f5", "g5", "h5", "i5", "xx",
    "xx", "a4", "b4", "c4", "d4", "e4", "f4", "g4", "h4", "i4", "xx",
    "xx", "a3", "b3", "c3", "d3", "e3", "f3", "g3", "h3", "i3", "xx",
    "xx", "a2", "b2", "c2", "d2", "e2", "f2", "g2", "h2", "i2", "xx",
    "xx", "a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1", "i1", "xx",
    "xx", "a0", "b0", "c0", "d0", "e0", "f0", "g0", "h0", "i0", "xx",
    "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx",
    "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx", "xx",
];    

const ORTHOGONAL_DIRECTIONS: [i32; 4] = [-11, 1, 11, -1]; // UP, RIGHT, DOWN, LEFT
const DIAGONAL_DIRECTIONS: [i32; 4] = [-12, -10, 10, 12]; // UP+LEFT, UP+RIGHT, DOWN+LEFT, DOWN+RIGHT

// Knight move offsets: for each orthogonal direction, two possible knight targets
// Index corresponds to ORTHOGONAL_DIRECTIONS order: UP, RIGHT, DOWN, LEFT
const KNIGHT_MOVE_OFFSETS: [[i32; 2]; 4] = [
    [-23, -21], // After UP: UP+UP+LEFT, UP+UP+RIGHT
    [-9, 13],   // After RIGHT: RIGHT+RIGHT+UP, RIGHT+RIGHT+DOWN
    [21, 23],   // After DOWN: DOWN+DOWN+LEFT, DOWN+DOWN+RIGHT
    [-13, 9],   // After LEFT: LEFT+LEFT+UP, LEFT+LEFT+DOWN
];

// Knight attack offsets (reverse lookup - which squares can attack this square)
const KNIGHT_ATTACK_OFFSETS: [[i32; 2]; 4] = [
    [-23, -21], // From UP+LEFT diagonal: possible knight positions
    [-13, -9],  // From UP+RIGHT diagonal
    [9, 13],    // From DOWN+LEFT diagonal
    [21, 23],   // From DOWN+RIGHT diagonal
];

// Elephant move offsets (2 squares diagonally)
const ELEPHANT_MOVE_OFFSETS: [i32; 4] = [-24, -20, 20, 24];

// Pawn move offsets per side [RED, BLACK]
// RED moves UP (toward rank 9), BLACK moves DOWN (toward rank 0)
const PAWN_MOVE_OFFSETS: [[i32; 3]; 2] = [
    [-11, -1, 1],  // RED: UP, LEFT, RIGHT (left/right only after crossing river)
    [11, -1, 1],   // BLACK: DOWN, LEFT, RIGHT
];

// Board zones for each side: 0 = enemy territory, 1 = own territory, 2 = palace
// Board layout: row 0-1 = offboard padding, rows 2-11 = ranks 9-0, rows 12-13 = offboard
// RED is at bottom (ranks 0-4), BLACK is at top (ranks 5-9)
const RED_ZONES: [u8; 154] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 0: offboard
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 1: offboard
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 2: rank 9 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 3: rank 8 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 4: rank 7 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 5: rank 6 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 6: rank 5 (enemy - river)
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,  // row 7: rank 4 (own)
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,  // row 8: rank 3 (own)
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 9: rank 2 (own + palace d2-f2)
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 10: rank 1 (own + palace d1-f1)
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 11: rank 0 (own + palace d0-f0)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 12: offboard
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 13: offboard
];

// BLACK is at top (ranks 5-9), palace at d7-f9
const BLACK_ZONES: [u8; 154] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 0: offboard
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 1: offboard
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 2: rank 9 (own + palace d9-f9)
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 3: rank 8 (own + palace d8-f8)
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,  // row 4: rank 7 (own + palace d7-f7)
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,  // row 5: rank 6 (own)
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,  // row 6: rank 5 (own - river)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 7: rank 4 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 8: rank 3 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 9: rank 2 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 10: rank 1 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 11: rank 0 (enemy)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 12: offboard
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  // row 13: offboard
];

// FEN character to piece mapping
fn char_to_piece(c: char) -> u8 {
    match c {
        'P' => RED_PAWN,
        'A' => RED_ADVISOR,
        'B' | 'E' => RED_ELEPHANT,
        'N' | 'H' => RED_KNIGHT,
        'C' => RED_CANNON,
        'R' => RED_ROOK,
        'K' => RED_KING,
        'p' => BLACK_PAWN,
        'a' => BLACK_ADVISOR,
        'b' | 'e' => BLACK_ELEPHANT,
        'n' | 'h' => BLACK_KNIGHT,
        'c' => BLACK_CANNON,
        'r' => BLACK_ROOK,
        'k' => BLACK_KING,
        _ => EMPTY,
    }
}

// Piece to FEN character mapping
pub fn piece_to_char(piece: u8) -> char {
    match piece {
        EMPTY => '.',
        RED_PAWN => 'P',
        RED_ADVISOR => 'A',
        RED_ELEPHANT => 'B',
        RED_KNIGHT => 'N',
        RED_CANNON => 'C',
        RED_ROOK => 'R',
        RED_KING => 'K',
        BLACK_PAWN => 'p',
        BLACK_ADVISOR => 'a',
        BLACK_ELEPHANT => 'b',
        BLACK_KNIGHT => 'n',
        BLACK_CANNON => 'c',
        BLACK_ROOK => 'r',
        BLACK_KING => 'k',
        _ => 'x',
    }
}

fn get_zone(square: usize, side: u8) -> u8 {
    if side == RED {
        RED_ZONES[square]
    } else {
        BLACK_ZONES[square]
    }
}

#[derive(Clone)]
pub struct Board {
    pub board: [u8; 154],              // Mailbox 11x14 board representation
    pub side: u8,                       // Side to move (RED or BLACK)
    pub king_squares: [usize; 2],       // King positions [RED, BLACK]
    move_stack: Vec<MoveState>,     // History for take_back
    encoding_lookup: HashMap<String, usize>,
    piece_lookup: HashMap<usize, String>,
}

// Store state for undoing moves
#[derive(Clone)]
struct MoveState {
    mv: Move,
    captured: u8,
}

impl Board {
    pub fn new() -> Board {
        let mut encoding_lookup = HashMap::new();
        let mut piece_lookup = HashMap::new();
        let mut board = [OFFBOARD; 154];

        for (index, coord) in BOARD_ENCODING.iter().enumerate() {
            encoding_lookup.insert(coord.to_string(), index);
            piece_lookup.insert(index, coord.to_string());
            if *coord != "xx" {
                board[index] = EMPTY;
            }
        }

        Board {
            board,
            side: RED,
            king_squares: [0, 0],
            move_stack: Vec::new(),
            encoding_lookup,
            piece_lookup,
        }
    }

    /// Reset board and parse FEN string
    pub fn set_board_from_fen(&mut self, fen: &str) {
        // Reset board
        for i in 0..154 {
            if BOARD_ENCODING[i] != "xx" {
                self.board[i] = EMPTY;
            } else {
                self.board[i] = OFFBOARD;
            }
        }
        self.side = RED;
        self.king_squares = [0, 0];
        self.move_stack.clear();

        let parts: Vec<&str> = fen.split_whitespace().collect();
        let position = parts.get(0).unwrap_or(&"");

        let mut square: usize = 23; // Start at a9

        for c in position.chars() {
            match c {
                '/' => {
                    // Move to next rank (add 2 to skip offboard squares)
                    square = ((square / 11) + 1) * 11 + 1;
                }
                '1'..='9' => {
                    // Empty squares
                    let empty_count = c.to_digit(10).unwrap() as usize;
                    square += empty_count;
                }
                _ => {
                    let piece = char_to_piece(c);
                    if piece != EMPTY {
                        self.board[square] = piece;
                        // Track king positions
                        if piece == RED_KING {
                            self.king_squares[RED as usize] = square;
                        } else if piece == BLACK_KING {
                            self.king_squares[BLACK as usize] = square;
                        }
                        square += 1;
                    }
                }
            }
        }

        // Parse side to move
        if let Some(side_str) = parts.get(1) {
            self.side = if *side_str == "b" { BLACK } else { RED };
        }
    }

    fn set_board(&mut self, new_board: [u8; 154]) {
        self.board = new_board;
    }

    pub fn square(&self, encoding: &str) -> Option<usize> {
        self.encoding_lookup.get(encoding).copied()
    }

    /// Get the piece at a given square index
    pub fn piece_at(&self, square: usize) -> u8 {
        if square < 154 { self.board[square] } else { OFFBOARD }
    }

    fn coord_from_square(&self, square: usize) -> Option<&str> {
        BOARD_ENCODING.get(square).copied()
    }

    pub fn square_from_file_rank(file: i32, rank: i32) -> usize {
        // rank 9 -> row 2, rank 0 -> row 11
        // row = 11 - rank, so index = (11 - rank) * 11 + (file + 1)
        ((11 - rank) * 11 + (file + 1)) as usize
    }

    fn file_from_square(square: usize) -> i32 {
        (square as i32 % 11) - 1
    }

    fn rank_from_square(square: usize) -> i32 {
        // Inverse of square_from_file_rank: row = 11 - rank => rank = 11 - row
        11 - (square as i32 / 11)
    }

    fn is_valid(square: usize) -> bool {
        if square >= 154 {
            return false;
        }
        BOARD_ENCODING[square] != "xx"
    }

    fn in_palace(square: usize, side: u8) -> bool {
        get_zone(square, side) == 2
    }

    fn crossed_river(square: usize, side: u8) -> bool {
        // Returns true if piece has crossed river (in enemy territory)
        get_zone(square, side) == 0
    }

    /// Public version of crossed_river for use by analysis modules
    pub fn crossed_river_pub(square: usize, side: u8) -> bool {
        get_zone(square, side) == 0
    }

    fn in_own_territory(square: usize, side: u8) -> bool {
        get_zone(square, side) >= 1
    }

    /// Generate advisor moves (diagonal moves within palace)
    fn gen_advisor_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        for &offset in DIAGONAL_DIRECTIONS.iter() {
            let target = (square as i32 + offset) as usize;

            if target < 154 && Board::is_valid(target) && Board::in_palace(target, side) {
                let target_piece = self.board[target];
                // Can move to empty square or capture enemy piece
                if target_piece == EMPTY || PIECE_COLOR[target_piece as usize] != side {
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: target_piece,
                        flags: if target_piece != EMPTY { 1 } else { 0 },
                    });
                }
            }
        }

        moves
    }

    /// Generate elephant moves (2 diagonal squares, blocked by piece at eye, cannot cross river)
    fn gen_elephant_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        for i in 0..4 {
            let eye = (square as i32 + DIAGONAL_DIRECTIONS[i]) as usize;
            let target = (square as i32 + ELEPHANT_MOVE_OFFSETS[i]) as usize;

            // Check if eye is not blocked and target is valid and in own territory
            if target < 154
                && Board::is_valid(target)
                && Board::in_own_territory(target, side)
                && eye < 154
                && self.board[eye] == EMPTY
            {
                let target_piece = self.board[target];
                if target_piece == EMPTY || PIECE_COLOR[target_piece as usize] != side {
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: target_piece,
                        flags: if target_piece != EMPTY { 1 } else { 0 },
                    });
                }
            }
        }

        moves
    }

    /// Generate knight moves (L-shape, blocked by piece at leg)
    fn gen_knight_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        // For each orthogonal direction, check if leg is clear
        for dir in 0..4 {
            let leg = (square as i32 + ORTHOGONAL_DIRECTIONS[dir]) as usize;

            // If leg square is empty, knight can move
            if leg < 154 && self.board[leg] == EMPTY {
                // Two possible target squares for this direction
                for &offset in KNIGHT_MOVE_OFFSETS[dir].iter() {
                    let target = (square as i32 + offset) as usize;

                    if target < 154 && Board::is_valid(target) {
                        let target_piece = self.board[target];
                        if target_piece == EMPTY || PIECE_COLOR[target_piece as usize] != side {
                            moves.moves.push(Move {
                                from: square as u8,
                                to: target as u8,
                                piece,
                                captured: target_piece,
                                flags: if target_piece != EMPTY { 1 } else { 0 },
                            });
                        }
                    }
                }
            }
        }

        moves
    }

    /// Generate rook moves (slides orthogonally until blocked)
    fn gen_rook_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        for &direction in ORTHOGONAL_DIRECTIONS.iter() {
            let mut target = (square as i32 + direction) as usize;

            while target < 154 && self.board[target] != OFFBOARD {
                let target_piece = self.board[target];

                if target_piece == EMPTY {
                    // Empty square - can move here and continue
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: EMPTY,
                        flags: 0,
                    });
                } else if PIECE_COLOR[target_piece as usize] != side {
                    // Enemy piece - can capture and stop
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: target_piece,
                        flags: 1,
                    });
                    break;
                } else {
                    // Own piece - stop
                    break;
                }

                target = (target as i32 + direction) as usize;
            }
        }

        moves
    }

    /// Generate cannon moves (slides orthogonally, captures by jumping over exactly one piece)
    fn gen_cannon_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        for &direction in ORTHOGONAL_DIRECTIONS.iter() {
            let mut target = (square as i32 + direction) as usize;
            let mut jumped = false;

            while target < 154 && self.board[target] != OFFBOARD {
                let target_piece = self.board[target];

                if !jumped {
                    // Haven't jumped yet
                    if target_piece == EMPTY {
                        // Empty square - can move here (non-capture)
                        moves.moves.push(Move {
                            from: square as u8,
                            to: target as u8,
                            piece,
                            captured: EMPTY,
                            flags: 0,
                        });
                    } else {
                        // Found piece to jump over
                        jumped = true;
                    }
                } else {
                    // Already jumped - looking for capture target
                    if target_piece != EMPTY {
                        if PIECE_COLOR[target_piece as usize] != side {
                            // Enemy piece after jump - can capture
                            moves.moves.push(Move {
                                from: square as u8,
                                to: target as u8,
                                piece,
                                captured: target_piece,
                                flags: 1,
                            });
                        }
                        // Stop after finding any piece (capture or blocked by own piece)
                        break;
                    }
                }

                target = (target as i32 + direction) as usize;
            }
        }

        moves
    }

    /// Generate pawn moves (forward always, sideways after crossing river)
    fn gen_pawn_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];
        let has_crossed_river = Board::crossed_river(square, side);

        for (i, &offset) in PAWN_MOVE_OFFSETS[side as usize].iter().enumerate() {
            // Index 0 is forward move (always allowed)
            // Indices 1,2 are sideways moves (only after crossing river)
            if i > 0 && !has_crossed_river {
                continue;
            }

            let target = (square as i32 + offset) as usize;

            if target < 154 && Board::is_valid(target) {
                let target_piece = self.board[target];
                if target_piece == EMPTY || PIECE_COLOR[target_piece as usize] != side {
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: target_piece,
                        flags: if target_piece != EMPTY { 1 } else { 0 },
                    });
                }
            }
        }

        moves
    }

    /// Generate king moves (orthogonal within palace, also checks flying general)
    fn gen_king_moves(&self, square: usize, side: u8) -> MoveList {
        let mut moves = MoveList { moves: vec![] };
        let piece = self.board[square];

        // Normal orthogonal moves within palace
        for &offset in ORTHOGONAL_DIRECTIONS.iter() {
            let target = (square as i32 + offset) as usize;

            if target < 154 && Board::is_valid(target) && Board::in_palace(target, side) {
                let target_piece = self.board[target];
                if target_piece == EMPTY || PIECE_COLOR[target_piece as usize] != side {
                    moves.moves.push(Move {
                        from: square as u8,
                        to: target as u8,
                        piece,
                        captured: target_piece,
                        flags: if target_piece != EMPTY { 1 } else { 0 },
                    });
                }
            }
        }

        moves
    }

    /// Check if a square is attacked by the given side
    pub fn is_square_attacked(&self, square: usize, by_side: u8) -> bool {
        // Check for pawn attacks
        for &offset in PAWN_MOVE_OFFSETS[by_side as usize].iter() {
            let attacker_sq = (square as i32 - offset) as usize;
            if attacker_sq < 154 {
                let piece = self.board[attacker_sq];
                if piece != OFFBOARD {
                    let expected_pawn = if by_side == RED { RED_PAWN } else { BLACK_PAWN };
                    if piece == expected_pawn {
                        // Check if this pawn can actually attack this direction
                        // Forward is always allowed, sideways only after crossing river
                        if offset == PAWN_MOVE_OFFSETS[by_side as usize][0] {
                            return true; // Forward attack
                        } else if Board::crossed_river(attacker_sq, by_side) {
                            return true; // Sideways attack after crossing river
                        }
                    }
                }
            }
        }

        // Check for knight attacks (reverse lookup)
        for dir in 0..4 {
            let eye = (square as i32 + DIAGONAL_DIRECTIONS[dir]) as usize;

            if eye < 154 && self.board[eye] == EMPTY {
                for &offset in KNIGHT_ATTACK_OFFSETS[dir].iter() {
                    let attacker_sq = (square as i32 + offset) as usize;
                    if attacker_sq < 154 {
                        let piece = self.board[attacker_sq];
                        let expected_knight = if by_side == RED { RED_KNIGHT } else { BLACK_KNIGHT };
                        if piece == expected_knight {
                            return true;
                        }
                    }
                }
            }
        }

        // Check for rook, cannon, and king attacks (orthogonal sliding)
        for &direction in ORTHOGONAL_DIRECTIONS.iter() {
            let mut target = (square as i32 + direction) as usize;
            let mut jump_count = 0;

            while target < 154 && self.board[target] != OFFBOARD {
                let piece = self.board[target];

                if piece != EMPTY {
                    let piece_color = PIECE_COLOR[piece as usize];
                    let piece_type = PIECE_TYPE[piece as usize];

                    if piece_color == by_side {
                        if jump_count == 0 {
                            // Direct attack by rook or king
                            if piece_type == ROOK || piece_type == KING {
                                return true;
                            }
                        } else if jump_count == 1 {
                            // Cannon capture (jumped over exactly one piece)
                            if piece_type == CANNON {
                                return true;
                            }
                        }
                    }

                    jump_count += 1;
                    if jump_count >= 2 && piece_color == by_side && piece_type != CANNON {
                        break;
                    }
                    if jump_count >= 2 {
                        break;
                    }
                }

                target = (target as i32 + direction) as usize;
            }
        }

        false
    }

    /// Make a move on the board, returns false if move leaves king in check
    pub fn make_move(&mut self, mv: &Move) -> bool {
        let from = mv.from as usize;
        let to = mv.to as usize;

        // Save state for undo
        self.move_stack.push(MoveState {
            mv: *mv,
            captured: self.board[to],
        });

        // Move piece
        self.board[to] = mv.piece;
        self.board[from] = EMPTY;

        // Update king position if king moved
        if mv.piece == RED_KING {
            self.king_squares[RED as usize] = to;
        } else if mv.piece == BLACK_KING {
            self.king_squares[BLACK as usize] = to;
        }

        // Switch side
        self.side ^= 1;

        // Check if move leaves own king in check (illegal)
        let own_king_sq = self.king_squares[(self.side ^ 1) as usize];
        if self.is_square_attacked(own_king_sq, self.side) {
            self.take_back();
            return false;
        }

        // Check flying general rule (kings facing each other with no piece between)
        if self.is_flying_general() {
            self.take_back();
            return false;
        }

        true
    }

    /// Undo the last move
    pub fn take_back(&mut self) {
        if let Some(state) = self.move_stack.pop() {
            let mv = &state.mv;
            let from = mv.from as usize;
            let to = mv.to as usize;

            // Restore piece positions
            self.board[from] = mv.piece;
            self.board[to] = state.captured;

            // Update king position if king moved
            if mv.piece == RED_KING {
                self.king_squares[RED as usize] = from;
            } else if mv.piece == BLACK_KING {
                self.king_squares[BLACK as usize] = from;
            }

            // Switch side back
            self.side ^= 1;
        }
    }

    /// Check if kings are facing each other (flying general rule)
    fn is_flying_general(&self) -> bool {
        let red_king = self.king_squares[RED as usize];
        let black_king = self.king_squares[BLACK as usize];

        // If either king position is 0, kings haven't been placed yet
        if red_king == 0 || black_king == 0 {
            return false;
        }

        // Kings must be on same file
        if Board::file_from_square(red_king) != Board::file_from_square(black_king) {
            return false;
        }

        // Red king is at higher index (rank 0 = row 11), black king at lower index (rank 9 = row 2)
        // So we iterate from black_king down to red_king (increasing index = +11)
        let mut sq = black_king + 11; // Start one square below black king

        while sq < red_king {
            if self.board[sq] != EMPTY {
                return false;
            }
            sq += 11;
        }

        true // No piece between - flying general!
    }

    /// Check if current side's king is in check
    fn in_check(&self) -> bool {
        let king_sq = self.king_squares[self.side as usize];
        self.is_square_attacked(king_sq, self.side ^ 1)
    }

    /// Check if current side is in checkmate (in check with no legal moves)
    fn is_checkmate(&mut self) -> bool {
        if !self.in_check() {
            return false;
        }
        self.generate_legal_moves().len() == 0
    }

    /// Check if current side is in stalemate (not in check but no legal moves)
    fn is_stalemate(&mut self) -> bool {
        if self.in_check() {
            return false;
        }
        self.generate_legal_moves().len() == 0
    }

    /// Check if game is over (checkmate or stalemate)
    fn is_game_over(&mut self) -> bool {
        self.generate_legal_moves().len() == 0
    }

    /// Generate all pseudo-legal moves for the current side
    fn generate_pseudo_legal_moves(&self) -> MoveList {
        let mut all_moves = MoveList { moves: vec![] };

        for square in 0..154 {
            let piece = self.board[square];
            if piece == EMPTY || piece == OFFBOARD {
                continue;
            }

            let piece_color = PIECE_COLOR[piece as usize];
            if piece_color != self.side {
                continue;
            }

            let piece_type = PIECE_TYPE[piece as usize];
            let mut piece_moves = match piece_type {
                PAWN => self.gen_pawn_moves(square, self.side),
                ADVISOR => self.gen_advisor_moves(square, self.side),
                ELEPHANT => self.gen_elephant_moves(square, self.side),
                KNIGHT => self.gen_knight_moves(square, self.side),
                CANNON => self.gen_cannon_moves(square, self.side),
                ROOK => self.gen_rook_moves(square, self.side),
                KING => self.gen_king_moves(square, self.side),
                _ => MoveList { moves: vec![] },
            };

            all_moves.moves.append(&mut piece_moves.moves);
        }

        all_moves
    }

    /// Generate all legal moves for the current side
    pub fn generate_legal_moves(&mut self) -> MoveList {
        let pseudo_moves = self.generate_pseudo_legal_moves();
        let mut legal_moves = MoveList { moves: vec![] };

        for mv in pseudo_moves.moves {
            if self.make_move(&mv) {
                self.take_back();
                legal_moves.moves.push(mv);
            }
        }

        legal_moves
    }

    /// Print board to console (for debugging)
    fn print_board(&self) {
        println!("\n  a b c d e f g h i");
        for rank in 0..10 {
            print!("{} ", 9 - rank);
            for file in 0..9 {
                let square = Board::square_from_file_rank(file, rank as i32);
                print!("{} ", piece_to_char(self.board[square]));
            }
            println!();
        }
        println!("\nSide to move: {}", if self.side == RED { "Red" } else { "Black" });
    }
}

#[derive(Copy, Clone, Debug)]
pub struct Move {
    pub from: u8,
    pub to: u8,
    pub piece: u8,
    pub captured: u8,
    pub flags: u8, // 1 = capture
}

impl Move {
    /// Convert move to string format (e.g., "e2e4")
    fn to_string(&self) -> String {
        let from_coord = BOARD_ENCODING[self.from as usize];
        let to_coord = BOARD_ENCODING[self.to as usize];
        format!("{}{}", from_coord, to_coord)
    }
}

pub struct MoveList {
    pub moves: Vec<Move>,
}

impl MoveList {
    pub fn new() -> MoveList {
        MoveList { moves: vec![] }
    }

    pub fn len(&self) -> usize {
        self.moves.len()
    }

    pub fn is_empty(&self) -> bool {
        self.moves.is_empty()
    }
}

// ========================
//     UNIT TESTS
// ========================
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_board_initialization() {
        let board = Board::new();
        assert_eq!(board.side, RED);
        assert_eq!(board.board[23], EMPTY); // a9 should be empty
    }

    #[test]
    fn test_fen_parsing() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);

        // Check some pieces are in correct positions
        assert_eq!(board.board[23], BLACK_ROOK);   // a9 = black rook
        assert_eq!(board.board[27], BLACK_KING);   // e9 = black king
        assert_eq!(board.board[122], RED_ROOK);    // a0 = red rook
        assert_eq!(board.board[126], RED_KING);    // e0 = red king
        assert_eq!(board.side, RED);
    }

    #[test]
    fn test_starting_position_moves() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);

        let moves = board.generate_legal_moves();
        // Starting position should have 44 legal moves for Red
        assert_eq!(moves.len(), 44);
    }

    #[test]
    fn test_king_in_palace() {
        let _board = Board::new();
        // Red palace squares (d0-f0, d1-f1, d2-f2)
        assert!(Board::in_palace(Board::square_from_file_rank(3, 0), RED));
        assert!(Board::in_palace(Board::square_from_file_rank(4, 0), RED));
        assert!(Board::in_palace(Board::square_from_file_rank(5, 0), RED));
        assert!(!Board::in_palace(Board::square_from_file_rank(2, 0), RED));

        // Black palace squares (d7-f7, d8-f8, d9-f9)
        assert!(Board::in_palace(Board::square_from_file_rank(3, 9), BLACK));
        assert!(Board::in_palace(Board::square_from_file_rank(4, 9), BLACK));
    }

    #[test]
    fn test_square_coordinate_conversion() {
        // Test that square_from_file_rank correctly maps to board indices
        assert_eq!(Board::square_from_file_rank(0, 9), 23);  // a9
        assert_eq!(Board::square_from_file_rank(4, 9), 27);  // e9 (black king start)
        assert_eq!(Board::square_from_file_rank(0, 0), 122); // a0
        assert_eq!(Board::square_from_file_rank(4, 0), 126); // e0 (red king start)

        // Test file extraction
        assert_eq!(Board::file_from_square(23), 0);  // a9 -> file 0
        assert_eq!(Board::file_from_square(27), 4);  // e9 -> file 4
    }

    #[test]
    fn test_rook_moves() {
        let mut board = Board::new();
        // Place red rook at e5 (center of board)
        let e5 = Board::square_from_file_rank(4, 5);
        board.board[e5] = RED_ROOK;
        board.king_squares[RED as usize] = Board::square_from_file_rank(4, 0);
        board.king_squares[BLACK as usize] = Board::square_from_file_rank(4, 9);
        board.board[board.king_squares[RED as usize]] = RED_KING;
        board.board[board.king_squares[BLACK as usize]] = BLACK_KING;

        let moves = board.gen_rook_moves(e5, RED);
        // Rook at e5 can move to many squares orthogonally
        assert!(moves.len() > 10);
    }

    #[test]
    fn test_knight_blocked_leg() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);

        // In starting position, knights have limited moves due to blocked legs
        let b0 = Board::square_from_file_rank(1, 0);
        let knight_moves = board.gen_knight_moves(b0, RED);
        // Red knight at b0 should have 2 moves (a2 and c2)
        assert_eq!(knight_moves.len(), 2);
    }

    #[test]
    fn test_cannon_jump_capture() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);

        // Red cannon at b2 can capture black pieces by jumping
        let b2 = Board::square_from_file_rank(1, 2);
        let cannon_moves = board.gen_cannon_moves(b2, RED);
        // Should have several moves (slides) but no captures in starting position
        assert!(cannon_moves.len() > 5);
    }

    #[test]
    fn test_pawn_before_river() {
        let mut board = Board::new();
        board.set_board_from_fen(START_FEN);

        // Red pawn at c3 can only move forward before crossing river
        let c3 = Board::square_from_file_rank(2, 3);
        let pawn_moves = board.gen_pawn_moves(c3, RED);
        assert_eq!(pawn_moves.len(), 1); // Only forward
    }

    #[test]
    fn test_pawn_after_river() {
        let mut board = Board::new();
        // Place red pawn at e6 (crossed river)
        let e6 = Board::square_from_file_rank(4, 6);
        board.board[e6] = RED_PAWN;
        board.king_squares[RED as usize] = Board::square_from_file_rank(4, 0);
        board.king_squares[BLACK as usize] = Board::square_from_file_rank(4, 9);
        board.board[board.king_squares[RED as usize]] = RED_KING;
        board.board[board.king_squares[BLACK as usize]] = BLACK_KING;

        let pawn_moves = board.gen_pawn_moves(e6, RED);
        // After crossing river, pawn can move forward, left, and right
        assert_eq!(pawn_moves.len(), 3);
    }

    #[test]
    fn test_elephant_blocked_eye() {
        let mut board = Board::new();
        // Place red elephant at c0 and block its eye at d1
        let c0 = Board::square_from_file_rank(2, 0);
        let d1 = Board::square_from_file_rank(3, 1);
        board.board[c0] = RED_ELEPHANT;
        board.board[d1] = RED_PAWN; // Block the eye
        board.king_squares[RED as usize] = Board::square_from_file_rank(4, 0);
        board.king_squares[BLACK as usize] = Board::square_from_file_rank(4, 9);
        board.board[board.king_squares[RED as usize]] = RED_KING;
        board.board[board.king_squares[BLACK as usize]] = BLACK_KING;

        let elephant_moves = board.gen_elephant_moves(c0, RED);
        // One diagonal direction is blocked
        assert!(elephant_moves.len() < 4);
    }

    #[test]
    fn test_check_detection() {
        let mut board = Board::new();
        // Set up a position where red king is in check by black rook
        let e0 = Board::square_from_file_rank(4, 0);
        let e5 = Board::square_from_file_rank(4, 5);
        let e9 = Board::square_from_file_rank(4, 9);

        board.board[e0] = RED_KING;
        board.board[e5] = BLACK_ROOK;
        board.board[e9] = BLACK_KING;
        board.king_squares[RED as usize] = e0;
        board.king_squares[BLACK as usize] = e9;
        board.side = RED;

        assert!(board.in_check());
    }

    #[test]
    fn test_flying_general() {
        let mut board = Board::new();
        // Set up flying general (kings facing with no piece between)
        let e0 = Board::square_from_file_rank(4, 0);
        let e9 = Board::square_from_file_rank(4, 9);

        board.board[e0] = RED_KING;
        board.board[e9] = BLACK_KING;
        board.king_squares[RED as usize] = e0;
        board.king_squares[BLACK as usize] = e9;

        assert!(board.is_flying_general());

        // Add a piece between - no longer flying general
        let e5 = Board::square_from_file_rank(4, 5);
        board.board[e5] = RED_PAWN;
        assert!(!board.is_flying_general());
    }

    #[test]
    fn test_advisor_stays_in_palace() {
        let mut board = Board::new();
        // Place red advisor at d0 (corner of palace)
        let d0 = Board::square_from_file_rank(3, 0);
        board.board[d0] = RED_ADVISOR;
        board.king_squares[RED as usize] = Board::square_from_file_rank(4, 0);
        board.king_squares[BLACK as usize] = Board::square_from_file_rank(4, 9);
        board.board[board.king_squares[RED as usize]] = RED_KING;
        board.board[board.king_squares[BLACK as usize]] = BLACK_KING;

        let advisor_moves = board.gen_advisor_moves(d0, RED);
        // Advisor at corner can only move to e1 (center of palace)
        assert_eq!(advisor_moves.len(), 1);
    }

    #[test]
    fn test_elephant_cannot_cross_river() {
        let mut board = Board::new();
        // Place red elephant at c4 (edge of red territory)
        let c4 = Board::square_from_file_rank(2, 4);
        board.board[c4] = RED_ELEPHANT;
        board.king_squares[RED as usize] = Board::square_from_file_rank(4, 0);
        board.king_squares[BLACK as usize] = Board::square_from_file_rank(4, 9);
        board.board[board.king_squares[RED as usize]] = RED_KING;
        board.board[board.king_squares[BLACK as usize]] = BLACK_KING;

        let elephant_moves = board.gen_elephant_moves(c4, RED);
        // All moves should stay in red's territory
        for mv in &elephant_moves.moves {
            assert!(Board::in_own_territory(mv.to as usize, RED));
        }
    }
}
