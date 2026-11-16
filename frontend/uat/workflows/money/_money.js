// W5b shared helpers: money and approval workflows on the UAT copy.
// Only the harness interfaces (uat/lib/*) are used; nothing here talks to anything but the
// UAT server behind the Vite proxy (baseURL), which serves the reader copy on 8200.
import fs from 'node:fs'
import path from 'node:path'
import { request, expect } from '@playwright/test'
import { gotoSettled } from '../../lib/page.js'
import { stateFile, UAT_USERS } from '../../lib/users.js'
import { can } from '../../lib/expected.js'
import { finding, FINDINGS_FILE } from '../../lib/findings.js'
import { assertReaderCopy } from '../../lib/guard.js'

export const WS = 'W5b'
export const TAG = 'UAT-W5b'
export const stamp = () => String(Date.now()).slice(-7)

// The ten roles in their home branch (A): the users that "do the work" in each area.
export const HOME = UAT_USERS.filter(u => u.shape === 'home' && !u.key.includes('@')).map(u => u.key)
export const doers = (module, action) => HOME.filter(k => can(k, module, action))
export const nonDoers = (module, action) => HOME.filter(k => !can(k, module, action))

/** An API client signed in as `key` (the login setup's cookies), with the app's CSRF marker. */
export async function apiAs(baseURL, key) {
  const ctx = await request.newContext({
    baseURL, storageState: stateFile(key),
    extraHTTPHeaders: { 'X-Requested-With': 'XMLHttpRequest' },
  })
  const call = async (method, url, data) => {
    const res = await ctx.fetch(url, { method, data })
    let body
    try { body = await res.json() } catch { body = null }
    return { status: res.status(), body }
  }
  return {
    get: url => call('GET', url),
    post: (url, data = {}) => call('POST', url, data),
    patch: (url, data = {}) => call('PATCH', url, data),
    dispose: () => ctx.dispose(),
  }
}

/** Record a finding and fail the test softly (the rest of the test still runs). */
export function flag(f, message) {
  finding({ ws: WS, ...f })
  expect.soft(false, message || `${f.severity} ${f.kind} ${f.key} ${f.route}: ${f.actual}`).toBe(true)
}

/** A "must be refused" call: 401/403/404 are a refusal; anything 2xx is the role doing what it must not. */
export function expectRefused(r, { key, route, what, severity = 'P1', kind = 'workflow' }) {
  if (r.status >= 200 && r.status < 300) {
    flag({ key, route, kind, severity, expected: `${what} refused`, actual: `allowed (HTTP ${r.status})` })
  }
  return r.status
}

/** Short, phone-free text from an API body for a finding. */
export const brief = body => JSON.stringify(body ?? '').replace(/\d{8,}/g, '#').slice(0, 220)

/**
 * The safety gate for the owner-approved writes (POS push, pricing approval): the server must be
 * the reader copy. If not, a P0 finding is written and the caller aborts the whole spec.
 */
export async function readerGate(baseURL, area) {
  try {
    await assertReaderCopy(baseURL)
    return true
  } catch (e) {
    finding({ ws: WS, key: 'admin', route: '/api/sync/writer-switches/', kind: 'workflow', severity: 'P0',
      expected: `${area}: reader copy, every writer off`, actual: String(e.message).slice(0, 200) })
    return false
  }
}

/**
 * Open `url` as `key` in its own browser context and expect it to settle. Anything but ok/slow is
 * a finding (crash → P1 crash; refused/blank → `severity`, default P1 since the role does this work).
 */
export async function screenOk(browser, key, url, { severity = 'P1', what = 'screen opens' } = {}) {
  const ctx = await browser.newContext({ storageState: stateFile(key) })
  const page = await ctx.newPage()
  try {
    const r = await gotoSettled(page, url)
    let near = ''
    if (r.status === 'refused' && r.finalUrl === new URL(url, 'http://x').pathname && !r.apiErrors.some(e => e.status === 403)) {
      // Same screen, no 403: gotoSettled's refusal words may have matched page data (e.g. an
      // amount containing "403"). Say what matched, so a false "refused" is visible as such.
      const text = await page.locator('main, #root').first().innerText().catch(() => '')
      const m = text.match(/غير مصرح|ليس لديك صلاحية|لا تملك صلاحية|403|Forbidden/)
      near = m ? text.slice(Math.max(0, m.index - 25), m.index + 25).replace(/\s+/g, ' ').replace(/\d{8,}/g, '#') : ''
      if (m && m[0] === '403') {
        finding({ ws: WS, key, route: url.replace(/\/\d+(?=\/|$)/g, '/:id'), kind: 'decision', severity: 'P3',
          expected: 'harness: "refused" means a refusal screen',
          actual: `uat/lib/page.js REFUSED_TEXT matched "403" inside page data ("${near}"); the screen rendered (no 403 API call, same URL)` })
        return { ...r, status: 'ok' }
      }
    }
    if (!['ok', 'slow'].includes(r.status)) {
      const api = r.apiErrors.map(e => `${e.status} ${e.url.split('?')[0]}`).slice(0, 4).join(', ')
      flag({ key, route: url.replace(/\/\d+(?=\/|$)/g, '/:id'), kind: r.status === 'crash' ? 'crash' : 'workflow',
        severity: r.status === 'crash' ? 'P1' : severity, expected: what,
        actual: `${r.status} (landed on ${r.finalUrl}${api ? `; API ${api}` : ''}${near ? `; text "${near}"` : ''})`.replace(/\d{8,}/g, '#') })
    }
    return r
  } finally { await ctx.close() }
}

/**
 * A P0 that must stop a whole spec even across Playwright worker restarts: a marker keyed to the
 * runner process (the workers' parent), so the next run starts clean.
 */
const markerFile = name => path.join(path.dirname(FINDINGS_FILE), `.w5b-abort-${name}`)
const runner = () => globalThis.process.ppid
export function setAbort(name, why) {
  fs.mkdirSync(path.dirname(markerFile(name)), { recursive: true })
  fs.writeFileSync(markerFile(name), JSON.stringify({ runner: runner(), why }))
}
export function getAbort(name) {
  try {
    const m = JSON.parse(fs.readFileSync(markerFile(name), 'utf-8'))
    return m.runner === runner() ? m.why : ''
  } catch { return '' }
}

/** Money equality to the cent. */
export const money = v => Math.round(Number(v) * 100) / 100
export const sameMoney = (a, b, tol = 0.01) => Math.abs(Number(a) - Number(b)) <= tol + 1e-9
