use std::io::Write;
use std::time::Instant;
use std::collections::{HashSet, VecDeque};

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
    last_event_seq: u64,
    processed_command_ids: HashSet<String>,
    processed_command_order: VecDeque<String>,
}

impl GameSession {
    pub fn new() -> Self {
        Self {
            state: ChessGameState::new(),
            ai: AlphaBetaMinMax::new(),
            logger: GameLogger::new(),
            last_event_seq: 0,
            processed_command_ids: HashSet::new(),
            processed_command_order: VecDeque::new(),
        }
    }

    pub fn get_state_message(&self) -> ServerMessage {
        ServerMessage::State {
            fen: self.state.to_fen(),
            side_to_move: if self.state.side_to_move() == RED { "red".to_string() } else { "black".to_string() },
            result: self.result_to_string(),
            is_check: self.state.current_side_in_check(),
            seq: self.last_event_seq,
        }
    }

    fn next_event_seq(&mut self) -> u64 {
        self.last_event_seq += 1;
        self.last_event_seq
    }

    fn remember_command_id(&mut self, command_id: &str) {
        const MAX_TRACKED_COMMAND_IDS: usize = 4096;

        if self.processed_command_ids.insert(command_id.to_string()) {
            self.processed_command_order.push_back(command_id.to_string());
        }

        while self.processed_command_order.len() > MAX_TRACKED_COMMAND_IDS {
            if let Some(expired) = self.processed_command_order.pop_front() {
                self.processed_command_ids.remove(&expired);
            }
        }
    }

    fn claim_command_id(&mut self, command_id: Option<&str>) -> Result<Option<String>, ServerMessage> {
        let normalized = command_id
            .map(str::trim)
            .filter(|id| !id.is_empty())
            .map(str::to_string);

        if let Some(id) = normalized.as_ref() {
            if self.processed_command_ids.contains(id) {
                return Err(ServerMessage::Error {
                    message: format!("Duplicate command_id '{}'", id),
                    command_id: Some(id.clone()),
                });
            }
            self.remember_command_id(id);
        }

        Ok(normalized)
    }

    fn result_to_string(&self) -> String {
        match self.state.result() {
            GameResult::InProgress => "in_progress".to_string(),
            GameResult::RedWins => "red_wins".to_string(),
            GameResult::BlackWins => "black_wins".to_string(),
            GameResult::Draw => "draw".to_string(),
        }
    }

    fn helper_ai(&self, difficulty: Option<u8>) -> AlphaBetaMinMax {
        let mut ai = AlphaBetaMinMax::with_config(self.ai.config().clone());
        if let Some(level) = difficulty {
            ai.set_difficulty(level);
        }
        ai
    }

    pub fn apply_move(&mut self, move_str: &str, command_id: Option<&str>) -> ServerMessage {
        let command_id = match self.claim_command_id(command_id) {
            Ok(id) => id,
            Err(message) => return message,
        };

        if self.state.is_game_over() {
            return ServerMessage::MoveResult {
                valid: false, fen: self.state.to_fen(),
                reason: Some("Game is already over".to_string()),
                move_str: None, is_check: false, result: self.result_to_string(),
                seq: None, command_id,
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
            let seq = self.next_event_seq();
            self.logger.log_player_move(side, move_str, piece,
                if captured_piece != 0 { Some(captured_piece) } else { None }, &fen, is_check);
            if self.state.is_game_over() { self.logger.log_game_over(&result_str, &fen); }
            ServerMessage::MoveResult {
                valid: true, fen, reason: None,
                move_str: Some(move_str.to_string()), is_check, result: result_str,
                seq: Some(seq), command_id,
            }
        } else {
            self.logger.log_invalid_move(side, move_str, "Invalid move");
            ServerMessage::MoveResult {
                valid: false, fen: self.state.to_fen(),
                reason: Some("Invalid move".to_string()), move_str: None,
                is_check: self.state.current_side_in_check(), result: self.result_to_string(),
                seq: None, command_id,
            }
        }
    }

    pub fn generate_ai_move(&mut self, difficulty: Option<u8>) -> ServerMessage {
        if self.state.is_game_over() {
            return ServerMessage::Error { message: "Game is already over".to_string(), command_id: None };
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
                let seq = self.next_event_seq();
                self.logger.log_ai_move(side, &move_str, mv.piece, captured,
                    &fen_after, is_check, &config, &result, elapsed_ms);
                if self.state.is_game_over() { self.logger.log_game_over(&result_str, &fen_after); }
                ServerMessage::AiMoveResult {
                    move_str, fen: fen_after, score: result.score,
                    nodes_searched: result.nodes_searched, is_check, result: result_str,
                    seq,
                }
            }
            None => ServerMessage::Error { message: "AI could not find a valid move".to_string(), command_id: None },
        }
    }

