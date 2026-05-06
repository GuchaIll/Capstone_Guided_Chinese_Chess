// Client-side helpers for the Go chess-coach service.
//
// All coach + dashboard traffic is proxied through Next.js BFF routes
// (lib/server/bridgeProxy.ts) which inject the real STATE_BRIDGE_TOKEN
// server-side. The browser only sees /api/coach/* and /api/dashboard/*
// and forwards the same-origin inkstone_session cookie automatically.
//
// Symmetric with bridgeClient.ts. Keep both files in lockstep when the
// proxy contract changes.

const COACH_API = '/api/coach';
const DASHBOARD_API = '/api/dashboard';

export function coachUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${COACH_API}${normalized}`;
}

export function dashboardUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${DASHBOARD_API}${normalized}`;
}

export async function coachFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(coachUrl(path), init);
}

export async function dashboardFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(dashboardUrl(path), init);
}

export async function coachFetchJson<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await coachFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Coach ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function dashboardFetchJson<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await dashboardFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Dashboard ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
