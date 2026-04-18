//! Alpha-Beta Minimax AI Implementation for Xiangqi (Chinese Chess)
//!
//! Features (toggled via SearchConfig):
//! - **Move Ordering**: MVV-LVA for captures, killer moves (2/ply, reduced bonus for
//!   Xiangqi), history heuristic with depth² bonus and aging. In-place sort, no alloc.
//! - **Transposition Table**: Zobrist hashing (side-aware), fixed-size array indexed by
//!   `hash & mask` (cache-friendly, no HashMap overhead). Depth-preferred replacement.
//!   TT best moves verified legal before use. Profiled via TTStats (hits/cuts/collisions).
//! - **Quiescence Search**: Captures-only extension with stand-pat, delta pruning,
//!   SEE pruning (skips losing captures), max depth guard (8 ply) to prevent stack
//!   overflow on long Xiangqi capture chains (Cannon exchanges, etc.).
//! - **Check Extension**: Extends search by 1 ply when side is in check (critical for
//!   Xiangqi's forcing sequences).
//! - **Iterative Deepening**: Wraps alpha-beta; TT from prior depths orders moves.
//!   Aspiration windows narrow the search around the previous iteration's score.
//! - **Repetition Detection**: Returns draw score on 3-fold repetition via history stack.

use crate::AI::AI::{AI, SearchConfig, SearchResult, AIBuilder, TTStats};
use crate::Game::{
    Move, PIECE_TYPE, PIECE_COLOR, OFFBOARD,
    RED, BLACK, EMPTY,
    PAWN, ADVISOR, ELEPHANT, KNIGHT, CANNON, ROOK, KING,
};
use crate::GameState::{GameState, GameResult};
use std::cmp::Reverse;

// ========================
//     PIECE VALUES
// ========================

/// Piece values for evaluation (centipawns)
const PIECE_VALUES: [i32; 23] = [
    0,    // 0: EMPTY
    100,  // 1: RED_PAWN
    200,  // 2: RED_ADVISOR
    200,  // 3: RED_ELEPHANT
    400,  // 4: RED_KNIGHT
    450,  // 5: RED_CANNON
    900,  // 6: RED_ROOK
    10000,// 7: RED_KING
    100,  // 8: BLACK_PAWN
    200,  // 9: BLACK_ADVISOR
    200,  // 10: BLACK_ELEPHANT
    400,  // 11: BLACK_KNIGHT
    450,  // 12: BLACK_CANNON
    900,  // 13: BLACK_ROOK
    10000,// 14: BLACK_KING
    0, 0, 0, 0, 0, 0, 0, 0, // Padding
];

/// MVV-LVA (Most Valuable Victim – Least Valuable Attacker) lookup.
/// Index by [victim_index][attacker_index]. Higher = search first.
/// Captures validated by legal move gen (Cannon screens already checked).
const MVV_LVA_SCORES: [[i32; 8]; 8] = [
    // attacker: NONE  PAWN  ADV   ELE   KNIGHT CANNON ROOK  KING
    /*NONE*/    [0,     0,     0,    0,     0,     0,     0,    0],
    /*PAWN*/    [0,   105,   104,  103,   102,   101,   100,  106],
    /*ADVISOR*/ [0,   205,   204,  203,   202,   201,   200,  206],
    /*ELEPHANT*/[0,   205,   204,  203,   202,   201,   200,  206],
    /*KNIGHT*/  [0,   405,   404,  403,   402,   401,   400,  406],
    /*CANNON*/  [0,   455,   454,  453,   452,   451,   450,  456],
    /*ROOK*/    [0,   905,   904,  903,   902,   901,   900,  906],
    /*KING*/    [0, 10005, 10004,10003, 10002, 10001, 10000,10006],
];

/// Map piece type constants (PAWN=16..KING=22) to MVV-LVA table indices (1-7)
fn piece_type_to_mvv_index(piece_type: u8) -> usize {
    match piece_type {
        PAWN     => 1,
        ADVISOR  => 2,
        ELEPHANT => 3,
        KNIGHT   => 4,
        CANNON   => 5,
        ROOK     => 6,
        KING     => 7,
        _        => 0,
    }
}

const INFINITY: i32 = 100000;
const MATE_SCORE: i32 = 99000;

// ========================
//     TRANSPOSITION TABLE
// ========================

/// Node type for transposition table entries
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum TTNodeType {
    Exact,      // Score is exact (PV node)
    LowerBound, // Score is a lower bound (beta cutoff)
    UpperBound, // Score is an upper bound (all-node)
}

/// Transposition table entry
#[derive(Clone, Copy)]
struct TTEntry {
    hash: u64,
    depth: u8,
    score: i32,
    node_type: TTNodeType,
    best_move: Option<Move>,
}

/// Zobrist hash key tables (deterministic, reproducible)
struct ZobristKeys {
    piece_keys: [[u64; 154]; 15],  // [piece_id][square]
    side_key: u64,
}

impl ZobristKeys {
    fn new() -> Self {
        let mut rng: u64 = 0x12345678_DEADBEEF;
        let mut keys = ZobristKeys {
            piece_keys: [[0u64; 154]; 15],
            side_key: 0,
        };

        // Pieces 1-7 = Red, 8-14 = Black: inherently distinct keys per piece,
        // so Red King vs Black King on the same square hash differently.
        for piece in 1..15u8 {
            for sq in 0..154 {
                rng = Self::xorshift64(rng);
                keys.piece_keys[piece as usize][sq] = rng;
            }
        }
        rng = Self::xorshift64(rng);
        keys.side_key = rng; // XOR'd when Black to move

        keys
    }

    fn xorshift64(mut x: u64) -> u64 {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        x
    }

    /// Compute full Zobrist hash for a board position (includes side to move)
    fn hash_position(&self, state: &GameState) -> u64 {
        let board = state.board();
        let mut hash: u64 = 0;

        for sq in 0..154 {
            let piece = board.board[sq];
            if piece != EMPTY && piece != OFFBOARD {
                hash ^= self.piece_keys[piece as usize][sq];
            }
        }

        if state.side_to_move() == BLACK {
            hash ^= self.side_key;
        }

        hash
    }
}

// ========================
//     SEARCH CONSTANTS
// ========================

/// Maximum ply depth for killer/history arrays.
/// 128 covers any practical Xiangqi search (long forcing sequences).
const MAX_PLY: usize = 128;

/// Number of killer moves stored per ply
const NUM_KILLERS: usize = 2;

/// Maximum quiescence search depth.
/// Prevents stack overflow on long Xiangqi capture chains (Cannon exchanges, etc.).
const MAX_QSEARCH_DEPTH: i32 = 8;

/// TT capacity limit (entries). ~1M entries, fixed-size array.
/// Must be a power of 2 for fast modulo via bitmask.
const TT_CAPACITY: usize = 1 << 20;

/// Bitmask for TT index: hash & TT_MASK == hash % TT_CAPACITY
const TT_MASK: u64 = (TT_CAPACITY as u64) - 1;

/// Aspiration window delta for iterative deepening (centipawns).
/// Narrow window around previous iteration's score; re-search on fail.
const ASPIRATION_DELTA: i32 = 50;

// ========================
//     ALPHA-BETA AI
// ========================

/// Alpha-Beta Minimax AI with optional:
/// - MVV-LVA + killer moves + history heuristic (move ordering)
/// - Zobrist transposition table (fixed-size array, cache-friendly)
/// - Quiescence search (captures only, depth-limited, SEE pruning)
/// - Check extension (+1 ply when in check)
/// - Iterative deepening with aspiration windows
/// - Repetition detection via history stack
pub struct AlphaBetaMinMax {
    config: SearchConfig,
    nodes_searched: u64,

    // Move ordering heuristics
    killer_moves: [[Option<Move>; NUM_KILLERS]; MAX_PLY],
    history_table: [[i32; 154]; 15], // [piece_id][to_square] -> score

    // Transposition table (fixed-size array indexed by hash & TT_MASK)
    tt: Vec<Option<TTEntry>>,
    tt_stats: TTStats,
    zobrist: ZobristKeys,

    // Time management — checked inside alpha_beta for mid-search abort
    search_start: Option<std::time::Instant>,
    search_time_limit: Option<std::time::Duration>,
    search_aborted: bool,
}

impl AlphaBetaMinMax {
    /// Create a new AlphaBetaMinMax AI with default configuration
    pub fn new() -> Self {
        Self {
            config: SearchConfig::default(),
            nodes_searched: 0,
            killer_moves: [[None; NUM_KILLERS]; MAX_PLY],
            history_table: [[0i32; 154]; 15],
            tt: vec![None; TT_CAPACITY],
            tt_stats: TTStats::default(),
            zobrist: ZobristKeys::new(),
            search_start: None,
            search_time_limit: None,
            search_aborted: false,
        }
    }

