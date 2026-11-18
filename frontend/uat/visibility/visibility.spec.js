/* global __dirname, process */
// W2 — visibility sweep: every screen × every UAT user (plan Task 6, design §5.2 / §7.1).
//
// Routes: every <Route path> in src/App.jsx ∪ navGroups.js items ∪ the mobile /m tabs (routes.js).
// `:param` routes run only with an id from reference(<user's branch>); the rest are listed as skipped.
// Per user × route: is its menu entry shown (navItemVisible / the MobileLayout tab rule, with the
// user's /api/auth/me/ caps and the exported expected perms = can(key, module, 'view')), what
// openScreen() saw (time to first content or refusal, not to network idle), console/API errors and ms.
//
// "Refused" = refusal text or a 403 on a near-empty screen, a redirect to a landing screen (/dashboard, /m/me, /rider…), or
// a screen that opens but whose own data APIs all answer 403 (served = 'refused'). Layout calls
// (seen on >= 40 % of one surface's visits) are not "own data" (matrix shellApis).
// Verdicts (findings via finding(), ws 'W2'):
//   crash (page error / 5xx)                           → P1 crash   (page errors that are only unhandled 401/403
//                                                        rejections = 'unhandled403', a refusal that does not say so: P3 hidden / P2 shown)
//   menu hidden, own data APIs answer 2xx, not in KNOWN_GAPS → P1 screen   (in KNOWN_GAPS → pass, owner-accepted 2026-11-06)
//   menu shown, screen refused                         → P2 screen  (P3 when the entry is only a parent: /finance → /finance/coa)
//   blank, or a loading text still on screen 20 s after first content ('stuck') → P2 screen
//   menu hidden, screen opens but serves no data       → P3 screen  (not a clean refusal; nothing leaks)
//   slow (> 5000 ms to content)                → P3 slow, on top of any other verdict
//   hidden + refused, shown + renders, no menu entry   → pass
//
// Output: test-results-uat/visibility-matrix.json, rewritten after each user (users merged by key):
// {
//   updatedAt: ISO, webPort, capMs, slowMs, branches: {A, B},
//   skipped: [{route, reason}],                        // :param / public routes not visited
//   users: {
//     [key]: { role, shape, branch, at: ISO, durationMs, relogins, shellApis: {desk|m|rider: [apiPath]},
//       rows: { [route]: { status: 'ok'|'slow'|'refused'|'blank'|'stuck'|'unhandled403'|'crash'|'hang', raw: <openScreen status>,
//                          served: 'data'|'refused'|'none', ms, finalUrl,
//                          menu: true|false|null, menuPath, inherited: bool,
//                          canView: bool|null,             // can(key, item.module, 'view') when the menu item names a module
//                          knownGap: bool, verdict: 'pass'|'P1'|'P2'|'P3', reason,
//                          dataApis: ['<status> <path>'], consoleErrors: number, apiErrors: [{url, status}] } } } }
// }
//
// Dev filters (never commit narrowed): UAT_VIS_USERS=pharmacist,viewer  UAT_VIS_ROUTES=/finance,/m
import fs from 'node:fs'
import path from 'node:path'
import { test } from '@playwright/test'
import { UAT_USERS, stateFile, safeKey, BRANCH_A, BRANCH_B, userByKey, PASSWORD } from '../lib/users.js'
import { expectedFor, can, reference } from '../lib/expected.js'
import { finding } from '../lib/findings.js'
import { KNOWN_GAPS } from '../../e2e/knownGaps.js'
import { sweepRoutes, menuEntryFor, menuShown } from './routes.js'

// Time-to-content, not time-to-idle (run 3): lib gotoSettled waits for networkidle, which polling
// screens (bell, freshness, queue status) reach late or never: 125 min for one user. A visibility
// check only needs "rendered or refused", so openScreen() below waits for the FIRST of: content
// (main or an h1 with text, no spinner, no loading text), a refusal (refusal text, URL
// left the route, /login). CAP_MS bounds that wait; SETTLE_MS then collects late API errors.
// ms = time to that first signal; > SLOW_MS is 'slow'; no signal within CAP_MS = 'slow' at CAP_MS.
const CAP_MS = 20_000
const SLOW_MS = 5_000
const SETTLE_MS = 1_500
// Backstop per visit: past it the visit is a 'hang' finding and the sweep moves on.
const HANG_MS = 60_000
// One user's whole sweep (~10-15 min with openScreen); the chunk runner kills at 45 min.
const USER_TIMEOUT_MS = 40 * 60_000
const SPINNERS = '[aria-busy="true"], .animate-spin, [data-loading="true"]'
// Same refusal wording as lib/page.js (gotoSettled), which this spec no longer calls.
const REFUSED_TEXT = /غير مصرح|ليس لديك صلاحية|لا تملك صلاحية|403|Forbidden/
const OUT_DIR = path.resolve(__dirname, '..', '..', 'test-results-uat')
const MATRIX = path.join(OUT_DIR, 'visibility-matrix.json')
const SHOTS = path.join(OUT_DIR, 'visibility', 'shots')
const LANDING = /^\/(dashboard|login|rider|m|m\/me)\/?$/

