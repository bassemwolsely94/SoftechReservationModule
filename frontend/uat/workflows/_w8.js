// W8 shared helpers: mobile /m, rider /rider and 2FA worked through per role on the UAT copy
// (docs/uat/runs/w8-plan.md). Only the uat/lib interfaces and the W5a ops helpers are reused.
//
// Expectations come from the server's own answers, read LIVE at run time, never from role lists:
//   • the role matrix — GET /api/users/my-permissions/ ({permissions, seeded}) for each user;
//   • the branch rule — /api/auth/me/ can_pick_any_branch (core.branch_scope);
//   • the phone rule — can_see_customer_phone + branch scope (apps/customers/access.py phones_visible);
//   • the role registry flags (qa_inspections, mfa_required) — parsed from apps/users/roles.py.
// The Nov-17 .uat-expected.json predates the role review (PR 283), so it is used for branch ids and
// reference records only.
//
// Harness lessons (docs/uat/2026-11-role-uat-report.md): every session is checked (relogin guard)
// before use, a backend that does not answer fails the test (never counted as a refusal), trace off.
import fs from 'node:fs'
import path from 'node:path'
import { devices, expect } from '@playwright/test'
import { stateFile, userByKey, PASSWORD, UAT_USERS } from '../lib/users.js'
import { finding } from '../lib/findings.js'
import { assertUatCopy } from '../lib/guard.js'
import { installInlineConfirmAnswerer } from '../lib/inlineConfirmAnswerer.js'
import { scrub } from './ops/_ops.js'

export { clickFor, scrub, FAKE_PHONE, BASE, field } from './ops/_ops.js'

export const WS = 'W8'
export const stamp = () => String(Date.now()).slice(-7)
/** `UAT-W8-<area>-<stamp>`: what we write into notes / names so the rows are easy to find. */
export const tag = area => `UAT-${WS}-${area}-${stamp()}`

// The ten roles in branch A, and the branch-B twins of the branch-scoped roles.
export const HOME = UAT_USERS.filter(u => u.shape === 'home' && !u.key.includes('@')).map(u => u.key)
export const TWINS_B = UAT_USERS.filter(u => u.shape === 'twinB').map(u => u.key)

/** A phone-sized Chromium (the /m and /rider shells are phone screens). */
export const PHONE = (() => { const { defaultBrowserType: _b, ...d } = devices['Pixel 7']; return d })()
const XHR = { 'X-Requested-With': 'XMLHttpRequest' }

// ── session guard (W2/W4 lesson: logins expire after 1 h and refresh tokens rotate) ──────────────
async function meStatus(page) {
  try { return (await page.request.get('/api/auth/me/', { headers: XHR, timeout: 15_000 })).status() } catch { return 0 }
}

/**
 * The page's session is alive before a step: me/ 200, else refresh, else sign in again with the
 * UAT password (only ever sent to the copy — assertUatCopy ran in beforeAll). A backend that does
 * not answer for a minute throws: the run fails instead of recording refusals.
 * Not for a 2FA-enabled user (its password login needs a code) — the MFA spec manages its own.
 */
export async function ensureSignedIn(page, key, when = '') {
  let s = await meStatus(page)
  if (s === 200) return false
  for (let waited = 0; (s === 0 || s >= 500) && waited < 60_000; waited += 5_000) {
    await page.waitForTimeout(5_000)
    s = await meStatus(page)
  }
  if (s === 200) return false
  if (s === 0 || s >= 500) throw new Error(`UAT backend not answering ${when} for over a minute (status ${s || 'refused'}); this run does not count`)
  await page.request.post('/api/auth/refresh/', { headers: XHR }).catch(() => null)
  if ((s = await meStatus(page)) !== 200) {
    // a dead session (e.g. a retired device's cookies) must not ride along with the password login
    // (W8 triage 1d): sign in from a clean cookie jar
    await page.context().clearCookies()
    const r = await page.request.post('/api/auth/login/', {
      headers: XHR, data: { username: userByKey(key).username, password: PASSWORD } }).catch(() => null)
    if ((s = await meStatus(page)) !== 200) throw new Error(`${key}: could not sign in again ${when} (login ${r?.status() ?? 'failed'}, me ${s}); this run does not count`)
  }
  await page.context().storageState({ path: stateFile(key) })
  return true
}

/** The «جديد هنا؟» tour offer chip (frontend/src/help/Hints.jsx TourOffer). */
export const HELP_CHIP = '[data-tour="general-help-center-offer"]'

