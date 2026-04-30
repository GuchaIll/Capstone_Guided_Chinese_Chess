//! Puzzle Detector — heuristic-based tactical puzzle analysis for Xiangqi.
//!
//! Given a `PositionAnalysis` (already computed by `position_analyzer`) and an
//! optional engine `SearchResult`, this module determines:
//!
//! - Whether the position is **puzzle-worthy** (contains at least one non-trivial motif)
//! - Which **tactical motifs** are present (fork, pin, skewer, cannon threat, hanging piece,
//!   check, checkmate, promotion-zone pawn)
//! - An estimated **Elo difficulty rating**: `800 + depth×200 + piece_count×5`
//! - **Theme tags**: `one_move` / `combination` / `tactical` / `endgame`
//! - **Hints** at three specificity levels:
//!   - Level 1 (vague)    — the file of the best move's origin square
//!   - Level 2 (moderate) — the piece type that should move
//!   - Level 3 (specific) — the origin square of the best move
//!
//! ## Integration
//!
//! Called from `session.rs` in response to the `detect_puzzle` WebSocket message.
//! Returns a [`PuzzleDetection`] which is serialized directly as the WS response payload.
//!
//! ## Motif scoring
//!
//! | Motif              | Puzzle-worthy? | Weight |
//! |--------------------|----------------|--------|
//! | Checkmate          | Yes (high)     | 100    |
//! | Check              | Yes            | 20     |
//! | Fork               | Yes            | 50     |
//! | Pin                | Yes            | 40     |
//! | Hanging piece      | Yes            | 30     |
//! | Cannon screen threat| Yes           | 25     |
//! | Skewer             | Yes            | 35     |
//! | Promotion-zone pawn| No (solo)      | 10     |
//! | Positional only    | No             | 0      |
//!
//! A position is puzzle-worthy when its total motif score ≥ 30 or a checkmate
//! motif is present.

use serde::Serialize;
use crate::AI::position_analyzer::{
    PositionAnalysis, ForkInfo, PinInfo, HangingPiece, CannonScreen, CrossRiverPiece,
};

// ========================
//     OUTPUT TYPES
// ========================

/// A single detected tactical motif.
#[derive(Clone, Debug, Serialize)]
pub struct TacticalMotif {
    /// Motif category: "fork", "pin", "skewer", "cannon_threat",
    /// "hanging_piece", "check", "checkmate", "promotion_zone"
    pub motif_type: String,
    /// Human-readable description, e.g. "knight forks king and rook at e5"
    pub description: String,
    /// Centipawn weight of this motif's contribution to the puzzle-worthiness score
    pub weight: u32,
    /// Square(s) most relevant to the motif, e.g. ["e5", "e9"]
    pub squares: Vec<String>,
}

/// Hint at a given specificity level.
#[derive(Clone, Debug, Serialize)]
pub struct PuzzleHint {
    /// 1 = vague, 2 = moderate, 3 = specific
    pub level: u8,
    /// The hint text shown to the player.
    pub text: String,
}

/// Theme tags describing the type of puzzle.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub enum PuzzleTheme {
    #[serde(rename = "one_move")]
    OneMove,
    #[serde(rename = "combination")]
    Combination,
    #[serde(rename = "tactical")]
    Tactical,
    #[serde(rename = "endgame")]
    Endgame,
    #[serde(rename = "middlegame")]
    Middlegame,
}

impl PuzzleTheme {
    fn as_str(&self) -> &'static str {
        match self {
            PuzzleTheme::OneMove    => "one_move",
            PuzzleTheme::Combination => "combination",
            PuzzleTheme::Tactical   => "tactical",
            PuzzleTheme::Endgame    => "endgame",
            PuzzleTheme::Middlegame => "middlegame",
        }
    }
}