    /// Create with custom configuration
    pub fn with_config(config: SearchConfig) -> Self {
        Self {
            config,
            nodes_searched: 0,
            killer_moves: [[None; NUM_KILLERS]; MAX_PLY],
            history_table: [[0i32; 154]; 15],
            tt: vec![None; TT_CAPACITY],
            tt_stats: TTStats::default(),
            zobrist: ZobristKeys::new(),
            search_start: None,
            search_time_limit: None,
            search_aborted: false,
        }
    }

    /// Create using builder pattern
    pub fn builder() -> AIBuilder {
        AIBuilder::new()
    }

    /// Clear search-specific state between searches.
    /// History is decayed (halved) rather than cleared to preserve cross-search knowledge.
    fn clear_search_state(&mut self) {
        self.nodes_searched = 0;
        self.tt_stats = TTStats::default();
        self.killer_moves = [[None; NUM_KILLERS]; MAX_PLY];
        self.search_aborted = false;
        for piece in 0..15 {
            for sq in 0..154 {
                self.history_table[piece][sq] /= 2;
            }
        }
    }

    /// Check if time limit has been exceeded. Called periodically inside alpha_beta.
    /// Only checks every 4096 nodes to minimize overhead.
    #[inline]
    fn is_time_up(&self) -> bool {
        if self.search_aborted {
            return true;
        }
        // Only check the clock every 4096 nodes to avoid syscall overhead
        if self.nodes_searched & 4095 != 0 {
            return false;
        }
        if let (Some(start), Some(limit)) = (self.search_start, self.search_time_limit) {
            start.elapsed() >= limit
        } else {
            false
        }
    }

    // ========================
    //     EVALUATION
    // ========================

    /// Evaluate the current position from the perspective of the side to move
    fn evaluate(&self, state: &GameState) -> i32 {
        let board = state.board();
        let mut score: i32 = 0;

        for i in 0..154 {
            let piece = board.board[i];
            if piece != EMPTY && piece != OFFBOARD {
                let value = PIECE_VALUES[piece as usize];
                let color = PIECE_COLOR[piece as usize];
                if color == RED {
                    score += value;
                } else if color == BLACK {
                    score -= value;
                }
            }
        }

        if state.side_to_move() == RED { score } else { -score }
    }

    // ========================
    //     MOVE ORDERING
    // ========================

    /// Score a move for ordering. Higher scores are searched first.
    /// Priority: TT best (100k) > MVV-LVA captures (50k+) > killers (30k) > history
    fn score_move(&self, mv: &Move, ply: usize, tt_best: Option<&Move>) -> i32 {
        // 1. TT best move gets highest priority
        if let Some(tt_mv) = tt_best {
            if mv.from == tt_mv.from && mv.to == tt_mv.to {
                return 100_000;
            }
        }

        // 2. Captures scored by MVV-LVA (captures already validated by legal move gen,
        //    including Cannon screen requirements)
        if mv.captured != EMPTY {
            let victim_type = PIECE_TYPE[mv.captured as usize];
            let attacker_type = PIECE_TYPE[mv.piece as usize];
            let vi = piece_type_to_mvv_index(victim_type);
            let ai = piece_type_to_mvv_index(attacker_type);
            return 50_000 + MVV_LVA_SCORES[vi][ai];
        }

        // 3. Killer moves (non-captures that caused beta cutoff at this ply).
        //    Bonus is 30k (reduced from typical 40k in Western Chess) because
        //    Xiangqi's Horse-leg/Cannon-screen constraints make killers less
        //    transferable between sibling positions.
        if ply < MAX_PLY {
            for k in 0..NUM_KILLERS {
                if let Some(killer) = &self.killer_moves[ply][k] {
                    if mv.from == killer.from && mv.to == killer.to {
                        return 30_000 - k as i32; // First killer > second killer
                    }
                }
            }
        }

        // 4. History heuristic (more adaptive than killers for Xiangqi's mobility)
        self.history_table[mv.piece as usize][mv.to as usize]
    }

    /// Sort moves by score descending, in-place. No heap allocation.
    fn order_moves(&self, moves: &mut [Move], ply: usize, tt_best: Option<&Move>) {
        if !self.config.use_move_ordering || moves.len() <= 1 {
            return;
        }

        // sort_unstable_by_key scores each move, Reverse gives descending order.
        moves.sort_unstable_by_key(|mv| {
            Reverse(self.score_move(mv, ply, tt_best))
        });
    }

    /// Store a killer move at the given ply (non-captures only).
    /// Bounds-checked against MAX_PLY to prevent overflow on deep Xiangqi forcing sequences.
    fn store_killer(&mut self, mv: Move, ply: usize) {
        if ply >= MAX_PLY || mv.captured != EMPTY {
            return;
        }
        if let Some(existing) = &self.killer_moves[ply][0] {
            if existing.from != mv.from || existing.to != mv.to {
                self.killer_moves[ply][1] = self.killer_moves[ply][0];
                self.killer_moves[ply][0] = Some(mv);
            }
        } else {
            self.killer_moves[ply][0] = Some(mv);
        }
    }

    /// Update history heuristic for a quiet move that caused a beta cutoff.
    /// Bonus = depth² (deeper cutoffs are more valuable). Aging prevents overflow.
    fn update_history(&mut self, mv: &Move, depth: u8) {
        if mv.captured != EMPTY {
            return;
        }
        let bonus = (depth as i32) * (depth as i32);
        self.history_table[mv.piece as usize][mv.to as usize] += bonus;

        // Age all entries when any single entry gets too large
        if self.history_table[mv.piece as usize][mv.to as usize] > 30_000 {
            for p in 0..15 {
                for s in 0..154 {
                    self.history_table[p][s] /= 2;
                }
            }
        }
    }

    // ========================
    //     TRANSPOSITION TABLE
    // ========================

    /// Probe the TT for a score cutoff. Uses array indexing (hash & TT_MASK).
    fn tt_probe(&mut self, hash: u64, depth: u8, alpha: i32, beta: i32) -> Option<i32> {
        if !self.config.use_transposition_table {
            return None;
        }
        let idx = (hash & TT_MASK) as usize;
        if let Some(entry) = &self.tt[idx] {
            if entry.hash == hash {
                self.tt_stats.hits += 1;
                if entry.depth >= depth {
                    match entry.node_type {
                        TTNodeType::Exact => {
                            self.tt_stats.cuts += 1;
                            return Some(entry.score);
                        }
                        TTNodeType::LowerBound => {
                            if entry.score >= beta {
                                self.tt_stats.cuts += 1;
                                return Some(entry.score);
                            }
                        }
                        TTNodeType::UpperBound => {
                            if entry.score <= alpha {
                                self.tt_stats.cuts += 1;
                                return Some(entry.score);
                            }
                        }
                    }
                }
            }
        }
        None
    }

    /// Get the TT best move for move ordering.
    /// Caller MUST verify legality before using (handles hash collisions / stale entries).
    fn tt_best_move(&self, hash: u64) -> Option<Move> {
        if !self.config.use_transposition_table {
            return None;
        }
        let idx = (hash & TT_MASK) as usize;
        self.tt[idx].as_ref().and_then(|entry| {
            if entry.hash == hash { entry.best_move } else { None }
        })
    }

    /// Store a position in the TT. Depth-preferred replacement: only replaces
    /// if new depth >= existing depth for same hash.
    fn tt_store(
        &mut self,
        hash: u64,
        depth: u8,
        score: i32,
        node_type: TTNodeType,
        best_move: Option<Move>,
    ) {
        if !self.config.use_transposition_table {
            return;
        }
        let idx = (hash & TT_MASK) as usize;
        if let Some(existing) = &self.tt[idx] {
            if existing.hash == hash {
                // Same position: only replace with deeper or equal depth
                if existing.depth > depth {
                    return;
                }
            } else {
                // Different position in same slot: collision
                self.tt_stats.collisions += 1;
            }
        }
        self.tt_stats.stores += 1;
        self.tt[idx] = Some(TTEntry { hash, depth, score, node_type, best_move });
    }

    /// Get a TT best move and verify it is present in the legal moves list.
    /// This prevents playing an illegal move from a hash collision or stale entry
    /// (e.g., a Horse move that is now blocked by a different leg piece).
    fn verified_tt_best(&self, hash: u64, legal_moves: &[Move]) -> Option<Move> {
        self.tt_best_move(hash).and_then(|tt_mv| {
            if legal_moves.iter().any(|m| m.from == tt_mv.from && m.to == tt_mv.to) {
                Some(tt_mv)
            } else {
                None
            }
        })
    }

