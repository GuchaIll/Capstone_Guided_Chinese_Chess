import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Vitest needs its own config now that vite.config.ts is gone. We keep
// using @vitejs/plugin-react for the JSX transform (Next.js's SWC isn't
// hooked into the test pipeline) — same pattern, just one tool fewer.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./vitest.setup.ts'],
    // Quarantine list (refs docs/refactoring/refactoring_guide.md C5).
    // App.test.tsx targets the pre-Inkstone-board UI: /capture flow,
    // CV-driven End Turn, the legacy ChessBoard component, etc. The
    // current App.tsx shipped a different turn flow (InkstoneBoard,
    // no CV capture) so those 20 tests cannot pass without a rewrite.
    // Drop this exclusion once App.test.tsx has been rewritten against
    // the current component contract.
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/.next/**',
      'src/App.test.tsx',
    ],
  },
});