/** Init script: hide the help chip, so whether it shows (it is offered once per screen version and
 *  remembered in localStorage) never decides a click (W8 triage 1b). The overlap itself is checked
 *  once, on its own, by mobile.spec.js «chip:». */
function hideHelpChip(selector) {
  const add = () => {
    const st = document.createElement('style')
    st.textContent = `${selector}{display:none !important}`
    ;(document.head || document.documentElement).appendChild(st)
  }
  if (document.documentElement) add()
  else document.addEventListener('DOMContentLoaded', add, { once: true })
}

/**
 * A page signed in as `key` in its own context (phone-sized unless `desktop`), session checked.
 * Inline confirms are answered like the old native dialogs (D-25). close() writes rotated cookies
 * back to the role's state file. The help chip is hidden unless `helpChip: true`.
 */
export async function asUser(browser, key, { desktop = false, helpChip = false, ...contextOptions } = {}) {
  const context = await browser.newContext({ ...(desktop ? {} : PHONE), storageState: stateFile(key), locale: 'ar-EG', ...contextOptions })
  await context.addInitScript(installInlineConfirmAnswerer, `UAT-${WS} done`)
  if (!helpChip) await context.addInitScript(hideHelpChip, HELP_CHIP)
  const page = await context.newPage()
  page.on('dialog', d => d.accept(d.type() === 'prompt' ? `UAT-${WS} done` : undefined).catch(() => {}))
  await ensureSignedIn(page, key, 'at the start')
  const close = async () => {
    const st = await context.storageState().catch(() => null)
    if (st?.cookies?.some(c => c.name === 'erp_refresh')) fs.writeFileSync(stateFile(key), JSON.stringify(st))
    await context.close()
  }
  return { page, api: page.request, context, close }
}

// ── live expectations ─────────────────────────────────────────────────────────────────────────────
/** {me, role, perms, seeded} for the page's user, from the server. */
export async function live(api) {
  const me = await call(api, 'GET', '/api/auth/me/')
  const p = await call(api, 'GET', '/api/users/my-permissions/')
  return { me, role: me.role, perms: p.permissions || {}, seeded: p.seeded || [] }
}

/**
 * Does the matrix allow `module:action` (any of `actions`)? true/false, or null when the module has
 * no matrix rows on this copy (the server then fails open for legacy roles — no matrix to judge by).
 */
export function allows(l, module, actions) {
  if (l.role === 'admin') return true
  if (!l.seeded.includes(module)) return null
  const grant = l.perms[module] || {}
  return [].concat(actions).some(a => !!grant[a])
}
/** The write grants a POST asks of a module (core/middleware/module_access.py _POST_ACTIONS). */
export const POST_ACTIONS = ['create', 'edit', 'approve', 'assign', 'finalize']

/** Role registry flags, read from apps/users/roles.py (the registry is the source; no role lists here). */
export function registry() {
  const file = path.resolve(__dirname, '..', '..', '..', 'apps', 'users', 'roles.py')
  const src = fs.readFileSync(file, 'utf-8')
  const roles = {}
  for (const m of src.matchAll(/Role\('(\w+)',([\s\S]*?)\)(?:,\s*\n|\s*\n\))/g)) {
    const body = m[2]
    const flag = (name, dflt) => { const f = new RegExp(`${name}=(True|False)`).exec(body); return f ? f[1] === 'True' : dflt }
    roles[m[1]] = { mfa_required: flag('mfa_required', true), qa_inspections: flag('qa_inspections', false),
                    all_branches: flag('all_branches', false) }
  }
  if (Object.keys(roles).length < 5) throw new Error('registry(): could not read apps/users/roles.py')
  return roles
}

/**
 * The copy must carry today's role matrix (users 0062_role_review_modules: `rider`, `dispatch` …
 * seeded). On an older copy every expectation would be judged against the wrong matrix: stop.
 */