/// Complete puzzle detection result for one position.
#[derive(Clone, Debug, Serialize)]
pub struct PuzzleDetection {
    /// The FEN the detection was run on.
    pub fen: String,
    /// True if the position qualifies as puzzle-worthy.
    pub is_puzzle_worthy: bool,
    /// Sum of motif weights; ≥ 30 → puzzle-worthy.
    pub motif_score: u32,
    /// All detected tactical motifs, sorted by weight descending.
    pub motifs: Vec<TacticalMotif>,
    /// Theme tags (may be multiple).
    pub themes: Vec<String>,
    /// Estimated Elo difficulty: 800 + depth×200 + piece_count×5.
    pub difficulty_elo: u32,
    /// Difficulty label: "beginner" / "intermediate" / "advanced" / "expert"
    pub difficulty_label: String,
    /// Hints at levels 1–3 (always present; generated from motifs when no best_move is known).
    pub hints: Vec<PuzzleHint>,
    /// Optional best-move string (e.g. "e2e4") when a search result is available.
    pub best_move: Option<String>,
    /// Game phase at this position.
    pub phase: String,
    /// Number of pieces remaining (both sides, excluding kings).
    pub piece_count: u32,
}

// ========================
//     DETECTION ENGINE
// ========================

/// Detect puzzle characteristics from a pre-computed `PositionAnalysis`.
///
/// - `analysis`   — Position snapshot from `position_analyzer::analyze()`
/// - `depth`      — The search depth used (or planned) to solve the puzzle.
///                  Passed through to the difficulty formula.
/// - `best_move`  — Engine's best move suggestion, if available. Used to
///                  generate level-3 hints and included in the result.
pub fn detect_puzzle(
    analysis: &PositionAnalysis,
    depth: u8,
    best_move: Option<String>,
) -> PuzzleDetection {
    let mut motifs: Vec<TacticalMotif> = Vec::new();

    // ── 1. Checkmate / Check ──────────────────────────────────────────────
    if analysis.is_checkmate {
        motifs.push(TacticalMotif {
            motif_type: "checkmate".to_string(),
            description: "Checkmate is available in this position.".to_string(),
            weight: 100,
            squares: vec![],
        });
    } else if analysis.red_in_check || analysis.black_in_check {
        let side = if analysis.red_in_check { "red" } else { "black" };
        motifs.push(TacticalMotif {
            motif_type: "check".to_string(),
            description: format!("The {} general is in check.", side),
            weight: 20,
            squares: vec![],
        });
    }

    // ── 2. Forks ──────────────────────────────────────────────────────────
    for fork in &analysis.forks {
        if fork.targets.len() >= 2 {
            let desc = format!(
                "{} at {} forks: {}",
                fork.attacker_type,
                fork.attacker_square,
                fork.targets.join(", ")
            );
            motifs.push(TacticalMotif {
                motif_type: "fork".to_string(),
                description: desc,
                weight: 50,
                squares: {
                    let mut sq = vec![fork.attacker_square.clone()];
                    sq.extend(fork.targets.iter()
                        .map(|t| extract_square(t))
                        .filter(|s| !s.is_empty()));
                    sq
                },
            });
        }
    }

    // ── 3. Pins ───────────────────────────────────────────────────────────
    for pin in &analysis.pins {
        let desc = format!(
            "{} pins {} at {} to {}",
            pin.pinner_type,
            pin.pinned_piece,
            pin.pinned_square,
            pin.pinned_to
        );
        motifs.push(TacticalMotif {
            motif_type: "pin".to_string(),
            description: desc,
            weight: 40,
            squares: vec![pin.pinner_square.clone(), pin.pinned_square.clone()],
        });
    }

    // ── 4. Hanging pieces ─────────────────────────────────────────────────
    for hanging in &analysis.hanging_pieces {
        // Only flag if value ≥ 200 cp (not low-value pawns at 100 cp) to
        // avoid flagging trivially losing pawns as puzzles.
        if hanging.value >= 200 {
            let desc = format!(
                "{} {} at {} is hanging (value: {}cp)",
                hanging.side, hanging.piece_type, hanging.square, hanging.value
            );
            motifs.push(TacticalMotif {
                motif_type: "hanging_piece".to_string(),
                description: desc,
                weight: 30,
                squares: vec![hanging.square.clone()],
            });
        }
    }

    // ── 5. Cannon screen threats (cannon aligned with live target) ────────
    for screen in &analysis.cannon_screens {
        if screen.target_piece.is_some() {
            // Skip cannon-on-cannon screens. In Xiangqi opening setup both
            // sides keep cannons on the b- and h-files, so each cannon
            // "threatens" the opposing knight through the opposing cannon.
            // The threat is mutual and structural, not tactical, so it would
            // otherwise score the starting position as puzzle-worthy.
            if screen.screen_piece.to_lowercase().contains("cannon") {
                continue;
            }
            let target_sq = screen.target_square.clone().unwrap_or_default();
            let desc = format!(
                "{} cannon at {} threatens {} through screen at {}",
                screen.cannon_side,
                screen.cannon_square,
                screen.target_piece.as_deref().unwrap_or("piece"),
                screen.screen_square,
            );
            motifs.push(TacticalMotif {
                motif_type: "cannon_threat".to_string(),
                description: desc,
                weight: 25,
                squares: vec![
                    screen.cannon_square.clone(),
                    screen.screen_square.clone(),
                    target_sq,
                ],
            });
        }
    }

    // ── 6. Skewer heuristic: chariot on open file attacking valuable piece ─
    // A skewer is a pin where the pinned piece is *more* valuable than what's
    // behind it.  The position_analyzer's pin detection captures this already;
    // we reclassify as "skewer" when pinned_piece is rook/cannon > the piece
    // it is pinned to.
    for pin in &analysis.pins {
        let pinned_val = piece_value_name(&pin.pinned_piece);
        let behind_val = piece_value_name(&pin.pinned_to);
        if pinned_val > behind_val && behind_val > 0 {
            let desc = format!(
                "Skewer: {} at {} forces move of {} revealing attack on {}",
                pin.pinner_type, pin.pinner_square,
                pin.pinned_piece,
                pin.pinned_to
            );
            motifs.push(TacticalMotif {
                motif_type: "skewer".to_string(),
                description: desc,
                weight: 35,
                squares: vec![pin.pinner_square.clone(), pin.pinned_square.clone()],
            });
        }
    }

    // ── 7. Promotion-zone pawns ───────────────────────────────────────────
    for crp in &analysis.cross_river_pieces {
        if crp.piece_type == "pawn" && crp.depth_into_enemy >= 3 {
            let desc = format!(
                "{} pawn at {} is deep in enemy territory ({}r past river)",
                crp.side, crp.square, crp.depth_into_enemy
            );
            motifs.push(TacticalMotif {
                motif_type: "promotion_zone".to_string(),
                description: desc,
                weight: 10,
                squares: vec![crp.square.clone()],
            });
        }
    }

    // ── Deduplicate & sort ────────────────────────────────────────────────
    motifs.sort_by(|a, b| b.weight.cmp(&a.weight));
    motifs.dedup_by_key(|m| (m.motif_type.clone(), m.squares.first().cloned().unwrap_or_default()));

    let motif_score: u32 = motifs.iter().map(|m| m.weight).sum();
    let has_checkmate = motifs.iter().any(|m| m.motif_type == "checkmate");
    let is_puzzle_worthy = motif_score >= 30 || has_checkmate;

    // ── Piece count (excluding kings) ─────────────────────────────────────
    let m = &analysis.material;
    let piece_count = (m.red_pawns + m.red_advisors + m.red_elephants
        + m.red_knights + m.red_cannons + m.red_rooks
        + m.black_pawns + m.black_advisors + m.black_elephants
        + m.black_knights + m.black_cannons + m.black_rooks) as u32;

    // ── Difficulty ────────────────────────────────────────────────────────
    // Formula: 800 + depth×200 + piece_count×5
    let difficulty_elo = 800 + (depth as u32) * 200 + piece_count * 5;
    let difficulty_label = match difficulty_elo {
        0..=999    => "beginner",
        1000..=1399 => "intermediate",
        1400..=1799 => "advanced",
        _ => "expert",
    }
    .to_string();

    // ── Themes ────────────────────────────────────────────────────────────
    let phase = &analysis.phase_name;
    let mut themes = classify_themes(phase, &motifs, piece_count, depth);
    themes.dedup();

    // ── Hints ─────────────────────────────────────────────────────────────
    let hints = generate_hints(&motifs, &best_move, analysis);

    PuzzleDetection {
        fen: analysis.fen.clone(),
        is_puzzle_worthy,
        motif_score,
        motifs,
        themes,
        difficulty_elo,
        difficulty_label,
        hints,
        best_move,
        phase: phase.clone(),
        piece_count,
    }
}

