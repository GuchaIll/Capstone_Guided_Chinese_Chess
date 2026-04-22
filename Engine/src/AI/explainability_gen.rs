//! Explainability Generator — stage-aware heuristic explanations for Xiangqi moves.
//!
//! Takes two `PositionAnalysis` snapshots (before/after a move) and produces
//! a structured `ExplainabilityResult` containing:
//!
//! - Per-metric weighted deltas (Development, King Safety, Attack Potential, …)
//! - Stage-specific weighting (opening / midgame / endgame)
//! - Natural-language explanation templates mapped from metric name + sign
//! - Sorted breakdown: top positive factors ("key_factors") + negative trade-offs
//! - A one-sentence condensed summary
//!
//! ## Stage detection
//! Uses `before.phase_name`, already computed by the position analyzer:
//!   - `"opening"`  — phase_value > 0.70
//!   - `"midgame"`  — phase_value > 0.35
//!   - `"endgame"`  — phase_value ≤ 0.35
//!
//! ## Scoring convention
//! All raw metric deltas are from the **mover's perspective**:
//! positive = good for the player who just moved.
//! `MetricDelta.delta` = raw_delta × stage_weight  (rounded to 2 dp).
//!
//! ## Eval formula
//!   overall = Σ (metric_delta_i × weight_i(stage))
//!
//! Weights are higher for metrics that matter most in that stage so the
//! top-contributing factors always reflect Xiangqi-domain priorities.

use serde::Serialize;

use crate::AI::position_analyzer::PositionAnalysis;

// ========================
//     OUTPUT TYPES
// ========================

/// A single evaluated heuristic with its weighted delta and explanation template.
#[derive(Clone, Debug, Serialize)]
pub struct MetricDelta {
    /// Human-readable metric name, e.g. "Attack Potential"
    pub name: String,
    /// Weighted signed delta from mover's perspective (2 dp). Positive = improvement.
    pub delta: f32,
    /// Template explanation sentence for this metric's change.
    pub explanation: String,
}

/// Complete stage-aware explainability result for one move.
#[derive(Clone, Debug, Serialize)]
pub struct ExplainabilityResult {
    /// Detected game stage: "opening", "midgame", or "endgame"
    pub stage: String,
    /// The side that made the move: "red" or "black"
    pub mover_side: String,
    /// Sum of all weighted metric deltas
    pub overall_delta: f32,
    /// Structured summary sentence  
    pub summary: String,
    /// Condensed one-sentence explanation for the UI
    pub condensed: String,
    /// Top 1–3 positive metric contributors (sorted by delta desc)
    pub key_factors: Vec<MetricDelta>,
    /// Negative metric contributors — trade-offs the mover accepted
    pub trade_offs: Vec<MetricDelta>,
    /// Full ordered list of all non-trivial metric deltas
    pub all_metrics: Vec<MetricDelta>,
}

// ========================
//     STAGE WEIGHTS
// ========================
//
// Each stage emphasises different metrics.
//
// Opening:   high Development, King Safety, Center Control
// Midgame:   high Attack Potential, Piece Activity, Tactical Threats, Coordination
// Endgame:   high Material, Pawn Advancement, Conversion, Chariot Dominance

struct StageWeights {
    development:    f32,
    king_safety:    f32,
    center_control: f32,
    mobility:       f32,
    attack:         f32,
    activity:       f32,
    coordination:   f32,
    pawn_advance:   f32,
    tactical:       f32,
    material:       f32,
    king_activity:  f32,
    conversion:     f32,
    chariot_ctrl:   f32,
}