const onlyUsers = (process.env.UAT_VIS_USERS || '').split(',').map(s => s.trim()).filter(Boolean)
const onlyRoutes = (process.env.UAT_VIS_ROUTES || '').split(',').map(s => s.trim()).filter(Boolean)
const users = UAT_USERS.filter(u => !onlyUsers.length || onlyUsers.includes(u.key))

const branchLetter = u => (String(u.branch) === String(BRANCH_B?.code) ? 'B' : 'A')
const clean = s => String(s).replace(/\d{8,}/g, '#')

function writeMatrix(key, entry, skipped) {
  let m = {}
  try { m = JSON.parse(fs.readFileSync(MATRIX, 'utf-8')) } catch { /* first user */ }
  m.updatedAt = new Date().toISOString()
  m.webPort = Number(process.env.UAT_WEB_PORT || 5200)
  m.capMs = CAP_MS; m.slowMs = SLOW_MS
  m.branches = { A: BRANCH_A?.code ?? null, B: BRANCH_B?.code ?? null }
  m.skipped = skipped
  m.users = { ...(m.users || {}), [key]: entry }
  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.writeFileSync(MATRIX, JSON.stringify(m, null, 1))
}

const LOADING = /جار[ٍِ]?\s*التحميل|Loading\.\.\./

