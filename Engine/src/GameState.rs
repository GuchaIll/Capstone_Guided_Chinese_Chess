//! Game State Management Module
//!
//! This module handles all game state tracking including:
//! - Game stage (PreGame, InGame, PostGame)
//! - Game result tracking
//! - Move history and undo functionality
//! - Captured pieces tracking
//! - Terminal condition detection (checkmate, stalemate, 60-move rule, repetition)

use std::collections::HashMap;
use crate::Game::{
    Board, Move,
    RED, BLACK, EMPTY, OFFBOARD, PAWN,
    PIECE_TYPE, PIECE_COLOR,
    START_FEN, piece_to_char,
};

// ========================
//     GAME STAGE
// ========================

/// Game stage enumeration
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum GameStage {
    PreGame,    // Before game starts
    InGame,     // Game in progress
    PostGame,   // Game ended
}

// ========================
//     GAME RESULT
// ========================

/// Game result enumeration
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum GameResult {
    InProgress,
    RedWins,
    BlackWins,
    Draw,
}

// ========================
//     CAPTURED PIECES
// ========================

/// Captured pieces tracking for each side
#[derive(Clone, Debug, Default)]
pub struct CapturedPieces {
    pub red_captured: Vec<u8>,    // Pieces captured by red
    pub black_captured: Vec<u8>,  // Pieces captured by black
}

impl CapturedPieces {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_capture(&mut self, side: u8, piece: u8) {
        if side == RED {
            self.red_captured.push(piece);
        } else {
            self.black_captured.push(piece);
        }
    }

    pub fn remove_last_capture(&mut self, side: u8) -> Option<u8> {
        if side == RED {
            self.red_captured.pop()
        } else {
            self.black_captured.pop()
        }
    }

    pub fn clear(&mut self) {
        self.red_captured.clear();
        self.black_captured.clear();
    }
}

// ========================
//     HISTORY ENTRY
// ========================

/// History entry for tracking game state for repetition detection
#[derive(Clone)]
pub struct HistoryEntry {
    pub mv: Move,
    pub position_hash: u64,
    pub halfmove_clock: u32,
    pub captured_piece: u8,
}

// ========================
//     GAME STATE
// ========================

/// Complete game state with all required fields
pub struct GameState {
    board: Board,
    stage: GameStage,
    result: GameResult,
    history: Vec<HistoryEntry>,
    captured: CapturedPieces,
    halfmove_clock: u32,
    fullmove_number: u32,
    position_counts: HashMap<u64, u8>,
}

impl GameState {
    /// Create a new game state with starting position
    pub fn new() -> Self {
        let mut state = Self {
            board: Board::new(),
            stage: GameStage::PreGame,
            result: GameResult::InProgress,
            history: Vec::new(),
            captured: CapturedPieces::new(),
            halfmove_clock: 0,
            fullmove_number: 1,
            position_counts: HashMap::new(),
        };
        state.board.set_board_from_fen(START_FEN);
        state.stage = GameStage::InGame;

        // Record initial position
        let hash = state.compute_position_hash();
        state.position_counts.insert(hash, 1);

        state
    }

    /// Create a game state from a FEN string
    pub fn from_fen(fen: &str) -> Self {
        let mut state = Self {
            board: Board::new(),
            stage: GameStage::InGame,
            result: GameResult::InProgress,
            history: Vec::new(),
            captured: CapturedPieces::new(),
            halfmove_clock: 0,
            fullmove_number: 1,
            position_counts: HashMap::new(),
        };
        state.board.set_board_from_fen(fen);

        // Parse halfmove clock and fullmove number from FEN if present
        let parts: Vec<&str> = fen.split_whitespace().collect();
        if parts.len() > 4 {
            state.halfmove_clock = parts[4].parse().unwrap_or(0);
        }
        if parts.len() > 5 {
            state.fullmove_number = parts[5].parse().unwrap_or(1);
        }

        // Record initial position
        let hash = state.compute_position_hash();
        state.position_counts.insert(hash, 1);

        state
    }

