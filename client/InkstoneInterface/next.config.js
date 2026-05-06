/** @type {import('next').NextConfig} */
const nextConfig = {
  // BFF migration (refs docs/refactoring/refactoring_guide.md C3/C4).
  //
  // The previous unauthenticated rewrites under /bridge/*, /api/*,
  // /dashboard/*, /coach/* exposed the upstream services to the browser
  // with no token injection. They have been replaced by App Router
  // route handlers under app/api/{bridge,coach,dashboard,...} which
  // verify the BFF session cookie and attach the real STATE_BRIDGE_TOKEN
  // server-side.
  //
  // No rewrites are needed any more. The browser only sees /api/...,
  // and the route handlers reach the upstream services via internal
  // URLs from lib/server/env.ts.
  async headers() {
    return [
      {
        source: '/',
        headers: [{ key: 'Cache-Control', value: 'no-store, max-age=0' }],
      },
      {
        source: '/agents',
        headers: [{ key: 'Cache-Control', value: 'no-store, max-age=0' }],
      },
      {
        source: '/hardware',
        headers: [{ key: 'Cache-Control', value: 'no-store, max-age=0' }],
      },
    ];
  },
  // Output a standalone server for the production Docker image.
  output: 'standalone',
  // The chess UI is fully interactive; SSR adds no value and several
  // hooks (useWebSocket, voice service, three.js) need browser globals.
  // Keep React strict mode on for dev correctness checks.
  reactStrictMode: true,
  // Don't auto-308 trailing slashes. The Go coaching service serves the
  // dashboard at `/dashboard/` (with the slash) and 307-redirects from
  // `/dashboard`. Without this flag Next inverts the redirect and the
  // browser ends up in a loop.
  skipTrailingSlashRedirect: true,
};

module.exports = nextConfig;
