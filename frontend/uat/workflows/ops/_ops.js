// Shared steps for the W5a operational workflows (plan Task 9). Uses only the uat/lib interfaces.
//
// Rules: a broken step in a journey → P1 `workflow` finding (screen + error), then the test fails.
// A role that can do what it must not → P1 `workflow` finding. Records we create carry `UAT-` in
// their notes/remarks. Never a full phone number in a finding (finding() also refuses 8+ digits).
//
// Sessions: each role runs in its own browser context from its saved login. API calls go through
// that page's own `page.request` (same cookies), never a manual /auth/refresh/. Refresh tokens
// rotate, so asUser().close() writes the context's current cookies back to the role's state file.
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { expect } from '@playwright/test'
import { stateFile } from '../../lib/users.js'
import { can } from '../../lib/expected.js'
import { finding, FINDINGS_FILE } from '../../lib/findings.js'
import { installInlineConfirmAnswerer } from '../../lib/inlineConfirmAnswerer.js'

export const WS = 'W5a'
/** The Vite origin this session's run uses (playwright.uat.config.js: UAT_WEB_PORT). */
export const BASE = `http://127.0.0.1:${process.env.UAT_WEB_PORT || 5200}`
// Cookie auth honours a write only with this header (core/auth_cookies.py, CSRF guard) - the app's
// axios client always sends it; our direct API calls must too.
const XHR = { 'X-Requested-With': 'XMLHttpRequest' }

// A failed test restarts the Playwright worker and loses module state, so each journey keeps the ids
// it created in a small file: the later steps (other roles) still run after an earlier soft failure.
const STATE_FILE = path.join(path.dirname(FINDINGS_FILE), 'w5a-ops-state.json')
const readState = () => { try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8')) } catch { return {} } }
export const recall = area => readState()[area] || {}
export function remember(area, patch) {
  const all = readState()
  all[area] = patch === null ? {} : { ...(all[area] || {}), ...patch }
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true })
  fs.writeFileSync(STATE_FILE, JSON.stringify(all, null, 1))
}
export const stamp = () => String(Date.now()).slice(-7)
/** `UAT-W5a-<area>-<stamp>`: what we write into notes/remarks so the rows are easy to find. */
export const tag = area => `UAT-${WS}-${area}-${stamp()}`
/** Fake contact numbers only (0100000000x) - never a real customer phone. */
export const FAKE_PHONE = n => `0100000000${n}`

const ANSI = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, 'g')   // colour codes in Playwright errors
// A Django debug page is reduced to its <title> ("TypeError at /api/...").
const htmlTitle = s => { const m = /<title>([\s\S]*?)<\/title>/i.exec(s); return m ? `[HTML] ${m[1].trim()}` : s }
export const scrub = s => htmlTitle(String(s ?? ''))
  .replace(ANSI, '')
  .replace(/\d{8,}/g, '#')
  .replace(/\s+/g, ' ')
  .trim()
  .slice(0, 400)

/** First key in `keys` whose expectations allow module:action (null if none). */
export const firstWho = (keys, module, action) => keys.find(k => can(k, module, action)) ?? null
/** First key in `keys` whose expectations do NOT allow module:action. */
export const firstNot = (keys, module, action) => keys.find(k => !can(k, module, action)) ?? null

/** A page signed in as `key`, in its own context. Call `close()` when done. */
export async function asUser(browser, key, contextOptions = {}) {
  const context = await browser.newContext({ storageState: stateFile(key), locale: 'ar-EG', ...contextOptions })
  // D-25: the app's checks are inline now (bottom bar / press-twice buttons); answer them like the
  // old native dialogs were — confirm, and type the UAT answer into an input. Any native dialog
  // still left in the app is accepted as before.
  await context.addInitScript(installInlineConfirmAnswerer, `UAT-${WS} done`)
  const page = await context.newPage()
  page.on('dialog', d => d.accept(d.type() === 'prompt' ? `UAT-${WS} done` : undefined).catch(() => {}))
  // The app refreshes the session in this context (refresh tokens rotate): write the new cookies
  // back so the next context opened for this role does not start from a spent refresh token.
  const close = async () => {
    const st = await context.storageState().catch(() => null)
    if (st?.cookies?.some(c => c.name === 'erp_refresh')) fs.writeFileSync(stateFile(key), JSON.stringify(st))
    await context.close()
  }
  return { page, api: page.request, close }
}

