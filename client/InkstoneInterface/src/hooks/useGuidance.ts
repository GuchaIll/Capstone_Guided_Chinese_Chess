import { useEffect, useRef, useState } from 'react';
import { coachFetchJson } from '../services/coachClient';
import { deriveGamePhaseFromFen, squareToCoords } from '../utils/engineBoardAdapter';

export interface CoachAnalyzeResponse {
  session_id?: string;
  response?: string;
  metrics?: Record<string, unknown>;
  game_phase?: string;
  material?: Record<string, unknown> | string;
}

export interface GuidanceResult {
  summary: string;
  gamePhase?: string;
  metrics?: Record<string, unknown>;
}

export interface StructuredGuidanceMove {
  from: [number, number];
  to: [number, number];
  label: string;
  /** Move in algebraic notation, e.g. "b2e2". Useful for stable React keys. */
  move: string;
}

export interface StructuredGuidance {
  summary: string;
  gamePhase: string;
  recommendedLine: StructuredGuidanceMove[];
  highlightSquares: [number, number][];
  score: number;
  /** Monotonic key for triggering animation resets when guidance refreshes. */
  key: number;
}

interface RawStructuredGuidance {
  summary?: string;
  gamePhase?: string;
  recommendedLine?: Array<{ from?: string; to?: string; label?: string }>;
  highlightSquares?: Array<{ from?: string; to?: string }>;
  score?: number;
}

const ANALYZE_DEBOUNCE_MS = 600;
const GUIDANCE_DEBOUNCE_MS = 250;

/**
 * Fetches position-aware coaching guidance from /coach/analyze when the
 * guidance panel is open. Debounces by FEN so we don't burn cycles while
 * the user is mid-move. Returns null guidance until the first response.
 */
export function useGuidance(fen: string, enabled: boolean) {
  const [guidance, setGuidance] = useState<GuidanceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!enabled || !fen) {
      setLoading(false);
      return;
    }

    const requestId = ++requestIdRef.current;
    setGuidance(null);
    setLoading(true);
    setError(null);
    const debounce = window.setTimeout(() => {
      void coachFetchJson<CoachAnalyzeResponse>('/analyze', {
        method: 'POST',
        body: JSON.stringify({ fen, depth: 12 }),
      })
        .then((res) => {
          if (requestIdRef.current !== requestId) return;
          const summary = (res.response ?? '').toString().trim();
          if (!summary) {
            setGuidance(null);
            return;
          }
          setGuidance({
            summary,
            gamePhase: res.game_phase ?? deriveGamePhaseFromFen(fen),
            metrics: res.metrics,
          });
        })
        .catch(() => {
          if (requestIdRef.current !== requestId) return;
          setGuidance(null);
          setError('Coach guidance unavailable');
        })
        .finally(() => {
          if (requestIdRef.current !== requestId) return;
          setLoading(false);
        });
    }, ANALYZE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(debounce);
    };
  }, [fen, enabled]);

  return { guidance, loading, error };
}

/**
 * Fetches structured agent-orchestrated guidance from /coach/guidance and
 * maps the engine's algebraic squares into UI [row, col] coordinates so
 * the panel can drive board highlights directly.
 *
 * Refetches whenever `fen` changes (debounced). The returned `key` field
 * is bumped on every successful refresh so consumer animations (e.g. the
 * typewriter text reveal) can re-mount cleanly.
 */
export function useStructuredGuidance(fen: string, enabled: boolean) {
  const [guidance, setGuidance] = useState<StructuredGuidance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!enabled || !fen) {
      setLoading(false);
      return;
    }

    const requestId = ++requestIdRef.current;
    setGuidance(null);
    setLoading(true);
    setError(null);
    const debounce = window.setTimeout(() => {
      void coachFetchJson<RawStructuredGuidance>('/guidance', {
        method: 'POST',
        body: JSON.stringify({ fen }),
      })
        .then((res) => {
          if (requestIdRef.current !== requestId) return;
          const recommendedLine: StructuredGuidanceMove[] = (res.recommendedLine ?? [])
            .map((entry) => {
              if (!entry.from || !entry.to) return null;
              const fromCoords = squareToCoords(entry.from);
              const toCoords = squareToCoords(entry.to);
              if (!fromCoords || !toCoords) return null;
              return {
                from: fromCoords,
                to: toCoords,
                label: entry.label ?? `${entry.from}${entry.to}`,
                move: `${entry.from}${entry.to}`,
              };
            })
            .filter((entry): entry is StructuredGuidanceMove => entry !== null);

          const highlightSquares: [number, number][] = (res.highlightSquares ?? [])
            .flatMap((entry) => {
              const out: [number, number][] = [];
              if (entry.from) {
                const c = squareToCoords(entry.from);
                if (c) out.push(c);
              }
              if (entry.to) {
                const c = squareToCoords(entry.to);
                if (c) out.push(c);
              }
              return out;
            });

          setGuidance({
            summary: (res.summary ?? '').trim(),
            gamePhase: (res.gamePhase ?? '').trim() || deriveGamePhaseFromFen(fen),
            recommendedLine,
            highlightSquares,
            score: typeof res.score === 'number' ? res.score : 0,
            key: Date.now(),
          });
        })
        .catch(() => {
          if (requestIdRef.current !== requestId) return;
          setGuidance(null);
          setError('Structured guidance unavailable');
        })
        .finally(() => {
          if (requestIdRef.current !== requestId) return;
          setLoading(false);
        });
    }, GUIDANCE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(debounce);
    };
  }, [fen, enabled]);

  return { guidance, loading, error };
}
