import { afterEach, describe, expect, it, vi } from 'vitest';

describe('bridgeSseUrl', () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_STATE_BRIDGE_BASE;
    delete process.env.NEXT_PUBLIC_STATE_BRIDGE_SSE_BASE;
    delete process.env.NEXT_PUBLIC_STATE_BRIDGE_TOKEN;
    vi.resetModules();
  });

  it('defaults to the direct bridge port instead of the Next /bridge rewrite', async () => {
    process.env.NEXT_PUBLIC_STATE_BRIDGE_TOKEN = 'integration-bridge-token';

    const { bridgeSseUrl } = await import('./bridgeClient');

    expect(bridgeSseUrl('/state/events')).toBe(
      'http://localhost:5003/state/events?token=integration-bridge-token',
    );
  });
});
