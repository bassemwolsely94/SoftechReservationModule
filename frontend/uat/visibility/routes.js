/* global __dirname */
// W2 route list, generated from the code (never hand-kept):
//   every <Route path> in src/App.jsx (nesting resolved) ∪ every side-menu item in navGroups.js
//   ∪ the mobile bottom tabs (MOBILE_TABS in App.jsx).
// `:param` routes are kept only when the UAT reference set gives an id for that record type.
import fs from 'node:fs'
import path from 'node:path'
import { NAV_GROUPS, navItemVisible } from '../../src/components/navGroups.js'
import { MOBILE_RESERVATION_ROLES, MOBILE_TRANSFER_ROLES } from '../../src/pages/mobile/mobileAccess.js'

const APP = fs.readFileSync(path.resolve(__dirname, '..', '..', 'src', 'App.jsx'), 'utf-8')

// Screens outside the staff app (public tokens, customer portal, the login screen itself).
const OUT_OF_SCOPE = [/^\/login$/, /^\/notify$/, /^\/portal(\/|$)/, /^\/track\//, /^\/c\//, /\*/]

/** Text of a JSX tag with every {…} block removed (so JSX inside element={…} is ignored). */
function stripBraces(tag) {
  let out = '', depth = 0, quote = null
  for (const c of tag) {
    if (depth > 0) {
      if (quote) { if (c === quote) quote = null; continue }
      if (c === '"' || c === "'" || c === '`') { quote = c; continue }
      if (c === '{') depth++
      else if (c === '}') depth--
      continue
    }
    if (c === '{') { depth = 1; continue }
    out += c
  }
  return out
}

/** All <Route> paths in App.jsx with their parents joined. A tag ends at the first '>' outside
 *  braces/strings, so the JSX inside element={…} (full of '>') never ends it early. */
export function appRoutes(src = APP) {
  const out = []
  const stack = []          // full paths of the open (non-self-closing) <Route>s
  let i = 0
  for (;;) {
    const open = src.indexOf('<Route', i)
    const close = src.indexOf('</Route>', i)
    if (open < 0 && close < 0) break
    if (close >= 0 && (open < 0 || close < open)) { stack.pop(); i = close + 8; continue }
    if (!/[\s/>]/.test(src[open + 6])) { i = open + 6; continue }      // <Routes>
    let j = open + 6, depth = 0, quote = null
    for (; j < src.length; j++) {
      const c = src[j]
      if (quote) { if (c === quote) quote = null; continue }
      if (c === '"' || c === "'" || c === '`') { quote = c; continue }
      if (c === '{') depth++
      else if (c === '}') depth--
      else if (c === '>' && depth === 0) break
    }
    const tag = src.slice(open, j + 1)
    const m = stripBraces(tag).match(/\spath="([^"]*)"/)
    const parent = stack.length ? stack[stack.length - 1] : ''
    const own = m ? m[1] : ''
    const full = '/' + (own.startsWith('/') ? own : `${parent}/${own}`).split('/').filter(Boolean).join('/')
    if (m) out.push(full)
    if (src[j - 1] !== '/') stack.push(m ? full : parent)
    i = j + 1
  }
  return [...new Set(out)]
}

/** MOBILE_TABS from App.jsx, evaluated with the same role constants App imports. */
export function mobileTabs(src = APP) {
  const start = src.indexOf('const MOBILE_TABS = [')
  const end = src.indexOf('\n]', start)
  const literal = src.slice(start + 'const MOBILE_TABS = '.length, end + 2)
  // reads our own App.jsx literal, never outside input
  return new Function('MOBILE_RESERVATION_ROLES', 'MOBILE_TRANSFER_ROLES', `return ${literal}`)(
    MOBILE_RESERVATION_ROLES, MOBILE_TRANSFER_ROLES)
}

export const NAV_ITEMS = NAV_GROUPS.flatMap(g => g.items)
export const MOBILE_TABS = mobileTabs()

/** Same rule as MobileLayout's visibleTabs filter. */
export function mobileTabVisible(tab, { role, user, perms }) {
  return (!tab.roles || tab.roles.includes(role)) && (!tab.feature || !!user?.features?.[tab.feature])
    && (!tab.module || !perms || role === 'admin' || !!perms[tab.module]?.view)
}

/** The menu entry that leads to `route`: the exact item, else the longest item path that is a
 *  prefix of it (/finance/coa → /finance). Mobile routes look in MOBILE_TABS. null = no menu entry. */
export function menuEntryFor(route) {
  const pathOnly = route.split('?')[0]
  const isMobile = pathOnly === '/m' || pathOnly.startsWith('/m/')
  const list = isMobile ? MOBILE_TABS : NAV_ITEMS
  const exact = list.find(it => it.to === route)
  if (exact) return { item: exact, mobile: isMobile }
  let best = null
  for (const it of list) {
    if (it.to.includes('?')) continue
    if (pathOnly === it.to || pathOnly.startsWith(it.to + '/')) {
      if (!best || it.to.length > best.to.length) best = it
    }
  }
  return best ? { item: best, mobile: isMobile } : null
}

/** Is the menu entry for `route` shown to this user? true / false / null (no entry). */
export function menuShown(route, ctx) {
  const e = menuEntryFor(route)
  if (!e) return { shown: null, menuPath: null }
  const shown = e.mobile ? mobileTabVisible(e.item, ctx) : navItemVisible(e.item, ctx)
  return { shown, menuPath: e.item.to }
}

// `:param` → which reference list gives an id, and how to read the id from an entry.
const PARAMS = [
  [/^\/(m\/)?reservations\/:id$/, 'reservations'],
  [/^\/(m\/)?transfers\/:id$/, 'transfers'],
  [/^\/(m\/)?demand\/:id$/, 'demand'],
  [/^\/m\/shortage\/:id$/, 'shortage'],
  [/^\/customers\/:id$/, 'customers'],
]
const idOf = x => (x && typeof x === 'object' ? x.id : x)

/**
 * The sweep's route list for one reference branch.
 * @returns {{routes: Array<{route: string, sources: string[]}>, skipped: Array<{route: string, reason: string}>}}
 */
export function sweepRoutes(ref) {
  const sources = new Map()
  const add = (r, s) => { if (!sources.has(r)) sources.set(r, new Set()); sources.get(r).add(s) }
  for (const r of appRoutes()) add(r, 'app')
  for (const it of NAV_ITEMS) add(it.to, 'nav')
  for (const t of MOBILE_TABS) add(t.to, 'mobile')
  const routes = [], skipped = []
  for (const [r, s] of sources) {
    if (r === '/' || OUT_OF_SCOPE.some(re => re.test(r))) { skipped.push({ route: r, reason: 'outside the staff app' }); continue }
    if (!r.includes(':')) { routes.push({ route: r, sources: [...s] }); continue }
    const p = PARAMS.find(([re]) => re.test(r))
    const id = p && idOf(ref?.[p[1]]?.[0])
    if (id == null) { skipped.push({ route: r, reason: p ? `no ${p[1]} id in the reference set` : 'no id source' }); continue }
    routes.push({ route: r.replace(':id', String(id)), pattern: r, sources: [...s] })
  }
  return { routes, skipped }
}