fn weights_for_stage(stage: &str) -> StageWeights {
    match stage {
        "opening" => StageWeights {
            development:    1.5,
            king_safety:    1.2,
            center_control: 1.0,
            mobility:       0.6,
            attack:         0.4,
            activity:       0.5,
            coordination:   0.4,
            pawn_advance:   0.3,
            tactical:       0.6,
            material:       0.8,
            king_activity:  0.2,
            conversion:     0.1,
            chariot_ctrl:   0.3,
        },
        "midgame" => StageWeights {
            development:    0.3,
            king_safety:    1.0,
            center_control: 0.4,
            mobility:       0.6,
            attack:         1.5,
            activity:       1.2,
            coordination:   1.0,
            pawn_advance:   0.8,
            tactical:       1.3,
            material:       1.0,
            king_activity:  0.3,
            conversion:     0.4,
            chariot_ctrl:   0.8,
        },
        _ => StageWeights {
            // endgame
            development:    0.1,
            king_safety:    0.8,
            center_control: 0.2,
            mobility:       0.5,
            attack:         0.8,
            activity:       0.6,
            coordination:   0.4,
            pawn_advance:   1.8,
            tactical:       0.7,
            material:       1.5,
            king_activity:  1.0,
            conversion:     1.5,
            chariot_ctrl:   1.3,
        },
    }
}

// ========================
//     HELPERS
// ========================

#[inline]
fn is_red(side: &str) -> bool {
    side == "red"
}

#[inline]
fn opponent(side: &str) -> &'static str {
    if is_red(side) { "black" } else { "red" }
}

fn round2(v: f32) -> f32 {
    (v * 100.0).round() / 100.0
}

// ========================
//     METRIC SCORERS
// ========================
//
// Each scorer returns a single float score for one side in one position.
// Delta = score_after − score_before.

/// King safety for the given side.
///   +1 per advisor, +1 per elephant, +2 × palace_integrity
///   −2 if general exposed, −0.5 per attacker adjacent to king
fn king_safety_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let ks = if is_red(side) {
        &analysis.red_king_safety
    } else {
        &analysis.black_king_safety
    };
    let base = ks.advisor_count as f32
        + ks.elephant_count as f32
        + ks.palace_integrity * 2.0;
    let penalty =
        if ks.king_exposed { 2.0 } else { 0.0 }
        + ks.attackers_near_king as f32 * 0.5;
    base - penalty
}

/// Development: activated pieces off the back rank / on central files.
///   Chariot off back rank → +1.0
///   Knight off back rank  → +0.5
///   Cannon on central file (d–f, files 3–5) → +1.0
fn development_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let back_rank: u8 = if is_red(side) { 0 } else { 9 };
    let mut score = 0.0f32;
    for loc in &analysis.piece_locations {
        if loc.side.as_str() != side {
            continue;
        }
        match loc.piece_type.as_str() {
            "rook"   => { if loc.rank != back_rank { score += 1.0; } }
            "knight" => { if loc.rank != back_rank { score += 0.5; } }
            "cannon" => { if loc.file >= 3 && loc.file <= 5 { score += 1.0; } }
            _ => {}
        }
    }
    score
}

/// Center control: cannons + crossed-river pawns on central files (d–f).
///   Cannon on central file → +2.0
///   Pawn on central file past river → +1.0
///   Pawn approaching river on central file → +0.5
fn center_control_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    // Red crosses river going up (rank 3→5+); Black going down (rank 6→4−)
    let river_rank: u8 = if is_red(side) { 5 } else { 4 };
    let mut score = 0.0f32;
    for loc in &analysis.piece_locations {
        if loc.side.as_str() != side {
            continue;
        }
        match loc.piece_type.as_str() {
            "cannon" => {
                if loc.file >= 3 && loc.file <= 5 {
                    score += 2.0;
                }
            }
            "pawn" => {
                if loc.file >= 3 && loc.file <= 5 {
                    if is_red(side) && loc.rank >= river_rank {
                        score += 1.0;
                    } else if !is_red(side) && loc.rank <= river_rank {
                        score += 1.0;
                    } else {
                        score += 0.5;
                    }
                }
            }
            _ => {}
        }
    }
    score
}

