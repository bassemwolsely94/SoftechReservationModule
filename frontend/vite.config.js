import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Django server behind /api, /media and /ws. The browser tests (e2e/) point it at their own
// e2e server (config.settings_e2e) so they never touch the dev backend.
const API = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // Each checkout keeps its own pre-bundled deps. Worktrees link frontend/node_modules to the main
  // checkout, so the default node_modules/.vite was one cache shared by every dev server: one
  // server re-bundling React broke the others ("Invalid hook call", useState of null).
  cacheDir: fileURLToPath(new URL('./.vite-cache', import.meta.url)),
  server: {
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    // OneDrive breaks native file-watching, so HMR silently stops picking up
    // edits. Polling detects changes reliably (small CPU cost). Requires a
    // one-time dev-server restart to take effect.
    watch: { usePolling: true, interval: 300 },
    proxy: {
      '/api': {
        target: API,
        changeOrigin: true,
      },
      // relative /media/… URLs (POS search thumbnails) — Nginx serves these in production
      '/media': {
        target: API,
        changeOrigin: true,
      },
      '/ws': {
        target: API.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
    }
  },
  build: {
    outDir: '../staticfiles/frontend',
    emptyOutDir: true,
  }
})
