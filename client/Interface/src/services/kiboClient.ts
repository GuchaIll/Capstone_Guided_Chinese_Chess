// Kibo trigger producer.
//
// Every End Turn that the engine accepts is classified by the Go
// coaching service (`/coach/classify-move`); the result is mapped to
// one of the eight Kibo trigger names per docs/Kibo_flow.md and posted
// to the state bridge (`/kibo/trigger`), which fans the trigger out to
// every connected Kibo viewer over `/ws/kibo`.
//
// If a move doesn't warrant a reaction (e.g. "inaccuracy", neutral
// position) the producer returns null and *nothing* is posted, so Kibo
// stays in its idle loop. Same with errors — the trigger pipeline is
// best-effort and never blocks gameplay.

import { bridgeFetch } from './bridgeClient';

/** Mirror of Kibo/src/types.ts KiboTrigger. Keep in sync. */
export type KiboTrigger =
  | 'player_win'
  | 'player_lose'
  | 'material_gain'
  | 'high_accuracy'
  | 'avoids_blunder'
  | 'optimal_move'
  | 'misses_move'
  | 'illegal_move';

export interface ClassifyMoveResult {
  classification?: string;
  centipawn_loss?: number;
  score?: number;
  score_delta?: number;
  alternatives?: unknown[];
}

const COACH_BASE = '/coach';
// score_delta swings (centipawns) above this magnitude count as a
// "major advantage" event per the Kibo flow doc.
const MATERIAL_GAIN_CP_THRESHOLD = 150;
// "good" moves with centipawn_loss below this still count as the
// high-accuracy reaction; otherwise they're neutral and Kibo stays idle.
const HIGH_ACCURACY_MAX_CP_LOSS = 30;

/** POST a trigger to the bridge. Best-effort; logs and swallows errors. */
export async function fireKiboTrigger(trigger: KiboTrigger): Promise<void> {
  try {
    const response = await bridgeFetch('/kibo/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trigger }),
    });
    if (!response.ok) {
      console.warn('[kibo] trigger POST failed', trigger, response.status);
    }
  } catch (error) {
    console.warn('[kibo] trigger POST failed', trigger, error);
  }
}

/** Ask the Go coaching service to classify a move. Returns null on error. */
export async function classifyMove(
  fenBefore: string,
  move: string,
): Promise<ClassifyMoveResult | null> {
  try {
    const response = await fetch(`${COACH_BASE}/classify-move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fen: fenBefore, move }),
    });
    if (!response.ok) return null;
    return (await response.json()) as ClassifyMoveResult;
  } catch (error) {
    console.warn('[kibo] classify-move failed', error);
    return null;
  }
}

/**
 * Pick the outcome trigger when the engine reports a terminal result.
 * Per the doc, game-outcome events have the highest priority and
 * override any move-quality trigger derived from the same submission.
 */
export function pickOutcomeTrigger(
  result: string,
  playerSide: 'red' | 'black',
): KiboTrigger | null {
  if (result === 'red_wins') return playerSide === 'red' ? 'player_win' : 'player_lose';
  if (result === 'black_wins') return playerSide === 'black' ? 'player_win' : 'player_lose';
  // 'draw', 'in_progress', and unknown values produce no trigger.
  return null;
}

/**
 * Pick a move-quality trigger from a classify-move response.
 *
 * Priority within this layer (lower-priority than outcome / illegal):
 *   1. Major advantage  — `score_delta` swings ≥ 150cp in player's favor
 *   2. Optimal move     — classification === 'brilliant'
 *   3. High accuracy    — classification === 'good' AND cp_loss < 30
 *   4. Misses move      — classification ∈ {mistake, blunder}
 *   5. (no trigger)     — inaccuracy / unrecognized → Kibo stays idle
 *
 * `avoids_blunder` would require inspecting alternatives — left for a
 * future iteration; the current heuristics already cover the common
 * cases the doc enumerates.
 */
export function pickMoveQualityTrigger(
  result: ClassifyMoveResult,
): KiboTrigger | null {
  const classification = (result.classification ?? '').toLowerCase();
  const cpLoss = result.centipawn_loss ?? 0;
  const scoreDelta = result.score_delta ?? 0;

  if (scoreDelta >= MATERIAL_GAIN_CP_THRESHOLD) {
    return 'material_gain';
  }
  if (classification === 'brilliant') return 'optimal_move';
  if (classification === 'good' && cpLoss < HIGH_ACCURACY_MAX_CP_LOSS) {
    return 'high_accuracy';
  }
  if (classification === 'mistake' || classification === 'blunder') {
    return 'misses_move';
  }
  return null;
}
