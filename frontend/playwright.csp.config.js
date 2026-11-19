// D-04 browser check: the BUILT bundle under the production Content-Security-Policy.
// `npx playwright test -c playwright.csp.config.js` (CI runs it after the main e2e run).
//
// Same Django e2e server as playwright.config.js, but the SPA is `vite build` + `vite preview`, which
// sends the policy from deploy/nginx-csp.conf (vite.config.js) — the dev server cannot: its HMR
// client needs inline scripts. e2e/csp.enforce.js opens every menu screen and fails on any violation.
import { defineConfig, devices } from '@playwright/test'

const PY = process.env.E2E_PYTHON || 'python'
const API_PORT = Number(process.env.E2E_API_PORT || 8100)
const WEB_PORT = Number(process.env.E2E_CSP_WEB_PORT || 5191)
const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  testMatch: /csp\.enforce\.js/,
  outputDir: './test-results-csp',
  fullyParallel: false,
  workers: 1,
  retries: 0,                       // a violation is deterministic; a retry would only hide a flake
  timeout: 600_000,
  expect: { timeout: 15_000 },
  reporter: CI ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-csp' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: 'ar-EG',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: `"${PY}" manage.py runserver 127.0.0.1:${API_PORT} --noreload`,
      cwd: '..',
      url: `http://127.0.0.1:${API_PORT}/api/auth/me/`,
      env: { ...process.env, DJANGO_SETTINGS_MODULE: 'config.settings_e2e', PYTHONIOENCODING: 'utf-8' },
      reuseExistingServer: !CI,
      timeout: 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      env: { ...process.env, VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: !CI,
      timeout: 300_000,
    },
  ],
})