/// Mobility: raw legal move count for the given side (normalised ÷10).
fn mobility_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let raw = if is_red(side) {
        analysis.mobility.red_legal_moves
    } else {
        analysis.mobility.black_legal_moves
    };
    raw as f32 / 10.0
}

/// Attack potential: open lines to enemy general, armed cannon screens, forks.
///   Opponent in check           → +2.0
///   Cannon with live target      → +1.5
///   Rook on open file            → +1.0
///   Rook controlling enemy rank  → +2.0
///   Fork by mover                → +2.0
fn attack_potential_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let opp_in_check = if is_red(side) {
        analysis.black_in_check
    } else {
        analysis.red_in_check
    };
    let mut score = 0.0f32;
    if opp_in_check {
        score += 2.0;
    }
    for sc in &analysis.cannon_screens {
        if sc.cannon_side.as_str() == side && sc.target_piece.is_some() {
            score += 1.5;
        }
    }
    for rf in &analysis.rook_files {
        if rf.rook_side.as_str() == side {
            if rf.is_open_file  { score += 1.0; }
            if rf.controls_rank { score += 2.0; }
        }
    }
    for fork in &analysis.forks {
        if fork.attacker_side.as_str() == side && fork.targets.len() >= 2 {
            score += 2.0;
        }
    }
    score
}

/// Piece activity: crossed-river pieces, rooks on open/semi-open files.
///   Cross-river piece         → +1.5 + 0.3 × depth
///   Rook on open file         → +1.0
///   Rook on semi-open file    → +0.5
///   Passive back-rank rook/cannon → −0.4 each
fn piece_activity_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let back_rank: u8 = if is_red(side) { 0 } else { 9 };
    let mut score = 0.0f32;
    for cr in &analysis.cross_river_pieces {
        if cr.side.as_str() == side {
            score += 1.5 + cr.depth_into_enemy as f32 * 0.3;
        }
    }
    for rf in &analysis.rook_files {
        if rf.rook_side.as_str() == side {
            if rf.is_open_file       { score += 1.0; }
            else if rf.is_semi_open  { score += 0.5; }
        }
    }
    // Passive heavy pieces still on back rank
    let passive: f32 = analysis.piece_locations.iter()
        .filter(|loc| {
            loc.side.as_str() == side
                && loc.rank == back_rank
                && matches!(loc.piece_type.as_str(), "rook" | "cannon")
        })
        .count() as f32;
    score -= passive * 0.4;
    score
}

/// Coordination: cannon–screen pairs, aligned rooks, isolated-piece penalties.
///   Cannon with live target   → +1.5; just a screen → +0.8
///   Two rooks within 1 file   → +2.0
///   Own hanging piece         → −1.0 each
fn coordination_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let mut score = 0.0f32;
    for sc in &analysis.cannon_screens {
        if sc.cannon_side.as_str() == side {
            score += if sc.target_piece.is_some() { 1.5 } else { 0.8 };
        }
    }
    // Double-rook file alignment bonus
    let mut rook_files: Vec<u8> = analysis.rook_files.iter()
        .filter(|rf| rf.rook_side.as_str() == side)
        .map(|rf| rf.file)
        .collect();
    rook_files.sort_unstable();
    if rook_files.len() >= 2 {
        let gap = (rook_files[0] as i32 - rook_files[1] as i32).unsigned_abs();
        if gap <= 1 {
            score += 2.0;
        }
    }
    // Own hanging pieces = poor coordination
    let own_hanging: f32 = analysis.hanging_pieces.iter()
        .filter(|h| h.side.as_str() == side)
        .count() as f32;
    score -= own_hanging;
    score
}

/// Pawn advancement: crossed-river pawns weighted by depth.
///   Each crossed pawn → +2.0 + 0.5 × depth_into_enemy
fn pawn_advance_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    analysis.cross_river_pieces.iter()
        .filter(|cr| cr.side.as_str() == side && cr.piece_type == "pawn")
        .map(|cr| 2.0 + cr.depth_into_enemy as f32 * 0.5)
        .sum()
}

