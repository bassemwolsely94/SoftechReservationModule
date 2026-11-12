// The finance ledger through its real screens, as the accountant: accounts, a manual entry from draft
// to approved to reversed, the reports over it, and confirming parties from the review sheet.
// Everything stays in the e2e database: the ledger never writes to SOFTECH, and this server has none.
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

const stamp = () => String(Date.now()).slice(-7)

// The review sheet, built with openpyxl (the frontend has no Excel writer; Python is already here).
function reviewSheet(rows) {
  const code = `
import base64, io, json, sys
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['النوع', 'كود المالية', 'اسم المالية', 'الكود المعتمد (تملؤه المالية)'])
for r in json.loads(sys.argv[1]):
    ws.append(r)
buf = io.BytesIO()
wb.save(buf)
print(base64.b64encode(buf.getvalue()).decode())
`
  const out = execFileSync(process.env.E2E_PYTHON || 'python', ['-c', code, JSON.stringify(rows)],
    { env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } })
  return { name: 'review.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from(out.toString().trim(), 'base64') }
}

test.describe('finance ledger', () => {
  test.use({ storageState: stateFile('accountant') })

  test('the chart of accounts lists the accounts', async ({ page }) => {
    await page.goto('/finance/coa')
    await expect(page.locator('[data-tour="finance-coa-view"]')).toBeVisible()
    await expect(page.getByText('E2E الخزينة').first()).toBeVisible()
    await expect(page.getByText('E2E المبيعات').first()).toBeVisible()
  })

  test('a manual entry goes draft → approved → reversed and reaches the reports', async ({ page }) => {
    const text = `E2E قيد ${stamp()}`
    await page.goto('/finance/journal')
    await page.getByRole('button', { name: '+ قيد يدوي' }).click()

    await page.locator('label', { hasText: 'البيان' }).locator('input').fill(text)
    const lines = page.locator('[data-tour="finance-gl-entry-lines"] tbody tr')
    await lines.nth(0).getByPlaceholder('كود أو اسم الحساب').click()
    await lines.nth(0).getByPlaceholder('كود أو اسم الحساب').fill('9901')
    await lines.nth(0).getByPlaceholder('كود أو اسم الحساب').press('Enter')
    await lines.nth(0).locator('input[type="number"]').nth(0).fill('100.50')
    await lines.nth(1).getByPlaceholder('كود أو اسم الحساب').click()
    await lines.nth(1).getByPlaceholder('كود أو اسم الحساب').fill('9902')
    await lines.nth(1).getByPlaceholder('كود أو اسم الحساب').press('Enter')
    await lines.nth(1).locator('input[type="number"]').nth(1).fill('100.50')
    await expect(page.locator('[data-tour="finance-gl-entry-totals"]')).toContainText('متوازن')

    const saved = page.waitForResponse(r => /\/api\/finance\/gl\/entries\/$/.test(r.url()) && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'حفظ مسودة' }).click()
    const savedRes = await saved
    expect(savedRes.status(), await savedRes.text()).toBe(201)
    await expect(page.getByText('تم حفظ المسودة')).toBeVisible()

    const approved = page.waitForResponse(r => /\/entries\/\d+\/approve\/$/.test(r.url()))
    await page.getByRole('button', { name: 'اعتماد', exact: true }).click()
    const approvedRes = await approved
    expect(approvedRes.status(), await approvedRes.text()).toBe(200)
    const { id, number } = await approvedRes.json()
    expect(number).toBeTruthy()
    await expect(page.getByText(`تم الاعتماد — ${number}`)).toBeVisible()

    // the reports while it stands
    await page.goto('/finance/trial-balance')
    await expect(page.locator('tfoot')).toContainText('متوازن')
    await expect(page.getByText('9901').first()).toBeVisible()

    const stmt = page.waitForResponse(r => r.url().includes('/reports/account-statement/'))
    await page.goto('/finance/ledger?code=9901')
    expect((await stmt).status()).toBe(200)
    await expect(page.getByText(text).first()).toBeVisible()

    const pos = page.waitForResponse(r => r.url().includes('/reports/position/'))
    await page.goto('/finance/statements?tab=position')
    expect((await pos).status()).toBe(200)
    await expect(page.locator('[data-tour="finance-gl-position-check"]')).toBeVisible()

    // reverse it (the journal lists drafts by default; its link opens any entry)
    await page.goto(`/finance/journal?entry=${id}`)
    await expect(page.getByRole('heading', { name: number })).toBeVisible()
    await page.getByPlaceholder('سبب العكس (مطلوب)').fill('اختبار')
    const reversed = page.waitForResponse(r => /\/entries\/\d+\/reverse\/$/.test(r.url()))
    await page.getByRole('button', { name: 'عكس القيد' }).click()
    const reversedRes = await reversed
    expect(reversedRes.ok(), await reversedRes.text()).toBeTruthy()
    await expect(page.getByText(/تم العكس بالقيد/)).toBeVisible()
  })

  test('the review sheet previews, adds a new code, then holds back a different name', async ({ page }) => {
    const n = stamp()
    const box = page.locator('[data-tour="finance-gl-parties-confirm-upload"]')
    await page.goto('/finance/parties')

    await box.locator('input[type="file"]').setInputFiles(reviewSheet([['عميل', Number(n), `شركة النور ${n}`, Number(n)]]))
    await box.getByRole('button', { name: 'معاينة' }).click()
    await expect(box.getByText('سيُضاف ويتأكد 1')).toBeVisible()
    await box.getByRole('button', { name: 'تأكيد 1 طرف' }).click()
    await expect(box.getByText('أُضيف وتأكد 1')).toBeVisible()

    // on the grid, confirmed
    // the status filter is a multi-select (opens on «مقترح»): show «مؤكد» only, then close it
    await page.getByRole('button', { name: /^مقترح/ }).click()
    await page.getByRole('checkbox', { name: 'مؤكد', exact: true }).check()
    await page.getByRole('checkbox', { name: 'مقترح', exact: true }).uncheck()
    await page.keyboard.press('Escape')
    await page.getByPlaceholder(/بحث بالكود أو الاسم/).fill(n)
    await expect(page.locator('[data-tour="finance-gl-parties-grid"] tbody tr', { hasText: `شركة النور ${n}` })).toContainText('مؤكد')

    // the same code under a name that shares no word: never confirmed, shown with its reason
    await box.locator('input[type="file"]').setInputFiles(reviewSheet([['عميل', Number(n), 'اسم اخر تماما', Number(n) + 1]]))
    await box.getByRole('button', { name: 'معاينة' }).click()
    await expect(box.getByText('اسم مختلف 1')).toBeVisible()
    await expect(box.getByText(/غير الاسم المسجل/)).toBeVisible()
    await expect(box.getByRole('button', { name: /^تأكيد \d+ طرف$/ })).toHaveCount(0)
  })
})
