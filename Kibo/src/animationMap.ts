/**
 * Kibo Animation Map
 *
 * Defines which FBX animations are triggered by each game event (KiboTrigger)
 * and provides weighted-random selection when multiple animations are valid.
 *
 * Priority order (highest first):
 *   1. Game outcome  (player_win / player_lose)
 *   2. Major advantage (material_gain)
 *   3. Move quality  (optimal_move / high_accuracy / avoids_blunder / misses_move)
 *   4. Rule violation (illegal_move)
 */

import type { FbxAnimation, KiboTrigger } from './types';

/** Each candidate has a weight (higher = more likely) */
interface WeightedAnimation {
  animation: FbxAnimation;
  weight: number;
}

/** Trigger → weighted pool of FBX animations */
const TRIGGER_MAP: Record<KiboTrigger, WeightedAnimation[]> = {
  player_win: [
    { animation: 'Cheering', weight: 1 },
  ],
  player_lose: [
    { animation: 'KnockedOut', weight: 1 },
  ],
  material_gain: [
    { animation: 'FistPump', weight: 1 },
  ],
  high_accuracy: [
    { animation: 'Cheering', weight: 1 },
  ],
  avoids_blunder: [
    { animation: 'StandingClap', weight: 1 },
    { animation: 'FistPump',     weight: 1 },
  ],
  optimal_move: [
    { animation: 'BootyDance',   weight: 1 },
    { animation: 'Dancing',      weight: 1 },
    { animation: 'NorthernSpin', weight: 1 },
  ],
  misses_move: [
    { animation: 'SittingDisbelief', weight: 1 },
    { animation: 'Crying',           weight: 1 },
  ],
  illegal_move: [
    { animation: 'Angry', weight: 1 },
  ],
};

/**
 * Pick an animation for a given trigger using weighted random selection.
 * Returns `null` if the trigger has no candidates (should not happen in practice).
 */
export function pickAnimation(trigger: KiboTrigger): FbxAnimation | null {
  const pool = TRIGGER_MAP[trigger];
  if (!pool || pool.length === 0) return null;

  const total = pool.reduce((sum, c) => sum + c.weight, 0);
  let roll = Math.random() * total;

  for (const candidate of pool) {
    roll -= candidate.weight;
    if (roll <= 0) return candidate.animation;
  }
  // Fallback (floating-point edge case)
  return pool[pool.length - 1].animation;
}