/** Run one journey step; on failure write a P1 workflow finding naming the screen and the error. */
export async function step(key, route, name, fn) {
  try {
    return await fn()
  } catch (e) {
    finding({ ws: WS, key, route, kind: 'workflow', severity: 'P1',
              expected: `${name}: works for ${key}`, actual: scrub(e?.message || e) })
    throw e
  }
}

/** Wait for the API response a click causes; returns {status, body}. Throws with the server's words on >=400. */
export async function clickFor(page, locator, urlRe, method = 'POST', okStatuses = [200, 201, 202, 204]) {
  const resP = page.waitForResponse(r => urlRe.test(r.url()) && r.request().method() === method, { timeout: 60_000 })
  await locator.click()
  const res = await resP
  const text = await res.text().catch(() => '')
  let body = null
  try { body = JSON.parse(text) } catch { body = text }
  if (!okStatuses.includes(res.status())) {
    throw new Error(`${method} ${new URL(res.url()).pathname} → HTTP ${res.status()}: ${scrub(text)}`)
  }
  return { status: res.status(), body }
}

/** API call through a role's own session; throws with the server's words when not 2xx. */
export async function call(api, method, url, data) {
  const res = await api.fetch(url, { method, data, headers: XHR })
  const text = await res.text().catch(() => '')
  if (res.status() === 401) throw new Error(`session expired for this role (401) on ${url}`)
  if (res.status() >= 300) throw new Error(`${method} ${url} → HTTP ${res.status()}: ${scrub(text)}`)
  try { return JSON.parse(text) } catch { return text }
}

/**
 * The server must refuse `key` doing `what`. 403/404/405 = refused (404 = not in its scope).
 * Anything else (2xx, or 400 = it got past the permission check) → P1 workflow finding.
 * `alsoRefused` (e.g. [400]) only where the server's scope rule is a validation error by design.
 */
export async function mustRefuse(api, { key, route, what, method, url, data, alsoRefused = [] }) {
  const res = await api.fetch(url, { method, data, headers: XHR })
  const s = res.status()
  if (s === 401) throw new Error(`session expired for ${key} (401) - refusal not proven: ${what}`)
  const refused = [403, 404, 405, ...alsoRefused].includes(s)
  if (!refused) {
    const text = await res.text().catch(() => '')
    finding({ ws: WS, key, route, kind: 'workflow', severity: 'P1',
              expected: `${key} is refused: ${what}`,
              actual: `HTTP ${s} ${scrub(text)}` })
  }
  expect.soft(refused, `${key} must be refused: ${what} (got HTTP ${s})`).toBe(true)
  return s
}

/** Pick a branch in the shared <BranchSelect> whose trigger shows `placeholder`. */
export async function pickBranch(page, placeholder, code) {
  await page.getByText(placeholder, { exact: true }).first().click()
  await page.getByPlaceholder('ابحث بالكود أو الاسم...').fill(code)
  await page.locator('div.cursor-pointer', { has: page.locator('span.font-mono', { hasText: new RegExp(`^${code}$`) }) })
    .first().click()
}

/** The input/select/textarea in the innermost block that holds a <label> with this exact text. */
export function field(scope, labelText, sel = 'input, select, textarea') {
  const page = typeof scope.page === 'function' ? scope.page() : scope   // a Locator or the Page
  return scope.locator('div', { has: page.locator('label', { hasText: labelText }) })
    .last().locator(sel).first()
}
