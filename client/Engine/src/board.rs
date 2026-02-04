// Board representation and coordinate system for Xiangqi
// Reference: Wukong Xiangqi engine

// Piece encoding - follows Wukong's piece encoding scheme
pub const EMPTY: u8 = 0;
pub const RED_PAWN: u8 = 1;
pub const RED_ADVISOR: u8 = 2;
pub const RED_BISHOP: u8 = 3;
pub const RED_KNIGHT: u8 = 4;
pub const RED_CANNON: u8 = 5;
pub const RED_ROOK: u8 = 6;
pub const RED_KING: u8 = 7;
pub const BLACK_PAWN: u8 = 8;
pub const BLACK_ADVISOR: u8 = 9;
pub const BLACK_BISHOP: u8 = 10;
pub const BLACK_KNIGHT: u8 = 11;
pub const BLACK_CANNON: u8 = 12;
pub const BLACK_ROOK: u8 = 13;
pub const BLACK_KING: u8 = 14;
pub const OFFBOARD: u8 = 15;

// Sides to move
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Side {
    Red = 0,
    Black = 1,
}

impl Side {
    pub fn opposite(&self) -> Side {
        match self {
            Side::Red => Side::Black,
            Side::Black => Side::Red,
        }
    }
}

// Piece types (for move generation)
pub const PAWN: u8 = 16;
pub const ADVISOR: u8 = 17;
pub const BISHOP: u8 = 18;
pub const KNIGHT: u8 = 19;
pub const CANNON: u8 = 20;
pub const ROOK: u8 = 21;
pub const KING: u8 = 22;

// Map piece to type
pub const PIECE_TYPE: [u8; 15] = [
    0,
    PAWN, ADVISOR, BISHOP, KNIGHT, CANNON, ROOK, KING,  // Red pieces
    PAWN, ADVISOR, BISHOP, KNIGHT, CANNON, ROOK, KING,  // Black pieces
];

// Map piece to color (2 = no color)
pub const PIECE_COLOR: [u8; 15] = [
    2,  // Empty
    0, 0, 0, 0, 0, 0, 0,  // Red pieces
    1, 1, 1, 1, 1, 1, 1,  // Black pieces
];

// Square encoding for 11x14 mailbox board
// Actual board is 9x10, but mailbox adds borders for efficient bounds checking
pub const A9: usize = 23;  pub const B9: usize = 24;  pub const C9: usize = 25;
pub const D9: usize = 26;  pub const E9: usize = 27;  pub const F9: usize = 28;
pub const G9: usize = 29;  pub const H9: usize = 30;  pub const I9: usize = 31;

pub const A8: usize = 34;  pub const B8: usize = 35;  pub const C8: usize = 36;
pub const D8: usize = 37;  pub const E8: usize = 38;  pub const F8: usize = 39;
pub const G8: usize = 40;  pub const H8: usize = 41;  pub const I8: usize = 42;

pub const A7: usize = 45;  pub const B7: usize = 46;  pub const C7: usize = 47;
pub const D7: usize = 48;  pub const E7: usize = 49;  pub const F7: usize = 50;
pub const G7: usize = 51;  pub const H7: usize = 52;  pub const I7: usize = 53;

pub const A6: usize = 56;  pub const B6: usize = 57;  pub const C6: usize = 58;
pub const D6: usize = 59;  pub const E6: usize = 60;  pub const F6: usize = 61;
pub const G6: usize = 62;  pub const H6: usize = 63;  pub const I6: usize = 64;

pub const A5: usize = 67;  pub const B5: usize = 68;  pub const C5: usize = 69;
pub const D5: usize = 70;  pub const E5: usize = 71;  pub const F5: usize = 72;
pub const G5: usize = 73;  pub const H5: usize = 74;  pub const I5: usize = 75;

pub const A4: usize = 78;  pub const B4: usize = 79;  pub const C4: usize = 80;
pub const D4: usize = 81;  pub const E4: usize = 82;  pub const F4: usize = 83;
pub const G4: usize = 84;  pub const H4: usize = 85;  pub const I4: usize = 86;

pub const A3: usize = 89;  pub const B3: usize = 90;  pub const C3: usize = 91;
pub const D3: usize = 92;  pub const E3: usize = 93;  pub const F3: usize = 94;
pub const G3: usize = 95;  pub const H3: usize = 96;  pub const I3: usize = 97;