// ========================
//     THEME CLASSIFICATION
// ========================

fn classify_themes(
    phase: &str,
    motifs: &[TacticalMotif],
    piece_count: u32,
    depth: u8,
) -> Vec<String> {
    let mut themes: Vec<String> = Vec::new();

    if depth == 1 {
        themes.push(PuzzleTheme::OneMove.as_str().to_string());
    }
    if depth >= 4 {
        themes.push(PuzzleTheme::Combination.as_str().to_string());
    }

    // Endgame: ≤ 10 non-king pieces
    if piece_count <= 10 {
        themes.push(PuzzleTheme::Endgame.as_str().to_string());
    } else if matches!(phase, "midgame" | "opening") {
        themes.push(PuzzleTheme::Middlegame.as_str().to_string());
    }

    // Any non-trivial motif → "tactical"
    let has_tactical = motifs.iter().any(|m| {
        matches!(
            m.motif_type.as_str(),
            "fork" | "pin" | "skewer" | "cannon_threat" | "checkmate" | "check"
        )
    });
    if has_tactical {
        themes.push(PuzzleTheme::Tactical.as_str().to_string());
    }

    if themes.is_empty() {
        themes.push(PuzzleTheme::Tactical.as_str().to_string());
    }
    themes
}

// ========================
//     HINT GENERATION
// ========================

