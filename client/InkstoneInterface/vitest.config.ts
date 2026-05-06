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
  },
});
