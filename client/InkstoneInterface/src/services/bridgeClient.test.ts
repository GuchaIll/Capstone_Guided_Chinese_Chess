import { afterEach, describe, expect, it, vi } from 'vitest';

describe('bridgeClient (BFF)', () => {
  afterEach(() => {
    vi.resetModules();
  });

  it('routes SSE through the BFF proxy path', async () => {
    const { bridgeSseUrl } = await import('./bridgeClient');
    expect(bridgeSseUrl('/state/events')).toBe('/api/bridge/state/events');
  });

  it('routes HTTP through the BFF proxy path', async () => {
    const { bridgeUrl } = await import('./bridgeClient');
    expect(bridgeUrl('/state')).toBe('/api/bridge/state');
  });

  it('does not embed any bearer token in URLs', async () => {
    const { bridgeUrl, bridgeSseUrl } = await import('./bridgeClient');
    expect(bridgeUrl('/state')).not.toContain('token=');
    expect(bridgeSseUrl('/state/events')).not.toContain('token=');
  });
});
