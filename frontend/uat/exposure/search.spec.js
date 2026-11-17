// W4 — search boxes (customers list search, analytics customer search, universal search behind
// Ctrl+K, call-center phone lookup). B-2: a NAME search finds own customers only; a FULL phone
// finds any customer, but another branch's numbers come back masked.
import { test } from '@playwright/test'
import { stateFile } from '../lib/users.js'
import { phoneDigits } from '../lib/expected.js'
import { gotoSettled } from '../lib/page.js'
import { EXPOSURE_USERS, sees, DOMAINS } from './rules.js'
import { captureJson, pageText, checkPhones, refCustomers, branchLeak, api } from './scan.js'
import { guardBackend, keepSignedIn } from './alive.js'

const NAME_ENDPOINTS = [
  q => `/api/customers/?search=${encodeURIComponent(q)}`,
  q => `/api/search/universal?q=${encodeURIComponent(q)}`,
  q => `/api/analytics/customer-search/?q=${encodeURIComponent(q)}&limit=20`,
]
const PHONE_ENDPOINTS = [
  ...NAME_ENDPOINTS,
  q => `/api/callcenter/calls/lookup/?phone=${encodeURIComponent(q)}`,
]
const label = u => u.split('?')[0]
const dbg = (...a) => { if (process.env.W4_DEBUG) console.log('[w4]', ...a) }

/** Is customer `c` among the results of `json` (by id or PIC)? */
function contains(json, c) {
  let found = false
  const walk = v => {
    if (found || v == null || typeof v !== 'object') return
    if (Array.isArray(v)) return v.forEach(walk)
    if (String(v.id) === String(c.id) || (c.pic && (v.softech_pic === c.pic || v.pic === c.pic))) { found = true; return }
    Object.values(v).forEach(walk)
  }
  walk(json)
  return found
}

const distinctive = list => [...list].filter(c => (c.name || '').trim().split(/\s+/).length >= 2)
  .sort((a, b) => b.name.length - a.name.length)

guardBackend()

for (const key of EXPOSURE_USERS) {
  test.describe(`exposure search as ${key}`, () => {
    test.use({ storageState: stateFile(key) })
    keepSignedIn(key)
    const all = refCustomers()
    const unseen = all.filter(c => !sees(key, c.branch))
    const own = all.filter(c => sees(key, c.branch))

    test(`${key} name search finds own customers only`, async ({ page }) => {
      await gotoSettled(page, '/dashboard')
      for (const c of distinctive(unseen).slice(0, 3)) {
        for (const ep of NAME_ENDPOINTS) {
          const url = ep(c.name)
          const res = await api(page, 'GET', url)
          if (!res.ok()) continue
          const json = await res.json().catch(() => null)
          dbg(key, 'name', label(url), res.status(), c.branch, 'found', contains(json, c))
          if (contains(json, c)) {
            branchLeak(key, label(url), `absent (${DOMAINS.search.src})`, `name search returned branch-${c.branch} customer PIC ${c.pic}`)
          }
          checkPhones({ key, domain: 'search', route: label(url), bodies: [{ url, json }] })
        }
      }
    })

    test(`${key} full-phone search masks other branches`, async ({ page }) => {
      await gotoSettled(page, '/dashboard')
      for (const c of [...unseen.slice(0, 3), ...own.slice(0, 2)]) {
        const q = phoneDigits(c.phone)
        for (const ep of PHONE_ENDPOINTS) {
          const url = ep(q)
          const res = await api(page, 'GET', url)
          dbg(key, 'phone', label(url), res.status(), c.branch)
          if (!res.ok()) continue
          const json = await res.json().catch(() => null)
          dbg(key, 'phone', label(url), 'found', contains(json, c), 'maskedTail', new RegExp(`[•*●]{3,}${c.tail}`).test(JSON.stringify(json)))
          if (json && typeof json === 'object' && !Array.isArray(json) && url.includes('/calls/lookup/')) delete json.phone  // the typed number echoed
          const domain = url.includes('/calls/lookup/') ? 'callcenter' : 'search'
          checkPhones({ key, domain, route: label(url), bodies: [{ url, json }], overMask: contains(json, c) ? [c] : [] })
        }
      }
    })

    test(`${key} Ctrl+K palette`, async ({ page }) => {
      await gotoSettled(page, '/dashboard')
      const input = page.getByPlaceholder('ابحث عن صنف، عميل، طلب، حجز… أو اكتب أمرًا')
      const tries = [
        ...distinctive(unseen).slice(0, 2).map(c => ({ c, q: c.name, byPhone: false })),
        ...unseen.slice(0, 2).map(c => ({ c, q: phoneDigits(c.phone), byPhone: true })),
      ]
      for (const { c, q, byPhone } of tries) {
        await page.keyboard.press('Control+k')
        if (!(await input.isVisible().catch(() => false))) {
          await page.keyboard.press('Control+K')
          if (!(await input.isVisible().catch(() => false))) return   // palette not offered to this user
        }
        const cap = captureJson(page)
        await input.fill(q)
        await page.waitForResponse(r => r.url().includes('/api/search/universal'), { timeout: 20_000 }).catch(() => {})
        await page.waitForTimeout(800)
        const text = await pageText(page)
        const bodies = await cap.done()
        const uni = bodies.filter(b => b.url.includes('/api/search/universal') && b.json)
        if (!byPhone && uni.some(b => contains(b.json, c))) {
          branchLeak(key, 'Ctrl+K', `absent (${DOMAINS.search.src})`, `name search returned branch-${c.branch} customer PIC ${c.pic}`)
        }
        checkPhones({ key, domain: 'search', route: 'Ctrl+K', text, bodies, textMayEcho: byPhone })
        await page.keyboard.press('Escape')
      }
    })
  })
}