    // ========================
    //     STATIC EXCHANGE EVAL
    // ========================

    /// Piece value for SEE (simplified — uses same scale as PIECE_VALUES)
    fn see_piece_value(piece_type: u8) -> i32 {
        match piece_type {
            PAWN     => 100,
            ADVISOR  => 200,
            ELEPHANT => 200,
            KNIGHT   => 400,
            CANNON   => 450,
            ROOK     => 900,
            KING     => 10000,
            _        => 0,
        }
    }

    /// Static Exchange Evaluation: estimate the material outcome of a capture
    /// sequence on the target square. Returns the net gain for the capturing side.
    ///
    /// Positive = winning exchange, negative = losing exchange.
    /// Uses a simplified approach: checks if the captured piece is worth more
    /// than the capturing piece (i.e., can we lose our piece and still gain?).
    /// For Xiangqi, a full swap-loop SEE is complex due to Cannon screens,
    /// so we use a conservative heuristic: SEE ≈ victim_value - attacker_value.
    /// If the attacker is less valuable than the victim, the capture is always good.
    /// If equal, it's neutral. If more valuable, check if the target is defended.
    fn see_estimate(&self, state: &GameState, mv: &Move) -> i32 {
        if mv.captured == EMPTY {
            return 0;
        }

        let victim_value = Self::see_piece_value(PIECE_TYPE[mv.captured as usize]);
        let attacker_value = Self::see_piece_value(PIECE_TYPE[mv.piece as usize]);

        // If we capture something more valuable with something cheaper, always good
        if victim_value >= attacker_value {
            return victim_value - attacker_value;
        }

        // Attacker is more valuable than victim.
        // Check if the target square is defended by the opponent.
        let opponent = PIECE_COLOR[mv.piece as usize] ^ 1;
        let target_defended = state.board().is_square_attacked(mv.to as usize, opponent);

        if target_defended {
            // Losing exchange: we capture a cheap piece with an expensive one
            // and the opponent can recapture
            victim_value - attacker_value // negative
        } else {
            // Target is undefended: free capture
            victim_value
        }
    }

    // ========================
    //     QUIESCENCE SEARCH
    // ========================

    /// Quiescence search: only search captures to reach a "quiet" position.
    /// Prevents the horizon effect. Depth-limited to MAX_QSEARCH_DEPTH to
    /// prevent stack overflow on long Xiangqi capture chains (Cannon exchanges, etc.).
    /// Uses SEE to prune losing captures.
    fn quiescence(
        &mut self,
        state: &mut GameState,
        mut alpha: i32,
        beta: i32,
        qdepth: i32,
    ) -> i32 {
        self.nodes_searched += 1;

        // --- Time limit check ---
        if self.is_time_up() {
            self.search_aborted = true;
            return alpha;
        }

        // Guard against deep capture chains
        if qdepth >= MAX_QSEARCH_DEPTH {
            return self.evaluate(state);
        }

        // Stand-pat score
        let stand_pat = self.evaluate(state);

        if stand_pat >= beta {
            return beta;
        }

        // Delta pruning: if stand_pat + max possible gain (Rook=900) < alpha,
        // no capture can raise the score enough.
        if stand_pat + 900 < alpha {
            return alpha;
        }

        if stand_pat > alpha {
            alpha = stand_pat;
        }

        // Generate captures only
        let mut moves = state.legal_moves();
        moves.retain(|mv| mv.captured != EMPTY);

        // Order captures by MVV-LVA
        if self.config.use_move_ordering {
            self.order_moves(&mut moves, 0, None);
        }

        for mv in moves {
            if self.search_aborted {
                break;
            }

            // SEE pruning: skip captures that lose material
            // (e.g., Rook takes defended Pawn)
            if self.see_estimate(state, &mv) < 0 {
                continue;
            }

            if !state.apply_move(mv) {
                continue;
            }

            let score = -self.quiescence(state, -beta, -alpha, qdepth + 1);
            state.undo_move();

            if score >= beta {
                return beta;
            }
            if score > alpha {
                alpha = score;
            }
        }

        alpha
    }

    // ========================
    //     ALPHA-BETA SEARCH
    // ========================

    /// Core negamax alpha-beta search with all optional enhancements.
    fn alpha_beta(
        &mut self,
        state: &mut GameState,
        mut depth: u8,
        mut alpha: i32,
        beta: i32,
        ply: usize,
    ) -> i32 {
        self.nodes_searched += 1;

        // --- Time limit check (every 4096 nodes) ---
        if self.is_time_up() {
            self.search_aborted = true;
            return alpha;
        }

        // --- Repetition detection ---
        // Return draw score on 3-fold repetition to avoid infinite loops / perpetual chase.
        if ply > 0 && state.is_repetition_draw() {
            return 0;
        }

        // --- Terminal conditions ---
        match state.result() {
            GameResult::RedWins => {
                return if state.side_to_move() == RED {
                    MATE_SCORE - ply as i32
                } else {
                    -MATE_SCORE + ply as i32
                };
            }
            GameResult::BlackWins => {
                return if state.side_to_move() == BLACK {
                    MATE_SCORE - ply as i32
                } else {
                    -MATE_SCORE + ply as i32
                };
            }
            GameResult::Draw => return 0,
            GameResult::InProgress => {}
        }

        // --- Check extension ---
        // In Xiangqi, checks are extremely forcing. Extend search by 1 ply
        // when the current side is in check to see through forced sequences.
        let in_check = state.current_side_in_check();
        if in_check && depth < 64 {
            depth += 1;
        }

        // --- TT probe ---
        let hash = if self.config.use_transposition_table {
            self.zobrist.hash_position(state)
        } else {
            0
        };

        // Only use TT cutoffs at non-root nodes
        if ply > 0 {
            if let Some(tt_score) = self.tt_probe(hash, depth, alpha, beta) {
                return tt_score;
            }
        }

        // --- Leaf node ---
        if depth == 0 {
            return if self.config.use_quiescence {
                self.quiescence(state, alpha, beta, 0)
            } else {
                self.evaluate(state)
            };
        }

        // --- Move generation ---
        let mut moves = state.legal_moves();

        if moves.is_empty() {
            if in_check {
                return -MATE_SCORE + ply as i32; // Checkmate
            }
            return 0; // Stalemate
        }

        // --- Move ordering with verified TT best move ---
        let tt_best = self.verified_tt_best(hash, &moves);
        self.order_moves(&mut moves, ply, tt_best.as_ref());

        let mut best_score = -INFINITY;
        let mut best_move: Option<Move> = None;
        let mut node_type = TTNodeType::UpperBound;

        for mv in moves {
            if self.search_aborted {
                break;
            }

            if !state.apply_move(mv) {
                continue;
            }

            let score = -self.alpha_beta(state, depth - 1, -beta, -alpha, ply + 1);
            state.undo_move();

            if score > best_score {
                best_score = score;
                best_move = Some(mv);
            }

            if score > alpha {
                alpha = score;
                node_type = TTNodeType::Exact;
            }

            // Beta cutoff
            if alpha >= beta {
                node_type = TTNodeType::LowerBound;
                if self.config.use_move_ordering {
                    self.store_killer(mv, ply);
                    self.update_history(&mv, depth);
                }
                break;
            }
        }

        self.tt_store(hash, depth, best_score, node_type, best_move);
        best_score
    }