/// Tactical threats: checks, forks, pins, opponent hanging pieces.
///   Opponent in check         → +2.0
///   Fork by mover             → +1.5
///   Any pin on board          → +0.5 (rough proxy; pins hurt the pinned side)
///   Opponent hanging piece    → +1.0 each
fn tactical_threats_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let opp_in_check = if is_red(side) {
        analysis.black_in_check
    } else {
        analysis.red_in_check
    };
    let opp = opponent(side);
    let mut score = 0.0f32;
    if opp_in_check { score += 2.0; }
    for fork in &analysis.forks {
        if fork.attacker_side.as_str() == side { score += 1.5; }
    }
    score += analysis.pins.len() as f32 * 0.5;
    score += analysis.hanging_pieces.iter()
        .filter(|h| h.side.as_str() == opp)
        .count() as f32;
    score
}

/// Material advantage (centipawn balance scaled to float, mover perspective).
fn material_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let balance = analysis.material.material_balance as f32;
    if is_red(side) { balance / 100.0 } else { -balance / 100.0 }
}

/// King activity within the palace (endgame relevance).
///   Palace integrity × 0.5  
///   −0.3 per attacker near king
///   −1.0 if exposed
fn king_activity_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let ks = if is_red(side) {
        &analysis.red_king_safety
    } else {
        &analysis.black_king_safety
    };
    let mut score = ks.palace_integrity * 0.5;
    score -= ks.attackers_near_king as f32 * 0.3;
    if ks.king_exposed { score -= 1.0; }
    score + 1.0 // baseline so small improvements are visible
}

/// Conversion potential: material advantage × simplification factor.
/// Only positive if the mover is already ahead in material.
fn conversion_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    let mat_adv = material_score(analysis, side);
    if mat_adv <= 0.0 {
        return 0.0;
    }
    let m = &analysis.material;
    let total_pieces = (m.red_pawns + m.red_knights + m.red_cannons + m.red_rooks
        + m.black_pawns + m.black_knights + m.black_cannons + m.black_rooks) as f32;
    let simplification = 1.0 / (1.0 + (total_pieces).sqrt() * 0.1);
    mat_adv * simplification * 2.0
}

/// Chariot dominance: open / semi-open files and rank control.
///   Open file        → +2.0
///   Semi-open file   → +1.0
///   Controls rank    → +2.0
fn chariot_dominance_score(analysis: &PositionAnalysis, side: &str) -> f32 {
    analysis.rook_files.iter()
        .filter(|rf| rf.rook_side.as_str() == side)
        .map(|rf| {
            let file_bonus = if rf.is_open_file { 2.0 } else if rf.is_semi_open { 1.0 } else { 0.0 };
            let rank_bonus = if rf.controls_rank { 2.0 } else { 0.0 };
            file_bonus + rank_bonus
        })
        .sum()
}

// ========================
//     EXPLANATION TEMPLATES
// ========================

