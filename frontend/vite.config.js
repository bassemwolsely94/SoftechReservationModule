import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    // OneDrive breaks native file-watching, so HMR silently stops picking up
    // edits. Polling detects changes reliably (small CPU cost). Requires a
    // one-time dev-server restart to take effect.
    watch: { usePolling: true, interval: 300 },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
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
