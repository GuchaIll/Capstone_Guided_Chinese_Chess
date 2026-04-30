// Shared client for the state-bridge HTTP, SSE, and WebSocket APIs.
//
// Centralizes:
//   • the bridge base URL (overridable via NEXT_PUBLIC_STATE_BRIDGE_BASE)
//   • the Bearer-token auth contract — header for fetch, ?token= query
//     parameter for EventSource and WebSocket which cannot set headers

function defaultBridgeBase(): string {
  if (typeof globalThis.window === 'undefined') return '';
  return `${globalThis.location.origin}/bridge`;
}

function defaultDirectHttpBase(): string {
  if (typeof globalThis.window === 'undefined') return '';
  return `${globalThis.location.protocol}//${globalThis.location.hostname}:5003`;
}

function defaultWsBase(): string {
  // Next's HTTP rewrites don't proxy WebSocket upgrades, so the browser
  // must connect directly to the bridge port. Compose publishes 5003 to
  // the host, so ws://<host>:5003 works in dev and prod-on-localhost.
  if (typeof globalThis.window === 'undefined') return '';
  const wsProtocol = globalThis.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${wsProtocol}://${globalThis.location.hostname}:5003`;
}

const CONFIGURED_BRIDGE_BASE = (process.env.NEXT_PUBLIC_STATE_BRIDGE_BASE || '').trim();
const RAW_BRIDGE_BASE =
  CONFIGURED_BRIDGE_BASE || defaultBridgeBase();
export const bridgeBase = RAW_BRIDGE_BASE.replace(/\/+$/, '');
const RAW_SSE_BASE =
  process.env.NEXT_PUBLIC_STATE_BRIDGE_SSE_BASE ||
  (CONFIGURED_BRIDGE_BASE.startsWith('http') ? CONFIGURED_BRIDGE_BASE : defaultDirectHttpBase());
const sseBase = RAW_SSE_BASE.replace(/\/+$/, '');
const RAW_WS_BASE =
  process.env.NEXT_PUBLIC_STATE_BRIDGE_WS_BASE || defaultWsBase();
const wsBase = RAW_WS_BASE.replace(/\/+$/, '');
export const bridgeToken = (process.env.NEXT_PUBLIC_STATE_BRIDGE_TOKEN || '').trim();

if (!bridgeToken && typeof globalThis.window !== 'undefined') {
  // Surfaced once at module load so the user gets a single clear pointer
  // instead of staring at a stream of 1006 disconnects from the bridge.
  console.warn(
    '[bridgeClient] NEXT_PUBLIC_STATE_BRIDGE_TOKEN is empty. The state ' +
    'bridge requires a Bearer token on every gated route, so HTTP calls ' +
    'will return 401 and WebSocket upgrades will be closed with 1008. ' +
    'Set the env before next build / next dev (or pass it as a docker ' +
    'build arg), e.g.:\n' +
    '  echo NEXT_PUBLIC_STATE_BRIDGE_TOKEN=<token> >> .env.local\n' +
    '  docker compose build --build-arg STATE_BRIDGE_TOKEN=<token> client',
  );
}

function appendTokenQuery(url: string): string {
  if (!bridgeToken) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}token=${encodeURIComponent(bridgeToken)}`;
}

export function bridgeUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${bridgeBase}${normalized}`;
}

export function bridgeWsUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return appendTokenQuery(`${wsBase}${normalized}`);
}

export function bridgeSseUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return appendTokenQuery(`${sseBase}${normalized}`);
}

export async function bridgeFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (bridgeToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${bridgeToken}`);
  }
  return fetch(bridgeUrl(path), { ...init, headers });
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
