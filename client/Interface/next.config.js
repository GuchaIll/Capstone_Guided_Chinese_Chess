/** @type {import('next').NextConfig} */
const nextConfig = {
  // Mirrors what vite.config.ts used to proxy in dev. In production we
  // either keep these rewrites (Next runs the proxy itself) or front
  // Next with a real load balancer that handles them — both work.
  // Note: HTTP rewrites only. The browser opens the bridge WebSocket
  // directly via NEXT_PUBLIC_STATE_BRIDGE_BASE because Next's dev
  // rewrite layer doesn't proxy WS upgrades reliably.
  async rewrites() {
    const bridge = process.env.NEXT_PUBLIC_STATE_BRIDGE_INTERNAL_URL || 'http://localhost:5003';
    const coaching = process.env.NEXT_PUBLIC_COACHING_INTERNAL_URL || 'http://localhost:5001';
    const dashboard = process.env.NEXT_PUBLIC_DASHBOARD_INTERNAL_URL || 'http://localhost:5002';
    return [
      // /bridge/foo → state-bridge:/foo  (bridge serves at root, e.g. /state, /health)
      { source: '/bridge/:path*', destination: `${bridge}/:path*` },
      // /api/foo → coaching:/foo  (matches the previous Vite proxy rewrite)
      { source: '/api/:path*', destination: `${coaching}/:path*` },
      // /dashboard/foo → go-coaching:/dashboard/foo
      // /coach/foo → go-coaching:/coach/foo
      // The Go service serves these paths *with* their prefix. Handle the
      // bare `/dashboard` and `/dashboard/` cases explicitly because
      // Next's `:path*` collapses the trailing slash on empty captures,
      // which would otherwise produce a redirect loop with Go's
      // automatic `/dashboard` → `/dashboard/` 307.
      { source: '/dashboard', destination: `${dashboard}/dashboard/` },
      { source: '/dashboard/', destination: `${dashboard}/dashboard/` },
      { source: '/dashboard/:path+', destination: `${dashboard}/dashboard/:path+` },
      { source: '/coach', destination: `${dashboard}/coach/` },
      { source: '/coach/', destination: `${dashboard}/coach/` },
      { source: '/coach/:path+', destination: `${dashboard}/coach/:path+` },
    ];
  },
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