    /// Reset to starting position
    pub fn reset(&mut self) {
        self.board = Board::new();
        self.board.set_board_from_fen(START_FEN);
        self.stage = GameStage::InGame;
        self.result = GameResult::InProgress;
        self.history.clear();
        self.captured.clear();
        self.halfmove_clock = 0;
        self.fullmove_number = 1;
        self.position_counts.clear();

        let hash = self.compute_position_hash();
        self.position_counts.insert(hash, 1);
    }

    // ========================
    //     GETTERS
    // ========================

    /// Get current side to move
    pub fn side_to_move(&self) -> u8 {
        self.board.side
    }

    /// Get current game stage
    pub fn stage(&self) -> GameStage {
        self.stage
    }

    /// Get current game result
    pub fn result(&self) -> GameResult {
        self.result
    }

    /// Get captured pieces
    pub fn captured(&self) -> &CapturedPieces {
        &self.captured
    }

    /// Get move history length
    pub fn history_len(&self) -> usize {
        self.history.len()
    }

    /// Get full history
    pub fn history(&self) -> &[HistoryEntry] {
        &self.history
    }

    /// Get the last move played, if any
    pub fn last_move(&self) -> Option<Move> {
        self.history.last().map(|entry| entry.mv)
    }

    /// Get the current halfmove clock (for 60-move rule)
    pub fn halfmove_clock(&self) -> u32 {
        self.halfmove_clock
    }

    /// Get the current fullmove number
    pub fn fullmove_number(&self) -> u32 {
        self.fullmove_number
    }

    /// Get read-only access to the board
    pub fn board(&self) -> &Board {
        &self.board
    }

    // ========================
    //     CHECK DETECTION
    // ========================

    /// Check if a specific side's king is in check
    pub fn in_check(&self, side: u8) -> bool {
        let king_sq = self.board.king_squares[side as usize];
        self.board.is_square_attacked(king_sq, side ^ 1)
    }

    /// Check if current side is in check
    pub fn current_side_in_check(&self) -> bool {
        self.in_check(self.board.side)
    }

    // ========================
    //     MOVE GENERATION
    // ========================

    /// Generate all legal moves for the current side
    pub fn legal_moves(&mut self) -> Vec<Move> {
        self.board.generate_legal_moves().moves
    }

    // ========================
    //     POSITION HASH
    // ========================

    /// Compute a simple position hash for repetition detection
    fn compute_position_hash(&self) -> u64 {
        let mut hash: u64 = 0;
        for i in 0..154 {
            let piece = self.board.board[i];
            if piece != EMPTY && piece != OFFBOARD {
                hash ^= (piece as u64) << ((i % 64) as u64);
                hash = hash.wrapping_mul(31).wrapping_add(i as u64);
            }
        }
        hash ^= (self.board.side as u64) << 63;
        hash
    }

    // ========================
    //     MOVE APPLICATION
    // ========================

    /// Apply a move to the game state (validates and updates everything)
    /// Returns true if the move was legal and applied, false otherwise
    pub fn apply_move(&mut self, mv: Move) -> bool {
        // Check if game is still in progress
        if self.stage != GameStage::InGame {
            return false;
        }

        // Verify the move is for the correct side
        let piece_color = PIECE_COLOR[mv.piece as usize];
        if piece_color != self.board.side {
            return false;
        }

        // Try to make the move on the board
        if !self.board.make_move(&mv) {
            return false;
        }

        // Move was legal - update game state
        let is_capture = mv.captured != EMPTY;
        let is_pawn_move = PIECE_TYPE[mv.piece as usize] == PAWN;

        // Track captured piece
        if is_capture {
            self.captured.add_capture(piece_color, mv.captured);
        }

        // Compute position hash before updating counters
        let position_hash = self.compute_position_hash();

        // Update halfmove clock (reset on capture or pawn move)
        let prev_halfmove = self.halfmove_clock;
        if is_capture || is_pawn_move {
            self.halfmove_clock = 0;
        } else {
            self.halfmove_clock += 1;
        }

        // Update fullmove number (increment after Black moves)
        if piece_color == BLACK {
            self.fullmove_number += 1;
        }

        // Record history entry
        self.history.push(HistoryEntry {
            mv,
            position_hash,
            halfmove_clock: prev_halfmove,
            captured_piece: mv.captured,
        });

        // Update position count for repetition detection
        *self.position_counts.entry(position_hash).or_insert(0) += 1;

        // Check for terminal conditions
        self.check_terminal_conditions();

        true
    }

