'use client';

import dynamic from 'next/dynamic';

// The board UI is fully interactive: WebSockets, voice service, three.js,
// and several module-level singletons reach for `window` at construction
// time. Disable SSR for this page so the server prerender skips them.
const App = dynamic(() => import('../src/App'), { ssr: false });

export default function HomePage() {
  return <App />;
}