fn explanation(stage: &str, metric: &str, positive: bool) -> String {
    match (stage, metric, positive) {
        // ── Opening ──────────────────────────────────────────────────────────
        ("opening", "Development", true) =>
            "Your pieces are better activated; chariots and horses develop toward active squares.".into(),
        ("opening", "Development", false) =>
            "Piece development is delayed; chariots or cannons remain passive on the back rank.".into(),
        ("opening", "King Safety", true) =>
            "Your palace integrity improves with advisors and elephants guarding the general.".into(),
        ("opening", "King Safety", false) =>
            "Your palace structure weakens; the general becomes more exposed to threats.".into(),
        ("opening", "Center Control", true) =>
            "You increase influence over central files, enabling flexible future attacks.".into(),
        ("opening", "Center Control", false) =>
            "You cede central influence, limiting your attacking flexibility.".into(),
        ("opening", "Mobility", true) =>
            "Your position gains more available moves, improving overall piece coordination.".into(),
        ("opening", "Mobility", false) =>
            "Your position becomes more cramped, with fewer available moves.".into(),

        // ── Midgame ───────────────────────────────────────────────────────────
        ("midgame", "Attack Potential", true) =>
            "You open a direct line toward the opponent's general, creating immediate tactical threats.".into(),
        ("midgame", "Attack Potential", false) =>
            "Attacking pressure decreases; fewer direct threats to the opponent's general.".into(),
        ("midgame", "Piece Activity", true) =>
            "Your chariot becomes highly active on an open file, exerting pressure across the board.".into(),
        ("midgame", "Piece Activity", false) =>
            "A piece becomes less active or blocked, reducing your board influence.".into(),
        ("midgame", "Coordination", true) =>
            "Your cannon is aligned with a screen piece, enabling powerful combined attacks.".into(),
        ("midgame", "Coordination", false) =>
            "Piece coordination weakens; cannons or chariots lose effective alignment.".into(),
        ("midgame", "Pawn Advancement", true) =>
            "Your advanced pawn restricts enemy movement and supports the attack.".into(),
        ("midgame", "Pawn Advancement", false) =>
            "Pawn pressure reduces; fewer threats to restrict the opponent.".into(),
        ("midgame", "Tactical Threats", true) =>
            "You create multiple forcing moves, maintaining initiative and pressure.".into(),
        ("midgame", "Tactical Threats", false) =>
            "Tactical initiative is reduced; the opponent has more breathing room.".into(),

        // ── Endgame ───────────────────────────────────────────────────────────
        ("endgame", "Material", true) =>
            "You maintain or extend your material advantage in this simplified position.".into(),
        ("endgame", "Material", false) =>
            "Material balance shifts against you; accurate play is required.".into(),
        ("endgame", "King Activity", true) =>
            "Your general is better positioned within the palace, improving defense and coordination.".into(),
        ("endgame", "King Activity", false) =>
            "Your general is less well-positioned; defensive coverage weakens.".into(),
        ("endgame", "Pawn Advancement", true) =>
            "Your advanced pawn is difficult to stop and close to deciding the game.".into(),
        ("endgame", "Pawn Advancement", false) =>
            "Pawn progression slows; the opponent has more time to organise defense.".into(),
        ("endgame", "Conversion", true) =>
            "Simplifying favours your side; converting the advantage becomes more straightforward.".into(),
        ("endgame", "Conversion", false) =>
            "The position remains complex, making it harder to convert any advantage.".into(),
        ("endgame", "Chariot Dominance", true) =>
            "Your chariot controls key lines and restricts the opponent's general.".into(),
        ("endgame", "Chariot Dominance", false) =>
            "Your chariot loses control of key files, reducing pressure on the opponent.".into(),

        // ── Shared fallbacks ──────────────────────────────────────────────────
        (_, "King Safety", true) =>
            "Your general's defensive coverage improves.".into(),
        (_, "King Safety", false) =>
            "Your own king safety decreases; this may become relevant if the attack stalls.".into(),
        (_, "Material", true) =>
            "You gain a material edge in this phase.".into(),
        (_, "Material", false) =>
            "You sacrifice material, which requires accurate follow-up.".into(),
        (_, name, true)  => format!("{} improves, benefiting your position.", name),
        (_, name, false) => format!("{} decreases, adding some risk.", name),
    }
}

// ========================
//     NATURAL LANGUAGE BUILDERS
// ========================

