use std::io::Write;
use std::time::Instant;

use crate::GameState::GameState as ChessGameState;
use crate::GameState::GameResult;
use crate::AI::AI::{AI as AITrait, SearchConfig, SearchResult};
use crate::AI::AlphaBetaMinMax::AlphaBetaMinMax;
use crate::Game::{
    RED, BOARD_ENCODING, PIECE_TYPE, piece_to_char,
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,
};
use crate::api::ServerMessage;

// ========================
//     GAME LOGGER
// ========================

pub struct GameLogger {
    file: std::fs::File,
    move_number: u32,
}

impl GameLogger {
    pub fn new() -> Self {
        let _ = std::fs::create_dir_all("Engine/logs");
        let file = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open("Engine/logs/game.txt")
            .expect("Failed to open Engine/logs/game.txt");
        let mut logger = Self { file, move_number: 0 };
        logger.write_header();
        logger
    }

    fn write_header(&mut self) {
        let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
        let _ = writeln!(self.file, "================================================================");
        let _ = writeln!(self.file, "  CHINESE CHESS ENGINE - GAME LOG");
        let _ = writeln!(self.file, "  Started: {}", timestamp);
        let _ = writeln!(self.file, "================================================================");
        let _ = writeln!(self.file);
        let _ = self.file.flush();
    }

    fn piece_name(piece_type: u8) -> &'static str {
        match piece_type {
            PAWN     => "Pawn",
            ADVISOR  => "Advisor",
            ELEPHANT => "Elephant",
            KNIGHT   => "Knight",
            CANNON   => "Cannon",
            ROOK     => "Rook",
            KING     => "King",
            _        => "Unknown",
        }
    }

    fn side_name(side: u8) -> &'static str {
        if side == RED { "RED" } else { "BLACK" }
    }

    fn features_str(config: &SearchConfig) -> String {
        let mut features = Vec::new();
        if config.use_move_ordering { features.push("MVV-LVA+Killers+History"); }
        if config.use_transposition_table { features.push("TranspositionTable"); }
        if config.use_quiescence { features.push("Quiescence+SEE"); }
        if features.is_empty() { features.push("None (raw alpha-beta)"); }
        features.join(", ")
    }

    pub fn log_new_game(&mut self) {
        self.move_number = 0;
        let timestamp = chrono::Local::now().format("%H:%M:%S");
        let _ = writeln!(self.file, "\n--- NEW GAME [{}] ---\n", timestamp);
        let _ = self.file.flush();
    }

    pub fn log_player_move(&mut self, side: u8, move_str: &str, piece: u8,
        captured: Option<u8>, fen_after: &str, is_check: bool) {
        self.move_number += 1;
        let piece_type = PIECE_TYPE[piece as usize];
        let piece_char = piece_to_char(piece);
        let capture_str = match captured {
            Some(cap) => format!(" x {} ({})", piece_to_char(cap), Self::piece_name(PIECE_TYPE[cap as usize])),
            None => String::new(),
        };
        let check_str = if is_check { " [CHECK]" } else { "" };
        let _ = writeln!(self.file, "Move #{}: {} (Player)", self.move_number, Self::side_name(side));
        let _ = writeln!(self.file, "  Piece:    {} ({})", piece_char, Self::piece_name(piece_type));
        let _ = writeln!(self.file, "  Move:     {}{}{}", move_str, capture_str, check_str);
        let _ = writeln!(self.file, "  FEN:      {}", fen_after);
        let _ = writeln!(self.file);
        let _ = self.file.flush();
    }

    pub fn log_ai_move(&mut self, side: u8, move_str: &str, piece: u8,
        captured: Option<u8>, fen_after: &str, is_check: bool,
        config: &SearchConfig, result: &SearchResult, elapsed_ms: f64) {
        self.move_number += 1;
        let piece_type = PIECE_TYPE[piece as usize];
        let piece_char = piece_to_char(piece);
        let capture_str = match captured {
            Some(cap) => format!(" x {} ({})", piece_to_char(cap), Self::piece_name(PIECE_TYPE[cap as usize])),
            None => String::new(),
        };
        let check_str = if is_check { " [CHECK]" } else { "" };
        let nps = if elapsed_ms > 0.0 { result.nodes_searched as f64 / (elapsed_ms / 1000.0) } else { 0.0 };
        let _ = writeln!(self.file, "Move #{}: {} (AI)", self.move_number, Self::side_name(side));
        let _ = writeln!(self.file, "  Piece:    {} ({})", piece_char, Self::piece_name(piece_type));
        let _ = writeln!(self.file, "  Move:     {}{}{}", move_str, capture_str, check_str);
        let _ = writeln!(self.file, "  --- Search Config ---");
        let _ = writeln!(self.file, "  Method:   Alpha-Beta Minimax + Iterative Deepening");
        let _ = writeln!(self.file, "  Features: {}", Self::features_str(config));
        let _ = writeln!(self.file, "  Depth:    {} (target) / {} (reached)", config.depth, result.depth_reached);
        let _ = writeln!(self.file, "  TimeLimit: {}ms", config.time_limit_ms.unwrap_or(0));
        let _ = writeln!(self.file, "  --- Search Results ---");
        let _ = writeln!(self.file, "  Score:    {}", result.score);
        let _ = writeln!(self.file, "  Nodes:    {}", result.nodes_searched);
        let _ = writeln!(self.file, "  Time:     {:.1}ms", elapsed_ms);
        let _ = writeln!(self.file, "  NPS:      {:.0} nodes/sec", nps);
        if let Some(ref tt) = result.tt_stats {
            let hit_rate = if tt.hits + tt.stores > 0 { (tt.hits as f64 / (tt.hits + tt.stores) as f64) * 100.0 } else { 0.0 };
            let _ = writeln!(self.file, "  --- TT Stats ---");
            let _ = writeln!(self.file, "  Hits:       {}", tt.hits);
            let _ = writeln!(self.file, "  Cutoffs:    {}", tt.cuts);
            let _ = writeln!(self.file, "  Stores:     {}", tt.stores);
            let _ = writeln!(self.file, "  Collisions: {}", tt.collisions);
            let _ = writeln!(self.file, "  Hit Rate:   {:.1}%", hit_rate);
        }
        let _ = writeln!(self.file, "  FEN:      {}", fen_after);
        let _ = writeln!(self.file);
        let _ = self.file.flush();
    }

    pub fn log_suggestion(&mut self, side: u8, move_str: &str,
        config: &SearchConfig, result: &SearchResult, elapsed_ms: f64) {
        let nps = if elapsed_ms > 0.0 { result.nodes_searched as f64 / (elapsed_ms / 1000.0) } else { 0.0 };
        let _ = writeln!(self.file, "Suggestion for {} (Move #{})", Self::side_name(side), self.move_number + 1);
        let _ = writeln!(self.file, "  Best Move: {}", move_str);
        let _ = writeln!(self.file, "  Method:    Alpha-Beta Minimax + Iterative Deepening");
        let _ = writeln!(self.file, "  Features:  {}", Self::features_str(config));
        let _ = writeln!(self.file, "  Depth:     {} / {}", result.depth_reached, config.depth);
        let _ = writeln!(self.file, "  Score:     {}", result.score);
        let _ = writeln!(self.file, "  Nodes:     {}", result.nodes_searched);
        let _ = writeln!(self.file, "  Time:      {:.1}ms", elapsed_ms);
        let _ = writeln!(self.file, "  NPS:       {:.0} nodes/sec", nps);
        if let Some(ref tt) = result.tt_stats {
            let _ = writeln!(self.file, "  TT: hits={} cuts={} stores={} collisions={}", tt.hits, tt.cuts, tt.stores, tt.collisions);
        }
        let _ = writeln!(self.file);
        let _ = self.file.flush();
    }

    pub fn log_game_over(&mut self, result_str: &str, fen: &str) {
        let _ = writeln!(self.file, "================================================================");
        let _ = writeln!(self.file, "  GAME OVER: {}", result_str);
        let _ = writeln!(self.file, "  Total Moves: {}", self.move_number);
        let _ = writeln!(self.file, "  Final FEN: {}", fen);
        let _ = writeln!(self.file, "================================================================\n");
        let _ = self.file.flush();
    }

    pub fn log_invalid_move(&mut self, side: u8, move_str: &str, reason: &str) {
        let _ = writeln!(self.file, "  [REJECTED] {} attempted {}: {}", Self::side_name(side), move_str, reason);
        let _ = self.file.flush();
    }
}

