import { useEffect } from 'react';
import { bridgeSseUrl } from '../services/bridgeClient';
import { parseBridgeBusEvent } from '../types/bridgeProtocol';
import type { BridgeBusEvent } from '../types/bridgeProtocol';

export type { BridgeBusEvent } from '../types/bridgeProtocol';

export type BridgeEventHandler = (event: BridgeBusEvent) => void;

/**
 * Subscribes to /state/events and forwards parsed + validated payloads
 * to `onEvent`. Malformed messages are dropped at the boundary.
 *
 * EventSource auto-reconnects on disconnect, which means a permanent
 * server error (401 from bad/missing auth, 503 from misconfigured
 * bridge) would otherwise spin forever. We cap consecutive failures
 * with no intervening onopen and stop trying.
 */
const MAX_CONSECUTIVE_FAILURES = 5;

export function useBridgeEventStream(
  onEvent: BridgeEventHandler,
  enabled: boolean = true,
): void {
  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let failures = 0;
    let events: EventSource | null = null;

    const connect = () => {
      if (cancelled) return;
      events = new EventSource(bridgeSseUrl('/state/events'));
      events.onopen = () => { failures = 0; };
      events.onmessage = (raw: MessageEvent<string>) => {
        const parsed = parseBridgeBusEvent(raw.data);
        if (parsed === null) return;
        onEvent(parsed);
      };
      events.onerror = () => {
        events?.close();
        failures += 1;
        if (cancelled || failures >= MAX_CONSECUTIVE_FAILURES) {
          if (failures >= MAX_CONSECUTIVE_FAILURES) {
            console.error(
              `[useBridgeEventStream] SSE failed ${failures} times — ` +
              `giving up. Reload the page after fixing the bridge or ` +
              `the auth token.`,
            );
          }
          return;
        }
        setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      cancelled = true;
      events?.close();
    };
  }, [onEvent, enabled]);
}