pub const A2: usize = 100; pub const B2: usize = 101; pub const C2: usize = 102;
pub const D2: usize = 103; pub const E2: usize = 104; pub const F2: usize = 105;
pub const G2: usize = 106; pub const H2: usize = 107; pub const I2: usize = 108;

pub const A1: usize = 111; pub const B1: usize = 112; pub const C1: usize = 113;
pub const D1: usize = 114; pub const E1: usize = 115; pub const F1: usize = 116;
pub const G1: usize = 117; pub const H1: usize = 118; pub const I1: usize = 119;

pub const A0: usize = 122; pub const B0: usize = 123; pub const C0: usize = 124;
pub const D0: usize = 125; pub const E0: usize = 126; pub const F0: usize = 127;
pub const G0: usize = 128; pub const H0: usize = 129; pub const I0: usize = 130;

// Board dimensions
pub const MAILBOX_SIZE: usize = 11 * 14; // 154 squares including borders
pub const FILE_COUNT: usize = 9;
pub const RANK_COUNT: usize = 10;

// Coordinate string mapping for each square
pub const COORDINATES: [&str; MAILBOX_SIZE] = [
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

// Board zones for piece movement restrictions
// 0 = not on board, 1 = normal zone, 2 = palace (for kings and advisors)
pub const BOARD_ZONES_RED: [u8; MAILBOX_SIZE] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
];

pub const BOARD_ZONES_BLACK: [u8; MAILBOX_SIZE] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
];

// Direction offsets for move generation
pub const UP: isize = -11;
pub const DOWN: isize = 11;
pub const LEFT: isize = -1;
pub const RIGHT: isize = 1;

pub const ORTHOGONALS: [isize; 4] = [LEFT, RIGHT, UP, DOWN];
pub const DIAGONALS: [isize; 4] = [UP + LEFT, UP + RIGHT, DOWN + LEFT, DOWN + RIGHT];

// Starting position FEN
pub const START_FEN: &str = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";

// ASCII character to piece mapping for FEN parsing
pub fn char_to_piece(c: char) -> Option<u8> {
    match c {
        'P' => Some(RED_PAWN),
        'A' => Some(RED_ADVISOR),
        'B' | 'E' => Some(RED_BISHOP),
        'N' | 'H' => Some(RED_KNIGHT),
        'C' => Some(RED_CANNON),
        'R' => Some(RED_ROOK),
        'K' => Some(RED_KING),
        'p' => Some(BLACK_PAWN),
        'a' => Some(BLACK_ADVISOR),
        'b' | 'e' => Some(BLACK_BISHOP),
        'n' | 'h' => Some(BLACK_KNIGHT),
        'c' => Some(BLACK_CANNON),
        'r' => Some(BLACK_ROOK),
        'k' => Some(BLACK_KING),
        _ => None,
    }
}

// Piece to ASCII character mapping
pub const PIECE_TO_CHAR: [char; 16] = [
    '.', 'P', 'A', 'B', 'N', 'C', 'R', 'K',
    'p', 'a', 'b', 'n', 'c', 'r', 'k', 'x'
];

// Board structure
pub struct Board {
    pub squares: [u8; MAILBOX_SIZE],
    pub side: Side,
    pub king_square: [usize; 2],  // [Red king, Black king]
    pub sixty_move: u32,
}

impl Board {
    // Create a new empty board
    pub fn new() -> Self {
        let mut board = Board {
            squares: [OFFBOARD; MAILBOX_SIZE],
            side: Side::Red,
            king_square: [E0, E9],
            sixty_move: 0,
        };
        
        // Initialize playable squares to empty
        for rank in 0..14 {
            for file in 0..11 {
                let square = rank * 11 + file;
                if COORDINATES[square] != "xx" {
                    board.squares[square] = EMPTY;
                }
            }
        }
        
        board
    }
    
    // Reset board to starting position
    pub fn reset(&mut self) {
        *self = Board::new();
        self.set_position(START_FEN);
    }
    
