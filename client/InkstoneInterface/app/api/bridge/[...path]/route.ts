import type { NextRequest } from 'next/server';
import { proxyRequest } from '../../../../lib/server/bridgeProxy';
import { stateBridgeInternalUrl, stateBridgeToken } from '../../../../lib/server/env';

// Required so Next doesn't try to statically render or cache these.
export const dynamic = 'force-dynamic';
// Node runtime — Edge does not support `req.body` streaming with
// `duplex: 'half'` on every deployment target, and we lean on Node's
// crypto module from the session helper.
export const runtime = 'nodejs';

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  return proxyRequest(req, path ?? [], {
    baseUrl: stateBridgeInternalUrl(),
    bearer: stateBridgeToken(),
  });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
