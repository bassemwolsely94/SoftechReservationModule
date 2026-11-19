// Full audit FE-10: the supervisor ticks three waiting requests and approves them in one action —
// no decision window per request. Each still goes through the per-request decide endpoint, so the
// server checks the approver for each. seed_e2e_users leaves three «E2E طلب للموافقة n» requests
// from the pharmacist waiting for the supervisor (one-step e2e-only workflow).
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

test.describe('approvals inbox', () => {
  test.use({ storageState: stateFile('supervisor') })

  test('the supervisor ticks three requests and approves them with one click', async ({ page }) => {
    const decided = []
    page.on('response', r => {
      if (/\/api\/approvals\/requests\/\d+\/decide\/$/.test(r.url())) decided.push(r.status())
    })

    await page.goto('/approvals')
    const grid = page.getByTestId('approvals-grid')
    for (const n of [1, 2, 3]) await expect(grid.getByText(`E2E طلب للموافقة ${n}`)).toBeVisible()

    // (the keys — ↑↓ Space Ctrl+A Enter — are covered by ApprovalsPage.test.jsx)
    const boxes = [1, 2, 3].map(n => page.getByLabel(`تحديد E2E طلب للموافقة ${n}`))
    await boxes[0].check()
    await boxes[1].check()
    await boxes[2].check()
    await expect(page.getByTestId('approvals-bulk-bar')).toContainText('محدد: 3')

    await page.getByRole('button', { name: /موافقة على المحدد \(3\)/ }).click()
    await expect(page.getByTestId('approvals-bulk-result')).toContainText('تمت الموافقة على 3')
    expect(decided).toEqual([200, 200, 200])
    expect(await page.getByRole('dialog').count()).toBe(0)                    // no window per request

    for (const n of [1, 2, 3]) await expect(grid.getByText(`E2E طلب للموافقة ${n}`)).toHaveCount(0)
  })
})
