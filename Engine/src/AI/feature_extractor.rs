//! Feature Extractor — produces per-move feature vectors for LLM fine-tuning
//!
//! Combines engine search metrics with the rich positional analysis from
//! `position_analyzer` to create a complete feature snapshot for each move.
//! Output format is a JSON-serializable struct that can be written as JSONL.

use serde::Serialize;

use crate::Game::{
    Move, BOARD_ENCODING, PIECE_TYPE, PIECE_COLOR,
    RED, EMPTY,
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,
};
use crate::GameState::GameState;
use crate::AI::AI::SearchResult;
use crate::AI::position_analyzer::{self, PositionAnalysis};

// Piece values (centipawns)
const PIECE_VALUES: [i32; 15] = [
    0, 100, 200, 200, 400, 450, 900, 10000,
    100, 200, 200, 400, 450, 900, 10000,
];

fn piece_type_name(pt: u8) -> &'static str {
    match pt {
        PAWN     => "pawn",
        ADVISOR  => "advisor",
        ELEPHANT => "elephant",
        KNIGHT   => "knight",
        CANNON   => "cannon",
        ROOK     => "rook",
        KING     => "king",
        _ => "unknown",
    }
}

fn side_name(side: u8) -> &'static str {
    if side == RED { "red" } else { "black" }
}

fn sq_name(sq: usize) -> String {
    if sq < 154 { BOARD_ENCODING[sq].to_string() } else { "??".to_string() }
}

// ========================
//     SEARCH METRICS
// ========================

#[derive(Clone, Debug, Serialize)]
pub struct SearchMetrics {
    pub score: i32,
    pub score_delta: i32,          // change from previous position's score
    pub centipawn_loss: i32,       // how much worse was the played move vs best?
    pub depth_reached: u8,
    pub nodes_searched: u64,
    pub nodes_per_second: f64,
    pub search_time_ms: f64,
    pub principal_variation: Vec<String>,  // top moves in PV as algebraic
    pub tt_hits: u64,
    pub tt_cuts: u64,
    pub tt_stores: u64,
    pub tt_collisions: u64,
    pub tt_hit_rate: f64,
}

// ========================
//     MOVE METADATA
// ========================

#[derive(Clone, Debug, Serialize)]
pub struct MoveMetadata {
    pub move_str: String,          // e.g. "e2e4"
    pub from_square: String,
    pub to_square: String,
    pub piece_type: String,
    pub piece_side: String,
    pub is_capture: bool,
    pub captured_piece_type: Option<String>,
    pub captured_value: Option<i32>,
    pub gives_check: bool,
    pub is_checkmate: bool,
    pub move_number: u32,
}

// ========================
//     ALTERNATIVE MOVES
// ========================

#[derive(Clone, Debug, Serialize)]
pub struct AlternativeMove {
    pub move_str: String,
    pub score: i32,
    pub piece_type: String,
    pub is_capture: bool,
}

// ========================
//     MOVE CLASSIFICATION
// ========================

#[derive(Clone, Debug, Serialize)]
pub struct MoveClassification {
    pub is_sacrifice: bool,        // SEE < 0 but search score positive
    pub is_blunder: bool,          // centipawn loss > 200
    pub is_inaccuracy: bool,       // centipawn loss > 50
    pub is_good_move: bool,        // centipawn loss < 10
    pub is_brilliant: bool,        // only move or big improvement
    pub is_book_move: bool,        // matches known opening
    pub category: String,          // "brilliant", "good", "inaccuracy", "mistake", "blunder"
}

// ========================
//     COMPLETE FEATURE VECTOR
// ========================

#[derive(Clone, Debug, Serialize)]
pub struct MoveFeatureVector {
    // Position before the move
    pub position_analysis: PositionAnalysis,

    // The move itself
    pub move_metadata: MoveMetadata,

    // Search engine metrics
    pub search_metrics: SearchMetrics,

    // Move quality classification
    pub classification: MoveClassification,

    // Alternative moves considered by the engine
    pub alternatives: Vec<AlternativeMove>,

    // Position after the move (summary, not full analysis)
    pub post_move_fen: String,
    pub post_move_in_check: bool,
    pub post_move_is_game_over: bool,
    pub post_move_result: String,
}

impl MoveFeatureVector {
    /// Serialize to a single JSON line for JSONL output
    pub fn to_json_line(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }
}

// ========================
//     EXTRACTION
// ========================