    /// Apply a move from string notation (e.g., "e2e4")
    pub fn apply_move_str(&mut self, move_str: &str) -> bool {
        if move_str.len() != 4 {
            return false;
        }

        let from_str = &move_str[0..2];
        let to_str = &move_str[2..4];

        let from = match self.board.square(from_str) {
            Some(sq) => sq,
            None => return false,
        };

        let to = match self.board.square(to_str) {
            Some(sq) => sq,
            None => return false,
        };

        // Validate against the legal move list to ensure the move
        // is actually legal for this piece type (prevents illegal moves
        // like pawns teleporting across the board)
        let legal_moves = self.board.generate_legal_moves();
        let legal_mv = legal_moves.moves.iter().find(|mv| {
            mv.from as usize == from && mv.to as usize == to
        });

        let mv = match legal_mv {
            Some(m) => *m,
            None => return false,
        };

        self.apply_move(mv)
    }

    /// Undo the last move
    pub fn undo_move(&mut self) -> bool {
        if let Some(entry) = self.history.pop() {
            // Undo on the board
            self.board.take_back();

            // Restore halfmove clock
            self.halfmove_clock = entry.halfmove_clock;

            // Restore fullmove number if Black's move was undone
            let piece_color = PIECE_COLOR[entry.mv.piece as usize];
            if piece_color == BLACK {
                self.fullmove_number -= 1;
            }

            // Remove captured piece from tracking
            if entry.captured_piece != EMPTY {
                self.captured.remove_last_capture(piece_color);
            }

            // Update position count
            if let Some(count) = self.position_counts.get_mut(&entry.position_hash) {
                *count = count.saturating_sub(1);
                if *count == 0 {
                    self.position_counts.remove(&entry.position_hash);
                }
            }

            // Reset game state if it was terminal
            if self.stage == GameStage::PostGame {
                self.stage = GameStage::InGame;
                self.result = GameResult::InProgress;
            }

            true
        } else {
            false
        }
    }

    // ========================
    //     TERMINAL CONDITIONS
    // ========================

    /// Check for terminal conditions (checkmate, stalemate, 60-move, repetition)
    fn check_terminal_conditions(&mut self) {
        let legal_moves = self.board.generate_legal_moves();

        // No legal moves - checkmate or stalemate
        if legal_moves.len() == 0 {
            self.stage = GameStage::PostGame;
            if self.current_side_in_check() {
                // Checkmate - the other side wins
                self.result = if self.board.side == RED {
                    GameResult::BlackWins
                } else {
                    GameResult::RedWins
                };
            } else {
                // Stalemate - draw
                self.result = GameResult::Draw;
            }
            return;
        }

        // 60-move rule (120 half-moves without capture or pawn move)
        if self.halfmove_clock >= 120 {
            self.stage = GameStage::PostGame;
            self.result = GameResult::Draw;
            return;
        }

        // Threefold repetition
        let current_hash = self.compute_position_hash();
        if let Some(&count) = self.position_counts.get(&current_hash) {
            if count >= 3 {
                self.stage = GameStage::PostGame;
                self.result = GameResult::Draw;
            }
        }
    }

    /// Check if the game has ended
    pub fn is_game_over(&self) -> bool {
        self.stage == GameStage::PostGame
    }

    /// Check if current position is checkmate
    pub fn is_checkmate(&mut self) -> bool {
        self.current_side_in_check() && self.board.generate_legal_moves().len() == 0
    }

    /// Check if current position is stalemate
    pub fn is_stalemate(&mut self) -> bool {
        !self.current_side_in_check() && self.board.generate_legal_moves().len() == 0
    }

