import type { ProxyOptions } from 'vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backend = 'http://127.0.0.1:8000'

// The dev proxy buffers a streamed response unless each write is flushed, which
// turns a token stream into one blob delivered at the end. Disabling compression
// and proxying the event-stream path without buffering keeps the typing effect
// visible in development, not just when calling the API directly.
const streaming: ProxyOptions = {
  target: backend,
  changeOrigin: true,
  selfHandleResponse: true,
  configure: (proxy) => {
    proxy.on('proxyReq', (request) => {
      request.setHeader('Accept-Encoding', 'identity')
    })
    proxy.on('proxyRes', (response, _request, res) => {
      res.writeHead(response.statusCode ?? 200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache, no-transform',
        connection: 'keep-alive',
        'x-accel-buffering': 'no',
      })
      response.on('data', (chunk: Buffer) => {
        res.write(chunk)
        ;(res as { flush?: () => void }).flush?.()
      })
      response.on('end', () => res.end())
    })
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api/chat/stream': streaming,
      '/api/search/answer/stream': streaming,
      '/api': { target: backend, changeOrigin: true },
      '/ready': { target: backend, changeOrigin: true },
      '/health': { target: backend, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api/chat/stream': streaming,
      '/api/search/answer/stream': streaming,
      '/api': { target: backend, changeOrigin: true },
      '/ready': { target: backend, changeOrigin: true },
      '/health': { target: backend, changeOrigin: true },
    },
  },
})
