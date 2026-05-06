import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { issueSession, sessionCookieAttributes, SESSION_COOKIE_NAME, verifySession } from './lib/server/session';

// Auto-issues a signed HTTP-only session cookie on first visit.
//
// This isn't authentication — it's a same-origin marker. It exists so
// the API routes under /api/bridge and /api/coach can refuse requests
// that don't carry the cookie (e.g. cross-origin fetches that bypass
// the page) before they ever talk to the upstream services. Real auth
// would replace this with a proper login flow.

export const config = {
  // Run on every page and API route. Only static assets and Next's own
  // internals are skipped. Keep this matcher tight to avoid handing
  // signed cookies to image / font requests.
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|images/|public/).*)',
  ],
};

export async function middleware(req: NextRequest) {
  const presented = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (presented && await verifySession(presented)) {
    return NextResponse.next();
  }
  const fresh = await issueSession();
  const res = NextResponse.next();
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: fresh.raw,
    ...sessionCookieAttributes(),
  });
  return res;
}
