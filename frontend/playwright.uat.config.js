// Role-by-role UAT on the restored copy (docs/superpowers/specs/2026-11-16-role-uat-design.md).
//   . scripts/uat/uat-env.ps1   (from the repo root)
//   npm run test:uat -- [path or grep]
//
// Django: ONE shared UAT server on 127.0.0.1:8200 with config.settings_uat (reader copy, no
// SOFTECH, no sends, RBAC enforce). Started here if nothing listens yet; reused otherwise, so
// parallel sessions share it. Vite: each session its own UAT_WEB_PORT (5200 here, 5201+ others).
import { defineConfig, devices } from '@playwright/test'

const PY = process.env.UAT_PYTHON || process.env.E2E_PYTHON || 'python'
const API_PORT = Number(process.env.UAT_API_PORT || 8200)
const WEB_PORT = Number(process.env.UAT_WEB_PORT || 5200)

export default defineConfig({
  testDir: './uat',
  outputDir: './test-results-uat',
  fullyParallel: false,
  workers: 1,                       // one shared copy; flows create rows
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'test-results-uat/html' }]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: 'ar-EG',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'login', testMatch: /login\.setup\.js/, use: { ...devices['Desktop Chrome'] } },
    { name: 'uat', dependencies: ['login'], testMatch: /.*\.spec\.js/, use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command: `"${PY}" manage.py runserver 127.0.0.1:${API_PORT} --noreload --settings=config.settings_uat`,
      cwd: '..',
      url: `http://127.0.0.1:${API_PORT}/api/auth/me/`,
      env: { ...process.env, DJANGO_SETTINGS_MODULE: 'config.settings_uat', PYTHONIOENCODING: 'utf-8' },
      reuseExistingServer: true,
      timeout: 300_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      env: { ...process.env, VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
})
