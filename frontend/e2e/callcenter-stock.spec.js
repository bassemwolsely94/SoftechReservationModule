// Full audit C01: network stock inside the call centre. A call-centre agent finds the customer,
// adds an item that is out at the customer's branch, saves the call, opens «📍» and reserves it at
// the branch that has stock — through the call's own convert endpoint, so it stays linked to the call.
// e2e database only (config/settings_e2e.py: E2E_STOCK puts E2E001 at «فرع الاختبار ٢» only).
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

test.describe('call centre network stock', () => {
  test.use({ storageState: stateFile('call_center') })

  test('an agent reserves an item at the branch that has it, linked to the call', async ({ page }) => {
    await page.goto('/callcenter')
    await page.locator('[data-tour="callcenter-operator-phone"]').fill('01099990001')
    await page.locator('[data-tour="callcenter-operator-search"]').click()
    await expect(page.getByText('عميل الاختبار E2E').first()).toBeVisible()

    await page.locator('[data-tour="callcenter-operator-items-search"]').click()
    await page.getByPlaceholder('ابحث باسم الصنف أو الكود... (*نجمة للبحث الشامل)').fill('E2E PARA')
    await page.getByText('E2E PARACETAMOL 500MG 20 TAB').first().click()

    // C12: saving needs a reason chip (one tap)
    await page.locator('[data-tour="callcenter-operator-purpose"]').getByRole('button', { name: /توفر صنف/ }).click()
    const saved = page.waitForResponse(r => /\/api\/callcenter\/calls\/$/.test(r.url()) && r.request().method() === 'POST')
    await page.locator('[data-tour="callcenter-operator-save"]').click()
    expect((await saved).status()).toBe(201)

    // the item is stored with the call → «📍» shows beside it
    await page.locator('[data-tour="callcenter-operator-items-stock"]').first().click()
    const drawer = page.getByTestId('stock-lookup-drawer')
    await expect(drawer.getByText('فرع الاختبار ٢')).toBeVisible()

    const converted = page.waitForResponse(r => r.url().includes('/convert-to-reservation/') && r.request().method() === 'POST')
    await drawer.getByRole('button', { name: 'حجز هنا' }).first().click()
    const res = await converted
    expect(res.status(), await res.text()).toBe(201)
    expect((await res.json()).count).toBe(1)
    await expect(drawer.getByText(/وربطه بالمكالمة/)).toBeVisible()
  })
})
