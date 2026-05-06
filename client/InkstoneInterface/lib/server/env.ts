// Server-only env accessors for the BFF.
//
// IMPORTANT: every export from this module reads `process.env` and must
// only be imported from server code (route handlers, middleware, server
// components). The variable names below are not prefixed
// NEXT_PUBLIC_, so they are stripped from the client bundle by Next.
// Calling these from a 'use client' component would yield empty values
// and the `required(...)` checks would throw at build/eval time.

function required(name: string): string {
  const value = (process.env[name] || '').trim();
  if (!value) {
    throw new Error(
      `${name} is required for the Inkstone BFF. ` +
        'Set it in the runtime environment (docker compose env or .env.local).',
    );
  }
  return value;
}

function optional(name: string, fallback: string): string {
  const value = (process.env[name] || '').trim();
  return value || fallback;
}

// State-bridge — never sent to the browser. The BFF attaches it as a
// Bearer header on every proxied request.
export const stateBridgeToken = (): string => required('STATE_BRIDGE_TOKEN');

// In-cluster URL of the state bridge. The browser hits the BFF at
// /api/bridge/...; the BFF forwards to this URL with the bearer header.
export const stateBridgeInternalUrl = (): string =>
  optional('STATE_BRIDGE_INTERNAL_URL', 'http://state-bridge:5003').replace(/\/+$/, '');

// In-cluster URL of the Go chess-coach service.
export const coachInternalUrl = (): string =>
  optional('COACH_INTERNAL_URL', 'http://go-coaching:8080').replace(/\/+$/, '');

// Cookie-signing secret for the BFF session. A 32+ byte random value.
// The session cookie itself is HMAC(secret, sessionId) so a stolen
// cookie can't be forged without the secret.
export const sessionSecret = (): string => required('BFF_SESSION_SECRET');
