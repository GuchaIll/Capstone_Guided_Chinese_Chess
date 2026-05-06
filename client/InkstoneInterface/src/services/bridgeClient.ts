// Client-side helpers for the Inkstone BFF.
//
// All bridge / coach / dashboard traffic goes through Next.js API
// routes:
//   /api/bridge/*    → state-bridge (bearer attached server-side)
//   /api/coach/*     → go-coach
//   /api/dashboard/* → go-coach dashboard
//
// The browser never sees STATE_BRIDGE_TOKEN. Same-origin auth is
// enforced by the signed `inkstone_session` cookie issued in
// middleware.ts; fetch() forwards it automatically because it's
// same-origin and we don't override credentials.
//
// WebSockets are still opened directly to the bridge because Next 14
// App Router cannot proxy WS upgrades. The browser fetches a
// short-lived (30 s, single-use) ticket from /api/bridge/ws-ticket
// and uses it as ?token=<ticket> on the WS URL. Bridge accepts the
// ticket once and discards it.

const BRIDGE_API = '/api/bridge';

export const bridgeBase = BRIDGE_API;

export function bridgeUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${BRIDGE_API}${normalized}`;
}

export function bridgeSseUrl(path: string): string {
  return bridgeUrl(path);
}

export async function bridgeFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(bridgeUrl(path), init);
}

export async function bridgeFetchJson<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await bridgeFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Bridge ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// ── WebSocket ────────────────────────────────────────────────────────
// Resolve the direct bridge WS origin for the browser. We can't proxy
// WS through Next API routes, so the browser still opens the connection
// directly. In the standard local-demo setup, compose binds the bridge
// to 127.0.0.1:5003 and the page is served from the same host, so
// the protocol/hostname pair below resolves to ws://localhost:5003.
//
// If you front the bridge with a TLS terminator on a different host,
// set NEXT_PUBLIC_BRIDGE_WS_ORIGIN to its origin (e.g.
// `wss://bridge.example.com`). This env var only encodes a *URL*, not
// a secret, so NEXT_PUBLIC_ is appropriate.
function bridgeWsOrigin(): string {
  if (typeof globalThis.window === 'undefined') return '';
  const override = (process.env.NEXT_PUBLIC_BRIDGE_WS_ORIGIN || '').trim();
  if (override) return override.replace(/\/+$/, '');
  const wsProtocol = globalThis.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${wsProtocol}://${globalThis.location.hostname}:5003`;
}

interface WsTicketResponse {
  ticket: string;
  expires_in: number;
}

async function fetchWsTicket(): Promise<string> {
  const response = await fetch(`${BRIDGE_API}/ws-ticket`, {
    method: 'GET',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`ws-ticket failed: ${response.status}`);
  }
  const body = (await response.json()) as WsTicketResponse;
  if (!body.ticket) throw new Error('ws-ticket: empty payload');
  return body.ticket;
}

/**
 * Resolves a fully-qualified WebSocket URL with a freshly-minted ticket.
 * Tickets are single-use and expire 30 s after issue, so callers must
 * call this *immediately* before opening the WebSocket. Reconnects must
 * call it again — they do not get to reuse a previous ticket.
 */
export async function getBridgeWsUrl(path: string): Promise<string> {
  const ticket = await fetchWsTicket();
  const normalized = path.startsWith('/') ? path : `/${path}`;
  const origin = bridgeWsOrigin();
  return `${origin}${normalized}?token=${encodeURIComponent(ticket)}`;
}
