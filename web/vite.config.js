import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The frontend always calls same-origin relative URLs like fetch('/api/health').
// In dev, Vite proxies /api to the FastAPI server on :8000. In production,
// FastAPI serves this build and answers /api itself. Identical URLs both ways,
// so there is no VITE_API_URL to configure and CORS never engages.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