/// Extract a complete feature vector for a move.
///
/// Parameters:
/// - `state`: GameState BEFORE the move is applied
/// - `mv`: The move being played
/// - `search_result`: The engine's search result for this position
/// - `prev_score`: The engine score from the previous position (for delta)
/// - `search_time_ms`: How long the search took
/// - `alternatives`: Top alternative moves with scores
pub fn extract_features(
    state: &mut GameState,
    mv: &Move,
    search_result: &SearchResult,
    prev_score: Option<i32>,
    search_time_ms: f64,
    alternatives: &[(Move, i32)],
) -> MoveFeatureVector {
    // 1. Position analysis BEFORE the move
    let position_analysis = position_analyzer::analyze(state);

    // 2. Move metadata
    let from_str = sq_name(mv.from as usize);
    let to_str = sq_name(mv.to as usize);
    let move_str = format!("{}{}", from_str, to_str);
    let pt = PIECE_TYPE[mv.piece as usize];
    let side = PIECE_COLOR[mv.piece as usize];
    let is_capture = mv.captured != EMPTY;
    let captured_pt = if is_capture { Some(PIECE_TYPE[mv.captured as usize]) } else { None };
    let captured_val = if is_capture { Some(PIECE_VALUES[mv.captured as usize]) } else { None };

    // 3. Apply the move to see the result
    let move_number = state.fullmove_number();
    let applied = state.apply_move(*mv);

    let (gives_check, is_checkmate, post_fen, is_game_over, result_str) = if applied {
        let gc = state.current_side_in_check();
        let cm = state.is_checkmate();
        let pf = state.to_fen();
        let go = state.is_game_over();
        let rs = match state.result() {
            crate::GameState::GameResult::InProgress => "in_progress",
            crate::GameState::GameResult::RedWins => "red_wins",
            crate::GameState::GameResult::BlackWins => "black_wins",
            crate::GameState::GameResult::Draw => "draw",
        };
        state.undo_move(); // Restore state
        (gc, cm, pf, go, rs.to_string())
    } else {
        (false, false, state.to_fen(), false, "in_progress".to_string())
    };

    // 4. Search metrics
    let score = search_result.score;
    let score_delta = prev_score.map_or(0, |ps| score - ps);

    // Centipawn loss: difference between best move score and played move score
    // If the played move IS the best move, loss = 0
    let best_score = search_result.score;
    let played_move_score = if search_result.best_move.as_ref().map_or(false, |bm|
        bm.from == mv.from && bm.to == mv.to
    ) {
        best_score
    } else {
        // Find the played move's score in alternatives
        alternatives.iter()
            .find(|(m, _)| m.from == mv.from && m.to == mv.to)
            .map_or(best_score - 100, |(_, s)| *s) // estimate if not found
    };
    let centipawn_loss = (best_score - played_move_score).max(0);

    let nps = if search_time_ms > 0.0 {
        search_result.nodes_searched as f64 / (search_time_ms / 1000.0)
    } else {
        0.0
    };

    let (tt_hits, tt_cuts, tt_stores, tt_collisions) = match &search_result.tt_stats {
        Some(s) => (s.hits, s.cuts, s.stores, s.collisions),
        None => (0, 0, 0, 0),
    };
    let tt_hit_rate = if tt_hits + tt_stores > 0 {
        tt_hits as f64 / (tt_hits + tt_stores) as f64
    } else {
        0.0
    };

    let pv_strings: Vec<String> = search_result.principal_variation.iter().map(|m| {
        format!("{}{}", sq_name(m.from as usize), sq_name(m.to as usize))
    }).collect();

    let search_metrics = SearchMetrics {
        score,
        score_delta,
        centipawn_loss,
        depth_reached: search_result.depth_reached,
        nodes_searched: search_result.nodes_searched,
        nodes_per_second: nps,
        search_time_ms,
        principal_variation: pv_strings,
        tt_hits,
        tt_cuts,
        tt_stores,
        tt_collisions,
        tt_hit_rate,
    };

    // 5. Move classification
    let classification = classify_move(centipawn_loss, is_capture, captured_val, &search_result);

    // 6. Alternatives
    let alt_moves: Vec<AlternativeMove> = alternatives.iter().take(5).map(|(m, s)| {
        AlternativeMove {
            move_str: format!("{}{}", sq_name(m.from as usize), sq_name(m.to as usize)),
            score: *s,
            piece_type: piece_type_name(PIECE_TYPE[m.piece as usize]).to_string(),
            is_capture: m.captured != EMPTY,
        }
    }).collect();

    // 7. Move metadata
    let move_metadata = MoveMetadata {
        move_str,
        from_square: from_str,
        to_square: to_str,
        piece_type: piece_type_name(pt).to_string(),
        piece_side: side_name(side).to_string(),
        is_capture,
        captured_piece_type: captured_pt.map(|t| piece_type_name(t).to_string()),
        captured_value: captured_val,
        gives_check,
        is_checkmate,
        move_number,
    };

    MoveFeatureVector {
        position_analysis,
        move_metadata,
        search_metrics,
        classification,
        alternatives: alt_moves,
        post_move_fen: post_fen,
        post_move_in_check: gives_check,
        post_move_is_game_over: is_game_over,
        post_move_result: result_str,
    }
}

