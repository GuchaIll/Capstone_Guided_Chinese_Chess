// Generic upstream proxy used by /api/bridge, /api/coach, /api/dashboard.
//
// Responsibilities:
//   1. Verify the BFF session cookie. Reject anonymous callers.
//   2. Build the upstream URL: <baseUrl>/<...path><?queryString>.
//   3. Forward method, headers (filtered), and body (with passthrough
//      for streaming SSE responses).
//   4. Attach the upstream Bearer token. The browser never sees it.

import { NextRequest, NextResponse } from 'next/server';
import { SESSION_COOKIE_NAME, verifySession } from './session';

// Headers we never forward upstream. Authorization is overwritten by us
// with the real bearer; cookie/host/content-length are connection-
// specific and would confuse the upstream.
const HOP_BY_HOP_REQUEST_HEADERS = new Set([
  'host',
  'connection',
  'content-length',
  'transfer-encoding',
  'cookie',
  'authorization',
]);

// Headers we never copy back to the browser. These would either confuse
// the browser or leak upstream details we proxy on purpose.
const HOP_BY_HOP_RESPONSE_HEADERS = new Set([
  'connection',
  'transfer-encoding',
  'keep-alive',
  'content-length',
  'content-encoding',
]);

export interface ProxyConfig {
  baseUrl: string;
  bearer: string;
}

export async function proxyRequest(
  req: NextRequest,
  pathSegments: string[],
  config: ProxyConfig,
): Promise<Response> {
  // 1. Same-origin gate.
  const sessionId = await verifySession(req.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!sessionId) {
    return NextResponse.json(
      { error: 'session cookie missing or invalid' },
      { status: 401 },
    );
  }

  // 2. Construct upstream URL. pathSegments is what Next captured from
  // [...path] — already URL-decoded; re-encode each segment to be safe.
  const safePath = pathSegments.map(encodeURIComponent).join('/');
  const search = req.nextUrl.search; // includes leading '?' or empty
  const upstreamUrl = `${config.baseUrl}/${safePath}${search}`;

  // 3. Forward headers, filter hop-by-hop, attach bearer.
  const forwardHeaders = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_REQUEST_HEADERS.has(key.toLowerCase())) {
      forwardHeaders.set(key, value);
    }
  });
  forwardHeaders.set('Authorization', `Bearer ${config.bearer}`);

  // 4. Forward body for non-GET/HEAD. Browser fetch already streams
  // ReadableStream bodies; node fetch v18+ accepts them.
  //
  // cache: 'no-store' is mandatory: Next 14 App Router wraps global
  // fetch() with a request cache layer that would otherwise turn every
  // GET (e.g. /state, /health) into a stale snapshot, breaking the
  // entire point of the SSE / live-state contract.
  const init: RequestInit = {
    method: req.method,
    headers: forwardHeaders,
    redirect: 'manual',
    cache: 'no-store',
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    // duplex: 'half' is required by the Node fetch implementation when
    // streaming a request body.
    (init as RequestInit & { duplex?: string }).duplex = 'half';
    init.body = req.body;
  }

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, init);
  } catch (err) {
    return NextResponse.json(
      { error: 'upstream unreachable', detail: String(err) },
      { status: 502 },
    );
  }

  // 5. Build the response. Streaming bodies (SSE, chunked) pass through
  // the underlying ReadableStream; everything else is just bytes.
  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_RESPONSE_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}