/** Same return shape and status rules as lib gotoSettled, but timed to first content/refusal. */
async function openScreen(page, url) {
  const consoleErrors = []
  const apiErrors = []
  const onConsole = m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) }
  const onPageError = e => consoleErrors.push(`pageerror: ${String(e).slice(0, 300)}`)
  const onResponse = r => {
    if (r.url().includes('/api/') && r.status() >= 400) apiErrors.push({ url: r.url().replace(/^https?:\/\/[^/]+/, ''), status: r.status() })
  }
  const wanted = url.split('?')[0]
  page.on('console', onConsole); page.on('pageerror', onPageError); page.on('response', onResponse)
  const t0 = Date.now()
  let timedOut = false, ms, blocker, dataMs
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: CAP_MS })
    await page.waitForFunction(({ wanted, spin, refused, loading }) => {
      const p = location.pathname.replace(/\/$/, '') || '/'
      if (p !== (wanted.replace(/\/$/, '') || '/')) return true                     // redirected (refusal / landing / login)
      const root = document.querySelector('main') || document.querySelector('#root')
      const text = root ? root.innerText : ''
      if (new RegExp(refused).test(text)) return true                              // refusal text
      // main first: an icon-only (collapsed) nav rail [data-tour=shell-rail] precedes it with no text,
      // and querySelector('main, [data-tour], h1') returned that rail, so no screen ever "rendered"
      // for those users (run 4: 20 s on every desktop screen, users over the 40-min cap).
      const hasText = [document.querySelector('main'), ...document.querySelectorAll('h1')].some(e => e && e.innerText.trim().length > 0)
      return hasText && !document.querySelector(spin) && !new RegExp(loading).test(text)
    }, { wanted, spin: SPINNERS, refused: REFUSED_TEXT.source, loading: LOADING.source }, { timeout: CAP_MS, polling: 200 })
      .catch(() => { timedOut = true })
    ms = Date.now() - t0
    if (timedOut) blocker = await page.evaluate(({ spin, loading }) => {
      const sp = document.querySelector(spin)
      const main = document.querySelector('main')
      const m = (main?.innerText || '').match(new RegExp(loading))
      return [sp ? `spinner ${sp.tagName.toLowerCase()}.${String(sp.className).slice(0, 60)} in ${sp.closest('main') ? 'main' : (sp.closest('header,nav,aside')?.tagName.toLowerCase() || 'page')}` : '',
        m ? `loading text in main` : '', main ? `main text ${main.innerText.trim().length}` : 'no <main>',
        ...[...document.querySelectorAll('[data-tour], h1')].slice(0, 3).map(e => `${e.tagName.toLowerCase()}${e.dataset.tour ? '[' + e.dataset.tour + ']' : ''} text ${e.innerText.trim().length}`),
        `path ${location.pathname}`].filter(Boolean).join('; ')
    }, { spin: SPINNERS, loading: LOADING.source }).catch(() => 'page did not answer')
    await page.waitForTimeout(SETTLE_MS)
    // A section still saying "loading" after first content is usually a slower panel, not an
    // endless one (run 4b: 237 'stuck' rows, most with content in < 1 s). Give it up to CAP_MS to
    // clear; only a loading text still there after that is 'stuck'. dataMs = time until it cleared.
    if (!timedOut && LOADING.test(await page.locator('main').first().innerText({ timeout: 5_000 }).catch(() => ''))) {
      await page.waitForFunction(loading => !new RegExp(loading).test(document.querySelector('main')?.innerText || ''),
        LOADING.source, { timeout: CAP_MS, polling: 250 }).catch(() => {})
      dataMs = Date.now() - t0
    }
  } finally {
    page.off('console', onConsole); page.off('pageerror', onPageError); page.off('response', onResponse)
  }
  if (ms === undefined) ms = Date.now() - t0
  const finalUrl = new URL(page.url()).pathname
  const text = (await page.locator('main, #root').first().innerText({ timeout: 5_000 }).catch(() => '')).trim()
  const crashed = consoleErrors.some(e => e.startsWith('pageerror')) || apiErrors.some(e => e.status >= 500 && e.status !== 503)
  let status
  if (crashed) status = 'crash'
  else if (REFUSED_TEXT.test(text) || apiErrors.some(e => e.status === 403) && text.length < 200 ||
           (finalUrl !== new URL(url, 'http://x').pathname && /\/(dashboard|login|rider|m)$/.test(finalUrl))) status = 'refused'
  else if (timedOut) status = 'slow'
  else if (text.length < 20) status = 'blank'
  else status = ms > SLOW_MS ? 'slow' : 'ok'
  return { ms, status, consoleErrors, apiErrors, finalUrl, blocker, dataMs }
}// Calls any screen may make that say nothing about the screen's own data (pickers, badges, help).
const GENERIC_API = /^\/api\/(auth|config|access\/whoami|audit\/screen-view|help|users\/my-permissions|notifications|sync\/(status|freshness)|branches|counselling\/status|personal)(\/|$)/
const apiKey = u => u.replace(/^https?:\/\/[^/]+/, '').split('?')[0].replace(/\/\d+(?=\/|$)/g, '/:n')

/**
 * status: gotoSettled's ok/slow/refused/blank/crash, or 'stuck' (a loading text still on screen).
 * served: what the screen's own data APIs did (layout calls seen on most screens are excluded):
 *   'data' ≥1 answered 2xx · 'refused' none 2xx and ≥1 answered 403 · 'none' no data API ran.
 */
function judge({ status, served, menu, inherited, knownGap }) {
  if (status === 'hang') return { verdict: 'P2', kind: 'slow', severity: 'P2', reason: 'hang',
    expected: `screen settles or is refused within ${HANG_MS} ms`, actual: `the visit had not returned after ${HANG_MS} ms; visit abandoned` }
  if (status === 'crash') return { verdict: 'P1', kind: 'crash', severity: 'P1', reason: 'crash',
    expected: 'screen renders or is refused cleanly', actual: 'page error or 5xx' }
  if ((status === 'stuck' && served === 'refused') || status === 'unhandled403') {
    const how = status === 'stuck' ? 'the screen keeps loading' : 'an unhandled 403 error leaves an empty screen'
    if (menu === true) return { verdict: inherited ? 'P3' : 'P2', kind: 'screen', severity: inherited ? 'P3' : 'P2', reason: 'shown but refused',
      expected: 'menu entry shown → screen opens', actual: `data APIs answer 403 and ${how}` }
    return { verdict: 'P3', kind: 'screen', severity: 'P3', reason: 'refused without saying so',
      expected: 'refused screen says so', actual: `data APIs answer 403 but ${how}` }
  }
  if (status === 'stuck') return { verdict: 'P2', kind: 'screen', severity: 'P2', reason: 'endless loading',
    expected: 'screen settles (data or a clean refusal)', actual: 'still loading after settle' }
  if (status === 'blank') return { verdict: 'P2', kind: 'screen', severity: 'P2', reason: 'blank',
    expected: 'screen renders or is refused cleanly', actual: 'blank page' }
  const refused = status === 'refused' || served === 'refused'
  if (menu === true && refused) {
    const sev = inherited ? 'P3' : 'P2'
    return { verdict: sev, kind: 'screen', severity: sev, reason: 'shown but refused',
      expected: inherited ? 'screen under a shown menu entry opens' : 'menu entry shown → screen opens',
      actual: status === 'refused' ? 'refused' : 'opens but its data APIs answer 403' }
  }
  if (menu === false && !refused && served === 'data') {
    if (knownGap) return { verdict: 'pass', reason: 'hidden but served — owner-accepted KNOWN_GAPS pair' }
    return { verdict: 'P1', kind: 'screen', severity: 'P1', reason: 'hidden but served',
      expected: 'menu entry hidden → direct URL refused', actual: 'renders and its data APIs answer 2xx' }
  }
  if (menu === false && !refused) return { verdict: 'P3', kind: 'screen', severity: 'P3', reason: 'hidden screen opens without data',
    expected: 'menu entry hidden → direct URL refused', actual: 'screen shell opens (no data API served)' }
  return { verdict: 'pass', reason: menu === null ? 'no menu entry' : (refused ? 'hidden + refused' : 'shown + renders') }
}

