import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/bridge': {
        target: 'http://localhost:5003',
        ws: true,
      },
      // /ws/chat MUST come before /ws so vite matches the more-specific path first
      '/ws/chat': {
        target: 'ws://localhost:5001',
        ws: true,
      },
      '/bridge/ws': {
        target: 'ws://localhost:5003',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:5001',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/dashboard': {
        target: 'http://localhost:5002',
      },
      '/coach': {
        target: 'http://localhost:5002',
      },
    },
  },
})
