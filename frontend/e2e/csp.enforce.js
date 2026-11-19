// D-04: the enforced Content-Security-Policy breaks no screen.
// Run by playwright.csp.config.js against `vite preview` (the built bundle + the policy from
// deploy/nginx-csp.conf). Logs in as admin (sees every menu item), opens each screen and fails on any
// `securitypolicyviolation` event or CSP console error. Not named *.spec.js, so the main e2e run
// (Vite dev server, no CSP) never picks it up.
import { test, expect } from '@playwright/test'
import { PASSWORD, usernameOf } from './users.js'
import { NAV_GROUPS } from '../src/components/navGroups.js'

const SCREENS = [...new Set(NAV_GROUPS.flatMap(g => g.items).map(i => i.to.split('?')[0]))]
  .filter(p => !p.includes(':'))

test.describe.configure({ mode: 'serial' })

let page
const violations = []

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext()
  // Runs through CDP before any page script, so the page's own CSP does not apply to it.
  await context.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', e => {
      window.__cspViolations = window.__cspViolations || []
      window.__cspViolations.push(`${e.effectiveDirective} blocked ${e.blockedURI || '(inline)'}` +
        (e.sourceFile ? ` at ${e.sourceFile}:${e.lineNumber}` : ''))
    })
  })
  page = await context.newPage()
  page.on('console', msg => {
    if (msg.type() === 'error' && /Content Security Policy/i.test(msg.text())) {
      violations.push(`${page.url()} console: ${msg.text().slice(0, 300)}`)
    }
  })
})

test.afterAll(async () => { await page?.context().close() })

async function collect(where) {
  const found = await page.evaluate(() => {
    const v = window.__cspViolations || []
    window.__cspViolations = []
    return v
  }).catch(() => [])
  for (const v of found) violations.push(`${where}: ${v}`)
}

test('the SPA is served with the enforcing policy and its report URI', async () => {
  const res = await page.goto('/login')
  const headers = res.headers()
  expect(headers['content-security-policy'], 'enforcing header').toBeTruthy()
  expect(headers['content-security-policy-report-only']).toBeUndefined()
  expect(headers['content-security-policy']).toContain("script-src 'self'")
  expect(headers['content-security-policy']).toContain('report-uri /api/csp-report/')
})

test('the report endpoint still takes reports', async () => {
  const r = await page.request.post('/api/csp-report/', {
    headers: { 'Content-Type': 'application/csp-report' },
    data: JSON.stringify({ 'csp-report': { 'document-uri': 'http://e2e/x', 'effective-directive': 'img-src',
      'blocked-uri': 'https://e2e.invalid/p.png', disposition: 'enforce' } }),
  })
  expect(r.status()).toBe(204)
})

test('login works under the policy', async () => {
  await page.goto('/login')
  await page.getByPlaceholder('أدخل اسم المستخدم').fill(usernameOf('admin'))
  await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
  await page.getByRole('button', { name: 'دخول', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 })
  await page.waitForTimeout(1500)
  await collect('/login → /dashboard')
})

test(`every menu screen (${SCREENS.length}) loads without a CSP violation`, async () => {
  for (const path of SCREENS) {
    await page.goto(path, { waitUntil: 'load' }).catch(e => violations.push(`${path}: navigation ${e.message}`))
    await page.waitForTimeout(1200)                     // lazy chunks, fonts, first API calls
    await collect(path)
  }
  expect(violations, violations.join('\n')).toEqual([])
})
