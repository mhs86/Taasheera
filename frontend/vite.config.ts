import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.TAASHEERA_WEB_PORT || 5173),
    strictPort: true,
    // Same-origin browser requests; FastAPI needs no CORS middleware locally.
    proxy: {
      ...Object.fromEntries(['auth', 'passports', 'profile', 'sessions', 'activity', 'assistant', 'applications']
        .map(route => [`/${route}`, process.env.TAASHEERA_API_TARGET || 'http://127.0.0.1:8000'])),
      '/admin-api': { target: process.env.TAASHEERA_API_TARGET || 'http://127.0.0.1:8000',
        rewrite: path => path.replace(/^\/admin-api/, '/admin') },
    },
  },
})
