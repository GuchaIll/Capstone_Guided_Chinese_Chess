import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 3001,
    proxy: {
      '/ws/kibo': {
        target: 'ws://localhost:5003',
        ws: true,
      },
    },
  },
})