// ========================
//     GAME SESSION
// ========================

pub struct GameSession {
    state: ChessGameState,
    ai: AlphaBetaMinMax,
    logger: GameLogger,
}

impl GameSession {
    pub fn new() -> Self {
        Self {
            state: ChessGameState::new(),
            ai: AlphaBetaMinMax::new(),
            logger: GameLogger::new(),
        }
    }

    pub fn get_state_message(&self) -> ServerMessage {
        ServerMessage::State {
            fen: self.state.to_fen(),
            side_to_move: if self.state.side_to_move() == RED { "red".to_string() } else { "black".to_string() },
            result: self.result_to_string(),
            is_check: self.state.current_side_in_check(),
        }
    }

    fn result_to_string(&self) -> String {
        match self.state.result() {
            GameResult::InProgress => "in_progress".to_string(),
            GameResult::RedWins => "red_wins".to_string(),
            GameResult::BlackWins => "black_wins".to_string(),
            GameResult::Draw => "draw".to_string(),
        }
    }

    pub fn apply_move(&mut self, move_str: &str) -> ServerMessage {
        if self.state.is_game_over() {
            return ServerMessage::MoveResult {
                valid: false, fen: self.state.to_fen(),
                reason: Some("Game is already over".to_string()),
                move_str: None, is_check: false, result: self.result_to_string(),
            };
        }
        let side = self.state.side_to_move();
        let from_sq = self.state.board().square(&move_str[0..2]);
        let to_sq = self.state.board().square(&move_str[2..4]);
        let piece = from_sq.map(|sq| self.state.board().piece_at(sq)).unwrap_or(0);
        let captured_piece = to_sq.map(|sq| self.state.board().piece_at(sq)).unwrap_or(0);

        if self.state.apply_move_str(move_str) {
            let fen = self.state.to_fen();
            let is_check = self.state.current_side_in_check();
            let result_str = self.result_to_string();
            self.logger.log_player_move(side, move_str, piece,
                if captured_piece != 0 { Some(captured_piece) } else { None }, &fen, is_check);
            if self.state.is_game_over() { self.logger.log_game_over(&result_str, &fen); }
            ServerMessage::MoveResult {
                valid: true, fen, reason: None,
                move_str: Some(move_str.to_string()), is_check, result: result_str,
            }
        } else {
            self.logger.log_invalid_move(side, move_str, "Invalid move");
            ServerMessage::MoveResult {
                valid: false, fen: self.state.to_fen(),
                reason: Some("Invalid move".to_string()), move_str: None,
                is_check: self.state.current_side_in_check(), result: self.result_to_string(),
            }
        }
    }

