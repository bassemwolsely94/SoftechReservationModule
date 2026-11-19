// W5b · Finance GL manual entry: draft → approve → reverse through the real screens (the flow of
// e2e/finance-gl.spec.js, on the copy's real chart: 1302 admin cash box ↔ 1320 transfers, 1.25,
// reversed at the end so the copy's books net to zero). The ledger never writes to SOFTECH.
import { test, expect } from '@playwright/test'
import { stateFile } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import { WS, TAG, stamp, doers, nonDoers, apiAs, flag, expectRefused } from './_money.js'

const DEBIT = '1302'
const CREDIT = '1320'   // both: no party, no branch required
const AMOUNT = '1.25'
const ENTRIES = '/api/finance/gl/entries/'
let doneId = null   // an entry this spec approved and reversed

// ledger create + approve: the roles that keep the books
const keepers = doers('ledger', 'create').filter(k => k !== 'admin')

for (const key of keepers) {
  test.describe(`${key}`, () => {
    test.use({ storageState: stateFile(key) })

    test(`${key}: manual entry draft → approved → reversed, balanced at every step`, async ({ page, baseURL }) => {
      const text = `${TAG} قيد ${stamp()}`
      await page.goto('/finance/journal')
      await page.getByRole('button', { name: '+ قيد يدوي' }).click()
      await page.locator('label', { hasText: 'البيان' }).locator('input').fill(text)
      const lines = page.locator('[data-tour="finance-gl-entry-lines"] tbody tr')
      for (const [i, code, col] of [[0, DEBIT, 0], [1, CREDIT, 1]]) {
        const acct = lines.nth(i).getByPlaceholder('كود أو اسم الحساب')
        await acct.click(); await acct.fill(code)
        // the account list loads on the copy's real chart: wait for the match before Enter
        await expect(page.getByRole('button', { name: new RegExp(`^${code} ·`) }).first()).toBeVisible()
        await acct.press('Enter')
        await expect(acct).toHaveValue(new RegExp(`^${code} ·`))
        await lines.nth(i).locator('input[type="number"]').nth(col).fill(AMOUNT)
      }
      await expect(page.locator('[data-tour="finance-gl-entry-totals"]')).toContainText('متوازن')

      const saved = page.waitForResponse(r => /\/api\/finance\/gl\/entries\/$/.test(r.url()) && r.request().method() === 'POST')
      await page.getByRole('button', { name: 'حفظ مسودة' }).click()
      const savedRes = await saved
      if (savedRes.status() !== 201) {
        flag({ key, route: '/finance/journal', kind: 'workflow', severity: 'P1', expected: 'draft saved (201)', actual: `HTTP ${savedRes.status()} ${(await savedRes.text()).slice(0, 150)}` })
        return
      }
      const draft = await savedRes.json()
      if (!(Number(draft.total_debit) === Number(AMOUNT) && Number(draft.total_credit) === Number(AMOUNT))) {
        flag({ key, route: '/finance/journal', kind: 'workflow', severity: 'P1', expected: `draft totals ${AMOUNT}/${AMOUNT}`, actual: `${draft.total_debit}/${draft.total_credit}` })
      }

      const approved = page.waitForResponse(r => /\/entries\/\d+\/approve\/$/.test(r.url()))
      await page.getByRole('button', { name: 'اعتماد', exact: true }).click()
      const approvedRes = await approved
      if (approvedRes.status() !== 200) {
        flag({ key, route: '/finance/journal', kind: 'workflow', severity: 'P1', expected: 'entry approved (200)', actual: `HTTP ${approvedRes.status()} ${(await approvedRes.text()).slice(0, 150)}` })
        return
      }
      const { id, number } = await approvedRes.json()
      doneId = id
      await expect(page.getByText(`تم الاعتماد — ${number}`)).toBeVisible()
      // Same person drafted and approved: maker = checker.
      finding_selfApproved(key, number)

      await page.goto(`/finance/journal?entry=${id}`)
      await expect(page.getByRole('heading', { name: number })).toBeVisible()
      await page.getByPlaceholder('سبب العكس (مطلوب)').fill(TAG)
      const reversed = page.waitForResponse(r => /\/entries\/\d+\/reverse\/$/.test(r.url()))
      await page.getByRole('button', { name: 'عكس القيد' }).click()
      const reversedRes = await reversed
      if (!reversedRes.ok()) {
        flag({ key, route: '/finance/journal', kind: 'workflow', severity: 'P1', expected: 'entry reversed', actual: `HTTP ${reversedRes.status()} ${(await reversedRes.text()).slice(0, 150)}` })
        return
      }
      await expect(page.getByText(/تم العكس بالقيد/)).toBeVisible()
      const mirror = await reversedRes.json()
      if (Number(mirror.total_debit) !== Number(AMOUNT) || Number(mirror.total_credit) !== Number(AMOUNT)) {
        flag({ key, route: '/finance/journal', kind: 'workflow', severity: 'P1', expected: `reversal totals ${AMOUNT}/${AMOUNT}`, actual: `${mirror.total_debit}/${mirror.total_credit}` })
      }
      // reversing twice is refused
      const api = await apiAs(baseURL, key)
      try {
        const again = await api.post(`${ENTRIES}${id}/reverse/`, { reason: `${TAG} twice` })
        if (again.status < 400) flag({ key, route: `${ENTRIES}:id/reverse/`, kind: 'workflow', severity: 'P1', expected: 'second reversal refused', actual: `HTTP ${again.status}` })
      } finally { await api.dispose() }
    })
  })
}

