import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Django server behind /api, /media and /ws. The browser tests (e2e/) point it at their own
// e2e server (config.settings_e2e) so they never touch the dev backend.
const API = process.env.VITE_API_TARGET || 'http://localhost:8000'

// D-04: `vite preview` (the built bundle — CI's CSP browser check, the VPS workbench) sends the same
// Content-Security-Policy as nginx, read from the one file that defines it. `vite dev` does not:
// its HMR client needs inline scripts that the production policy rightly refuses.
export function cspFromNginx() {
  const conf = readFileSync(fileURLToPath(new URL('../deploy/nginx-csp.conf', import.meta.url)), 'utf-8')
  const mode = conf.match(/^set \$elr_csp_mode "([^"]+)";/m)?.[1]
  const policy = conf.match(/^set \$elr_csp_policy "([^"]+)";/m)?.[1]
  if (!mode || !policy) throw new Error('vite.config.js: cannot read the CSP from deploy/nginx-csp.conf')
  return { header: mode === 'enforce' ? 'Content-Security-Policy' : 'Content-Security-Policy-Report-Only', policy }
}
const CSP = cspFromNginx()

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
  preview: {
    headers: { [CSP.header]: CSP.policy },
  },
  build: {
    outDir: '../staticfiles/frontend',
    emptyOutDir: true,
  }
})
