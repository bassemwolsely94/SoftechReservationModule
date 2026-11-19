// W3 guards, adopted from W4 (frontend/uat/exposure/alive.js on claude/uat-w4-exposure-e89046,
// commits 226d62d7 + 4ff01558): a sweep that reaches nothing finds nothing and "passes".
// 1) backend: the shared Django server on 8200 can go away mid-run; probe before and after each
//    test, refused / 5xx = the test fails.
// 2) session: the access token lives 1 h and refresh tokens rotate + blacklist (SIMPLE_JWT), while
//    every test reloads the same saved login file. The first full W3 run took 1.3 h, so its later
//    tests opened /login and checked nothing. ensureSignedIn() checks /api/auth/me/ and signs in
//    again through the login API when the session has lapsed, saving it back to the git-ignored
//    state file; if it still is not 200, the test fails. The button sweep also calls it after every
//    screen, because one test (11 screens) can run past the expiry.
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

export async function signedIn(page) {
  return (await page.request.get('/api/auth/me/', { headers: HDR }).catch(() => null))?.status() === 200
}

/** Live session for `key` or throw. Returns true when it had to sign in again. */
export async function ensureSignedIn(page, key) {
  if (await signedIn(page)) return false
  await page.request.post('/api/auth/refresh/', { headers: HDR }).catch(() => null)
  if (!(await signedIn(page))) {
    const r = await page.request.post('/api/auth/login/', {
      headers: HDR, data: { username: userByKey(key).username, password: PASSWORD } })
    if (!(await signedIn(page))) throw new Error(`${key}: could not sign in again (login ${r.status()}); this result does not count`)
  }
  await page.context().storageState({ path: stateFile(key) })
  return true
}

/** Call inside a describe that uses stateFile(key): the test starts and ends with a live session. */
export function keepSignedIn(key) {
  test.beforeEach(async ({ page }) => { await ensureSignedIn(page, key) })
  test.afterEach(async ({ page }) => {
    if (!(await signedIn(page))) throw new Error(`${key}: session lost during the test; this result does not count`)
  })
}
