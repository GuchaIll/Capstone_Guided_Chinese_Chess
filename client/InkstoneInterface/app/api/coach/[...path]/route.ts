import type { NextRequest } from 'next/server';
import { proxyRequest } from '../../../../lib/server/bridgeProxy';
import { coachInternalUrl, stateBridgeToken } from '../../../../lib/server/env';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

// The Go chess-coach mounts these handlers under /coach/* — we proxy
// to the same path on the upstream, prepending /coach so the upstream
// router matches.
async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  return proxyRequest(req, ['coach', ...(path ?? [])], {
    baseUrl: coachInternalUrl(),
    bearer: stateBridgeToken(),
  });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