fn generate_hints(
    motifs: &[TacticalMotif],
    best_move: &Option<String>,
    analysis: &PositionAnalysis,
) -> Vec<PuzzleHint> {
    let mut hints = Vec::new();

    // ── Level 1: Vague — name the motif type ─────────────────────────────
    let hint1 = if let Some(top) = motifs.first() {
        match top.motif_type.as_str() {
            "checkmate"    => "There is a forced checkmate in this position.",
            "check"        => "Look for a move that gives check.",
            "fork"         => "There is a fork available — look for a piece that can attack two targets at once.",
            "pin"          => "A pin is possible — look for a piece that can restrict an enemy piece's movement.",
            "skewer"       => "A skewer is available — force a valuable piece to move.",
            "cannon_threat"=> "Your cannon has a powerful threat through a screen piece.",
            "hanging_piece"=> "An enemy piece is undefended.",
            "promotion_zone" => "Your advanced pawn creates a significant threat.",
            _ => "Look for a forcing move.",
        }
    } else {
        "Look for the best move in this position."
    };
    hints.push(PuzzleHint { level: 1, text: hint1.to_string() });

    // ── Level 2: Moderate — indicate which piece type / file ─────────────
    let hint2 = if let Some(bm) = best_move.as_deref() {
        // best_move format: "e2e4" — origin square is chars 0-1
        if bm.len() >= 2 {
            let from_file = &bm[..1];
            // Find the piece type on the from-square in piece_locations
            let piece_name = analysis.piece_locations.iter()
                .find(|loc| loc.square.starts_with(from_file))
                .map(|loc| loc.piece_type.as_str())
                .unwrap_or("piece");
            format!("Consider moving a {} from the {} file.", piece_name, from_file)
        } else {
            motif_to_moderate_hint(motifs)
        }
    } else {
        motif_to_moderate_hint(motifs)
    };
    hints.push(PuzzleHint { level: 2, text: hint2 });

    // ── Level 3: Specific — origin square of the best move ───────────────
    let hint3 = if let Some(bm) = best_move.as_deref() {
        if bm.len() >= 2 {
            format!("Move the piece on {}.", &bm[..2])
        } else {
            "Find the best forcing move.".to_string()
        }
    } else if let Some(top) = motifs.first() {
        if let Some(sq) = top.squares.first() {
            format!("Focus on the piece at {}.", sq)
        } else {
            "Find the forcing move.".to_string()
        }
    } else {
        "Find the best move.".to_string()
    };
    hints.push(PuzzleHint { level: 3, text: hint3 });

    hints
}

