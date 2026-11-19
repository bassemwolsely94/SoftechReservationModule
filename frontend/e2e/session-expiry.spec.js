// Full audit FE-12: an expired session no longer throws the page away.
//  * mid-work: the same user signs in again over the page; what was typed stays, and the request
//    that hit the expiry is retried;
//  * on opening a page with no session: the login page brings the user back to that page.
import { test, expect } from '@playwright/test'
import { PASSWORD, stateFile, usernameOf } from './users.js'

test.describe('session expiry keeps the page', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('mid-work: sign in again over the page, the typed text stays and the request goes through', async ({ page, context }) => {
    await page.goto('/transfers/new')
    const notes = page.locator('[data-tour="transfers-new-notes"] textarea')
    await notes.fill('ملاحظة لم تُحفظ بعد')

    await context.clearCookies()                       // the session runs out (access + refresh)

    const search = page.getByPlaceholder(/ابحث باسم الصنف أو الكود أو الباركود/)
    await search.fill('E2E PARA')                      // the next API call meets the expiry

    const overlay = page.getByTestId('session-expired')
    await expect(overlay).toBeVisible()
    await expect(page).toHaveURL(/\/transfers\/new$/)  // no reload, no redirect
    await expect(overlay.getByLabel('اسم المستخدم')).toHaveValue(usernameOf('pharmacist'))

    await overlay.getByLabel('كلمة المرور').fill(PASSWORD)
    const retried = page.waitForResponse(r => r.url().includes('/api/items/?search=') && r.status() === 200)
    await overlay.getByRole('button', { name: 'دخول ومتابعة' }).click()

    await expect(overlay).toBeHidden()
    const items = await (await retried).json()                                      // the retried search
    expect(JSON.stringify(items)).toContain('E2E PARACETAMOL 500MG 20 TAB')
    await expect(search).toBeFocused()                                              // back where the user was
    await expect(search).toHaveValue('E2E PARA')
    await expect(notes).toHaveValue('ملاحظة لم تُحفظ بعد')
    await expect(page).toHaveURL(/\/transfers\/new$/)
  })
})

test.describe('login returns to the page', () => {
  test('opening a page with no session → login → back on that page', async ({ page }) => {
    await page.goto('/transfers?status=pending')
    await expect(page).toHaveURL(/\/login\?next=%2Ftransfers%3Fstatus%3Dpending$/)

    await page.getByPlaceholder('أدخل اسم المستخدم').fill(usernameOf('pharmacist'))
    await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
    await page.getByRole('button', { name: 'دخول', exact: true }).click()

    await expect(page).toHaveURL(/\/transfers\?status=pending$/)
  })

  test('a next pointing at another site is ignored', async ({ page }) => {
    await page.goto('/login?next=%2F%2Fevil.example%2Fx')
    await page.getByPlaceholder('أدخل اسم المستخدم').fill(usernameOf('viewer'))
    await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
    await page.getByRole('button', { name: 'دخول', exact: true }).click()
    await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/dashboard$/)
  })
})
