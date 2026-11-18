// Full audit FE-11: a transfer request reaches «بانتظار الموافقة» in one action — «حفظ وتقديم» is the
// default and the server saves + submits in one call. After an item is added the cursor is in its
// quantity, and Enter goes back to the item search.
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

test.describe('transfer save and send', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('one press sends the request; qty is focused after the item', async ({ page }) => {
    const submits = []
    page.on('request', r => { if (/\/api\/transfers\/\d+\/submit\/$/.test(r.url())) submits.push(r.url()) })

    await page.goto('/transfers/new')
    await expect(page.locator('[data-tour="transfers-new-send-now"] input[type="checkbox"]')).toBeChecked()

    await page.getByText('اختر الفرع المصدر...').click()
    await page.locator('[data-tour="transfers-new-branches"]').getByText('فرع الاختبار ٢', { exact: true }).click()

    const search = page.getByPlaceholder(/ابحث باسم الصنف أو الكود أو الباركود/)
    await search.fill('E2E PARA')
    await page.getByText('E2E PARACETAMOL 500MG 20 TAB').first().click()

    const qty = page.getByTestId('transfer-qty').first()
    await expect(qty).toBeFocused()
    await qty.fill('3')
    await qty.press('Enter')
    await expect(page.locator('[data-tour="transfers-new-items"] input').first()).toBeFocused()

    const created = page.waitForResponse(r => /\/api\/transfers\/\?submit=1$/.test(r.url()) && r.request().method() === 'POST')
    await page.locator('[data-tour="transfers-new-submit"]').click()
    const res = await created
    expect(res.status(), await res.text()).toBe(201)
    expect((await res.json()).status).toBe('pending')
    await expect(page).toHaveURL(/\/transfers\/\d+$/)
    expect(submits).toHaveLength(0)            // no second call
  })
})