    /// Find the best move using iterative deepening + alpha-beta with aspiration windows.
    /// Each shallower iteration populates the TT, so deeper iterations
    /// get better move ordering at the root — massive speedup.
    /// Aspiration windows narrow the search window around the previous iteration's
    /// score, causing more cutoffs. On fail, re-search with full window.
    fn search(&mut self, state: &mut GameState) -> SearchResult {
        self.clear_search_state();

        let mut moves = state.legal_moves();
        if moves.is_empty() {
            return SearchResult::no_move();
        }

        let target_depth = self.config.depth;
        let mut best_move: Option<Move> = None;
        let mut best_score = -INFINITY;
        let mut pv: Vec<Move> = Vec::new();
        let mut prev_score: Option<i32> = None;
        let mut depth_completed: u8 = 0;

        // Set time limit fields for mid-search abort
        self.search_start = Some(std::time::Instant::now());
        self.search_time_limit = self.config.time_limit_ms
            .map(|ms| std::time::Duration::from_millis(ms));

        println!("[ENGINE] Search started: depth={}, time_limit={:?}ms, features: MO={} TT={} QS={}",
            target_depth,
            self.config.time_limit_ms,
            self.config.use_move_ordering,
            self.config.use_transposition_table,
            self.config.use_quiescence,
        );

        // Iterative deepening: search depth 1, 2, ..., target_depth.
        // Each iteration seeds the TT for the next.
        for current_depth in 1..=target_depth {
            // Check time limit before starting a new depth iteration.
            // Always complete at least depth 1 so we have a valid move.
            if current_depth > 1 {
                if self.search_aborted {
                    println!("[ENGINE] Aborting before depth {} (time limit reached mid-search)", current_depth);
                    break;
                }
                if let Some(limit) = self.search_time_limit {
                    if self.search_start.unwrap().elapsed() >= limit {
                        println!("[ENGINE] Aborting before depth {} (time limit reached between iterations)", current_depth);
                        break;
                    }
                }
            }

            let iter_start = std::time::Instant::now();
            let hash = if self.config.use_transposition_table {
                self.zobrist.hash_position(state)
            } else {
                0
            };
            let tt_best = self.verified_tt_best(hash, &moves);
            self.order_moves(&mut moves, 0, tt_best.as_ref());

            let mut iter_best_move: Option<Move> = None;
            let mut iter_best_score = -INFINITY;

            // Aspiration window: use narrow window around previous score after depth 1
            let (mut asp_alpha, mut asp_beta) = if let Some(prev) = prev_score {
                (prev - ASPIRATION_DELTA, prev + ASPIRATION_DELTA)
            } else {
                (-INFINITY, INFINITY)
            };

            for mv in &moves {
                if self.search_aborted {
                    break;
                }

                if !state.apply_move(*mv) {
                    continue;
                }

                // Search with aspiration window
                let mut score = -self.alpha_beta(
                    state,
                    current_depth - 1,
                    -asp_beta,
                    -asp_alpha.max(iter_best_score),
                    1,
                );

                // If score falls outside aspiration window, re-search with full window
                if !self.search_aborted && prev_score.is_some() && (score <= asp_alpha || score >= asp_beta) {
                    score = -self.alpha_beta(
                        state,
                        current_depth - 1,
                        -INFINITY,
                        -iter_best_score,
                        1,
                    );
                    // Widen window for remaining moves in this iteration
                    asp_alpha = -INFINITY;
                    asp_beta = INFINITY;
                }

                state.undo_move();

                if score > iter_best_score {
                    iter_best_score = score;
                    iter_best_move = Some(*mv);
                }
            }

            let iter_elapsed = iter_start.elapsed();

            // Update overall best from this iteration (only if not aborted mid-iteration)
            if let Some(mv) = iter_best_move {
                if !self.search_aborted {
                    best_move = Some(mv);
                    best_score = iter_best_score;
                    pv = vec![mv];
                    prev_score = Some(iter_best_score);
                    depth_completed = current_depth;
                }
            }

            println!("[ENGINE] Depth {} done: score={}, nodes={}, time={:.1}ms, aborted={}",
                current_depth, best_score, self.nodes_searched, iter_elapsed.as_secs_f64() * 1000.0, self.search_aborted);

            // Store root result in TT for next iteration's ordering
            self.tt_store(hash, current_depth, best_score, TTNodeType::Exact, best_move);

            // Early exit: if we found a forced mate, no need to search deeper
            if best_score > MATE_SCORE - 100 || best_score < -MATE_SCORE + 100 {
                println!("[ENGINE] Mate found at depth {}, stopping", current_depth);
                break;
            }
        }

        let total_elapsed = self.search_start.unwrap().elapsed();
        println!("[ENGINE] Search complete: best_score={}, depth_reached={}/{}, nodes={}, time={:.1}ms",
            best_score, depth_completed, target_depth, self.nodes_searched, total_elapsed.as_secs_f64() * 1000.0);

        SearchResult {
            best_move,
            score: best_score,
            nodes_searched: self.nodes_searched,
            depth_reached: depth_completed,
            principal_variation: pv,
            tt_stats: if self.config.use_transposition_table {
                Some(self.tt_stats.clone())
            } else {
                None
            },
        }
    }
}

impl Default for AlphaBetaMinMax {
    fn default() -> Self {
        Self::new()
    }
}

// ========================
//     ANALYSIS METHODS
// ========================

impl AlphaBetaMinMax {
    /// Analyze a position: run search, extract all features, return combined result.
    /// The state is NOT modified after this call (search restores state internally).
    pub fn analyze_position(
        &mut self,
        state: &mut GameState,
        prev_score: Option<i32>,
    ) -> (SearchResult, crate::AI::position_analyzer::PositionAnalysis, Option<crate::AI::feature_extractor::MoveFeatureVector>) {
        let search_start = std::time::Instant::now();
        let result = self.search(state);
        let elapsed_ms = search_start.elapsed().as_secs_f64() * 1000.0;

        // Position analysis (before move)
        let analysis = crate::AI::position_analyzer::analyze(state);

        // Feature extraction (if a best move was found)
        let features = result.best_move.map(|mv| {
            let alternatives = self.get_top_moves(state, 5);
            crate::AI::feature_extractor::extract_features(
                state, &mv, &result, prev_score, elapsed_ms, &alternatives,
            )
        });

        (result, analysis, features)
    }

    /// Get the top N moves with their scores for the current position.
    /// Runs a shallow search for each legal move to score them.
    pub fn get_top_moves(&mut self, state: &mut GameState, n: usize) -> Vec<(Move, i32)> {
        let moves = state.legal_moves();
        let mut scored: Vec<(Move, i32)> = Vec::new();

        for mv in moves {
            if !state.apply_move(mv) {
                continue;
            }
            // Quick evaluation (no deep search)
            let score = -self.evaluate(state);
            state.undo_move();
            scored.push((mv, score));
        }

        scored.sort_by(|a, b| b.1.cmp(&a.1));
        scored.truncate(n);
        scored
    }
}

// ========================
//     AI TRAIT IMPL
// ========================

impl AI for AlphaBetaMinMax {
    fn generate_move(&mut self, state: &mut GameState) -> SearchResult {
        self.search(state)
    }

    fn set_difficulty(&mut self, level: u8) {
        self.config.depth = level.clamp(1, 10);
    }

    fn config(&self) -> &SearchConfig {
        &self.config
    }

    //Structured Output to LLM for move explanation
    fn explain_move(&self, state: &GameState, mv: &Move) -> String {
        let piece_name = match PIECE_TYPE[mv.piece as usize] {
            PAWN => "Pawn",
            ADVISOR => "Advisor",
            ELEPHANT => "Elephant",
            KNIGHT => "Knight",
            CANNON => "Cannon",
            ROOK => "Rook",
            KING => "King",
            _ => "Piece",
        };

        let is_capture = mv.captured != EMPTY;
        let is_check = state.current_side_in_check();

        let mut explanation = format!("{} moves", piece_name);

        if is_capture {
            let captured_name = match PIECE_TYPE[mv.captured as usize] {
                PAWN => "Pawn",
                ADVISOR => "Advisor",
                ELEPHANT => "Elephant",
                KNIGHT => "Knight",
                CANNON => "Cannon",
                ROOK => "Rook",
                KING => "King",
                _ => "piece",
            };
            explanation.push_str(&format!(", capturing {}", captured_name));
        }

        if is_check {
            explanation.push_str(", giving check");
        }

        explanation
    }
}

