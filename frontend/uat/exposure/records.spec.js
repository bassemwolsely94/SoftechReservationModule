// W4 — detail screens: another branch's reservation / demand / transfer / shortage list / POS order
// must not open (branch_scope.get_or_404); a customer of either branch opens (B-2) with the numbers
// the rules allow; own customers' numbers are not over-masked.
import { test } from '@playwright/test'
import { stateFile } from '../lib/users.js'
import { reference } from '../lib/expected.js'
import { gotoSettled } from '../lib/page.js'
import { EXPOSURE_USERS, DOMAINS, sees, branchRule, seesBranchValue } from './rules.js'
import { captureJson, pageText, checkPhones, refCustomers, branchLeak, api, safePath } from './scan.js'
import { transferSides } from './transfers.js'

const PER_KIND = 3           // reference records tried per kind and branch
const CUSTOMERS = 3          // customer 360 pages per branch

const DETAIL_DOMAINS = ['reservations', 'demand', 'transfers', 'shortage', 'pos']

for (const key of EXPOSURE_USERS) {
  test.describe(`exposure records as ${key}`, () => {
    test.use({ storageState: stateFile(key) })

    test(`${key} other-branch detail records are absent`, async ({ page, baseURL }) => {
      const sides = await transferSides(baseURL)
      for (const b of ['A', 'B']) {
        if (sees(key, b)) continue
        for (const domain of DETAIL_DOMAINS) {
          const d = DOMAINS[domain]
          let ids = (reference(b)[d.refKey] || []).map(x => (typeof x === 'object' ? x.id : x))
          if (domain === 'transfers') {   // decision 3: absent only when neither side is the user's
            ids = ids.filter(id => {
              const s = sides.get(id)?.sides || []
              return s.some(v => v != null) && !s.some(v => v != null && seesBranchValue(key, v) === true)
            })
          }
          for (const id of ids.slice(0, PER_KIND)) {
            const rule = branchRule(key, domain, b)
            if (d.detail) {
              const route = d.detail(id)
              const cap = captureJson(page)
              const r = await gotoSettled(page, route, { capMs: 20_000 })
              const text = await pageText(page)
              const bodies = await cap.done()
              const hit = bodies.find(x => safePath(x.url) === d.detailApi(id) && x.status === 200 && x.json)
              if (hit) branchLeak(key, route, `absent (${rule.src})`, `branch-${b} ${domain} #${id} opened (${r.status}); ${safePath(hit.url)} 200`)
              checkPhones({ key, domain, route, text, bodies })
            } else {
              const res = await api(page, 'GET', d.detailApi(id))
              if (res.status() === 200) {
                branchLeak(key, d.detailApi(id), `absent (${rule.src})`, `branch-${b} ${domain} #${id} answered 200`)
                const json = await res.json().catch(() => null)
                checkPhones({ key, domain, route: d.detailApi(id), bodies: [{ url: d.detailApi(id), json }] })
              }
            }
          }
        }
      }
    })

    test(`${key} customer 360 and loyalty of both branches`, async ({ page }) => {
      const all = refCustomers()
      for (const b of ['A', 'B']) {
        for (const c of all.filter(x => x.branch === b).slice(0, CUSTOMERS)) {
          const route = `/customers/${c.id}`
          const cap = captureJson(page)
          const r = await gotoSettled(page, route, { capMs: 20_000 })
          await page.waitForTimeout(500)
          const text = await pageText(page)
          const bodies = await cap.done()
          checkPhones({ key, domain: 'customer360', route: '/customers/:id', text, bodies, overMask: [c] })

          const acct = await api(page, 'GET', `/api/loyalty/customers/${c.id}/account/`)
          if (acct.ok()) {
            const json = await acct.json().catch(() => null)
            checkPhones({ key, domain: 'loyalty', route: '/api/loyalty/customers/:id/account/', bodies: [{ url: '/api/loyalty/customers/x/account/', json }] })
          }
        }
      }
    })
  })
}