fn build_summary(
    overall: f32,
    key_factors: &[MetricDelta],
    trade_offs: &[MetricDelta],
    stage: &str,
) -> String {
    let direction = if overall > 0.05 {
        "improves"
    } else if overall < -0.05 {
        "weakens"
    } else {
        "is roughly neutral"
    };
    let main_reason = key_factors
        .first()
        .map(|m| format!(" due to increased {}", m.name.to_lowercase()))
        .unwrap_or_default();
    let trade_note = trade_offs
        .first()
        .map(|m| format!(", with some cost to {}", m.name.to_lowercase()))
        .unwrap_or_default();
    format!(
        "Position {} ({:+.2}) in the {}{}{}.",
        direction, overall, stage, main_reason, trade_note
    )
}

fn build_condensed(key_factors: &[MetricDelta], trade_offs: &[MetricDelta]) -> String {
    if key_factors.is_empty() && trade_offs.is_empty() {
        return "This move has minimal positional impact.".to_string();
    }
    let pos: String = key_factors
        .iter()
        .take(2)
        .map(|m| m.explanation.trim_end_matches('.').to_string())
        .collect::<Vec<_>>()
        .join(". ");
    let neg = trade_offs
        .first()
        .map(|m| {
            let e = m.explanation.trim_end_matches('.');
            // Lowercase first char for mid-sentence insertion
            let mut chars = e.chars();
            match chars.next() {
                None => String::new(),
                Some(c) => {
                    format!(" However, {}.", c.to_lowercase().collect::<String>() + chars.as_str())
                }
            }
        })
        .unwrap_or_default();
    if pos.is_empty() {
        format!("{}{}.", trade_offs[0].explanation.trim_end_matches('.'), "")
    } else {
        format!("{}.{}", pos, neg)
    }
}

// ========================
//     PUBLIC API
// ========================

