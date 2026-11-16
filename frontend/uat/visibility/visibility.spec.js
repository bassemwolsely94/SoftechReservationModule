/* global __dirname, process */
// W2 — visibility sweep: every screen × every UAT user (plan Task 6, design §5.2 / §7.1).
//
// Routes: every <Route path> in src/App.jsx ∪ navGroups.js items ∪ the mobile /m tabs (routes.js).
// `:param` routes run only with an id from reference(<user's branch>); the rest are listed as skipped.
// Per user × route: is its menu entry shown (navItemVisible / the MobileLayout tab rule, with the
// user's /api/auth/me/ caps and the exported expected perms = can(key, module, 'view')), what
// gotoSettled() saw, console/API errors and ms.
//
// "Refused" = gotoSettled's refusal, a redirect to a landing screen (/dashboard, /m/me, /rider…), or
// a screen that opens but whose own data APIs all answer 403 (served = 'refused'). Layout calls
// (seen on >= 40 % of one surface's visits) are not "own data" (matrix shellApis).
// Verdicts (findings via finding(), ws 'W2'):
//   crash (page error / 5xx)                           → P1 crash
//   menu hidden, own data APIs answer 2xx, not in KNOWN_GAPS → P1 screen   (in KNOWN_GAPS → pass, owner-accepted 2026-11-06)
//   menu shown, screen refused                         → P2 screen  (P3 when the entry is only a parent: /finance → /finance/coa)
//   blank, or a loading text still on screen ('stuck') → P2 screen
//   menu hidden, screen opens but serves no data       → P3 screen  (not a clean refusal; nothing leaks)
//   slow (> 5000 ms or never settled)                  → P3 slow, on top of any other verdict
//   hidden + refused, shown + renders, no menu entry   → pass
//
// Output: test-results-uat/visibility-matrix.json, rewritten after each user (users merged by key):
// {
//   updatedAt: ISO, webPort, capMs, slowMs, branches: {A, B},
//   skipped: [{route, reason}],                        // :param / public routes not visited
//   users: {
//     [key]: { role, shape, branch, at: ISO, durationMs, shellApis: {desk|m|rider: [apiPath]},
//       rows: { [route]: { status: 'ok'|'slow'|'refused'|'blank'|'stuck'|'crash', raw: <gotoSettled status>,
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
import { UAT_USERS, stateFile, safeKey, BRANCH_A, BRANCH_B } from '../lib/users.js'
import { expectedFor, can, reference } from '../lib/expected.js'
import { gotoSettled } from '../lib/page.js'
import { finding } from '../lib/findings.js'
import { KNOWN_GAPS } from '../../e2e/knownGaps.js'
import { sweepRoutes, menuEntryFor, menuShown } from './routes.js'

const CAP_MS = 60_000
const SLOW_MS = 5_000
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
// Calls any screen may make that say nothing about the screen's own data (pickers, badges, help).
const GENERIC_API = /^\/api\/(auth|config|access\/whoami|audit\/screen-view|help|users\/my-permissions|notifications|sync\/(status|freshness)|branches|counselling\/status|personal)(\/|$)/
const apiKey = u => u.replace(/^https?:\/\/[^/]+/, '').split('?')[0].replace(/\/\d+(?=\/|$)/g, '/:n')

/**
 * status: gotoSettled's ok/slow/refused/blank/crash, or 'stuck' (a loading text still on screen).
 * served: what the screen's own data APIs did (layout calls seen on most screens are excluded):
 *   'data' ≥1 answered 2xx · 'refused' none 2xx and ≥1 answered 403 · 'none' no data API ran.
 */
function judge({ status, served, menu, inherited, knownGap }) {
  if (status === 'crash') return { verdict: 'P1', kind: 'crash', severity: 'P1', reason: 'crash',
    expected: 'screen renders or is refused cleanly', actual: 'page error or 5xx' }
  if (status === 'stuck' && served === 'refused') {
    if (menu === true) return { verdict: inherited ? 'P3' : 'P2', kind: 'screen', severity: inherited ? 'P3' : 'P2', reason: 'shown but refused',
      expected: 'menu entry shown → screen opens', actual: 'data APIs answer 403 and the screen keeps loading' }
    return { verdict: 'P3', kind: 'screen', severity: 'P3', reason: 'refused without saying so',
      expected: 'refused screen says so', actual: 'data APIs answer 403 but the screen keeps loading' }
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

for (const u of users) {
  test.describe(`visibility: ${u.key}`, () => {
    test.use({ storageState: stateFile(u.key) })

    test(`every screen for ${u.key} (${u.role})`, async ({ page }) => {
      test.setTimeout(4 * 60 * 60_000)
      const t0 = Date.now()
      const { routes, skipped } = sweepRoutes(reference(branchLetter(u)))
      const list = routes.filter(r => !onlyRoutes.length || onlyRoutes.some(p => r.route === p || r.route.startsWith(p + '/')))

      let meRes = await page.request.get('/api/auth/me/')
      if (meRes.status() !== 200) { await page.goto('/'); meRes = await page.request.get('/api/auth/me/') }
      const me = meRes.status() === 200 ? await meRes.json() : {}
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
        visit++; seen = []
        const r = await gotoSettled(page, route, { capMs: CAP_MS, slowMs: SLOW_MS })
        const text = await page.locator('main, #root').first().innerText().catch(() => '')
        const wanted = route.split('?')[0]
        let status = r.status
        // A redirect to a landing screen is the app's refusal (RequireRole / RiderHome / mobile guards).
        if (['ok', 'slow', 'blank'].includes(status) && r.finalUrl !== wanted && LANDING.test(r.finalUrl) && !LANDING.test(wanted)) status = 'refused'
        else if (['ok', 'slow'].includes(status) && LOADING.test(text)) status = 'stuck'
        let evidence
        if (!['ok', 'slow', 'refused'].includes(status)) evidence = await shot(page, u.key, route)
        raw.push({ route, r, status, apis: seen, evidence })
      }

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
          status, raw: r.status, served, ms: r.ms, finalUrl: r.finalUrl, menu: shown, menuPath, inherited,
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
        if (r.status === 'slow' || r.ms > SLOW_MS) {
          finding({ ws: 'W2', key: u.key, route, kind: 'slow', severity: 'P3',
                    expected: `settles within ${SLOW_MS} ms`,
                    actual: r.ms >= CAP_MS - 1000 ? `not settled after ${r.ms} ms` : `${r.ms} ms` })
        }
      }

      writeMatrix(u.key, { role: u.role, shape: u.shape, branch: u.branch, at: new Date().toISOString(),
                           durationMs: Date.now() - t0, shellApis: Object.fromEntries(Object.entries(shell).map(([k, v]) => [k, [...v]])),
                           rows }, skipped)
    })
  })
}

async function shot(page, key, route) {
  fs.mkdirSync(SHOTS, { recursive: true })
  const file = path.join(SHOTS, `${safeKey(key)}${route.replace(/[^a-zA-Z0-9]+/g, '_')}.png`)
  try { await page.screenshot({ path: file }) } catch { return undefined }
  return path.relative(path.resolve(OUT_DIR, '..'), file)
}
// Judged after the loop, so the page has moved on: reopen briefly for the picture.
async function shotAgain(page, key, route) {
  await page.goto(route, { waitUntil: 'domcontentloaded', timeout: CAP_MS }).catch(() => {})
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  return shot(page, key, route)
}
