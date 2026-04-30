// Schemas for the wire contracts between the React client and the
// state-bridge / engine. Every JSON payload that crosses a process
// boundary should pass through one of these parsers — anything that
// fails validation is logged and dropped at the boundary, never bound
// to UI state.

import { z } from 'zod';

// ── Engine WS message envelope ────────────────────────────────────────
// Sent by either the engine directly (when VITE_USE_BRIDGE_COMMANDS is
// off) or by the state-bridge when relaying engine traffic.

const StateMessage = z.object({
  type: z.literal('state'),
  fen: z.string(),
  side_to_move: z.string().optional(),
  result: z.string().optional(),
  is_check: z.boolean().optional(),
  seq: z.number().optional(),
});

const MoveResultMessage = z.object({
  type: z.literal('move_result'),
  valid: z.boolean(),
  fen: z.string().optional(),
  move: z.string().optional(),
  result: z.string().optional(),
  is_check: z.boolean().optional(),
  score: z.number().optional(),
  reason: z.string().nullable().optional(),
  command_id: z.string().optional(),
});

const LegalMovesMessage = z.object({
  type: z.literal('legal_moves'),
  square: z.string().optional(),
  targets: z.array(z.string()).default([]),
});

const SuggestionMessage = z.object({
  type: z.literal('suggestion'),
  from: z.string(),
  to: z.string(),
  score: z.number().optional(),
});

const AiMoveMessage = z.object({
  type: z.literal('ai_move'),
  move: z.string().optional(),
  fen: z.string().optional(),
  score: z.number().optional(),
  result: z.string().optional(),
  is_check: z.boolean().optional(),
});

const ErrorMessage = z.object({
  type: z.literal('error'),
  message: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
});

const EngineMessage = z.discriminatedUnion('type', [
  StateMessage,
  MoveResultMessage,
  LegalMovesMessage,
  SuggestionMessage,
  AiMoveMessage,
  ErrorMessage,
]);

export type EngineMessage = z.infer<typeof EngineMessage>;
export type EngineStateMessage = z.infer<typeof StateMessage>;
export type EngineMoveResultMessage = z.infer<typeof MoveResultMessage>;
export type EngineLegalMovesMessage = z.infer<typeof LegalMovesMessage>;
export type EngineSuggestionMessage = z.infer<typeof SuggestionMessage>;
export type EngineAiMoveMessage = z.infer<typeof AiMoveMessage>;
export type EngineErrorMessage = z.infer<typeof ErrorMessage>;

/** Parse a raw engine WS message; returns null on malformed payloads. */
export function parseEngineMessage(raw: string): EngineMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  const result = EngineMessage.safeParse(parsed);
  if (!result.success) {
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'type' in parsed &&
      typeof (parsed as { type?: unknown }).type === 'string'
    ) {
      const type = (parsed as { type: string }).type;
      const knownTypes = new Set([
        'state',
        'move_result',
        'legal_moves',
        'suggestion',
        'ai_move',
        'error',
      ]);
      if (knownTypes.has(type)) {
        console.warn(`[protocol] Rejected engine message for type "${type}":`, result.error.issues);
      }
      // Unknown but well-formed type: silently ignore. Logging unknown
      // engine message types every render would flood the console.
      return null;
    }
    console.warn('[protocol] Rejected engine message:', result.error.issues);
    return null;
  }
  return result.data;
}

// ── Bridge SSE event envelope ──────────────────────────────────────────
// Every SSE frame on /state/events arrives as { type, data, ts, seq }.
// The shape of `data` depends on `type`; the schemas below cover the
// types App and HardwarePage actually consume.

const StateSyncData = z.object({
  fen: z.string(),
  side_to_move: z.string().optional(),
  game_result: z.string().optional(),
  result: z.string().optional(),
  is_check: z.boolean().optional(),
});

const FenUpdateData = StateSyncData.extend({
  source: z.string().optional(),
});

const BestMoveData = z.object({
  from: z.string(),
  to: z.string(),
});

const MoveMadeData = z.object({
  fen: z.string().optional(),
  from: z.string().optional(),
  to: z.string().optional(),
  source: z.string().optional(),
  result: z.string().optional(),
  is_check: z.boolean().optional(),
  score: z.number().optional(),
});

const BridgeBusEnvelope = z.object({
  type: z.string(),
  data: z.record(z.string(), z.unknown()).default({}),
  ts: z.number().optional(),
  seq: z.number().nullable().optional(),
});

export type BridgeBusEvent = z.infer<typeof BridgeBusEnvelope>;
export type BridgeStateSyncData = z.infer<typeof StateSyncData>;
export type BridgeFenUpdateData = z.infer<typeof FenUpdateData>;
export type BridgeBestMoveData = z.infer<typeof BestMoveData>;
export type BridgeMoveMadeData = z.infer<typeof MoveMadeData>;

/** Parse a raw SSE message body; returns null on malformed payloads. */
export function parseBridgeBusEvent(raw: string): BridgeBusEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  const result = BridgeBusEnvelope.safeParse(parsed);
  if (!result.success) {
    console.warn('[protocol] Rejected SSE event:', result.error.issues);
    return null;
  }
  return result.data;
}

/**
 * Narrow + validate the `data` payload of an SSE event. Returns the
 * typed shape on success or null when the payload doesn't match what
 * the consumer needs (e.g. fen_update without a fen string).
 */
export function asStateSyncData(event: BridgeBusEvent): BridgeStateSyncData | null {
  const result = StateSyncData.safeParse(event.data);
  return result.success ? result.data : null;
}

export function asFenUpdateData(event: BridgeBusEvent): BridgeFenUpdateData | null {
  const result = FenUpdateData.safeParse(event.data);
  return result.success ? result.data : null;
}

export function asBestMoveData(event: BridgeBusEvent): BridgeBestMoveData | null {
  const result = BestMoveData.safeParse(event.data);
  return result.success ? result.data : null;
}

export function asMoveMadeData(event: BridgeBusEvent): BridgeMoveMadeData | null {
  const result = MoveMadeData.safeParse(event.data);
  return result.success ? result.data : null;
}

// ── Bridge HTTP response shapes ────────────────────────────────────────

export const BridgeCaptureResultSchema = z.object({
  status: z.string(),
  fen: z.string().nullable(),
  issues: z.array(z.string()).optional(),
  image_base64: z.string().nullable().optional(),
  image_mime: z.string().nullable().optional(),
  image_path: z.string().nullable().optional(),
});
export type BridgeCaptureResult = z.infer<typeof BridgeCaptureResultSchema>;

export const BridgeHealthStatusSchema = z.object({
  cv_service_healthy: z.boolean().optional(),
});
export type BridgeHealthStatus = z.infer<typeof BridgeHealthStatusSchema>;

export const ValidateFenResponseSchema = z.object({
  valid: z.boolean().optional(),
});

export const MakeMoveResponseSchema = z.object({
  valid: z.boolean().optional(),
  fen: z.string().optional(),
});

export const IsMoveLegalResponseSchema = z.object({
  legal: z.boolean(),
});