    // Set board position from FEN string
    // FEN format: rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1
    pub fn set_position(&mut self, fen: &str) {
        // Reset board first
        for square in 0..MAILBOX_SIZE {
            if COORDINATES[square] != "xx" {
                self.squares[square] = EMPTY;
            } else {
                self.squares[square] = OFFBOARD;
            }
        }
        
        let parts: Vec<&str> = fen.split_whitespace().collect();
        if parts.is_empty() {
            return;
        }
        
        let position = parts[0];
        let ranks: Vec<&str> = position.split('/').collect();
        
        // Process each rank (from rank 9 to rank 0)
        for (rank_idx, rank_str) in ranks.iter().enumerate() {
            if rank_idx >= 10 {
                break; // Only 10 ranks in Xiangqi
            }
            
            // Calculate the actual rank number (rank 9 = index 2 in mailbox, rank 0 = index 11)
            let rank = rank_idx + 2;
            let mut file = 1; // Start at file 1 (after left border)
            
            for c in rank_str.chars() {
                if file >= 10 {
                    break; // Max 9 files
                }
                
                let square = rank * 11 + file;
                
                // Parse pieces
                if c.is_alphabetic() {
                    if let Some(piece) = char_to_piece(c) {
                        self.squares[square] = piece;
                        if piece == RED_KING {
                            self.king_square[Side::Red as usize] = square;
                        } else if piece == BLACK_KING {
                            self.king_square[Side::Black as usize] = square;
                        }
                    }
                    file += 1;
                }
                // Parse empty squares
                else if let Some(digit) = c.to_digit(10) {
                    // Skip 'digit' number of files (they remain empty)
                    file += digit as usize;
                }
            }
        }
        
        // Parse side to move
        if parts.len() > 1 {
            self.side = if parts[1] == "b" { Side::Black } else { Side::Red };
        }
        
        // Parse sixty move rule
        if parts.len() > 4 {
            self.sixty_move = parts[4].parse().unwrap_or(0);
        }
    }
    
    // Get piece at square
    pub fn piece_at(&self, square: usize) -> u8 {
        if square < MAILBOX_SIZE {
            self.squares[square]
        } else {
            OFFBOARD
        }
    }
    
    // Print board to string
    pub fn to_string(&self) -> String {
        let mut result = String::new();
        
        for rank in 0..14 {
            for file in 0..11 {
                let square = rank * 11 + file;
                
                if self.squares[square] != OFFBOARD {
                    if file == 1 {
                        // Display human-readable rank (9 at top, 0 at bottom)
                        // Mailbox rank 2 = display rank 9, rank 11 = display rank 0
                        result.push_str(&format!("{}  ", 11 - rank));
                    }
                    result.push(PIECE_TO_CHAR[self.squares[square] as usize]);
                    result.push(' ');
                }
            }
            
            if rank < 13 {
                result.push('\n');
            }
        }
        
        result.push_str("   a b c d e f g h i\n\n");
        result.push_str(&format!("   side:     {:?}\n", self.side));
        result.push_str(&format!("   sixty:    {}\n", self.sixty_move));
        result.push_str(&format!("   kings:    [{}, {}]\n",
                                 COORDINATES[self.king_square[0]],
                                 COORDINATES[self.king_square[1]]));
        
        result
    }
}

impl Default for Board {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_board_creation() {
        let board = Board::new();
        assert_eq!(board.side, Side::Red);
        assert_eq!(board.sixty_move, 0);
    }
    
    #[test]
    fn test_coordinate_mapping() {
        assert_eq!(COORDINATES[A9], "a9");
        assert_eq!(COORDINATES[I9], "i9");
        assert_eq!(COORDINATES[A0], "a0");
        assert_eq!(COORDINATES[I0], "i0");
        assert_eq!(COORDINATES[E0], "e0");
        assert_eq!(COORDINATES[E9], "e9");
    }
    
    #[test]
    fn test_offboard_squares() {
        let board = Board::new();
        assert_eq!(board.squares[0], OFFBOARD);
        assert_eq!(board.squares[10], OFFBOARD);
        assert_eq!(board.squares[MAILBOX_SIZE - 1], OFFBOARD);
    }
    
    #[test]
    fn test_starting_position() {
        let mut board = Board::new();
        board.set_position(START_FEN);
        
        // Check red pieces
        assert_eq!(board.squares[A0], RED_ROOK);
        assert_eq!(board.squares[E0], RED_KING);
        assert_eq!(board.squares[I0], RED_ROOK);
        
        // Check black pieces
        assert_eq!(board.squares[A9], BLACK_ROOK);
        assert_eq!(board.squares[E9], BLACK_KING);
        assert_eq!(board.squares[I9], BLACK_ROOK);
    }
    
    #[test]
    fn test_side_opposite() {
        assert_eq!(Side::Red.opposite(), Side::Black);
        assert_eq!(Side::Black.opposite(), Side::Red);
    }
}
