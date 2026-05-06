// Cookie-based session for the BFF.
//
// The Inkstone Interface is a single-tenant local demo, so we don't run
// a login flow. Instead, the first request without a session cookie
// gets an auto-issued one in middleware. The cookie is HMAC-signed so
// it can't be forged. Its only job is to be a same-origin marker the
// BFF route handlers can verify before attaching the upstream bearer.

import { sessionSecret } from './env';

export const SESSION_COOKIE_NAME = 'inkstone_session';
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days
const SESSION_ID_BYTES = 24; // → 32 base64url chars
const encoder = new TextEncoder();

// Cookie payload: <sessionId>.<hmac>
//   sessionId = base64url(random bytes)
//   hmac      = base64url(HMAC-SHA256(sessionSecret, sessionId))

export interface SessionCookieValue {
  raw: string;
  sessionId: string;
}

let cachedKeyPromise: Promise<CryptoKey> | null = null;

export async function issueSession(): Promise<SessionCookieValue> {
  const sessionBytes = new Uint8Array(SESSION_ID_BYTES);
  crypto.getRandomValues(sessionBytes);
  const sessionId = toBase64Url(sessionBytes);
  const mac = await sign(sessionId);
  return { raw: `${sessionId}.${mac}`, sessionId };
}

export async function verifySession(raw: string | undefined | null): Promise<string | null> {
  if (!raw) return null;
  const dot = raw.indexOf('.');
  if (dot <= 0 || dot === raw.length - 1) return null;
  const sessionId = raw.slice(0, dot);
  const presentedMac = raw.slice(dot + 1);
  const expectedMac = await sign(sessionId);

  const a = fromBase64Url(presentedMac);
  const b = fromBase64Url(expectedMac);
  if (a.length !== b.length) return null;

  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a[i] ^ b[i];
  }
  if (diff !== 0) return null;

  return sessionId;
}

async function sign(sessionId: string): Promise<string> {
  const key = await getSigningKey();
  const signature = await crypto.subtle.sign(
    'HMAC',
    key,
    encoder.encode(sessionId),
  );
  return toBase64Url(new Uint8Array(signature));
}

async function getSigningKey(): Promise<CryptoKey> {
  if (!cachedKeyPromise) {
    cachedKeyPromise = crypto.subtle.importKey(
      'raw',
      encoder.encode(sessionSecret()),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign'],
    );
  }
  return cachedKeyPromise;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromBase64Url(value: string): Uint8Array {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

export function sessionCookieAttributes() {
  return {
    httpOnly: true,
    sameSite: 'lax' as const,
    // `secure: false` for local http://localhost demos. In production
    // (TLS terminator in front of the BFF) override via env or wrap
    // this attribute factory.
    secure: process.env.NODE_ENV === 'production' && process.env.BFF_INSECURE_COOKIE !== '1',
    path: '/',
    maxAge: SESSION_TTL_SECONDS,
  };
}
