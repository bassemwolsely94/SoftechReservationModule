// W4 — list screens (desktop + mobile /m/*) per exposure user: rendered text and every JSON response
// are scanned for reference customers' full numbers, and for records of a branch the user may not see.
import { test } from '@playwright/test'
import { stateFile } from '../lib/users.js'
import { gotoSettled } from '../lib/page.js'
import { EXPOSURE_USERS, DOMAINS } from './rules.js'
import { captureJson, pageText, checkPhones, checkBranchAbsent } from './scan.js'
import { guardBackend } from './alive.js'
import { transferSkips } from './transfers.js'

// Control users only visit the domains they control for: the A viewer for the record rule's
// viewer masking (D4 / D7), the phone-visible pharmacist for B-2 over-/under-masking of customers.
const CONTROL_DOMAINS = {
  viewer: ['reservations', 'demand', 'followups', 'transfers', 'delivery', 'callcenter'],
  phoneVisible: ['customers', 'referral', 'loyalty', 'sales', 'picAnalytics'],
}

guardBackend()

for (const key of EXPOSURE_USERS) {
  test.describe(`exposure screens as ${key}`, () => {
    test.use({ storageState: stateFile(key) })

    for (const [domain, d] of Object.entries(DOMAINS)) {
      if (CONTROL_DOMAINS[key] && !CONTROL_DOMAINS[key].includes(domain)) continue
      for (const route of d.routes) {
        test(`${key} ${route}`, async ({ page, baseURL }) => {
          const cap = captureJson(page)
          const r = await gotoSettled(page, route, { capMs: 20_000 })
          await page.waitForTimeout(500)
          const text = await pageText(page)
          const bodies = await cap.done()
          test.info().annotations.push({ type: 'status', description: `${r.status} ${r.ms}ms` })
          // scanned even when refused: whatever JSON arrived before the refusal counts
          checkPhones({ key, domain, route, text, bodies })
          checkBranchAbsent({ key, domain, route, text, bodies, listApi: d.listApi, refKey: d.refKey,
            skip: domain === 'transfers' ? await transferSkips(baseURL, key) : undefined })
        })
      }
    }
  })
}