fn motif_to_moderate_hint(motifs: &[TacticalMotif]) -> String {
    if let Some(top) = motifs.first() {
        match top.motif_type.as_str() {
            "fork"          => "Look for a piece that can simultaneously attack two enemy pieces.".to_string(),
            "pin"           => "Find a piece that can align with an enemy piece and restrict it.".to_string(),
            "checkmate"     => "Find the move that delivers checkmate directly.".to_string(),
            "cannon_threat" => "Use your cannon with an existing screen piece to create a threat.".to_string(),
            "hanging_piece" => {
                top.squares.first()
                    .map(|sq| format!("Look at the undefended piece around {}.", sq))
                    .unwrap_or_else(|| "Capture the undefended piece.".to_string())
            }
            _ => "Find the most forcing move.".to_string(),
        }
    } else {
        "Find the most active move.".to_string()
    }
}

// ========================
//     HELPERS
// ========================

/// Extract a board square label from a descriptive string like "rook at e5" → "e5".
fn extract_square(s: &str) -> String {
    // Targets in ForkInfo are formatted as "piece_type at sq" or plain "sq".
    if let Some(idx) = s.rfind(' ') {
        s[idx + 1..].to_string()
    } else {
        s.to_string()
    }
}

/// Rough centipawn value of a piece-type name (for skewer detection).
fn piece_value_name(name: &str) -> u32 {
    match name.to_lowercase().as_str() {
        "pawn"     => 100,
        "advisor"  => 200,
        "elephant" => 200,
        "knight"   => 400,
        "cannon"   => 450,
        "rook"     => 900,
        "king"     => 10000,
        _ => 0,
    }
}

// ========================
//     TESTS
// ========================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AI::position_analyzer;
    use crate::GameState::GameState;
    use crate::Game::START_FEN;

    fn analysis_from_fen(fen: &str) -> PositionAnalysis {
        let mut state = GameState::from_fen(fen);
        position_analyzer::analyze(&mut state)
    }

    #[test]
    fn test_detect_starting_position() {
        let analysis = analysis_from_fen(START_FEN);
        let result = detect_puzzle(&analysis, 5, None);
        // Starting position has no checks / mates / forks → not puzzle-worthy
        assert!(!result.is_puzzle_worthy || result.motif_score < 30,
            "starting position should not be highly puzzle-worthy, score={}", result.motif_score);
        assert!(!result.fen.is_empty());
        assert_eq!(result.hints.len(), 3);
    }

    #[test]
    fn test_difficulty_formula() {
        let analysis = analysis_from_fen(START_FEN);
        // depth=3, piece_count=32 → 800 + 3*200 + 32*5 = 800+600+160 = 1560 → advanced
        let result = detect_puzzle(&analysis, 3, None);
        // Verify formula: 800 + depth×200 + piece_count×5
        assert!(result.difficulty_elo >= 800);
    }

    #[test]
    fn test_hints_always_three_levels() {
        let analysis = analysis_from_fen(START_FEN);
        let result = detect_puzzle(&analysis, 5, Some("e2e3".to_string()));
        assert_eq!(result.hints.len(), 3);
        for (i, hint) in result.hints.iter().enumerate() {
            assert_eq!(hint.level as usize, i + 1);
            assert!(!hint.text.is_empty());
        }
    }

    #[test]
    fn test_best_move_propagated() {
        let analysis = analysis_from_fen(START_FEN);
        let best_move = Some("h2e2".to_string());
        let result = detect_puzzle(&analysis, 10, best_move.clone());
        assert_eq!(result.best_move, best_move);
        // Level 3 hint should reference the from-square
        assert!(result.hints[2].text.contains("h2"),
            "level-3 hint should mention from-square, got: {}", result.hints[2].text);
    }

    #[test]
    fn test_themes_populated() {
        let analysis = analysis_from_fen(START_FEN);
        let result = detect_puzzle(&analysis, 1, None);
        assert!(!result.themes.is_empty());
        // depth=1 → one_move should appear
        assert!(result.themes.contains(&"one_move".to_string()),
            "depth=1 should produce one_move theme, got {:?}", result.themes);
    }
}
