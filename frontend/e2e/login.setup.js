// Login per role, through the real login screen. Each role's session cookies are saved for the
// other specs, so the whole run logs in exactly once per role (the login throttle is 10/min/IP).
import fs from 'node:fs'
import path from 'node:path'
import { test as setup, expect } from '@playwright/test'
import { ROLES, PASSWORD, usernameOf, stateFile } from './users.js'

for (const role of ROLES) {
  setup(`login as ${role}`, async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('أدخل اسم المستخدم').fill(usernameOf(role))
    await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
    await page.getByRole('button', { name: 'دخول', exact: true }).click()

    await expect(page).toHaveURL(role === 'delivery' ? /\/rider$/ : /\/dashboard$/, { timeout: 60_000 })
    const me = await page.request.get('/api/auth/me/')
    expect(me.status()).toBe(200)
    expect((await me.json()).role).toBe(role)

    fs.mkdirSync(path.dirname(stateFile(role)), { recursive: true })
    await page.context().storageState({ path: stateFile(role) })
  })
}
