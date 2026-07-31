import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // K-025：显式绑定 IPv4——默认 'localhost' 在 Node 17+ 只听 ::1（IPv6），
    // 而健康探测/浏览器统一走 127.0.0.1（否则启动脚本 60s 等就绪超时）
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      // K-025：target 必须 127.0.0.1 而非 localhost——localhost 先解析 IPv6(::1)，
      // uvicorn 只听 IPv4，回退延迟 ~170ms/新连接（页面所有 API 调用慢 5 倍的元凶）
      '/api': {
        target: 'http://127.0.0.1:9100',
        changeOrigin: true,
      },
      // WebSocket 代理
      '/api/runs/stream': {
        target: 'ws://127.0.0.1:9100',
        ws: true,
      },
      '/api/agent/ws': {
        target: 'ws://127.0.0.1:9100',
        ws: true,
      },
    },
  },
})