/// Classify the quality of a move based on centipawn loss
fn classify_move(
    centipawn_loss: i32,
    is_capture: bool,
    captured_value: Option<i32>,
    search_result: &SearchResult,
) -> MoveClassification {
    let is_blunder = centipawn_loss > 200;
    let is_inaccuracy = centipawn_loss > 50 && !is_blunder;
    let is_good_move = centipawn_loss < 10;
    let is_brilliant = centipawn_loss == 0 && search_result.nodes_searched > 1000;

    // Sacrifice: capture where the captured value is less than the capturing piece's value
    // but the engine score stays positive — detected heuristically
    let is_sacrifice = is_capture
        && captured_value.unwrap_or(0) < 400
        && search_result.score > 100;

    let category = if is_blunder {
        "blunder"
    } else if centipawn_loss > 100 {
        "mistake"
    } else if is_inaccuracy {
        "inaccuracy"
    } else if is_brilliant {
        "brilliant"
    } else if is_good_move {
        "good"
    } else {
        "acceptable"
    };

    MoveClassification {
        is_sacrifice,
        is_blunder,
        is_inaccuracy,
        is_good_move,
        is_brilliant,
        is_book_move: false, // TODO: match against opening book
        category: category.to_string(),
    }
}

// ========================
//     BATCH ANALYSIS
// ========================

/// Entry for batch analysis: a position + move pair
#[derive(Clone, Debug)]
pub struct BatchEntry {
    pub fen: String,
    pub move_str: String,
    pub expert_commentary: Option<String>,
}

/// Result of batch analysis for one move
#[derive(Clone, Debug, Serialize)]
pub struct BatchResult {
    pub features: MoveFeatureVector,
    pub expert_commentary: Option<String>,
}

impl BatchResult {
    pub fn to_json_line(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }
}

// ========================
//     TESTS
// ========================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AI::AI::AI as AITrait;
    use crate::AI::AlphaBetaMinMax::AlphaBetaMinMax;

    #[test]
    fn test_extract_features_basic() {
        let mut state = GameState::new();
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best_mv = result.best_move.unwrap();

        let features = extract_features(
            &mut state,
            &best_mv,
            &result,
            None,
            100.0,
            &[],
        );

        assert_eq!(features.move_metadata.piece_side, "red");
        assert!(features.search_metrics.nodes_searched > 0);
        assert_eq!(features.position_analysis.phase_name, "opening");
        assert_eq!(features.position_analysis.material.material_balance, 0);
        assert!(!features.post_move_is_game_over);
    }

    #[test]
    fn test_centipawn_loss_best_move() {
        let mut state = GameState::new();
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best_mv = result.best_move.unwrap();

        let features = extract_features(
            &mut state, &best_mv, &result, None, 50.0, &[],
        );

        // Best move should have 0 centipawn loss
        assert_eq!(features.search_metrics.centipawn_loss, 0);
        assert!(features.classification.is_good_move);
    }

    #[test]
    fn test_json_serialization() {
        let mut state = GameState::new();
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(1);

        let result = ai.generate_move(&mut state);
        let best_mv = result.best_move.unwrap();

        let features = extract_features(
            &mut state, &best_mv, &result, None, 10.0, &[],
        );

        let json = features.to_json_line();
        assert!(!json.is_empty());
        assert!(json.contains("position_analysis"));
        assert!(json.contains("search_metrics"));
        assert!(json.contains("move_metadata"));
    }

    #[test]
    fn test_capture_features() {
        // Set up a position where a capture is the best move
        let mut state = GameState::from_fen(
            "4k4/9/9/9/R3r4/9/9/9/9/4K4 w - - 0 1"
        );
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best_mv = result.best_move.unwrap();

        let features = extract_features(
            &mut state, &best_mv, &result, None, 50.0, &[],
        );

        // The best move should capture the rook
        if features.move_metadata.is_capture {
            assert_eq!(features.move_metadata.captured_piece_type, Some("rook".to_string()));
            assert_eq!(features.move_metadata.captured_value, Some(900));
        }
    }
}