export async function requireRoleReviewCopy(baseURL) {
  await assertUatCopy(baseURL)                     // also fails when the backend is down
  const { request } = await import('@playwright/test')
  const ctx = await request.newContext({ baseURL, storageState: stateFile('admin'), extraHTTPHeaders: XHR })
  try {
    let r = await ctx.get('/api/users/my-permissions/')
    if (r.status() === 401) {
      // a run over an hour: the saved admin login has lapsed — refresh, else sign in again, and save it
      await ctx.post('/api/auth/refresh/').catch(() => null)
      r = await ctx.get('/api/users/my-permissions/')
      if (r.status() === 401) {
        await ctx.post('/api/auth/login/', { data: { username: userByKey('admin').username, password: PASSWORD } })
        r = await ctx.get('/api/users/my-permissions/')
      }
      if (r.status() === 200) await ctx.storageState({ path: stateFile('admin') })
    }
    if (r.status() !== 200) throw new Error(`my-permissions answered ${r.status()} for admin — sign-in failed or backend down; this run does not count`)
    const seeded = (await r.json()).seeded || []
    const missing = ['rider', 'dispatch'].filter(m => !seeded.includes(m))
    if (missing.length) {
      throw new Error(`UAT copy not migrated to main: modules ${missing.join(', ')} have no matrix rows ` +
        '(users 0062_role_review_modules not applied) — migrate the copy before this wave; this run does not count')
    }
  } finally { await ctx.dispose() }
}

// ── steps, calls, refusals ────────────────────────────────────────────────────────────────────────
/** Record a finding and fail the test softly. */
export function flag(f, message) {
  finding({ ws: WS, ...f })
  expect.soft(false, message || `${f.severity} ${f.kind} ${f.key} ${f.route}: ${f.actual}`).toBe(true)
}

/** Run one journey step; on failure a P1 workflow finding naming the screen and the error. */
export async function step(key, route, name, fn) {
  try {
    return await fn()
  } catch (e) {
    finding({ ws: WS, key, route, kind: 'workflow', severity: 'P1',
              expected: `${name}: works for ${key}`, actual: scrub(e?.message || e) })
    throw e
  }
}

/** API call through a role's own session; throws with the server's words when not 2xx. */
export async function call(api, method, url, data) {
  const res = await api.fetch(url, { method, data, headers: XHR })
  const text = await res.text().catch(() => '')
  if (res.status() === 401) throw new Error(`session expired for this role (401) on ${url}`)
  if (res.status() === 0 || res.status() >= 500) throw new Error(`${method} ${url} → HTTP ${res.status()} (server error): ${scrub(text)}`)
  if (res.status() >= 300) throw new Error(`${method} ${url} → HTTP ${res.status()}: ${scrub(text)}`)
  try { return JSON.parse(text) } catch { return text }
}

/** Raw API answer {status, body} (no throw), for checks that judge the status themselves. */
export async function raw(api, method, url, data, headers = {}) {
  const res = await api.fetch(url, { method, data, headers: { ...XHR, ...headers } })
  const text = await res.text().catch(() => '')
  let body = text
  try { body = JSON.parse(text) } catch { /* not JSON */ }
  return { status: res.status(), body }
}

/**
 * The server must refuse `key` doing `what`: 403/404/405 (+ `alsoRefused`, e.g. 400 where the
 * branch rule is a validation error by design). 2xx → P1. 5xx → P1 crash. 401 → the run is void.
 */
export async function mustRefuse(api, { key, route, what, method, url, data, alsoRefused = [], severity = 'P1' }) {
  const r = await raw(api, method, url, data)
  if (r.status === 401) throw new Error(`session expired for ${key} (401) - refusal not proven: ${what}`)
  const refused = [403, 404, 405, ...alsoRefused].includes(r.status)
  if (!refused) {
    finding({ ws: WS, key, route, kind: r.status >= 500 ? 'crash' : 'workflow', severity: r.status >= 500 ? 'P1' : severity,
              expected: `${key} is refused: ${what}`, actual: `HTTP ${r.status} ${scrub(JSON.stringify(r.body))}` })
  }
  expect.soft(refused, `${key} must be refused: ${what} (got HTTP ${r.status})`).toBe(true)
  return r
}

/** The server must allow it: 2xx; anything else → P1 finding. Returns {status, body}. */
export async function mustAllow(api, { key, route, what, method, url, data, severity = 'P1' }) {
  const r = await raw(api, method, url, data)
  if (r.status === 401) throw new Error(`session expired for ${key} (401) - ${what} not proven`)
  const ok = r.status >= 200 && r.status < 300
  if (!ok) {
    finding({ ws: WS, key, route, kind: r.status >= 500 ? 'crash' : 'workflow', severity,
              expected: `${key} may ${what} (matrix grants it)`, actual: `HTTP ${r.status} ${scrub(JSON.stringify(r.body))}` })
  }
  expect.soft(ok, `${key} must be allowed: ${what} (got HTTP ${r.status})`).toBe(true)
  return r
}

/** id of a create answer, or of the newest row whose `field` equals `value` in a list answer. */
export const idOf = body => body?.id ?? body?.pk ?? null
export const rows = body => (Array.isArray(body) ? body : body?.results || [])