// Session + backend guard (same approach as W4's exposure/alive.js keepSignedIn/guardBackend).
// Access tokens live 1 h and refresh tokens rotate + blacklist, while each user's sweep runs well
// over an hour from one saved login: without this, later screens open on /login and are recorded
// as "refused", passing with nothing checked. Before every visit: /api/auth/me/ must be 200,
// else refresh, else sign in again through the login API (cookies, so the SPA picks it up). A
// backend that does not answer (or 5xx on me/) throws: the user's test fails and its rows are not
// written, so a down server is never counted as refusals.
const HDR = { 'X-Requested-With': 'XMLHttpRequest' }
async function meStatus(page) {
  try { return (await page.request.get('/api/auth/me/', { headers: HDR, timeout: 15_000 })).status() } catch { return 0 }
}
async function ensureSignedIn(page, key, when) {
  let s = await meStatus(page)
  if (s === 200) return false
  // The shared server runs under a watchdog that restarts it within seconds: ride out a short gap,
  // but a backend down for over a minute fails the test (reported, never counted as refusals).
  for (let waited = 0; (s === 0 || s >= 500) && waited < 60_000; waited += 5_000) {
    await page.waitForTimeout(5_000)
    s = await meStatus(page)
  }
  if (s === 200) return false
  if (s === 0 || s >= 500) throw new Error(`UAT backend not answering ${when} for over a minute (status ${s || 'refused'}); this run does not count`)
  await page.request.post('/api/auth/refresh/', { headers: HDR }).catch(() => null)
  if ((s = await meStatus(page)) !== 200) {
    const r = await page.request.post('/api/auth/login/', {
      headers: HDR, data: { username: userByKey(key).username, password: PASSWORD } }).catch(() => null)
    if ((s = await meStatus(page)) !== 200) throw new Error(`${key}: could not sign in again ${when} (login ${r?.status() ?? 'failed'}, me ${s}); this run does not count`)
  }
  await page.context().storageState({ path: stateFile(key) })
  return true
}

// No trace: a failed multi-hour test produced a 600 MB+ trace whose saving wedged Playwright for
// 17 h (run 2). Screenshots are the evidence.
test.use({ trace: 'off' })

