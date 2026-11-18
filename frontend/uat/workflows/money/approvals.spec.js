// W5b · Operational approvals (/approvals): the inbox per approver role, a decision taken through
// the real screen (supervisor, then admin, on a salesperson's leave), and the roles that must not
// reach the inbox at all.
import { test, expect } from '@playwright/test'
import { stateFile } from '../../lib/users.js'
import { gotoSettled } from '../../lib/page.js'
import { TAG, stamp, doers, nonDoers, apiAs, flag, expectRefused, brief, screenOk } from './_money.js'

const PENDING = '/api/approvals/requests/pending/'

for (const key of doers('approvals', 'view')) {
  test(`${key}: the approvals inbox opens`, async ({ browser, baseURL }) => {
    const api = await apiAs(baseURL, key)
    try {
      const r = await api.get(PENDING)
      if (r.status !== 200) flag({ key, route: PENDING, kind: 'workflow', severity: 'P2', expected: 'inbox loads (200)', actual: `HTTP ${r.status}` })
    } finally { await api.dispose() }
    await screenOk(browser, key, '/approvals', { severity: 'P2', what: 'approvals inbox opens' })
  })
}

test('a leave is decided through the /approvals screen: supervisor then admin', async ({ browser, baseURL }) => {
  const sp = await apiAs(baseURL, 'salesperson')
  const name = `${TAG} شاشة ${stamp()}`
  const lr = await sp.post('/api/hr/leave-requests/submit/', { leave_type_code: 'annual', start_date: '2027-02-01',
    end_date: '2027-02-01', days_requested: 1, reason: TAG, employee_hr_code: `UATW5B${stamp()}`, employee_name: name })
  expect(lr.status, brief(lr.body)).toBe(201)

  for (const key of ['supervisor', 'admin']) {
    const ctx = await browser.newContext({ storageState: stateFile(key) })
    const page = await ctx.newPage()
    await gotoSettled(page, '/approvals')
    const row = page.locator('tbody tr', { hasText: name })
    if (!(await row.count())) {
      flag({ key, route: '/approvals', kind: 'workflow', severity: 'P1', expected: `the leave of "${TAG}" in ${key}'s pending list`, actual: 'row not shown' })
      await ctx.close(); break
    }
    await row.getByRole('button', { name: 'اتخاذ قرار' }).click()
    await page.getByRole('button', { name: /موافقة/ }).click()
    await page.getByPlaceholder('ملاحظات (اختياري)...').fill(TAG)
    const res = page.waitForResponse(r => /\/approvals\/requests\/\d+\/decide\/$/.test(r.url()))
    await page.getByRole('button', { name: 'تأكيد القرار' }).click()
    const d = await res
    if (d.status() !== 200) {
      flag({ key, route: '/approvals', kind: 'workflow', severity: 'P1', expected: `${key} approves from the screen`, actual: `HTTP ${d.status()} ${(await d.text()).slice(0, 150)}` })
    }
    await expect(page.locator('tbody tr', { hasText: name })).toHaveCount(0)
    await ctx.close()
  }
  const g = await sp.get(`/api/hr/leave-requests/${lr.body.id}/`)
  if (g.body?.status !== 'approved') {
    flag({ key: 'salesperson', route: '/api/hr/leave-requests/:id/', kind: 'workflow', severity: 'P1', expected: 'leave approved after both screen decisions', actual: `status ${g.body?.status}` })
  }
  await sp.dispose()
})

test('must be refused: roles without approvals:view cannot read or decide', async ({ baseURL }) => {
  for (const key of nonDoers('approvals', 'view').filter(k => k !== 'admin')) {
    const api = await apiAs(baseURL, key)
    try {
      expectRefused(await api.get(PENDING), { key, route: PENDING, what: 'reading the approvals inbox' })
      expectRefused(await api.post('/api/approvals/requests/1/decide/', { decision: 'approved', notes: TAG }),
        { key, route: '/api/approvals/requests/:id/decide/', what: 'deciding an approval' })
    } finally { await api.dispose() }
  }
})
