import { NextRequest, NextResponse } from 'next/server';
import { SESSION_COOKIE_NAME, verifySession } from '../../../../lib/server/session';
import { stateBridgeInternalUrl, stateBridgeToken } from '../../../../lib/server/env';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

// Browser calls GET /api/bridge/ws-ticket to receive a single-use,
// 30-second ticket. The BFF forwards the request to the bridge with
// the real bearer; the bridge mints a ticket and returns it. Browser
// then opens its WebSocket directly with ?token=<ticket>.

interface BridgeTicketResponse {
  ticket?: unknown;
  expires_in?: unknown;
}

export async function GET(req: NextRequest) {
  if (!await verifySession(req.cookies.get(SESSION_COOKIE_NAME)?.value)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const upstreamUrl = `${stateBridgeInternalUrl()}/auth/ws-ticket`;
  let upstream: Response;
  try {
    // cache: 'no-store' is mandatory here. Next 14 App Router wraps
    // global fetch() with a request cache layer; without opt-out the
    // first ticket response would be served forever, breaking the
    // single-use semantics enforced by the bridge.
    upstream = await fetch(upstreamUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${stateBridgeToken()}`,
        'Content-Type': 'application/json',
      },
      body: '{}',
      cache: 'no-store',
    });
  } catch (err) {
    return NextResponse.json(
      { error: 'bridge unreachable', detail: String(err) },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    return NextResponse.json(
      { error: 'bridge rejected ticket request', status: upstream.status },
      { status: 502 },
    );
  }

  const body = (await upstream.json()) as BridgeTicketResponse;
  if (typeof body.ticket !== 'string') {
    return NextResponse.json({ error: 'malformed ticket payload' }, { status: 502 });
  }

  return NextResponse.json({
    ticket: body.ticket,
    expires_in: typeof body.expires_in === 'number' ? body.expires_in : 30,
  });
}