for (const u of users) {
  test.describe(`visibility: ${u.key}`, () => {
    test.use({ storageState: stateFile(u.key) })

    test(`every screen for ${u.key} (${u.role})`, async ({ page }) => {
      test.setTimeout(USER_TIMEOUT_MS)
      // openScreen with a hard stop; a hung visit is abandoned (page sent to about:blank).
      const visitOnce = async route => {
        let timer
        // Unload the previous screen first: at ~1 s per visit it is still firing requests (and could
        // throw page errors) while the next navigation starts, which were then counted for the new
        // screen (run 3 dev: purchasing/QA calls credited to /finance/pnl as "served data").
        await page.goto('about:blank', { timeout: 15_000 }).catch(() => {})
        const go = openScreen(page, route)
        const hang = new Promise(res => { timer = setTimeout(() => res(null), HANG_MS) })
        const r = await Promise.race([go, hang])
        clearTimeout(timer)
        if (r) return r
        go.catch(() => {})
        await page.goto('about:blank', { timeout: 30_000 }).catch(() => {})
        return { ms: HANG_MS, status: 'hang', consoleErrors: [], apiErrors: [], finalUrl: route.split('?')[0] }
      }
      const t0 = Date.now()
      const { routes, skipped } = sweepRoutes(reference(branchLetter(u)))
      const list = routes.filter(r => !onlyRoutes.length || onlyRoutes.some(p => r.route === p || r.route.startsWith(p + '/')))

      await ensureSignedIn(page, u.key, 'at start')
      const me = await (await page.request.get('/api/auth/me/', { headers: HDR })).json()
      let relogins = 0
      const ctx = { role: u.role, user: me, perms: expectedFor(u.key).perms }

      // Every /api/ answer to a request made during this visit (gotoSettled keeps only the errors).
      // Requests are tagged when sent, so a late answer to the previous screen is not counted here.
      let visit = 0, seen = []
      const sentIn = new WeakMap()
      page.on('request', q => sentIn.set(q, visit))
      page.on('response', r => {
        if (sentIn.get(r.request()) !== visit) return
        const p = new URL(r.url()).pathname
        if (p.startsWith('/api/') && !GENERIC_API.test(p)) seen.push({ key: apiKey(r.url()), status: r.status() })
      })

      // Pass 1: visit everything.
      const raw = []
      for (const { route } of list) {
        if (await ensureSignedIn(page, u.key, `before ${route}`)) relogins++
        visit++; seen = []
        let r = await visitOnce(route)
        // Landed on /login: the session lapsed mid-visit. Sign in again and visit once more; a
        // second /login is a lost session (throws), never a "refused" row.
        if (/^\/login\/?$/.test(r.finalUrl) && route !== '/login') {
          if (!(await ensureSignedIn(page, u.key, `after ${route}`))) throw new Error(`${u.key}: ${route} sent a signed-in user to /login; this run does not count`)
          relogins++; visit++; seen = []
          r = await visitOnce(route)
          if (/^\/login\/?$/.test(r.finalUrl)) throw new Error(`${u.key}: session lost again on ${route}; this run does not count`)
        }
        const text = await page.locator('main, #root').first().innerText({ timeout: 5_000 }).catch(() => '')
        const wanted = route.split('?')[0]
        let status = r.status
        // A redirect to a landing screen is the app's refusal (RequireRole / RiderHome / mobile guards).
        if (['ok', 'slow', 'blank'].includes(status) && r.finalUrl !== wanted && LANDING.test(r.finalUrl) && !LANDING.test(wanted)) status = 'refused'
        else if (['ok', 'slow'].includes(status) && LOADING.test(text)) status = 'stuck'
        // gotoSettled counts any page error as a crash. When every page error is an unhandled
        // 401/403 rejection and nothing answered 5xx, the server refused correctly and the screen
        // shows an empty state instead of saying so: judged like 'stuck' after a 403.
        else if (status === 'crash' && !r.apiErrors.some(e => e.status >= 500)) {
          const pageErrs = r.consoleErrors.filter(e => e.startsWith('pageerror'))
          if (pageErrs.length && pageErrs.every(e => /status code 40[13]\b/.test(e))) status = 'unhandled403'
        }
        let evidence
        if (!['ok', 'slow', 'refused', 'hang'].includes(status)) evidence = await shot(page, u.key, route)
        raw.push({ route, r, status, apis: seen, evidence })
        console.log(`[w2] ${u.key} ${raw.length}/${list.length} ${route} ${status} ${r.ms} ms${r.dataMs ? ' data ' + r.dataMs + ' ms' : ''} (+${Math.round((Date.now() - t0) / 1000)} s)${r.blocker ? ' [' + r.blocker + ']' : ''}`)
      }

      // Stop attributing: pass 2's evidence revisits (shotAgain) would otherwise be credited to the
      // last route's visit (seen run 3 dev: QA/purchasing calls landing on /finance/pnl).
      visit = -1; seen = []

      // Layout calls (menu badges, me, notifications …) = API paths seen on ≥ 40 % of the visits
      // of the same surface (desktop vs /m); what is left is each screen's own data.
      const surface = route => (route === '/m' || route.startsWith('/m/') ? 'm' : route.startsWith('/rider') ? 'rider' : 'desk')
      const shell = {}
      for (const sf of ['m', 'rider', 'desk']) {
        const visits = raw.filter(x => surface(x.route) === sf)
        const freq = new Map()
        for (const v of visits) for (const k of new Set(v.apis.map(a => a.key))) freq.set(k, (freq.get(k) || 0) + 1)
        shell[sf] = new Set([...freq].filter(([, n]) => visits.length >= 5 && n / visits.length >= 0.4).map(([k]) => k))
      }

      // Pass 2: judge, report.
      const rows = {}
      for (const x of raw) {
        const { route, r, status } = x
        const { shown, menuPath } = menuShown(route, ctx)
        const entry = menuEntryFor(route)
        const inherited = !!entry && entry.item.to !== route
        const mod = entry?.item?.module
        // A menu entry with a query (/vouchers?tab=coupons) shares its screen, and its owner decision, with the bare path.
        const knownGap = !!(menuPath && (KNOWN_GAPS[`${u.role} ${menuPath}`] || KNOWN_GAPS[`${u.role} ${menuPath.split("?")[0]}`]))
        const own = x.apis.filter(a => !shell[surface(route)].has(a.key))
        const served = own.some(a => a.status >= 200 && a.status < 300) ? 'data'
          : own.some(a => a.status === 403) ? 'refused' : 'none'
        const j = judge({ status, served, menu: shown, inherited, knownGap })
        rows[route] = {
          status, raw: r.status, served, ms: r.ms, dataMs: r.dataMs, finalUrl: r.finalUrl, menu: shown, menuPath, inherited,
          canView: mod ? can(u.key, mod, 'view') : null, knownGap, verdict: j.verdict, reason: j.reason,
          dataApis: [...new Set(own.map(a => `${a.status} ${clean(a.key)}`))].slice(0, 8),
          consoleErrors: r.consoleErrors.length,
          apiErrors: r.apiErrors.slice(0, 10).map(e => ({ url: clean(e.url).slice(0, 160), status: e.status })),
        }
        if (j.kind) {
          const errs = r.apiErrors.filter(e => e.status >= 500).map(e => `${e.status} ${clean(e.url).split('?')[0]}`)
          const okApis = own.filter(a => a.status < 300).map(a => clean(a.key))
          const pageErr = r.consoleErrors.find(e => e.startsWith('pageerror'))
          const detail = [j.actual,
            errs.length ? `api: ${errs.slice(0, 3).join(', ')}` : '',
            j.reason === 'hidden but served' ? `served: ${[...new Set(okApis)].slice(0, 3).join(', ')}` : '',
            pageErr ? clean(pageErr).slice(0, 160) : '',
            menuPath && menuPath !== route ? `menu entry ${menuPath}` : '', `${r.ms} ms`].filter(Boolean).join('; ')
          let evidence = x.evidence
          if (!evidence && (j.severity === 'P1' || j.severity === 'P2')) evidence = await shotAgain(page, u.key, route)
          finding({ ws: 'W2', key: u.key, route, kind: j.kind, severity: j.severity,
                    expected: j.expected, actual: clean(detail), ...(evidence ? { evidence } : {}) })
        }
        // Slow is reported on its own, on top of any other verdict.
        if (status !== 'hang' && (r.status === 'slow' || r.ms > SLOW_MS)) {
          finding({ ws: 'W2', key: u.key, route, kind: 'slow', severity: 'P3',
                    expected: `content or refusal within ${SLOW_MS} ms`,
                    actual: r.ms >= CAP_MS - 1000 ? `no content or refusal after ${r.ms} ms` : `${r.ms} ms to content` })
        }
      }

      writeMatrix(u.key, { role: u.role, shape: u.shape, branch: u.branch, at: new Date().toISOString(),
                           durationMs: Date.now() - t0, relogins, shellApis: Object.fromEntries(Object.entries(shell).map(([k, v]) => [k, [...v]])),
                           rows }, skipped)
    })
  })
}

async function shot(page, key, route) {
  fs.mkdirSync(SHOTS, { recursive: true })
  const file = path.join(SHOTS, `${safeKey(key)}${route.replace(/[^a-zA-Z0-9]+/g, '_')}.png`)
  try { await page.screenshot({ path: file, timeout: 15_000 }) } catch { return undefined }
  return path.relative(path.resolve(OUT_DIR, '..'), file)
}
// Judged after the loop, so the page has moved on: reopen briefly for the picture.
async function shotAgain(page, key, route) {
  await page.goto(route, { waitUntil: 'domcontentloaded', timeout: CAP_MS }).catch(() => {})
  await page.waitForTimeout(3_000)   // not networkidle: polling screens never reach it
  return shot(page, key, route)
}