    pub fn generate_ai_move(&mut self, difficulty: Option<u8>) -> ServerMessage {
        if self.state.is_game_over() {
            return ServerMessage::Error { message: "Game is already over".to_string() };
        }
        if let Some(level) = difficulty { self.ai.set_difficulty(level); }

        let fen_before = self.state.to_fen();
        let side = self.state.side_to_move();
        let config = self.ai.config().clone();
        println!("[AI] generate_ai_move: depth={}, MO={}, TT={}, QS={}, time_limit={:?}ms",
            config.depth, config.use_move_ordering, config.use_transposition_table,
            config.use_quiescence, config.time_limit_ms);
        println!("[AI] Position: {}", fen_before);

        let search_start = Instant::now();
        let result = self.ai.generate_move(&mut self.state);
        let elapsed_ms = search_start.elapsed().as_secs_f64() * 1000.0;

        match result.best_move {
            Some(mv) => {
                let from_coord = BOARD_ENCODING[mv.from as usize];
                let to_coord = BOARD_ENCODING[mv.to as usize];
                let move_str = format!("{}{}", from_coord, to_coord);
                let captured = if mv.captured != 0 { Some(mv.captured) } else { None };
                self.state.apply_move(mv);
                let fen_after = self.state.to_fen();
                let is_check = self.state.current_side_in_check();
                let result_str = self.result_to_string();
                self.logger.log_ai_move(side, &move_str, mv.piece, captured,
                    &fen_after, is_check, &config, &result, elapsed_ms);
                if self.state.is_game_over() { self.logger.log_game_over(&result_str, &fen_after); }
                ServerMessage::AiMoveResult {
                    move_str, fen: fen_after, score: result.score,
                    nodes_searched: result.nodes_searched, is_check, result: result_str,
                }
            }
            None => ServerMessage::Error { message: "AI could not find a valid move".to_string() },
        }
    }

    pub fn reset(&mut self) {
        self.state.reset();
        self.logger.log_new_game();
    }

    pub fn set_position(&mut self, fen: &str) -> ServerMessage {
        self.state = ChessGameState::from_fen(fen);
        self.get_state_message()
    }

    pub fn get_legal_moves_for_piece(&mut self, square_str: &str) -> ServerMessage {
        let from_sq = match self.state.board().square(square_str) {
            Some(sq) => sq,
            None => return ServerMessage::LegalMovesResult { square: square_str.to_string(), targets: vec![] },
        };
        let legal_moves = self.state.legal_moves();
        let targets: Vec<String> = legal_moves.iter()
            .filter(|mv| mv.from as usize == from_sq)
            .filter_map(|mv| BOARD_ENCODING.get(mv.to as usize).map(|s| s.to_string()))
            .collect();
        ServerMessage::LegalMovesResult { square: square_str.to_string(), targets }
    }

    pub fn get_suggestion(&mut self, difficulty: Option<u8>) -> ServerMessage {
        if self.state.is_game_over() {
            return ServerMessage::Error { message: "Game is already over".to_string() };
        }
        if let Some(level) = difficulty { self.ai.set_difficulty(level); }

        let side = self.state.side_to_move();
        let config = self.ai.config().clone();
        println!("[AI] get_suggestion: depth={}, MO={}, TT={}, QS={}, time_limit={:?}ms",
            config.depth, config.use_move_ordering, config.use_transposition_table,
            config.use_quiescence, config.time_limit_ms);

        let search_start = Instant::now();
        let result = self.ai.generate_move(&mut self.state);
        let elapsed_ms = search_start.elapsed().as_secs_f64() * 1000.0;

        match result.best_move {
            Some(mv) => {
                let from_coord = BOARD_ENCODING[mv.from as usize].to_string();
                let to_coord = BOARD_ENCODING[mv.to as usize].to_string();
                let move_str = format!("{}{}", from_coord, to_coord);
                self.logger.log_suggestion(side, &move_str, &config, &result, elapsed_ms);
                ServerMessage::Suggestion {
                    move_str, from: from_coord, to: to_coord,
                    score: result.score, nodes_searched: result.nodes_searched,
                }
            }
            None => ServerMessage::Error { message: "No suggestion available".to_string() },
        }
    }
}