    pub fn reset(&mut self, command_id: Option<&str>) -> ServerMessage {
        if let Err(message) = self.claim_command_id(command_id) {
            return message;
        }
        self.state.reset();
        self.logger.log_new_game();
        let seq = self.next_event_seq();
        ServerMessage::State {
            fen: self.state.to_fen(),
            side_to_move: "red".to_string(),
            result: self.result_to_string(),
            is_check: self.state.current_side_in_check(),
            seq,
        }
    }

    pub fn set_position(&mut self, fen: &str, resume_seq: Option<u64>) -> ServerMessage {
        self.state = ChessGameState::from_fen(fen);
        let seq = match resume_seq {
            Some(seq) => {
                self.last_event_seq = seq;
                seq
            }
            None => self.next_event_seq(),
        };
        ServerMessage::State {
            fen: self.state.to_fen(),
            side_to_move: if self.state.side_to_move() == RED { "red".to_string() } else { "black".to_string() },
            result: self.result_to_string(),
            is_check: self.state.current_side_in_check(),
            seq,
        }
    }

    pub fn validate_fen_preview(&self, fen: &str) -> ServerMessage {
        let state = ChessGameState::from_fen(fen);
        ServerMessage::Validation {
            valid: true,
            normalized_fen: Some(state.to_fen()),
            reason: None,
        }
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

    pub fn get_legal_moves_for_piece_at_fen(&self, fen: &str, square_str: &str) -> ServerMessage {
        let mut state = ChessGameState::from_fen(fen);
        let from_sq = match state.board().square(square_str) {
            Some(sq) => sq,
            None => return ServerMessage::LegalMovesResult { square: square_str.to_string(), targets: vec![] },
        };
        let legal_moves = state.legal_moves();
        let targets: Vec<String> = legal_moves.iter()
            .filter(|mv| mv.from as usize == from_sq)
            .filter_map(|mv| BOARD_ENCODING.get(mv.to as usize).map(|s| s.to_string()))
            .collect();
        ServerMessage::LegalMovesResult { square: square_str.to_string(), targets }
    }

    pub fn get_suggestion(&mut self, difficulty: Option<u8>) -> ServerMessage {
        if self.state.is_game_over() {
            return ServerMessage::Error { message: "Game is already over".to_string(), command_id: None };
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
            None => ServerMessage::Error { message: "No suggestion available".to_string(), command_id: None },
        }
    }

    pub fn get_suggestion_for_fen(&self, fen: &str, difficulty: Option<u8>) -> ServerMessage {
        let mut state = ChessGameState::from_fen(fen);
        if state.is_game_over() {
            return ServerMessage::Error { message: "Game is already over".to_string(), command_id: None };
        }

        let mut ai = self.helper_ai(difficulty);
        let result = ai.generate_move(&mut state);

        match result.best_move {
            Some(mv) => {
                let from_coord = BOARD_ENCODING[mv.from as usize].to_string();
                let to_coord = BOARD_ENCODING[mv.to as usize].to_string();
                let move_str = format!("{}{}", from_coord, to_coord);
                ServerMessage::Suggestion {
                    move_str, from: from_coord, to: to_coord,
                    score: result.score, nodes_searched: result.nodes_searched,
                }
            }
            None => ServerMessage::Error { message: "No suggestion available".to_string(), command_id: None },
        }
    }

    pub fn preview_move_at_fen(&self, fen: &str, move_str: &str) -> ServerMessage {
        let mut state = ChessGameState::from_fen(fen);
        if state.is_game_over() {
            return ServerMessage::MoveResult {
                valid: false,
                fen: state.to_fen(),
                reason: Some("Game is already over".to_string()),
                move_str: None,
                is_check: false,
                result: match state.result() {
                    GameResult::InProgress => "in_progress".to_string(),
                    GameResult::RedWins => "red_wins".to_string(),
                    GameResult::BlackWins => "black_wins".to_string(),
                    GameResult::Draw => "draw".to_string(),
                },
                seq: None,
                command_id: None,
            };
        }

        if state.apply_move_str(move_str) {
            let fen_after = state.to_fen();
            let is_check = state.current_side_in_check();
            let result = match state.result() {
                GameResult::InProgress => "in_progress".to_string(),
                GameResult::RedWins => "red_wins".to_string(),
                GameResult::BlackWins => "black_wins".to_string(),
                GameResult::Draw => "draw".to_string(),
            };
            ServerMessage::MoveResult {
                valid: true,
                fen: fen_after,
                reason: None,
                move_str: Some(move_str.to_string()),
                is_check,
                result,
                seq: None,
                command_id: None,
            }
        } else {
            ServerMessage::MoveResult {
                valid: false,
                fen: state.to_fen(),
                reason: Some("Invalid move".to_string()),
                move_str: None,
                is_check: state.current_side_in_check(),
                result: match state.result() {
                    GameResult::InProgress => "in_progress".to_string(),
                    GameResult::RedWins => "red_wins".to_string(),
                    GameResult::BlackWins => "black_wins".to_string(),
                    GameResult::Draw => "draw".to_string(),
                },
                seq: None,
                command_id: None,
            }
        }
    }

    /// Deep position analysis with full feature extraction
    pub fn analyze_position(&mut self, fen: Option<&str>, difficulty: Option<u8>) -> ServerMessage {
        let mut state = fen
            .map(ChessGameState::from_fen)
            .unwrap_or_else(|| self.state.clone());
        let mut ai = self.helper_ai(difficulty);
        let (result, analysis, features) = ai.analyze_position(&mut state, None);

        // Combine analysis + features into a JSON value
        let mut output = serde_json::to_value(&analysis).unwrap_or(serde_json::json!({}));
        if let Some(feat) = features {
            if let Ok(feat_val) = serde_json::to_value(&feat) {
                output["move_features"] = feat_val;
            }
        }
        output["search_score"] = serde_json::json!(result.score);
        output["search_nodes"] = serde_json::json!(result.nodes_searched);
        output["search_depth"] = serde_json::json!(result.depth_reached);

        ServerMessage::Analysis { features: output }
    }

    /// Batch analyze a full game: process each FEN+move pair and extract features
    pub fn batch_analyze(
        &mut self,
        moves: &[crate::api::BatchEntryMsg],
        difficulty: Option<u8>,
    ) -> ServerMessage {
        if let Some(level) = difficulty {
            self.ai.set_difficulty(level);
        }

        let mut results: Vec<serde_json::Value> = Vec::new();
        let mut prev_score: Option<i32> = None;

        for (idx, entry) in moves.iter().enumerate() {
            println!("[BATCH] Processing move {}/{}: {} on {}",
                idx + 1, moves.len(), entry.move_str, entry.fen);

            let mut state = ChessGameState::from_fen(&entry.fen);
            let mut ai = self.helper_ai(difficulty);
            let search_start = std::time::Instant::now();
            let search_result = ai.generate_move(&mut state);
            let elapsed_ms = search_start.elapsed().as_secs_f64() * 1000.0;

            // Find the played move in legal moves
            let legal_moves = state.legal_moves();
            let played_mv = legal_moves.iter().find(|mv| {
                let from_str = BOARD_ENCODING[mv.from as usize];
                let to_str = BOARD_ENCODING[mv.to as usize];
                let mv_str = format!("{}{}", from_str, to_str);
                mv_str == entry.move_str
            });

            if let Some(mv) = played_mv {
                let alternatives = ai.get_top_moves(&mut state, 5);
                let features = crate::AI::feature_extractor::extract_features(
                    &mut state,
                    mv,
                    &search_result,
                    prev_score,
                    elapsed_ms,
                    &alternatives,
                );

                prev_score = Some(search_result.score);

                let batch_result = crate::AI::feature_extractor::BatchResult {
                    features,
                    expert_commentary: entry.expert_commentary.clone(),
                };

                if let Ok(val) = serde_json::to_value(&batch_result) {
                    results.push(val);
                }
            } else {
                println!("[BATCH] Warning: move '{}' not found in legal moves for FEN: {}",
                    entry.move_str, entry.fen);
                results.push(serde_json::json!({
                    "error": format!("Move '{}' not legal in position", entry.move_str),
                    "fen": entry.fen,
                }));
            }
        }

        let total = results.len();
        ServerMessage::BatchAnalysis {
            results,
            total_moves: total,
        }
    }

    /// Detect puzzle characteristics in a given FEN position.
    ///
    /// Runs a deep analyze on the position to get both the `PositionAnalysis`
    /// and the engine's best-move suggestion, then passes both to
    /// `puzzle_detector::detect_puzzle` and returns a `PuzzleDetection` payload.
    pub fn detect_puzzle(&mut self, fen: &str, depth: u8) -> ServerMessage {
        use crate::AI::position_analyzer;
        use crate::AI::puzzle_detector;

        let mut state = ChessGameState::from_fen(fen);

        // Run analysis to build PositionAnalysis.
        let analysis = position_analyzer::analyze(&mut state);

        // Run a shallow search to get the best move suggestion.
        // `set_difficulty` maps directly to search depth (1-10).
        let mut ai = self.helper_ai(Some(depth.clamp(1, 10)));
        let search = ai.generate_move(&mut state);
        let best_move = search.best_move.map(|mv| {
            let from = BOARD_ENCODING[mv.from as usize];
            let to   = BOARD_ENCODING[mv.to as usize];
            format!("{}{}", from, to)
        });

        let detection = puzzle_detector::detect_puzzle(&analysis, depth, best_move);

        match serde_json::to_value(&detection) {
            Ok(val) => ServerMessage::PuzzleDetection { detection: val },
            Err(e)  => ServerMessage::Error {
                message: format!("puzzle_detection: serialization error: {}", e),
                command_id: None,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const START_FEN: &str = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";

    #[test]
    fn preview_move_does_not_mutate_live_session() {
        let session = GameSession::new();
        let before = session.get_state_message();

        let preview = session.preview_move_at_fen(START_FEN, "b0c2");

        match preview {
            ServerMessage::MoveResult { valid, move_str, .. } => {
                assert!(valid);
                assert_eq!(move_str.as_deref(), Some("b0c2"));
            }
            other => panic!("unexpected preview response: {:?}", std::mem::discriminant(&other)),
        }

        let after = session.get_state_message();
        match (before, after) {
            (
                ServerMessage::State { fen: before_fen, .. },
                ServerMessage::State { fen: after_fen, .. },
            ) => assert_eq!(before_fen, after_fen),
            _ => panic!("expected state messages"),
        }
    }

    #[test]
    fn legal_moves_preview_does_not_mutate_live_session() {
        let session = GameSession::new();
        let before = session.get_state_message();

        let preview = session.get_legal_moves_for_piece_at_fen(START_FEN, "b0");
        match preview {
            ServerMessage::LegalMovesResult { square, targets } => {
                assert_eq!(square, "b0");
                assert!(targets.contains(&"c2".to_string()));
            }
            other => panic!("unexpected legal preview response: {:?}", std::mem::discriminant(&other)),
        }

        let after = session.get_state_message();
        match (before, after) {
            (
                ServerMessage::State { fen: before_fen, .. },
                ServerMessage::State { fen: after_fen, .. },
            ) => assert_eq!(before_fen, after_fen),
            _ => panic!("expected state messages"),
        }
    }

    #[test]
    fn authoritative_events_receive_strictly_increasing_seq() {
        let mut session = GameSession::new();

        let first = session.apply_move("b0c2", Some("cmd-1"));
        let second = session.generate_ai_move(Some(1));
        let third = session.reset(Some("cmd-2"));

        let first_seq = match first {
            ServerMessage::MoveResult { seq, .. } => seq.expect("move seq"),
            other => panic!("unexpected first response: {:?}", std::mem::discriminant(&other)),
        };
        let second_seq = match second {
            ServerMessage::AiMoveResult { seq, .. } => seq,
            other => panic!("unexpected second response: {:?}", std::mem::discriminant(&other)),
        };
        let third_seq = match third {
            ServerMessage::State { seq, .. } => seq,
            other => panic!("unexpected third response: {:?}", std::mem::discriminant(&other)),
        };

        assert!(first_seq < second_seq);
        assert!(second_seq < third_seq);
    }

    #[test]
    fn duplicate_command_id_is_rejected_without_advancing_state() {
        let mut session = GameSession::new();

        let first = session.apply_move("b0c2", Some("dup-1"));
        let first_seq = match first {
            ServerMessage::MoveResult { valid, seq, .. } => {
                assert!(valid);
                seq.expect("seq for valid move")
            }
            other => panic!("unexpected first response: {:?}", std::mem::discriminant(&other)),
        };

        let duplicate = session.apply_move("h0g2", Some("dup-1"));
        match duplicate {
            ServerMessage::Error { message, command_id } => {
                assert!(message.contains("Duplicate command_id"));
                assert_eq!(command_id.as_deref(), Some("dup-1"));
            }
            other => panic!("unexpected duplicate response: {:?}", std::mem::discriminant(&other)),
        }

        match session.get_state_message() {
            ServerMessage::State { seq, .. } => assert_eq!(seq, first_seq),
            other => panic!("unexpected state response: {:?}", std::mem::discriminant(&other)),
        }
    }
}
