//! AI trait and shared types for the Chinese Chess Engine.
//!
//! Defines the interface that all AI implementations (AlphaBetaMinMax, etc.)
//! must satisfy, plus the shared SearchConfig, SearchResult, and TTStats types.

use crate::Game::Move;
use crate::GameState::GameState;

// ========================
//     SEARCH CONFIG
// ========================

/// Configuration for an AI search.
#[derive(Debug, Clone)]
pub struct SearchConfig {
    /// Maximum search depth (plies).
    pub depth: u8,
    /// Enable MVV-LVA + killer moves + history heuristic.
    pub use_move_ordering: bool,
    /// Enable quiescence search (captures-only extension).
    pub use_quiescence: bool,
    /// Enable Zobrist transposition table.
    pub use_transposition_table: bool,
    /// Optional time limit in milliseconds (0 = unlimited).
    pub time_limit_ms: Option<u64>,
}

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            depth: 4,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: true,
            time_limit_ms: None,
        }
    }
}

// ========================
//     TT STATS
// ========================

/// Transposition table profiling statistics.
#[derive(Debug, Clone, Default)]
pub struct TTStats {
    pub hits: u64,
    pub cuts: u64,
    pub stores: u64,
    pub collisions: u64,
}

// ========================
//     SEARCH RESULT
// ========================

/// Result returned by an AI search.
#[derive(Debug, Clone)]
pub struct SearchResult {
    pub best_move: Option<Move>,
    pub score: i32,
    pub nodes_searched: u64,
    pub depth_reached: u8,
    pub principal_variation: Vec<Move>,
    pub tt_stats: Option<TTStats>,
}

impl SearchResult {
    /// A sentinel result when no legal moves exist.
    pub fn no_move() -> Self {
        Self {
            best_move: None,
            score: 0,
            nodes_searched: 0,
            depth_reached: 0,
            principal_variation: Vec::new(),
            tt_stats: None,
        }
    }
}

// ========================
//     AI BUILDER
// ========================

/// Builder for constructing an AI with custom SearchConfig.
pub struct AIBuilder {
    config: SearchConfig,
}

impl AIBuilder {
    pub fn new() -> Self {
        Self {
            config: SearchConfig::default(),
        }
    }

    pub fn depth(mut self, depth: u8) -> Self {
        self.config.depth = depth;
        self
    }

    pub fn move_ordering(mut self, enabled: bool) -> Self {
        self.config.use_move_ordering = enabled;
        self
    }

    pub fn quiescence(mut self, enabled: bool) -> Self {
        self.config.use_quiescence = enabled;
        self
    }

    pub fn transposition_table(mut self, enabled: bool) -> Self {
        self.config.use_transposition_table = enabled;
        self
    }

    pub fn time_limit_ms(mut self, ms: u64) -> Self {
        self.config.time_limit_ms = Some(ms);
        self
    }

    pub fn config(self) -> SearchConfig {
        self.config
    }
}

// ========================
//     AI TRAIT
// ========================

/// Trait that all AI implementations must satisfy.
pub trait AI {
    /// Generate the best move for the current position.
    fn generate_move(&mut self, state: &mut GameState) -> SearchResult;

    /// Set the search difficulty (depth).
    fn set_difficulty(&mut self, level: u8);

    /// Get the current search configuration.
    fn config(&self) -> &SearchConfig;

    /// Produce a human-readable explanation of a move.
    fn explain_move(&self, state: &GameState, mv: &Move) -> String;
}
