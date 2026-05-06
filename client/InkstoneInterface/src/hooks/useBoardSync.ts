import { useCallback, useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import { bridgeFetch } from '../services/bridgeClient';
import { fenPlacementsEqual, deriveMoveFromFenDiff } from '../utils/fenMoveDiff';
import {
  BridgeCaptureResultSchema,
  BridgeHealthStatusSchema,
  IsMoveLegalResponseSchema,
  MakeMoveResponseSchema,
  ValidateFenResponseSchema,
} from '../types/bridgeProtocol';
import type { BridgeCaptureResult } from '../types/bridgeProtocol';

export type { BridgeCaptureResult } from '../types/bridgeProtocol';

interface DerivedMove {
  move: string;
  from: string;
  to: string;
  piece: string;
}

export interface BoardSyncResult {
  ok: boolean;
  message: string | null;
}

const HEALTH_PROBE_INTERVAL_MS = 5_000;

// Single source of truth for the board-out-of-sync error string. Both
// `requestBoardCapture` (when the bridge can't make sense of the CV
// payload) and `validatePendingMoveWithLiveBoardCheck` (when the CV
// position disagrees with the engine view) raise this so the UI shows
// the same message regardless of which check failed.
export const BOARD_OUT_OF_SYNC_MESSAGE =
  'Board out of sync. This can be caused by a misplaced move or low CV confidence.';
export const MOVE_NOT_DETECTED_MESSAGE =
  'Live board check did not detect the move on the physical board yet.';

/**
 * Fetch from the bridge and validate the response against `schema`.
 * Bypasses the Zod check only when called with no schema (rare) so the
 * boundary stays explicit.
 */
async function fetchBridgeJson<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await bridgeFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Bridge request failed with ${response.status}`);
  }
  const raw: unknown = await response.json();
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(`Bridge ${path} returned a payload that failed validation`);
  }
  return parsed.data;
}

/**
 * Owns the CV-service health probe and the physical-board verification
 * helpers used during turn commits. Returning a small surface keeps App
 * free of the polling/timeout plumbing.
 */
export function useBoardSync(currentFen: string) {
  const [cvServiceHealthy, setCvServiceHealthy] = useState(false);
  const [liveBoardCheckEnabled, setLiveBoardCheckEnabled] = useState(false);
  const liveBoardCheckTouchedRef = useRef(false);

  // Health probe — runs every 5s and updates `cvServiceHealthy`. The user's
  // explicit toggle (via `setLiveBoardCheckEnabled`) wins over the auto-track.
  useEffect(() => {
    let cancelled = false;

    async function refreshBridgeHealth() {
      try {
        const payload = await fetchBridgeJson('/health', BridgeHealthStatusSchema);
        if (cancelled) return;
        const healthy = payload.cv_service_healthy === true;
        setCvServiceHealthy(healthy);
        if (!liveBoardCheckTouchedRef.current) {
          setLiveBoardCheckEnabled(healthy);
        }
      } catch {
        if (cancelled) return;
        setCvServiceHealthy(false);
        if (!liveBoardCheckTouchedRef.current) {
          setLiveBoardCheckEnabled(false);
        }
      }
    }

    void refreshBridgeHealth();
    const interval = window.setInterval(() => {
      void refreshBridgeHealth();
    }, HEALTH_PROBE_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const requestBoardCapture = useCallback(async (): Promise<BridgeCaptureResult> => {
    // The bridge returns:
    //   • 503 when the CV service itself is unreachable
    //       → return degraded `{fen: null}` so callers can submit anyway
    //   • 502 when CV responded but the FEN/payload is structurally invalid
    //       → throw the user-facing "Board out of sync" copy. The bridge's
    //         own message is server-internal and shouldn't reach the UI.
    //   • any other non-2xx → keep the raw error for debuggability.
    const response = await bridgeFetch('/capture', {
      method: 'POST',
      body: JSON.stringify({}),
      headers: { 'Content-Type': 'application/json' },
    });
    if (response.status === 503) {
      return { status: 'unavailable', fen: null };
    }
    if (response.status === 502) {
      throw new Error(BOARD_OUT_OF_SYNC_MESSAGE);
    }
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Bridge request failed with ${response.status}`);
    }
    const raw: unknown = await response.json();
    const parsed = BridgeCaptureResultSchema.safeParse(raw);
    if (!parsed.success) {
      console.warn('[useBoardSync] Rejected /capture payload:', parsed.error.issues, raw);
      throw new Error('Bridge /capture returned a payload that failed validation');
    }
    return parsed.data;
  }, []);

  // Cross-check the staged move with what the camera actually sees: the CV
  // FEN must validate, and applying the move on the engine's view of the
  // current FEN must produce the same placement as the camera's snapshot.
  const validatePendingMoveWithLiveBoardCheck = useCallback(async (
    moveStr: string,
    capture: BridgeCaptureResult,
  ): Promise<void> => {
    const outOfSync = BOARD_OUT_OF_SYNC_MESSAGE;

    if (!capture.fen) throw new Error(outOfSync);

    const validation = await fetchBridgeJson(
      '/engine/validate-fen',
      ValidateFenResponseSchema,
      { method: 'POST', body: JSON.stringify({ fen: capture.fen }) },
    );
    if (!validation.valid) throw new Error(outOfSync);

    const expected = await fetchBridgeJson(
      '/engine/make-move',
      MakeMoveResponseSchema,
      { method: 'POST', body: JSON.stringify({ fen: currentFen, move: moveStr }) },
    );
    if (!expected.valid || !expected.fen) {
      console.warn('[useBoardSync] Engine could not validate staged move against current FEN.', {
        currentFen,
        moveStr,
        captureFen: capture.fen,
        expected,
      });
      throw new Error(outOfSync);
    }
    if (fenPlacementsEqual(capture.fen, currentFen)) {
      console.warn('[useBoardSync] CV capture still matches the pre-move board.', {
        currentFen,
        moveStr,
        captureFen: capture.fen,
        expectedFen: expected.fen,
      });
      throw new Error(MOVE_NOT_DETECTED_MESSAGE);
    }
    if (!fenPlacementsEqual(capture.fen, expected.fen)) {
      console.warn('[useBoardSync] CV capture does not match the engine-expected post-move board.', {
        currentFen,
        moveStr,
        captureFen: capture.fen,
        expectedFen: expected.fen,
      });
      throw new Error(outOfSync);
    }
  }, [currentFen]);

  // Used in the player_idle End Turn path: derive the player's move from the
  // FEN diff between the engine's view and the camera, then ask the engine
  // to confirm legality before committing.
  const detectPhysicalMove = useCallback(async (): Promise<DerivedMove> => {
    const capture = await requestBoardCapture();
    if (!capture.fen) {
      throw new Error('No camera board position is available yet.');
    }

    const derivedMove = deriveMoveFromFenDiff(currentFen, capture.fen);
    const legality = await fetchBridgeJson(
      '/engine/is-move-legal',
      IsMoveLegalResponseSchema,
      { method: 'POST', body: JSON.stringify({ fen: currentFen, move: derivedMove.move }) },
    );
    if (!legality.legal) {
      throw new Error(`Detected physical move ${derivedMove.move} is not legal from the current position.`);
    }
    return derivedMove;
  }, [requestBoardCapture, currentFen]);

  // Used in the engine_done End Turn path. Returns ok/message so the caller
  // can distinguish "verified clean" (message: null), "degraded but advance"
  // (message: warning), and "blocked" (ok: false).
  const verifyPhysicalBoardSync = useCallback(async (): Promise<BoardSyncResult> => {
    try {
      const capture = await requestBoardCapture();
      if (!capture.fen) {
        return {
          ok: true,
          message: 'CV service unavailable; continuing without physical-board verification.',
        };
      }
      if (!fenPlacementsEqual(currentFen, capture.fen)) {
        return {
          ok: false,
          message: 'Physical board does not match the engine move yet. Mirror the engine move first.',
        };
      }
      return { ok: true, message: null };
    } catch (error) {
      console.warn('[useBoardSync] Bridge sync check failed:', error);
      return {
        ok: true,
        message: 'Bridge unavailable; continuing without physical-board verification.',
      };
    }
  }, [requestBoardCapture, currentFen]);

  const setLiveBoardCheckEnabledExplicit = useCallback((value: boolean) => {
    liveBoardCheckTouchedRef.current = true;
    setLiveBoardCheckEnabled(value);
  }, []);

  return {
    cvServiceHealthy,
    liveBoardCheckEnabled,
    setLiveBoardCheckEnabled: setLiveBoardCheckEnabledExplicit,
    requestBoardCapture,
    validatePendingMoveWithLiveBoardCheck,
    detectPhysicalMove,
    verifyPhysicalBoardSync,
    fetchBridgeJson,
  };
}
