// W4 guards: a scan that reaches nothing finds nothing and "passes".
// 1) backend: run 1 (2026-11-17) lost the shared Django server on 8200 for ~20 min and 260 tests
//    passed empty. Every W4 test probes the backend before and after; refused = the test fails.
// 2) session: the access token lives 1 h and refresh tokens rotate + blacklist (config/settings.py
//    SIMPLE_JWT), while every test reloads the same saved login file. After ~1 h of a run the
//    saved session is dead, screens show "refused" and the scan sees nothing. Each W4 test checks
//    /api/auth/me/ first and signs in again through the login API when the session has lapsed,
//    saving the new session back to the (git-ignored) state file; if it still is not 200, it fails.
// A quiet run therefore means "signed in, scanned and clean", never "nothing answered".
import { test } from '@playwright/test'
import { userByKey, PASSWORD, stateFile } from '../lib/users.js'

const API = `http://127.0.0.1:${Number(process.env.UAT_API_PORT || 8200)}/api/auth/me/`
const HDR = { 'X-Requested-With': 'XMLHttpRequest' }

async function probe(request, when) {
  let status = 0
  try { status = (await request.get(API, { timeout: 10_000 })).status() } catch { status = 0 }
  if (status === 0 || status >= 500) throw new Error(`UAT backend not answering ${when} the test (status ${status || 'refused'}); this result does not count`)
}

export function guardBackend() {
  test.beforeEach(async ({ request }) => { await probe(request, 'before') })
  test.afterEach(async ({ request }) => { await probe(request, 'after') })
}

async function signedIn(page) {
  return (await page.request.get('/api/auth/me/', { headers: HDR }).catch(() => null))?.status() === 200
}

/** Call inside a describe that uses stateFile(key): the test starts with a live session. */
export function keepSignedIn(key) {
  test.beforeEach(async ({ page }) => {
    if (await signedIn(page)) return
    await page.request.post('/api/auth/refresh/', { headers: HDR }).catch(() => null)
    if (!(await signedIn(page))) {
      const r = await page.request.post('/api/auth/login/', {
        headers: HDR, data: { username: userByKey(key).username, password: PASSWORD } })
      if (!(await signedIn(page))) throw new Error(`${key}: could not sign in again (login ${r.status()}); this result does not count`)
    }
    await page.context().storageState({ path: stateFile(key) })
  })
  test.afterEach(async ({ page }) => {
    if (!(await signedIn(page))) throw new Error(`${key}: session lost during the test; this result does not count`)
  })
}