    /// Check if 60-move rule applies
    pub fn is_sixty_move_draw(&self) -> bool {
        self.halfmove_clock >= 120
    }

    /// Check if threefold repetition occurred
    pub fn is_repetition_draw(&self) -> bool {
        let hash = self.compute_position_hash();
        self.position_counts.get(&hash).map_or(false, |&c| c >= 3)
    }

    // ========================
    //     FEN GENERATION
    // ========================

    /// Generate FEN string from current position
    pub fn to_fen(&self) -> String {
        let mut fen = String::new();

        // Piece placement
        for rank in (0..10).rev() {
            let mut empty_count = 0;
            for file in 0..9 {
                let square = Board::square_from_file_rank(file, rank);
                let piece = self.board.board[square];

                if piece == EMPTY {
                    empty_count += 1;
                } else {
                    if empty_count > 0 {
                        fen.push_str(&empty_count.to_string());
                        empty_count = 0;
                    }
                    fen.push(piece_to_char(piece));
                }
            }
            if empty_count > 0 {
                fen.push_str(&empty_count.to_string());
            }
            if rank > 0 {
                fen.push('/');
            }
        }

        // Side to move
        fen.push(' ');
        fen.push(if self.board.side == RED { 'w' } else { 'b' });

        // No castling in Xiangqi, use dash
        fen.push_str(" - - ");

        // Halfmove clock
        fen.push_str(&self.halfmove_clock.to_string());
        fen.push(' ');

        // Fullmove number
        fen.push_str(&self.fullmove_number.to_string());

        fen
    }

    // ========================
    //     DEBUG
    // ========================

    /// Print the current board state (for debugging)
    pub fn print(&self) {
        println!("\n  a b c d e f g h i");
        for rank in (0..10).rev() {
            print!("{} ", rank);
            for file in 0..9 {
                let square = Board::square_from_file_rank(file, rank);
                print!("{} ", piece_to_char(self.board.board[square]));
            }
            println!();
        }
        println!("\nSide to move: {}", if self.board.side == RED { "Red" } else { "Black" });
        println!("Halfmove clock: {}", self.halfmove_clock);
        println!("Fullmove number: {}", self.fullmove_number);
        println!("Stage: {:?}", self.stage);
        println!("Result: {:?}", self.result);
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}

// ========================
//     UNIT TESTS
// ========================
#[cfg(test)]
mod tests {
    use super::*;
    use crate::Game::{RED_CANNON, BLACK_PAWN};

    #[test]
    fn test_game_state_new() {
        let state = GameState::new();
        assert_eq!(state.side_to_move(), RED);
        assert_eq!(state.stage(), GameStage::InGame);
        assert_eq!(state.result(), GameResult::InProgress);
        assert_eq!(state.halfmove_clock(), 0);
        assert_eq!(state.fullmove_number(), 1);
        assert_eq!(state.history_len(), 0);
    }

    #[test]
    fn test_game_state_apply_move_str() {
        let mut state = GameState::new();

        let success = state.apply_move_str("b2b9");
        assert!(success);
        assert_eq!(state.side_to_move(), BLACK);
        assert_eq!(state.history_len(), 1);
        assert_eq!(state.captured().red_captured.len(), 1);
    }

    #[test]
    fn test_game_state_undo_move() {
        let mut state = GameState::new();

        let initial_fen = state.to_fen();
        state.apply_move_str("h2e2");
        assert_eq!(state.side_to_move(), BLACK);

        let undone = state.undo_move();
        assert!(undone);
        assert_eq!(state.side_to_move(), RED);
        assert_eq!(state.history_len(), 0);

        let restored_fen = state.to_fen();
        assert!(restored_fen.starts_with(&initial_fen[..50]));
    }

    #[test]
    fn test_game_state_legal_moves() {
        let mut state = GameState::new();
        let moves = state.legal_moves();
        assert_eq!(moves.len(), 44);
    }

    #[test]
    fn test_game_state_in_check() {
        let state = GameState::new();
        assert!(!state.in_check(RED));
        assert!(!state.in_check(BLACK));
        assert!(!state.current_side_in_check());
    }

