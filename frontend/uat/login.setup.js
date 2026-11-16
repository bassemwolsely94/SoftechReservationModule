// Log in once per UAT user through the real login screen and keep the session for the specs.
import fs from 'node:fs'
import path from 'node:path'
import { test as setup, expect } from '@playwright/test'
import { UAT_USERS, PASSWORD, stateFile } from './lib/users.js'
import { finding } from './lib/findings.js'

for (const u of UAT_USERS) {
  setup(`login as ${u.key}`, async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('أدخل اسم المستخدم').fill(u.username)
    await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
    await page.getByRole('button', { name: 'دخول', exact: true }).click()

    // Any screen but /login = signed in (delivery lands on /rider, phones on /m).
    await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 60_000 }).catch(() => {})
    if (new URL(page.url()).pathname.startsWith('/login')) {
      const msg = (await page.locator('body').innerText()).slice(0, 200)
      finding({ ws: 'W1', key: u.key, route: '/login', kind: 'decision', severity: 'P1',
                expected: 'UAT user signs in', actual: `stuck on login: ${msg.replace(/\d{8,}/g, '#')}` })
    }
    expect(new URL(page.url()).pathname).not.toMatch(/^\/login/)
    const me = await page.request.get('/api/auth/me/')
    expect(me.status()).toBe(200)
    expect((await me.json()).role).toBe(u.role)

    fs.mkdirSync(path.dirname(stateFile(u.key)), { recursive: true })
    await page.context().storageState({ path: stateFile(u.key) })
  })
}