let selfNoted = false
function finding_selfApproved(key, number) {
  if (selfNoted) return
  selfNoted = true
  finding({ ws: WS, key, route: '/finance/journal', kind: 'workflow', severity: 'P0',
    expected: 'a manual journal entry is approved by someone other than the person who drafted it (maker ≠ checker)',
    actual: `${key} drafted and approved the same entry (${number}); ledger.approve has no drafter check. e2e/finance-gl.spec.js does the same, so it may be a deliberate one-accountant setup: owner to confirm` })
}

for (const key of keepers.slice(0, 1)) {
  test.describe(`${key} (form check)`, () => {
    test.use({ storageState: stateFile(key) })
    test(`${key}: a line without an account is stopped on the screen, not by the server`, async ({ page }) => {
      await page.goto('/finance/journal')
      await page.getByRole('button', { name: '+ قيد يدوي' }).click()
      await page.locator('label', { hasText: 'البيان' }).locator('input').fill(`${TAG} بدون حساب`)
      const lines = page.locator('[data-tour="finance-gl-entry-lines"] tbody tr')
      await lines.nth(0).locator('input[type="number"]').nth(0).fill(AMOUNT)   // no account on line 1
      await lines.nth(1).locator('input[type="number"]').nth(1).fill(AMOUNT)
      const balanced = await page.locator('[data-tour="finance-gl-entry-totals"]').innerText()
      let posted = null
      page.on('request', r => { if (/\/api\/finance\/gl\/entries\/$/.test(r.url()) && r.method() === 'POST') posted = r })
      await page.getByRole('button', { name: 'حفظ مسودة' }).click()
      await page.waitForTimeout(1500)
      if (posted && /متوازن/.test(balanced)) {
        finding({ ws: WS, key, route: '/finance/journal', kind: 'workflow', severity: 'P3',
          expected: 'lines without an account flagged on the form before saving',
          actual: 'totals show «متوازن» and the draft is sent; only the server refuses («الحساب غير موجود أو موقوف»)' })
      }
    })
  })
}

test('must be refused: roles without ledger create/approve cannot draft, approve or reverse', async ({ baseURL }) => {
  for (const key of nonDoers('ledger', 'create').filter(k => k !== 'admin')) {
    const api = await apiAs(baseURL, key)
    try {
      expectRefused(await api.post(ENTRIES, { entry_date: new Date().toISOString().slice(0, 10), description: TAG,
        lines: [{ account_code: DEBIT, debit: AMOUNT, credit: 0 }, { account_code: CREDIT, debit: 0, credit: AMOUNT }] }),
        { key, route: ENTRIES, what: 'drafting a manual journal entry' })
      if (doneId) {
        // already reversed: an allowed role would get 409, a refused one 403 (never touches real entries)
        const r = await api.post(`${ENTRIES}${doneId}/reverse/`, { reason: TAG })
        if (r.status !== 403 && r.status !== 401) {
          flag({ key, route: `${ENTRIES}:id/reverse/`, kind: 'workflow', severity: 'P1', expected: 'reversing a journal entry refused (403)', actual: `passed the permission check (HTTP ${r.status})` })
        }
      }
    } finally { await api.dispose() }
  }
})
