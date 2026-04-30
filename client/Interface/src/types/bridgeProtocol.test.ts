import { describe, expect, it } from 'vitest';

import { parseEngineMessage } from './bridgeProtocol';

describe('parseEngineMessage', () => {
  it('accepts move_result payloads with a null reason', () => {
    const parsed = parseEngineMessage(JSON.stringify({
      type: 'move_result',
      valid: true,
      move: 'e3e4',
      fen: 'fen-after',
      reason: null,
      result: 'in_progress',
      is_check: false,
      seq: 3,
    }));

    expect(parsed).toEqual({
      type: 'move_result',
      valid: true,
      move: 'e3e4',
      fen: 'fen-after',
      reason: null,
      result: 'in_progress',
      is_check: false,
    });
  });
});
