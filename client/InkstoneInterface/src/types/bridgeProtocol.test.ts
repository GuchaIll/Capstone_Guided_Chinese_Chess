import { describe, expect, it } from 'vitest';

import { BridgeCaptureResultSchema, parseEngineMessage } from './bridgeProtocol';

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

describe('BridgeCaptureResultSchema', () => {
  it('accepts the full CV capture payload shape emitted by the bridge', () => {
    const parsed = BridgeCaptureResultSchema.parse({
      status: 'ok',
      fen: 'rheagaehr/9/1c5c1/s1s1s1s1s/9/4S4/S1S3S1S/1C5C1/9/RHEAGAEHR w - - 0 1',
      issues: [],
      source: 'cv',
      capture_id: 1,
      captured_at: '2026-05-01T01:19:01.669058+00:00',
      image_path: 'cv/output/http_capture.jpg',
      image_mime: 'image/jpeg',
      detections: 32,
      mapped: 32,
      assigned: 32,
      post_to_bridge: false,
    });

    expect(parsed.status).toBe('ok');
    expect(parsed.capture_id).toBe(1);
    expect(parsed.captured_at).toBe('2026-05-01T01:19:01.669058+00:00');
    expect(parsed.source).toBe('cv');
  });
});
