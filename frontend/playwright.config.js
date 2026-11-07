// Browser tests (test plan R8): `npm run test:e2e`. Chromium only.
//
// Two servers, both started here (or reused locally if already running):
//   * Django on 127.0.0.1:8100 with config.settings_e2e — its own database, never the dev .env,
//     SOFTECH read-only with no host, no outbound sends. Migrate + `seed_e2e_users` first.
//   * Vite on 127.0.0.1:5190, proxying /api to that Django (VITE_API_TARGET).
import { defineConfig, devices } from '@playwright/test'

const PY = process.env.E2E_PYTHON || 'python'
const API_PORT = Number(process.env.E2E_API_PORT || 8100)   // override to run beside another session's e2e servers
const WEB_PORT = Number(process.env.E2E_WEB_PORT || 5190)
const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: false,
  workers: 1,                       // one shared e2e database; flows create rows
  retries: CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: 'ar-EG',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'login', testMatch: /login\.setup\.js/, use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium', dependencies: ['login'], testMatch: /.*\.spec\.js/, use: { ...devices['Desktop Chrome'] } },
  ],
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
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      env: { ...process.env, VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: !CI,
      timeout: 180_000,
    },
  ],
})