    #[test]
    fn test_game_state_to_fen() {
        let state = GameState::new();
        let fen = state.to_fen();
        assert!(fen.starts_with("rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR"));
        assert!(fen.contains(" w "));
    }

    #[test]
    fn test_game_state_from_fen() {
        let fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR b - - 5 10";
        let state = GameState::from_fen(fen);
        assert_eq!(state.side_to_move(), BLACK);
        assert_eq!(state.halfmove_clock(), 5);
        assert_eq!(state.fullmove_number(), 10);
    }

    #[test]
    fn test_game_state_halfmove_clock_reset_on_capture() {
        let mut state = GameState::new();

        state.apply_move_str("h2e2");
        assert_eq!(state.halfmove_clock(), 1);

        state.apply_move_str("h9g7");
        assert_eq!(state.halfmove_clock(), 2);

        state.apply_move_str("e2e9");
        assert_eq!(state.halfmove_clock(), 0);
    }

    #[test]
    fn test_game_state_halfmove_clock_reset_on_pawn_move() {
        let mut state = GameState::new();

        state.apply_move_str("h2e2");
        state.apply_move_str("h9g7");
        assert_eq!(state.halfmove_clock(), 2);

        state.apply_move_str("c3c4");
        assert_eq!(state.halfmove_clock(), 0);
    }

    #[test]
    fn test_game_state_fullmove_counter() {
        let mut state = GameState::new();

        assert_eq!(state.fullmove_number(), 1);

        state.apply_move_str("h2e2");
        assert_eq!(state.fullmove_number(), 1);

        state.apply_move_str("h9g7");
        assert_eq!(state.fullmove_number(), 2);

        state.apply_move_str("e2e6");
        assert_eq!(state.fullmove_number(), 2);

        state.apply_move_str("g7f5");
        assert_eq!(state.fullmove_number(), 3);
    }

    #[test]
    fn test_game_state_last_move() {
        let mut state = GameState::new();

        assert!(state.last_move().is_none());

        state.apply_move_str("h2e2");
        let last = state.last_move();
        assert!(last.is_some());
        assert_eq!(last.unwrap().piece, RED_CANNON);
    }

    #[test]
    fn test_game_state_captured_pieces() {
        let mut state = GameState::new();

        assert_eq!(state.captured().red_captured.len(), 0);
        assert_eq!(state.captured().black_captured.len(), 0);

        let mut state2 = GameState::new();
        state2.apply_move_str("a0a1");
        state2.apply_move_str("a9a8");
        state2.apply_move_str("a1a6");

        assert_eq!(state2.captured().red_captured.len(), 1);
        assert_eq!(state2.captured().red_captured[0], BLACK_PAWN);
    }

    #[test]
    fn test_game_state_invalid_move_rejected() {
        let mut state = GameState::new();

        let result = state.apply_move_str("e5e6");
        assert!(!result);
        assert_eq!(state.history_len(), 0);

        let result2 = state.apply_move_str("a9a8");
        assert!(!result2);
    }

    #[test]
    fn test_game_state_game_over_flag() {
        let state = GameState::new();
        assert!(!state.is_game_over());
        assert_eq!(state.stage(), GameStage::InGame);
    }

    #[test]
    fn test_game_state_sixty_move_draw_detection() {
        let mut state = GameState::new();
        state.halfmove_clock = 118;

        state.apply_move_str("h2e2");
        assert!(!state.is_sixty_move_draw());

        state.apply_move_str("h9g7");
        assert!(state.is_sixty_move_draw());
        assert!(state.is_game_over());
        assert_eq!(state.result(), GameResult::Draw);
    }

    #[test]
    fn test_game_state_reset() {
        let mut state = GameState::new();
        state.apply_move_str("h2e2");
        state.apply_move_str("h9g7");

        assert_eq!(state.history_len(), 2);

        state.reset();

        assert_eq!(state.history_len(), 0);
        assert_eq!(state.side_to_move(), RED);
        assert_eq!(state.stage(), GameStage::InGame);
        assert_eq!(state.fullmove_number(), 1);
    }
}