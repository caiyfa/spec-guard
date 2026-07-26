import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:9100',
        changeOrigin: true,
      },
      // WebSocket 代理
      '/api/runs/stream': {
        target: 'ws://localhost:9100',
        ws: true,
      },
      '/api/agent/ws': {
        target: 'ws://localhost:9100',
        ws: true,
      },
    },
  },
})