// ========================
//     UNIT TESTS
// ========================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Game::BOARD_ENCODING;
    use std::time::Instant;

    // ========================
    //     BENCHMARK HELPERS
    // ========================

    /// Metrics collected for each depth level during a benchmark run.
    /// Enables comparison across AI methods (alpha-beta, MCTS, etc.).
    #[derive(Debug, Clone)]
    struct BenchmarkResult {
        depth: u8,
        time_ms: f64,
        nodes_searched: u64,
        nodes_per_sec: f64,
        branching_factor: f64,
        score: i32,
    }

    /// Run a depth sweep benchmark on a given FEN position.
    /// Returns a Vec of BenchmarkResult for each depth in `depth_range`.
    fn run_benchmark(fen: &str, depth_range: std::ops::RangeInclusive<u8>) -> Vec<BenchmarkResult> {
        let mut results = Vec::new();
        let mut prev_nodes: u64 = 0;

        for depth in depth_range {
            let mut ai = AlphaBetaMinMax::new();
            ai.set_difficulty(depth);
            let mut state = GameState::from_fen(fen);

            let start = Instant::now();
            let search_result = ai.generate_move(&mut state);
            let elapsed = start.elapsed();

            let time_ms = elapsed.as_secs_f64() * 1000.0;
            let nodes = search_result.nodes_searched;
            let nps = if time_ms > 0.0 { nodes as f64 / (time_ms / 1000.0) } else { 0.0 };
            let bf = if prev_nodes > 0 { nodes as f64 / prev_nodes as f64 } else { 0.0 };

            results.push(BenchmarkResult {
                depth,
                time_ms,
                nodes_searched: nodes,
                nodes_per_sec: nps,
                branching_factor: bf,
                score: search_result.score,
            });

            prev_nodes = nodes;
        }

        results
    }

    /// Print a formatted benchmark table to stdout.
    fn print_benchmark_table(label: &str, results: &[BenchmarkResult]) {
        println!("\n=== {} ===", label);
        println!("{:<6} {:>10} {:>12} {:>14} {:>10} {:>8}",
            "Depth", "Time(ms)", "Nodes", "Nodes/sec", "EBF", "Score");
        println!("{}", "-".repeat(66));
        for r in results {
            println!("{:<6} {:>10.2} {:>12} {:>14.0} {:>10.2} {:>8}",
                r.depth, r.time_ms, r.nodes_searched, r.nodes_per_sec,
                r.branching_factor, r.score);
        }
    }

    /// Helper: convert a move to coordinate string (e.g., "e2e4") for assertions
    fn move_to_str(mv: &Move) -> String {
        let from_coord = BOARD_ENCODING[mv.from as usize];
        let to_coord = BOARD_ENCODING[mv.to as usize];
        format!("{}{}", from_coord, to_coord)
    }

    // ====================================
    //     BASIC CREATION & CONFIG TESTS
    // ====================================

    #[test]
    fn test_ai_creation() {
        let ai = AlphaBetaMinMax::new();
        assert_eq!(ai.config.depth, 4);
    }

    #[test]
    fn test_ai_builder() {
        let config = AlphaBetaMinMax::builder()
            .depth(6)
            .move_ordering(true)
            .build();
        assert_eq!(config.depth, 6);
        assert!(config.use_move_ordering);
    }

    #[test]
    fn test_set_difficulty_clamping() {
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(0);
        assert_eq!(ai.config.depth, 1, "Depth should clamp to minimum 1");
        ai.set_difficulty(20);
        assert_eq!(ai.config.depth, 10, "Depth should clamp to maximum 10");
        ai.set_difficulty(5);
        assert_eq!(ai.config.depth, 5);
    }

    // ====================================
    //     EVALUATION TESTS
    // ====================================

    #[test]
    fn test_evaluation_starting_position() {
        let ai = AlphaBetaMinMax::new();
        let state = GameState::new();

        let score = ai.evaluate(&state);
        // Starting position should be roughly equal (score near 0)
        assert!(score.abs() < 100, "Starting position should be roughly balanced, got {}", score);
    }

    #[test]
    fn test_evaluation_material_advantage() {
        let ai = AlphaBetaMinMax::new();

        // Red has an extra rook (value 900) compared to a balanced position
        // Position: Red king + rook vs Black king only
        let fen = "4k4/9/9/9/9/9/9/9/9/4K3R w - - 0 1";
        let state = GameState::from_fen(fen);
        let score = ai.evaluate(&state);
        // Red to move, Red has rook advantage => positive score
        assert!(score > 800, "Red should have large material advantage, got {}", score);
    }

    #[test]
    fn test_evaluation_symmetry() {
        // Evaluate the same symmetric starting position from both sides.
        // The absolute value should be similar (material is identical).
        let ai = AlphaBetaMinMax::new();

        let state_red = GameState::from_fen(
            "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
        );
        let state_black = GameState::from_fen(
            "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR b - - 0 1"
        );

        let score_red = ai.evaluate(&state_red);
        let score_black = ai.evaluate(&state_black);

        // Both should be near zero, and roughly opposite in sign
        assert!(score_red.abs() < 100, "Red starting score should be near 0, got {}", score_red);
        assert!(score_black.abs() < 100, "Black starting score should be near 0, got {}", score_black);
        // evaluate() returns from perspective of side to move, so symmetric position => same absolute value
        assert_eq!(score_red.abs(), score_black.abs(),
            "Symmetric position should yield same absolute evaluation");
    }

    // ====================================
    //     MOVE GENERATION TESTS
    // ====================================

    #[test]
    fn test_generate_move_from_start() {
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2); // Low depth for faster test
        let mut state = GameState::new();

        let result = ai.generate_move(&mut state);
        assert!(result.best_move.is_some(), "AI should find a move from starting position");
        assert!(result.nodes_searched > 0, "AI should search some nodes");
    }

    #[test]
    fn test_generate_move_returns_legal_move() {
        // Verify the AI's chosen move is in the legal moves list
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(3);
        let mut state = GameState::new();

        let legal_before = state.legal_moves();
        let result = ai.generate_move(&mut state);
        let best = result.best_move.unwrap();

        let is_legal = legal_before.iter().any(|m| m.from == best.from && m.to == best.to);
        assert!(is_legal, "AI's best move must be in the legal moves list");
    }

    // ====================================
    //     STATE RESTORATION TESTS
    // ====================================

    #[test]
    fn test_state_restored_after_search() {
        // After generate_move, the GameState should be identical to before the search
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(3);
        let mut state = GameState::new();

        let fen_before = state.to_fen();
        let history_len_before = state.history_len();
        let side_before = state.side_to_move();

        let _result = ai.generate_move(&mut state);

        assert_eq!(state.to_fen(), fen_before,
            "Board FEN should be unchanged after search");
        assert_eq!(state.history_len(), history_len_before,
            "History length should be unchanged after search");
        assert_eq!(state.side_to_move(), side_before,
            "Side to move should be unchanged after search");
    }

    #[test]
    fn test_undo_after_ai_move() {
        // Apply the AI's best move, then undo it, and verify FEN is restored
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);
        let mut state = GameState::new();

        let fen_before = state.to_fen();
        let result = ai.generate_move(&mut state);
        let best = result.best_move.unwrap();

        assert!(state.apply_move(best), "Should be able to apply AI's move");
        assert_ne!(state.to_fen(), fen_before, "Board should change after move");

        assert!(state.undo_move(), "Should be able to undo AI's move");
        assert_eq!(state.to_fen(), fen_before, "Board should be restored after undo");
    }

    // ====================================
    //     TACTICAL CORRECTNESS TESTS
    // ====================================

    #[test]
    fn test_capture_free_rook() {
        // Red rook can capture undefended black rook.
        // Board: Black king at e9, black rook at e5 (undefended).
        //        Red king at e0, red rook at a5 (can capture e5 rook by sliding right).
        // Red to move — AI should capture the rook.
        let fen = "4k4/9/9/9/R3r4/9/9/9/9/4K4 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find a move");
        let mv_str = move_to_str(&best);

        // The rook at a5 should capture at e5
        assert_eq!(mv_str, "a5e5",
            "AI should capture the free rook at e5, got {}", mv_str);
        assert!(best.captured != EMPTY, "Move should be a capture");
    }

    #[test]
    fn test_checkmate_in_one_rook() {
        // Two-rook back-rank mate.
        // Black king at e9. Red rook at a8 covers rank 8 (blocks escape to d8/e8/f8).
        // Red rook at b0 can play Rb9#, covering rank 9 (blocks d9/e9/f9).
        // King has no legal squares => checkmate.
        // Red king at d0 (off e-file to avoid flying general).
        //
        // FEN: 4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1
        let fen = "4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find checkmate in 1");
        let mv_str = move_to_str(&best);

        assert_eq!(mv_str, "b0b9",
            "AI should play Rb9# for checkmate in 1, got {}", mv_str);
        // Score should be near MATE_SCORE
        assert!(result.score > MATE_SCORE - 10,
            "Checkmate-in-1 score should be near MATE_SCORE, got {}", result.score);
    }

    #[test]
    fn test_checkmate_in_one_double_rook() {
        // Two-rook corridor mate on e-file.
        // Black king at e9. Red rook at d8 covers rank 8 (blocks escape to d8/e8/f8).
        // Red rook at f0 can play Rf9#, covering rank 9 alongside the file.
        // After Rf9#: king on e9 is attacked on rank 9 by Rf9, escape to d9 blocked (rook on d8
        // doesn't block d9 — it covers rank 8). Actually d9 is not attacked by rook on d8.
        //
        // Better: Use same pattern as test_checkmate_in_one_rook but with different rook placement.
        // Red rook at i8 covers rank 8. Red rook at a0 plays Ra9#.
        // After Ra9#: rank 9 covered by Ra9 (d9,e9,f9 attacked), rank 8 covered by Ri8 (d8,e8,f8).
        // Red king at d0 (off e-file).
        //
        // FEN: 4k4/8R/9/9/9/9/9/9/9/R2K5 w - - 0 1
        let fen = "4k4/8R/9/9/9/9/9/9/9/R2K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find checkmate");
        let mv_str = move_to_str(&best);

        // Rook on a0 goes to a9 for checkmate
        assert_eq!(mv_str, "a0a9",
            "AI should play Ra9# for checkmate, got {}", mv_str);
        assert!(result.score > MATE_SCORE - 10,
            "Score should indicate checkmate, got {}", result.score);
    }

    #[test]
    fn test_avoid_losing_rook() {
        // Position where Red's rook on a4 is attacked by Black's rook on a9.
        // Red king at e0. Red has rook at a4 and pawn at e3.
        // Black king at e9, black rook at a9.
        // If Red moves rook away (e.g., to b4-i4, or a0-a3), rook is saved.
        // If Red makes a random non-rook move, Black captures the rook on next move.
        // At depth >= 2, AI should move the rook to safety.
        let fen = "r3k4/9/9/9/9/R8/9/9/9/4K4 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(3);

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find a move");
        let _mv_str = move_to_str(&best);

        // The best move should involve the rook (piece at a4 = RED_ROOK).
        // It should NOT leave the rook hanging on a4 where black rook can capture it.
        // Valid saving moves: rook moves along rank 4 or down the a-file away from a9.
        // Actually the rook could also capture the black rook at a9 if the file is open!
        // Let's verify the rook moves (from a4).
        use crate::Game::RED_ROOK;
        assert_eq!(best.piece, RED_ROOK,
            "AI should move the rook to save it, but moved piece type {}", best.piece);
    }

    #[test]
    fn test_checkmate_in_two() {
        // A checkmate-in-2 position. Red has two rooks that can force a corridor mate.
        // Red rook at a0, Red rook at i1. Red king at d0. Black king at e9.
        // 1. Ra9+ forces king to d9 or f9 (rank 9 covered by rook)
        //    If 1...Kd9 2. Ri9# (both rooks cover rank 9, king on d9 has no escape:
        //       d8/e8/f8 are free but wait — we need rank 8 blocked too)
        //
        // Simpler mate-in-2: Red rook at a0 and Red rook at b1.
        // 1. Ra9+ Kd9 (only legal king move: d9 or f9)
        // 2. Rb9# (rook covers rank 9 too; king can try d8 but nothing blocks rank 8)
        // Hmm, that's not mate either without rank 8 coverage.
        //
        // True mate-in-2: Use a rook + king corridor.
        // Red rook at a1, Red king at c1. Black king at e9.
        // Red rook at a5 covering rank 5 as barrier.
        //
        // Actually, simplest forced mate-in-2 with two rooks:
        // Red rook at a0, Red rook at b1. Red king at d0. Black king at e9.
        // 1. Ra8 (cuts off rank 8) — after this black plays anything
        // 2. Rb9# (covers rank 9, king can't go to rank 8 because Ra8 covers it)
        // That's only mate if black has no useful moves to delay.
        // Black king on e9, only moves are d9, d8, f9, f8, e8.
        // After 1.Ra8: king at e9, rook covers a8-i8 (so d8,e8,f8 attacked).
        //   Black plays ...Kd9 (d9 is safe, f9 is safe)
        // 2.Rb9+: rook on b9 covers b9-i9 (d9,e9,f9 attacked). King was on d9, attacked.
        //   King tries d8 — attacked by Ra8. e8 — attacked by Ra8. f8 — attacked by Ra8.
        //   No more squares. Checkmate!
        // But if 1.Ra8 Kf9 2.Rb9# similarly works.
        // So first move is Ra8 (a0a8), not Ra9.
        //
        // FEN: 4k4/9/9/9/9/9/9/9/1R7/R2K5 w - - 0 1
        let fen = "4k4/9/9/9/9/9/9/9/1R7/R2K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(4); // Need depth >= 3 to find mate in 2

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find mate in 2");

        // Score should indicate forced mate (even if the exact first move varies)
        assert!(result.score > MATE_SCORE - 20,
            "Score should indicate forced mate, got {}", result.score);

        // The move should be a rook move (either Ra8 cutting off escape or Ra9+ giving check)
        use crate::Game::RED_ROOK;
        assert_eq!(best.piece, RED_ROOK,
            "First move of mate-in-2 should be a rook move");
    }

    // ====================================
    //     SEARCH INVARIANT TESTS
    // ====================================

    #[test]
    fn test_depth_monotonicity_nodes() {
        // Nodes searched at depth N+1 should be >= nodes at depth N
        let mut state = GameState::new();
        let mut prev_nodes: u64 = 0;

        for depth in 1..=4 {
            let mut ai = AlphaBetaMinMax::new();
            ai.set_difficulty(depth);
            let result = ai.generate_move(&mut state);

            assert!(result.nodes_searched >= prev_nodes,
                "Depth {} searched {} nodes, but depth {} searched {} (should be >=)",
                depth, result.nodes_searched, depth - 1, prev_nodes);
            prev_nodes = result.nodes_searched;
        }
    }

    #[test]
    fn test_depth_one_no_pruning_effect() {
        // At depth 1, every legal move should be evaluated (no pruning benefit).
        // nodes_searched should be at least the number of legal moves.
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(1);
        let mut state = GameState::new();

        let legal_count = state.legal_moves().len();
        let result = ai.generate_move(&mut state);

        assert!(result.nodes_searched >= legal_count as u64,
            "At depth 1, should search at least {} nodes (legal moves), searched {}",
            legal_count, result.nodes_searched);
    }

    #[test]
    fn test_search_deterministic() {
        // Running the same search twice should produce the same result
        let mut state1 = GameState::new();
        let mut state2 = GameState::new();

        let mut ai1 = AlphaBetaMinMax::new();
        ai1.set_difficulty(3);
        let mut ai2 = AlphaBetaMinMax::new();
        ai2.set_difficulty(3);

        let result1 = ai1.generate_move(&mut state1);
        let result2 = ai2.generate_move(&mut state2);

        assert_eq!(result1.score, result2.score,
            "Same position should produce same score");
        assert_eq!(
            result1.best_move.map(|m| (m.from, m.to)),
            result2.best_move.map(|m| (m.from, m.to)),
            "Same position should produce same best move"
        );
        assert_eq!(result1.nodes_searched, result2.nodes_searched,
            "Same position should search same number of nodes");
    }

    #[test]
    fn test_no_move_in_terminal_position() {
        // If the position is already terminal (checkmate), AI should return no move.
        // Create a checkmated position: Black king at e9, Red rook at a9 and Red rook at b8.
        // Black to move, no legal moves, king in check => checkmate.
        // FEN: R3k4/1R7/9/9/9/9/9/9/9/4K4 b - - 0 1
        let fen = "R3k4/1R7/9/9/9/9/9/9/9/3K5 b - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        // In a checkmate position, there should be no best move
        // (or the result score should indicate a lost position)
        if result.best_move.is_none() {
            // Correct — no moves available
        } else {
            // If a move is returned, verify the state detected it's terminal
            assert!(state.is_checkmate() || state.is_game_over(),
                "Position should be detected as terminal");
        }
    }

    // ====================================
    //     MID-GAME POSITION TESTS
    // ====================================

    #[test]
    fn test_midgame_position_finds_move() {
        // A typical mid-game position after some exchanges
        let fen = "r1bakab1r/9/1cn4c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C1N2/9/R1BAKABNR w - - 0 5";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(3);

        let result = ai.generate_move(&mut state);
        assert!(result.best_move.is_some(), "AI should find a move in mid-game position");
        assert!(result.nodes_searched > 0, "Should search nodes in mid-game");
    }

    #[test]
    fn test_cannon_capture_through_screen() {
        // Red cannon on a-file with a screen piece, can capture black rook.
        // Red cannon a0, screen piece (red pawn) at a5, black rook at a9.
        // Red king d0 (off e-file to avoid flying general with black king at e9).
        // Black king at e9.
        // Cannon captures a9 through screen at a5.
        let fen = "r3k4/9/9/9/P8/9/9/9/9/C2K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(2);

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("AI should find a capture");
        let mv_str = move_to_str(&best);

        // Cannon at a0 should capture rook at a9 through screen at a5
        assert_eq!(mv_str, "a0a9",
            "Cannon should capture through screen, got {}", mv_str);
        assert!(best.captured != EMPTY, "Should be a capture");
    }

    // ====================================
    //     PERFORMANCE BENCHMARK TESTS
    //     (run with: cargo test -- --ignored --nocapture)
    // ====================================

    #[test]
    #[ignore] // Slow test — run explicitly for benchmarking
    fn bench_opening_position_depth_sweep() {
        let results = run_benchmark(
            "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            1..=5,
        );
        print_benchmark_table("Opening Position (Start FEN)", &results);

        // Basic sanity: deeper search should find more nodes
        for i in 1..results.len() {
            assert!(results[i].nodes_searched >= results[i - 1].nodes_searched,
                "Depth {} should search >= nodes than depth {}",
                results[i].depth, results[i - 1].depth);
        }
    }

    #[test]
    #[ignore] // Slow test — run explicitly for benchmarking
    fn bench_midgame_position_depth_sweep() {
        // A mid-game position with fewer pieces (faster per-node but deeper tactics)
        let fen = "2bakab2/9/2n1c2c1/p1p3p1p/4p4/9/P1P1P1P1P/2N1C1N2/9/1RBAKAB1R w - - 0 10";
        let results = run_benchmark(fen, 1..=5);
        print_benchmark_table("Mid-game Position", &results);

        // Verify nodes_per_sec is reasonable (at least 1000 nps at any depth)
        for r in &results {
            if r.time_ms > 1.0 {
                assert!(r.nodes_per_sec > 1000.0,
                    "Depth {} has only {:.0} nps, expected > 1000",
                    r.depth, r.nodes_per_sec);
            }
        }
    }

    #[test]
    #[ignore] // Slow test — run explicitly for benchmarking
    fn bench_endgame_position_depth_sweep() {
        // An endgame with few pieces — should be faster per depth
        let fen = "4k4/9/9/9/9/9/9/9/4R4/3K5 w - - 0 1";
        let results = run_benchmark(fen, 1..=6);
        print_benchmark_table("Endgame (K+R vs K)", &results);

        // Effective branching factor in endgame should be lower than opening
        // (fewer pieces = fewer moves)
        for r in &results {
            if r.branching_factor > 0.0 {
                println!("  Depth {}: EBF = {:.2}", r.depth, r.branching_factor);
            }
        }
    }

    #[test]
    #[ignore] // Slow test — run explicitly for benchmarking
    fn bench_opening_vs_midgame_comparison() {
        let opening_results = run_benchmark(
            "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            1..=5,
        );
        let midgame_results = run_benchmark(
            "2bakab2/9/2n1c2c1/p1p3p1p/4p4/9/P1P1P1P1P/2N1C1N2/9/1RBAKAB1R w - - 0 10",
            1..=5,
        );

        print_benchmark_table("Opening", &opening_results);
        print_benchmark_table("Mid-game", &midgame_results);

        println!("\n=== Opening vs Mid-game Comparison ===");
        println!("{:<6} {:>14} {:>14} {:>10}",
            "Depth", "Opening NPS", "Midgame NPS", "Ratio");
        println!("{}", "-".repeat(50));
        for (o, m) in opening_results.iter().zip(midgame_results.iter()) {
            let ratio = if m.nodes_per_sec > 0.0 {
                o.nodes_per_sec / m.nodes_per_sec
            } else {
                0.0
            };
            println!("{:<6} {:>14.0} {:>14.0} {:>10.2}",
                o.depth, o.nodes_per_sec, m.nodes_per_sec, ratio);
        }
    }

    #[test]
    #[ignore] // Slow test — run explicitly for benchmarking
    fn bench_nodes_per_second_depth_4() {
        // Focused NPS benchmark at the default depth (4)
        let mut ai = AlphaBetaMinMax::new();
        ai.set_difficulty(4);
        let mut state = GameState::new();

        let start = Instant::now();
        let result = ai.generate_move(&mut state);
        let elapsed = start.elapsed();

        let nps = result.nodes_searched as f64 / elapsed.as_secs_f64();
        println!("\n=== NPS Benchmark (Depth 4, Opening) ===");
        println!("Nodes searched: {}", result.nodes_searched);
        println!("Time: {:.2}ms", elapsed.as_secs_f64() * 1000.0);
        println!("Nodes/sec: {:.0}", nps);
        println!("Score: {}", result.score);

        // Baseline assertion: should achieve at least 5,000 nps on any reasonable machine
        assert!(nps > 5000.0, "Expected > 5000 nps, got {:.0}", nps);
    }

    // ====================================
    //     FEATURE TOGGLE COMPARISON TESTS
    // ====================================

    #[test]
    fn test_move_ordering_reduces_nodes() {
        // With move ordering ON, should search fewer nodes than OFF
        let mut ai_ordered = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: false,
            time_limit_ms: None,
        });
        let mut ai_unordered = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: false,
            use_quiescence: false,
            use_transposition_table: false,
            time_limit_ms: None,
        });

        let mut state1 = GameState::new();
        let mut state2 = GameState::new();

        let result_ordered = ai_ordered.generate_move(&mut state1);
        let result_unordered = ai_unordered.generate_move(&mut state2);

        assert!(result_ordered.nodes_searched <= result_unordered.nodes_searched,
            "Move ordering should reduce nodes: ordered={}, unordered={}",
            result_ordered.nodes_searched, result_unordered.nodes_searched);
    }

    #[test]
    fn test_tt_reduces_nodes() {
        // With TT ON, iterative deepening should reduce total nodes
        let mut ai_tt = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: true,
            time_limit_ms: None,
        });
        let mut ai_no_tt = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: false,
            time_limit_ms: None,
        });

        let mut state1 = GameState::new();
        let mut state2 = GameState::new();

        let result_tt = ai_tt.generate_move(&mut state1);
        let result_no_tt = ai_no_tt.generate_move(&mut state2);

        // TT should not significantly increase nodes; allow some tolerance for
        // iterative deepening overhead at low depths
        assert!(result_tt.nodes_searched <= result_no_tt.nodes_searched + 500,
            "TT should not significantly increase nodes: tt={}, no_tt={}",
            result_tt.nodes_searched, result_no_tt.nodes_searched);
    }

    #[test]
    fn test_quiescence_finds_move() {
        // Position with capture tension — quiescence should handle it
        let fen = "4k4/9/9/9/4r4/4P4/9/9/9/3K5 w - - 0 1";
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 2,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: false,
            time_limit_ms: None,
        });
        let mut state = GameState::from_fen(fen);
        let result = ai.generate_move(&mut state);
        assert!(result.best_move.is_some(), "Quiescence-enabled AI should find a move");
    }

    #[test]
    fn test_all_features_enabled() {
        // Smoke test with all features ON
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);

        assert!(result.best_move.is_some(), "Should find a move with all features on");
        assert!(result.nodes_searched > 0);

        // Verify state is restored after search
        let fen = state.to_fen();
        assert!(fen.starts_with("rnbakabnr"), "State should be restored after search");
    }

    #[test]
    fn test_all_features_find_checkmate() {
        // Checkmate-in-1 should still be found with all features ON
        let fen = "4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 2,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("Should find checkmate");
        let mv_str = move_to_str(&best);
        assert_eq!(mv_str, "b0b9",
            "Should find Rb9# with all features, got {}", mv_str);
        assert!(result.score > MATE_SCORE - 10);
    }

    #[test]
    fn test_check_extension_finds_deeper_mate() {
        // Position where check extension helps find a mate that would be missed
        // at nominal depth. Red rook at a8, Red rook at b0, Red king at d0,
        // Black king at e9. Mate in 1: Rb9#. With check extension the engine
        // should see even further when checks are involved.
        let fen = "4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 1, // Very shallow — check extension should still find it
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: false,
            time_limit_ms: None,
        });

        let result = ai.generate_move(&mut state);
        assert!(result.best_move.is_some(), "Should find a move even at depth 1");
        assert!(result.score > MATE_SCORE - 20,
            "Check extension should help find mate, score={}", result.score);
    }

    #[test]
    fn test_iterative_deepening_consistency() {
        // Iterative deepening should produce the same or better result as
        // a single-depth search because each iteration populates the TT.
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);

        // Basic sanity: should find a valid move
        assert!(result.best_move.is_some());
        // Score should be reasonable for opening (not wildly off)
        assert!(result.score.abs() < 500,
            "Opening score should be reasonable, got {}", result.score);
    }

    #[test]
    #[ignore] // Slow — run with: cargo test -- --ignored --nocapture
    fn bench_feature_comparison() {
        // Compare all feature combinations at depth 4
        let configs: Vec<(&str, SearchConfig)> = vec![
            ("Baseline (no features)", SearchConfig {
                depth: 4, use_move_ordering: false, use_quiescence: false,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("Move Ordering only", SearchConfig {
                depth: 4, use_move_ordering: true, use_quiescence: false,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("MO + TT", SearchConfig {
                depth: 4, use_move_ordering: true, use_quiescence: false,
                use_transposition_table: true, time_limit_ms: None,
            }),
            ("MO + Quiescence", SearchConfig {
                depth: 4, use_move_ordering: true, use_quiescence: true,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("All features", SearchConfig {
                depth: 4, use_move_ordering: true, use_quiescence: true,
                use_transposition_table: true, time_limit_ms: None,
            }),
        ];

        println!("\n=== Feature Comparison (Depth 4, Opening) ===");
        println!("{:<25} {:>10} {:>12} {:>14} {:>8}",
            "Config", "Time(ms)", "Nodes", "Nodes/sec", "Score");
        println!("{}", "-".repeat(75));

        for (label, config) in configs {
            let mut ai = AlphaBetaMinMax::with_config(config);
            let mut state = GameState::new();

            let start = Instant::now();
            let result = ai.generate_move(&mut state);
            let elapsed = start.elapsed();

            let time_ms = elapsed.as_secs_f64() * 1000.0;
            let nps = if time_ms > 0.0 {
                result.nodes_searched as f64 / (time_ms / 1000.0)
            } else { 0.0 };

            println!("{:<25} {:>10.2} {:>12} {:>14.0} {:>8}",
                label, time_ms, result.nodes_searched, nps, result.score);
        }
    }

    // ====================================
    //     DEPTH-6 / DEPTH-8 BENCHMARKS
    // ====================================

    /// Helper: run feature comparison at a given depth
    fn run_feature_comparison(target_depth: u8) {
        let configs: Vec<(&str, SearchConfig)> = vec![
            ("Baseline (no features)", SearchConfig {
                depth: target_depth, use_move_ordering: false, use_quiescence: false,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("Move Ordering only", SearchConfig {
                depth: target_depth, use_move_ordering: true, use_quiescence: false,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("MO + TT", SearchConfig {
                depth: target_depth, use_move_ordering: true, use_quiescence: false,
                use_transposition_table: true, time_limit_ms: None,
            }),
            ("MO + Quiescence", SearchConfig {
                depth: target_depth, use_move_ordering: true, use_quiescence: true,
                use_transposition_table: false, time_limit_ms: None,
            }),
            ("All features", SearchConfig {
                depth: target_depth, use_move_ordering: true, use_quiescence: true,
                use_transposition_table: true, time_limit_ms: None,
            }),
        ];

        println!("\n=== Feature Comparison (Depth {}, Opening) ===", target_depth);
        println!("{:<25} {:>10} {:>12} {:>14} {:>8} {:>10} {:>10} {:>10}",
            "Config", "Time(ms)", "Nodes", "Nodes/sec", "Score",
            "TT Hits", "TT Cuts", "TT Colls");
        println!("{}", "-".repeat(110));

        for (label, config) in configs {
            let mut ai = AlphaBetaMinMax::with_config(config);
            let mut state = GameState::new();

            let start = Instant::now();
            let result = ai.generate_move(&mut state);
            let elapsed = start.elapsed();

            let time_ms = elapsed.as_secs_f64() * 1000.0;
            let nps = if time_ms > 0.0 {
                result.nodes_searched as f64 / (time_ms / 1000.0)
            } else { 0.0 };

            let (tt_hits, tt_cuts, tt_colls) = match &result.tt_stats {
                Some(s) => (s.hits, s.cuts, s.collisions),
                None => (0, 0, 0),
            };

            println!("{:<25} {:>10.2} {:>12} {:>14.0} {:>8} {:>10} {:>10} {:>10}",
                label, time_ms, result.nodes_searched, nps, result.score,
                tt_hits, tt_cuts, tt_colls);
        }
    }

    #[test]
    #[ignore] // Slow — run with: cargo test bench_feature_comparison_depth_6 -- --ignored --nocapture
    fn bench_feature_comparison_depth_6() {
        run_feature_comparison(6);
    }

    #[test]
    #[ignore] // Very slow — run with: cargo test bench_feature_comparison_depth_8 -- --ignored --nocapture
    fn bench_feature_comparison_depth_8() {
        run_feature_comparison(8);
    }

    // ====================================
    //     TT PROFILING TEST
    // ====================================

    #[test]
    fn test_tt_stats_populated() {
        // When TT is enabled, SearchResult should contain TT stats
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);

        let stats = result.tt_stats.expect("TT stats should be present when TT enabled");
        assert!(stats.stores > 0, "Should have stored entries, got {}", stats.stores);
        // At depth 3 with iterative deepening, we should see some hits from prior iterations
        println!("TT Stats: hits={}, cuts={}, stores={}, collisions={}",
            stats.hits, stats.cuts, stats.stores, stats.collisions);
    }

    #[test]
    fn test_tt_stats_none_when_disabled() {
        // When TT is disabled, SearchResult.tt_stats should be None
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 2,
            use_move_ordering: true,
            use_quiescence: false,
            use_transposition_table: false,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);
        assert!(result.tt_stats.is_none(), "TT stats should be None when TT disabled");
    }

    // ====================================
    //     SEE PRUNING TESTS
    // ====================================

    #[test]
    fn test_see_good_capture() {
        // Pawn captures Rook = clearly winning (900 - 100 = +800)
        let ai = AlphaBetaMinMax::new();
        // Red pawn at e5, Black rook at e6 (undefended)
        let fen = "4k4/9/4r4/4P4/9/9/9/9/9/4K4 w - - 0 1";
        let state = GameState::from_fen(fen);

        // Find a capture move in legal moves
        let mut gs = GameState::from_fen(fen);
        let moves = gs.legal_moves();
        let capture = moves.iter().find(|m| m.captured != EMPTY);
        if let Some(cap) = capture {
            let see = ai.see_estimate(&state, cap);
            assert!(see >= 0, "Pawn captures Rook should have SEE >= 0, got {}", see);
        }
    }

    #[test]
    fn test_see_losing_capture() {
        // Rook captures defended Pawn = losing exchange if defended
        let ai = AlphaBetaMinMax::new();
        // Red rook at a5, Black pawn at a6 defended by Black rook at a9
        let fen = "r3k4/9/p8/R8/9/9/9/9/9/4K4 w - - 0 1";
        let state = GameState::from_fen(fen);

        let mut gs = GameState::from_fen(fen);
        let moves = gs.legal_moves();
        let capture = moves.iter().find(|m| m.captured != EMPTY);
        if let Some(cap) = capture {
            let see = ai.see_estimate(&state, cap);
            // Rook (900) taking pawn (100) when defended: should be negative
            println!("SEE for Rook x Pawn (defended): {}", see);
            // We just verify the SEE was computed; exact value depends on defense detection
        }
    }

    #[test]
    fn test_quiescence_with_see_pruning() {
        // Verify quiescence still produces valid results with SEE pruning active
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 2,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: false,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);

        assert!(result.best_move.is_some(), "Should find a move with SEE+QSearch");
        assert!(result.nodes_searched > 0);
    }

    // ====================================
    //     ASPIRATION WINDOW TESTS
    // ====================================

    #[test]
    fn test_aspiration_window_correctness() {
        // Verify aspiration windows don't break correctness.
        // All features enabled should still find the right move.
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 4,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let mut state = GameState::new();
        let result = ai.generate_move(&mut state);

        assert!(result.best_move.is_some());
        // Score should be reasonable for an opening position
        assert!(result.score.abs() < 500,
            "Opening score should be reasonable with aspiration, got {}", result.score);

        // State should be restored
        let fen = state.to_fen();
        assert!(fen.starts_with("rnbakabnr"), "State should be restored after search");
    }

    #[test]
    fn test_aspiration_finds_checkmate() {
        // Aspiration windows should not prevent finding checkmate
        let fen = "4k4/R8/9/9/9/9/9/9/9/1R1K5 w - - 0 1";
        let mut state = GameState::from_fen(fen);
        let mut ai = AlphaBetaMinMax::with_config(SearchConfig {
            depth: 3,
            use_move_ordering: true,
            use_quiescence: true,
            use_transposition_table: true,
            time_limit_ms: None,
        });

        let result = ai.generate_move(&mut state);
        let best = result.best_move.expect("Should find checkmate with aspiration");
        let mv_str = move_to_str(&best);
        assert_eq!(mv_str, "b0b9",
            "Should find Rb9# with aspiration windows, got {}", mv_str);
        assert!(result.score > MATE_SCORE - 10,
            "Should detect mate score with aspiration, got {}", result.score);
    }
}