/// Generate a heuristic move explanation.
///
/// # Parameters
/// - `before`    — `PositionAnalysis` of the position *before* the move
/// - `after`     — `PositionAnalysis` of the position *after* the move
/// - `move_str`  — Move in algebraic notation, e.g. `"e2e4"` (used in summary)
///
/// # Returns
/// An [`ExplainabilityResult`] with stage-weighted metric deltas, sorted key
/// factors, trade-offs, and ready-to-display natural-language strings.
///
/// # Example
/// ```rust
/// let result = explain(&before_analysis, &after_analysis, "c3c4");
/// println!("{}", result.condensed);
/// // "You open a direct line toward the opponent's general, creating immediate
/// //  tactical threats. However, your own king safety decreases."
/// ```
pub fn explain(
    before: &PositionAnalysis,
    after: &PositionAnalysis,
    move_str: &str,
) -> ExplainabilityResult {
    let mover = before.side_to_move.as_str();
    let stage = before.phase_name.as_str();
    let w = weights_for_stage(stage);

    // ── Raw deltas (after − before, mover perspective) ────────────────────
    let dev_d    = development_score(after, mover)      - development_score(before, mover);
    let safe_d   = king_safety_score(after, mover)      - king_safety_score(before, mover);
    let ctr_d    = center_control_score(after, mover)   - center_control_score(before, mover);
    let mob_d    = mobility_score(after, mover)         - mobility_score(before, mover);
    let atk_d    = attack_potential_score(after, mover) - attack_potential_score(before, mover);
    let act_d    = piece_activity_score(after, mover)   - piece_activity_score(before, mover);
    let crd_d    = coordination_score(after, mover)     - coordination_score(before, mover);
    let pwn_d    = pawn_advance_score(after, mover)     - pawn_advance_score(before, mover);
    let tct_d    = tactical_threats_score(after, mover) - tactical_threats_score(before, mover);
    let mat_d    = material_score(after, mover)         - material_score(before, mover);
    let kact_d   = king_activity_score(after, mover)    - king_activity_score(before, mover);
    let conv_d   = conversion_score(after, mover)       - conversion_score(before, mover);
    let chr_d    = chariot_dominance_score(after, mover)- chariot_dominance_score(before, mover);

    // ── Apply stage weights and filter near-zero changes ──────────────────
    let raw: &[(&str, f32, f32)] = &[
        ("Development",      dev_d,  w.development),
        ("King Safety",      safe_d, w.king_safety),
        ("Center Control",   ctr_d,  w.center_control),
        ("Mobility",         mob_d,  w.mobility),
        ("Attack Potential", atk_d,  w.attack),
        ("Piece Activity",   act_d,  w.activity),
        ("Coordination",     crd_d,  w.coordination),
        ("Pawn Advancement", pwn_d,  w.pawn_advance),
        ("Tactical Threats", tct_d,  w.tactical),
        ("Material",         mat_d,  w.material),
        ("King Activity",    kact_d, w.king_activity),
        ("Conversion",       conv_d, w.conversion),
        ("Chariot Dominance",chr_d,  w.chariot_ctrl),
    ];

    let mut all_metrics: Vec<MetricDelta> = raw
        .iter()
        .filter(|(_, raw_delta, _)| raw_delta.abs() > 0.01)
        .map(|(name, raw_delta, weight)| {
            let weighted = round2(raw_delta * weight);
            MetricDelta {
                name: name.to_string(),
                delta: weighted,
                explanation: explanation(stage, name, *raw_delta > 0.0),
            }
        })
        .collect();

    // Sort descending by weighted delta
    all_metrics.sort_by(|a, b| {
        b.delta
            .partial_cmp(&a.delta)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let overall_delta = round2(all_metrics.iter().map(|m| m.delta).sum());

    let key_factors: Vec<MetricDelta> = all_metrics
        .iter()
        .filter(|m| m.delta > 0.0)
        .take(3)
        .cloned()
        .collect();

    let trade_offs: Vec<MetricDelta> = all_metrics
        .iter()
        .filter(|m| m.delta < 0.0)
        .cloned()
        .collect();

    let summary  = build_summary(overall_delta, &key_factors, &trade_offs, stage);
    let condensed = build_condensed(&key_factors, &trade_offs);

    // Embed the move string in the summary if non-empty
    let summary = if !move_str.is_empty() {
        format!("[{}] {}", move_str, summary)
    } else {
        summary
    };

    ExplainabilityResult {
        stage: stage.to_string(),
        mover_side: mover.to_string(),
        overall_delta,
        summary,
        condensed,
        key_factors,
        trade_offs,
        all_metrics,
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
    fn test_explain_returns_valid_stage() {
        let before = analysis_from_fen(START_FEN);
        // Use start FEN for both — delta should be near zero
        let after = analysis_from_fen(START_FEN);
        let result = explain(&before, &after, "e2e4");
        assert!(
            matches!(result.stage.as_str(), "opening" | "midgame" | "endgame"),
            "unexpected stage: {}",
            result.stage
        );
        assert_eq!(result.mover_side.as_str(), "red");
    }

    #[test]
    fn test_explain_no_change_near_zero() {
        let before = analysis_from_fen(START_FEN);
        let after  = analysis_from_fen(START_FEN);
        let result = explain(&before, &after, "");
        // No structural change → overall delta should be essentially 0
        assert!(
            result.overall_delta.abs() < 0.5,
            "expected near-zero overall delta for no-change, got {}",
            result.overall_delta
        );
    }

    #[test]
    fn test_metric_delta_fields_populated() {
        let before = analysis_from_fen(START_FEN);
        let after  = analysis_from_fen(START_FEN);
        let result = explain(&before, &after, "test");
        // Key factors and trade-offs should each have name + explanation set
        for m in result.key_factors.iter().chain(result.trade_offs.iter()) {
            assert!(!m.name.is_empty(), "metric name should not be empty");
            assert!(!m.explanation.is_empty(), "explanation should not be empty");
        }
    }

    #[test]
    fn test_condensed_not_empty() {
        let before = analysis_from_fen(START_FEN);
        let after  = analysis_from_fen(START_FEN);
        let result = explain(&before, &after, "c3c4");
        assert!(!result.condensed.is_empty());
        assert!(!result.summary.is_empty());
    }
}
