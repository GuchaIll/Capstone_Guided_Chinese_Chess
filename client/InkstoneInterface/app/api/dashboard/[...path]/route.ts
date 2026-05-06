import type { NextRequest } from 'next/server';
import { proxyRequest } from '../../../../lib/server/bridgeProxy';
import { coachInternalUrl, stateBridgeToken } from '../../../../lib/server/env';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  return proxyRequest(req, ['dashboard', ...(path ?? [])], {
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
