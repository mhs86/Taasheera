import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Same-origin browser requests; FastAPI needs no CORS middleware locally.
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/passports': 'http://127.0.0.1:8000',
      '/activity': 'http://127.0.0.1:8000',
      '/assistant': 'http://127.0.0.1:8000',
    },
  },
})
