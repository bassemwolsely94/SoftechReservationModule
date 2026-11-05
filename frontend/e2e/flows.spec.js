// The three everyday flows, through the real screens, as the roles that do them.
// Nothing reaches SOFTECH: the e2e server has no SOFTECH host, SOFTECH_READ_ONLY=True and
// WRITER_INSTANCE=False (config/settings_e2e.py). The POS order stops at «جاهز للإرسال» (ready)
// and is never sent to the cashier.
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

const stamp = () => String(Date.now()).slice(-7)

test.describe('reservation', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('a pharmacist creates a reservation', async ({ page }) => {
    const name = `E2E صنف يدوي ${stamp()}`
    await page.goto('/reservations/new')
    await page.getByPlaceholder('اكتب اسم الصنف يدوياً...').fill(name)
    const contact = page.locator('[data-tour="reservations-new-contact"]')
    await contact.locator('input').first().fill('عميل الاختبار')
    await contact.locator('input[dir="ltr"]').fill('01000000001')

    const created = page.waitForResponse(r => r.url().includes('/api/reservations/') && r.request().method() === 'POST')
    await page.locator('[data-tour="reservations-new-submit"]').click()
    const res = await created
    expect(res.status(), await res.text()).toBe(201)
    const { id } = await res.json()

    await expect(page).toHaveURL(new RegExp(`/reservations/${id}$`))
    await expect(page.getByText(name).first()).toBeVisible()
  })
})

test.describe('transfer request', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('a pharmacist requests a transfer from another branch', async ({ page }) => {
    await page.goto('/transfers/new')
    await page.getByText('اختر الفرع المصدر...').click()
    await page.getByText('فرع الاختبار ٢').last().click()

    await page.getByPlaceholder(/ابحث باسم الصنف أو الكود أو الباركود/).fill('E2E PARA')
    await page.getByText('E2E PARACETAMOL 500MG 20 TAB').first().click()
    await page.getByPlaceholder('الكمية').fill('2')

    const created = page.waitForResponse(r => /\/api\/transfers\/$/.test(r.url()) && r.request().method() === 'POST')
    await page.getByRole('button', { name: /حفظ كمسودة|إرسال/ }).last().click()
    const res = await created
    expect(res.status(), await res.text()).toBe(201)
    const body = await res.json()
    expect(body.items?.length ?? 1).toBeGreaterThan(0)
  })
})

test.describe('POS order', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('a pharmacist takes a POS order to ready — never sent to SOFTECH', async ({ page }) => {
    // The checkout button runs ready → push. The push is blocked here at the network layer, so
    // the order stops at ready; the server would only dry-run it anyway (writer off, read-only).
    const pushes = []
    await page.route(/\/api\/pos-orders\/\d+\/push\//, (route) => {
      pushes.push(route.request().postDataJSON())
      return route.abort()
    })

    await page.goto('/pos')
    const search = page.getByPlaceholder(/صنف|بحث/).first()
    await search.fill('E2E PARA')
    await page.getByText('E2E PARACETAMOL 500MG 20 TAB').first().click()

    const ready = page.waitForResponse(r => /\/api\/pos-orders\/\d+\/ready\//.test(r.url()))
    await page.getByRole('button', { name: /جاهز|تجهيز|F9/ }).first().click()
    const res = await ready
    expect(res.status(), await res.text()).toBe(200)
    const order = await res.json()
    expect(order.status).toBe('ready')

    await expect.poll(() => pushes.length).toBe(1)
    expect(pushes[0]).toMatchObject({ dry_run: true })          // the UI asks for a dry run only
    expect(pushes[0].confirm).toBeUndefined()

    const after = await (await page.request.get(`/api/pos-orders/${order.id}/`)).json()
    expect(after.status).toBe('ready')
    expect(after.softech_docnumber || null).toBeNull()
  })
})
