// W8 two-factor sign-in worked through on the UAT copy (docs/uat/runs/w8-plan.md).
//
// 2FA is off on the copy (seed_uat_users clears every UAT user's 2FA and deletes the
// `security.mfa_enforced` row). This spec switches it on for ONE test user only, through the app's
// own API and screens, and restores everything in afterAll (also after a crash: the state file in the
// git-ignored frontend/uat/.auth/ lets the next run clean up first):
//   • the user: UAT_MFA_KEY (default `restricted`, a supervisor — a role with mfa_required in
//     apps/users/roles.py, needed for forced enrolment). Other sessions signing that user in while
//     this spec runs (~5 min) are asked for a code — run it when no other UAT run is signing in.
//   • the `security.mfa_enforced` row: written only to 'false'-like values (B-01: must NOT enforce)
//     — harmless to everyone. Turned to 'true' only with UAT_MFA_ENFORCE=1, for the forced-enrolment
//     check, for well under a minute: during that window EVERY admin / purchasing / supervisor sign-in
//     on the copy (other sessions included) is sent to enrolment. Restored in a finally.
//
// Checks: B-01 false rows; enrolment (forced at sign-in with UAT_MFA_ENFORCE=1, else from «أمان
// الحساب»); sign-in with a TOTP code (wrong code refused first); backup codes are one-time; «تذكّر
// هذا الجهاز» skips the code only on an admin-approved device and is cancelled by the admin's
// «إلغاء الأجهزة المحفوظة»; five wrong codes lock the account (429) until the admin unlocks it; an
// admin 2FA reset (none exists — recorded as a decision); then 2FA off again.
// TOTP codes are computed here (uat/lib/totp.js, RFC 6238). No secret or code is ever logged.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, request } from '@playwright/test'
import { userByKey, PASSWORD, stateFile } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import { assertUatCopy } from '../../lib/guard.js'
import { totp, freshLoginCode } from '../../lib/totp.js'
import { WS, asUser, registry, flag, step, call, raw, BASE, scrub } from '../_w8.js'

test.use({ trace: 'off', screenshot: 'off' })        // a screenshot of the set-up step shows the secret
test.describe.configure({ mode: 'serial', timeout: 8 * 60_000 })

const KEY = process.env.UAT_MFA_KEY || 'restricted'
const ENFORCE = process.env.UAT_MFA_ENFORCE === '1'
const U = userByKey(KEY)
const SETTING = 'security.mfa_enforced'
const XHR = { 'X-Requested-With': 'XMLHttpRequest' }
const CLEANUP_FILE = path.join(path.dirname(stateFile('x')), 'w8-mfa-cleanup.json')
const sleep = ms => new Promise(r => setTimeout(r, ms))

// shared across the serial tests (one worker)
const S = { secret: '', backup: [], lastStep: -1, profileId: null, devices: new Set(), setting: undefined }
const saveCleanup = () => {
  fs.mkdirSync(path.dirname(CLEANUP_FILE), { recursive: true })
  fs.writeFileSync(CLEANUP_FILE, JSON.stringify({ key: KEY, secret: S.secret, devices: [...S.devices], profileId: S.profileId, setting: S.setting }))
}

async function nextCode() {
  const { code, step } = await freshLoginCode(S.secret, S.lastStep, { sleep })
  S.lastStep = step
  return code
}

// ── API sign-in (a request context of its own; no X-Requested-With, so no device is enrolled) ─────
async function apiCtx() { return request.newContext({ baseURL: BASE }) }
async function apiLogin(ctx) {
  const r = await ctx.post('/api/auth/login/', { data: { username: U.username, password: PASSWORD } })
  let body = null
  try { body = await r.json() } catch { /* not JSON */ }
  return { status: r.status(), body: body || {} }
}
async function apiVerify(ctx, token, code, remember = false) {
  const r = await ctx.post('/api/auth/2fa/verify/', { data: { mfa_token: token, code, remember_device: remember } })
  let body = null
  try { body = await r.json() } catch { /* not JSON */ }
  return { status: r.status(), body: body || {} }
}
/** A signed-in request context for the 2FA user (password + a fresh code). */
async function mfaSession() {
  const ctx = await apiCtx()
  const l = await apiLogin(ctx)
  if (!l.body.mfa_required) throw new Error(`2FA user sign-in: expected a code step, got HTTP ${l.status}`)
  const v = await apiVerify(ctx, l.body.mfa_token, await nextCode())
  if (v.status !== 200) throw new Error(`2FA user sign-in: verify answered ${v.status} ${scrub(JSON.stringify(v.body))}`)
  return ctx
}
const statusOf = async ctx => (await ctx.get('/api/auth/2fa/status/', { headers: XHR })).json()

// ── browser sign-in through the real login screen ────────────────────────────────────────────────
async function uiLogin(page) {
  await page.goto('/login')
  await page.getByPlaceholder('أدخل اسم المستخدم').fill(U.username)
  await page.getByPlaceholder('أدخل كلمة المرور').fill(PASSWORD)
  await page.getByRole('button', { name: 'دخول', exact: true }).click()
  await page.waitForFunction(() => !location.pathname.startsWith('/login')
    || /التحقق بخطوتين|تأمين الحساب/.test(document.body.innerText) || !!document.querySelector('.bg-red-50'),
  null, { timeout: 60_000 })
  if (!new URL(page.url()).pathname.startsWith('/login')) return 'in'
  const text = await page.locator('h2').first().innerText().catch(() => '')
  if (/التحقق بخطوتين/.test(text)) return 'verify'
  if (/تأمين الحساب/.test(text)) return 'setup'
  return `error: ${scrub(await page.locator('.bg-red-50').first().innerText().catch(() => ''))}`
}
async function uiVerify(page, code, { remember = false } = {}) {
  await page.getByPlaceholder('000000').fill(code)
  if (remember) await page.getByLabel(/تذكّر هذا الجهاز/).check()
  const res = page.waitForResponse(r => r.url().includes('/api/auth/2fa/verify/'), { timeout: 30_000 })
  await page.getByRole('button', { name: 'تحقق', exact: true }).click()
  return (await res).status()
}
/** The device public id in this browser's session (the access token's `dev` claim), or null. */
async function deviceOf(context) {
  const c = (await context.cookies()).find(x => x.name === 'erp_access')
  if (!c) return null
  try { return JSON.parse(Buffer.from(c.value.split('.')[1], 'base64url').toString('utf-8')).dev || null } catch { return null }
}
async function signOut(page) {
  await page.request.post('/api/auth/logout/', { headers: XHR }).catch(() => null)   // keeps the device cookie
}

// ── the enforcement row (admin API) ──────────────────────────────────────────────────────────────
async function findSetting(adminApi) {
  for (let url = '/api/config/settings/?page_size=200'; url;) {
    const page = await call(adminApi, 'GET', url)
    const hit = (page.results || page).find(s => s.key === SETTING)
    if (hit) return hit
    url = page.next ? new URL(page.next).pathname + new URL(page.next).search : null
  }
  return null
}
async function writeSetting(adminApi, value, valueType = 'string') {
  const cur = await findSetting(adminApi)
  if (cur && cur.value_type === valueType) return call(adminApi, 'PATCH', `/api/config/settings/${cur.id}/`, { value })
  if (cur) await call(adminApi, 'DELETE', `/api/config/settings/${cur.id}/`)
  return call(adminApi, 'POST', '/api/config/settings/', {
    key: SETTING, label: 'UAT-W8 فرض المصادقة الثنائية', value, value_type: valueType, category: 'general', is_public: false })
}
async function restoreSetting(adminApi) {
  if (S.setting === undefined) return
  const cur = await findSetting(adminApi)
  if (S.setting === null) {
    if (cur) await call(adminApi, 'DELETE', `/api/config/settings/${cur.id}/`)
  } else if (!cur || cur.value !== S.setting.value || cur.value_type !== S.setting.value_type) {
    if (cur) await call(adminApi, 'DELETE', `/api/config/settings/${cur.id}/`)
    const { key, label, description, value, value_type, category, is_public } = S.setting
    await call(adminApi, 'POST', '/api/config/settings/', { key, label, description, value, value_type, category, is_public })
  }
}

/** Put the copy back: 2FA off for the user, our devices retired, lock lifted, the row restored. */
async function restoreAll(browser) {
  const problems = []
  const admin = await asUser(browser, 'admin', { desktop: true })
  try {
    if (S.profileId) await raw(admin.api, 'POST', `/api/users/${S.profileId}/unlock-login/`)
    if (S.secret) {
      try {
        const ctx = await mfaSession()
        const d = await ctx.post('/api/auth/2fa/disable/', { headers: XHR, data: { password: PASSWORD, code: totp(S.secret) } })
        if (d.status() !== 200) problems.push(`disable answered ${d.status()}`)
        await ctx.dispose()
      } catch (e) { problems.push(`disable: ${scrub(e.message)}`) }
    }
    for (const pub of S.devices) {
      const list = await call(admin.api, 'GET', `/api/access/devices/?q=${encodeURIComponent(U.username)}`)
      const d = (Array.isArray(list) ? list : list.results || []).find(x => x.public_id === pub)
      if (d && d.status !== 'retired') {
        const r = await raw(admin.api, 'POST', `/api/access/devices/${d.id}/retire/`)
        if (r.status >= 300) problems.push(`retire device ${d.id}: ${r.status}`)
      }
    }
    try { await restoreSetting(admin.api) } catch (e) { problems.push(`setting: ${scrub(e.message)}`) }
  } finally { await admin.close() }
  if (problems.length) {
    finding({ ws: WS, key: KEY, route: '/api/auth/2fa/', kind: 'decision', severity: 'P1',
      expected: 'W8 restores the copy (2FA off for the test user, devices retired, setting restored)',
      actual: `restore incomplete: ${problems.join('; ')} — rerun this spec or seed_uat_users before other runs` })
  } else {
    fs.rmSync(CLEANUP_FILE, { force: true })
  }
  return problems
}

test.describe(`2FA for ${KEY} (${U.role})`, () => {
  test.beforeAll(async ({ browser }) => {
    await assertUatCopy(BASE)
    const reg = registry()
    if (!reg[U.role]?.mfa_required) throw new Error(`UAT_MFA_KEY=${KEY} (${U.role}) is not a role with mfa_required: pick one that is`)
    // a crashed earlier run left 2FA on: clean up first
    if (fs.existsSync(CLEANUP_FILE)) {
      const old = JSON.parse(fs.readFileSync(CLEANUP_FILE, 'utf-8'))
      if (old.key === KEY) {
        Object.assign(S, { secret: old.secret || '', profileId: old.profileId, devices: new Set(old.devices || []), setting: old.setting })
        S.lastStep = Math.floor(Date.now() / 30_000) + 1   // the old run may have spent the current steps
        await restoreAll(browser)
        Object.assign(S, { secret: '', backup: [], devices: new Set(), setting: undefined })
      }
    }
    const me = await asUser(browser, KEY)
    try {
      const m = await call(me.api, 'GET', '/api/auth/me/')
      S.profileId = m.id
      const st = await call(me.api, 'GET', '/api/auth/2fa/status/')
      if (st.enabled) throw new Error(`${KEY} already has 2FA on and no saved secret — rerun seed_uat_users on the copy first`)
    } finally { await me.close() }
    const admin = await asUser(browser, 'admin', { desktop: true })
    try {
      const cur = await findSetting(admin.api)
      S.setting = cur ? { key: cur.key, label: cur.label, description: cur.description, value: cur.value,
        value_type: cur.value_type, category: cur.category, is_public: cur.is_public } : null
      saveCleanup()
    } finally { await admin.close() }
  })

  test.afterAll(async ({ browser }) => {
    const problems = await restoreAll(browser)
    expect(problems, 'the copy is restored').toEqual([])
  })

  test('B-01: a false-like enforcement row does not enforce', async ({ browser }) => {
    const admin = await asUser(browser, 'admin', { desktop: true })
    const me = await asUser(browser, KEY)
    try {
      const variants = S.setting && S.setting.value_type !== 'string'
        ? [[S.setting.value_type === 'boolean' ? 'false' : '0', S.setting.value_type]]
        : [['false', 'string'], ['False', 'string'], ['0', 'string'], ['off', 'string'], ['', 'string'], ['false', 'boolean']]
      for (const [value, type] of variants) {
        if (S.setting && type !== S.setting.value_type) continue      // never change an existing row's type
        await writeSetting(admin.api, value, type)
        const st = await call(me.api, 'GET', '/api/auth/2fa/status/')
        const ctx = await apiCtx()
        try {
          const l = await apiLogin(ctx)
          if (st.enforcement_on || l.body.mfa_setup_required || l.body.mfa_required) {
            flag({ key: KEY, route: '/api/auth/login/', kind: 'decision', severity: 'P1',
              expected: `${SETTING}=${JSON.stringify(value)} (${type}) does not enforce 2FA (B-01)`,
              actual: `enforcement_on=${st.enforcement_on}; login answered ${l.status} ${l.body.mfa_setup_required ? 'mfa_setup_required' : l.body.mfa_required ? 'mfa_required' : ''}` })
          } else {
            expect(l.status, 'a required-role user signs in without a code while enforcement is off').toBe(200)
          }
        } finally { await ctx.dispose() }
      }
    } finally {
      await restoreSetting(admin.api).catch(() => {})
      await admin.close(); await me.close()
    }
  })

  test(ENFORCE ? 'enrolment is forced at sign-in while enforcement is on' : 'enrolment from «أمان الحساب»', async ({ browser }) => {
    // A fresh browser of its own, never stateFile(KEY) (W8 triage 1d): restoreAll retires this
    // browser's device, and it used to be the device uat/.auth/<KEY>.json signs in with, so every
    // later spec for this user got 401 on a retired device.
    const context = await browser.newContext({ locale: 'ar-EG' })
    const page = await context.newPage()
    const admin = await asUser(browser, 'admin', { desktop: true })
    try {
      if (ENFORCE) {
        try {
          await writeSetting(admin.api, 'true', S.setting?.value_type === 'boolean' ? 'boolean' : 'string')
          await step(KEY, '/login', 'forced enrolment at sign-in', async () => {
            expect(await uiLogin(page), 'a required role without 2FA is sent to set-up').toBe('setup')
          })
        } finally {
          // the window ends as soon as the set-up screen showed: the enrol token is already issued
          await restoreSetting(admin.api)
        }
      } else {
        await step(KEY, '/login', 'password sign-in (2FA still off)', async () => {
          expect(await uiLogin(page), 'a user without 2FA signs in with the password').toBe('in')
        })
        await page.goto('/security')
        await page.locator('[data-tour="general-security-enable"]').click()
      }
      await step(KEY, ENFORCE ? '/login (set-up)' : '/security', 'scan / type the key, confirm a code, see backup codes', async () => {
        const secretBox = page.locator('div.font-mono.break-all').first()
        await expect(secretBox).toBeVisible({ timeout: 30_000 })
        S.secret = (await secretBox.innerText()).replace(/\s/g, '')
        saveCleanup()
        await page.locator('[data-tour="general-security-code"]').fill(totp(S.secret))
        const res = page.waitForResponse(r => r.url().includes('/api/auth/2fa/enable/'), { timeout: 30_000 })
        await page.locator('[data-tour="general-security-confirm"]').click()
        expect((await res).status(), '2fa/enable answers 200').toBe(200)
        const codes = page.locator('[data-tour="general-security-backup-codes"] > div')
        await expect(codes.first()).toBeVisible()
        S.backup = (await codes.allInnerTexts()).map(s => s.trim())
        expect(S.backup.length, 'ten backup codes').toBe(10)
        await page.getByRole('button', { name: /حفظت الرموز/ }).click()
        if (ENFORCE) await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 60_000 })
      })
      const pub = await deviceOf(context)
      if (pub) { S.devices.add(pub); saveCleanup() }
      const ctx = await mfaSession()
      try {
        const st = await statusOf(ctx)
        expect(st.enabled).toBe(true)
        expect(st.backup_codes_left).toBe(10)
        expect(st.required_for_role).toBe(true)
      } finally { await ctx.dispose() }
    } finally { await admin.close(); await context.close() }
  })

  test('sign-in with a TOTP code: a wrong code is refused, the right one signs in', async ({ browser }) => {
    test.skip(!S.secret, 'not enrolled')
    const context = await browser.newContext({ locale: 'ar-EG' })
    const page = await context.newPage()
    try {
      await step(KEY, '/login', 'code step', async () => {
        expect(await uiLogin(page)).toBe('verify')
        const wrong = String((Number(totp(S.secret)) + 500_000) % 1_000_000).padStart(6, '0')
        expect(await uiVerify(page, wrong), 'a wrong code answers 401').toBe(401)
        await expect(page.locator('.bg-red-50')).toContainText('رمز التحقق غير صحيح')
        expect(await uiVerify(page, await nextCode()), 'the right code answers 200').toBe(200)
        await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 60_000 })
      })
      const pub = await deviceOf(context)
      if (pub) { S.devices.add(pub); saveCleanup() }
    } finally { await context.close() }
  })

  test('backup codes sign in once only', async () => {
    test.skip(S.backup.length < 2, 'no backup codes')
    const code = S.backup[0]
    const a = await apiCtx()
    try {
      const l = await apiLogin(a)
      expect(l.body.mfa_required).toBe(true)
      const v = await apiVerify(a, l.body.mfa_token, code)
      expect(v.status, 'an unused backup code signs in').toBe(200)
      expect((await statusOf(a)).backup_codes_left).toBe(9)
    } finally { await a.dispose() }
    const b = await apiCtx()
    try {
      const l = await apiLogin(b)
      const again = await apiVerify(b, l.body.mfa_token, code)
      if (again.status === 200) {
        flag({ key: KEY, route: '/api/auth/2fa/verify/', kind: 'workflow', severity: 'P0', expected: 'a used backup code is refused', actual: 'the same backup code signed in twice' })
      } else {
        expect(again.status).toBe(401)
      }
      // finish with a good code: a completed sign-in ends the failure streak (lockout)
      expect((await apiVerify(b, l.body.mfa_token, await nextCode())).status).toBe(200)
    } finally { await b.dispose() }
  })

  test('«تذكّر هذا الجهاز» skips the code only on an approved device; the admin cancels it', async ({ browser }) => {
    test.skip(!S.secret, 'not enrolled')
    const context = await browser.newContext({ locale: 'ar-EG' })
    const page = await context.newPage()
    const admin = await asUser(browser, 'admin', { desktop: true })
    try {
      // a: a new (pending) device: «remember» is not honoured
      await step(KEY, '/login', 'remember on a pending device', async () => {
        expect(await uiLogin(page)).toBe('verify')
        expect(await uiVerify(page, await nextCode(), { remember: true })).toBe(200)
        await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 60_000 })
      })
      const pub = await deviceOf(context)
      expect(pub, 'the sign-in enrolled this browser as a device').toBeTruthy()
      S.devices.add(pub); saveCleanup()
      await signOut(page)
      const pendingAgain = await uiLogin(page)
      if (pendingAgain !== 'verify') {
        flag({ key: KEY, route: '/login', kind: 'workflow', severity: 'P1', expected: 'a pending device never skips the code (N2)', actual: `second sign-in: ${pendingAgain}` })
      } else {
        expect(await uiVerify(page, await nextCode())).toBe(200)
      }
      // b: the admin approves the device; «remember» now skips the code
      await step('admin', '/access/devices', 'approve the browser device', async () => {
        const list = await call(admin.api, 'GET', `/api/access/devices/?q=${encodeURIComponent(U.username)}`)
        const d = (Array.isArray(list) ? list : list.results || []).find(x => x.public_id === pub)
        expect(d, 'the device is listed for the admin').toBeTruthy()
        await call(admin.api, 'POST', `/api/access/devices/${d.id}/approve/`)
      })
      await signOut(page)
      expect(await uiLogin(page)).toBe('verify')
      expect(await uiVerify(page, await nextCode(), { remember: true })).toBe(200)
      await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 60_000 })
      await signOut(page)
      const remembered = await uiLogin(page)
      if (remembered !== 'in') {
        flag({ key: KEY, route: '/login', kind: 'workflow', severity: 'P2', expected: 'an approved, remembered device signs in without a code (30 days)', actual: `sign-in: ${remembered}` })
      }
      // c: admin «إلغاء الأجهزة المحفوظة» → the code is asked again
      // soft (W8 triage 4): a failing forget is recorded and the serial tail (lockout, admin reset,
      // 2FA off) still runs. The server bumps the device epoch before the audit row, so the check
      // below still means something when only the audit write failed (users 0063 drift repair).
      const forget = await raw(admin.api, 'POST', `/api/users/${S.profileId}/forget-devices/`)
      if (forget.status !== 200) {
        finding({ ws: WS, key: 'admin', route: '/api/users/:id/forget-devices/', kind: forget.status >= 500 ? 'crash' : 'workflow',
          severity: 'P1', expected: 'the admin «إلغاء الأجهزة المحفوظة» answers 200 and is audited',
          actual: `HTTP ${forget.status} ${scrub(JSON.stringify(forget.body)).slice(0, 200)}` })
        test.info().annotations.push({ type: 'finding', description: `forget-devices answered ${forget.status} (recorded P1, continuing)` })
      }
      await signOut(page)
      const after = await uiLogin(page)
      if (after !== 'verify') {
        flag({ key: KEY, route: '/login', kind: 'workflow', severity: 'P1', expected: 'after the admin forgets saved devices the code is asked again (N0/H7)', actual: `sign-in: ${after}` })
      } else {
        expect(await uiVerify(page, await nextCode())).toBe(200)
      }
    } finally { await admin.close(); await context.close() }
  })

  test('five wrong codes lock the account until the admin unlocks it', async ({ browser }) => {
    test.skip(!S.secret, 'not enrolled')
    const ctx = await apiCtx()
    const admin = await asUser(browser, 'admin', { desktop: true })
    try {
      const l = await apiLogin(ctx)
      expect(l.body.mfa_required).toBe(true)
      const seen = []
      for (let i = 0; i < 5; i++) {
        const wrong = String((Number(totp(S.secret)) + 111_111 * (i + 1)) % 1_000_000).padStart(6, '0')
        seen.push((await apiVerify(ctx, l.body.mfa_token, wrong)).status)
      }
      expect(seen.every(s => s === 401 || s === 429), `wrong codes answer 401/429 (${seen.join(',')})`).toBe(true)
      // the dead login token takes no more codes, even the right one
      const late = await apiVerify(ctx, l.body.mfa_token, totp(S.secret))
      if (late.status === 200) flag({ key: KEY, route: '/api/auth/2fa/verify/', kind: 'workflow', severity: 'P0', expected: 'after 5 wrong codes the login token is dead (A-2)', actual: 'the right code still signed in' })
      const locked = await apiLogin(ctx)
      if (locked.status !== 429) {
        flag({ key: KEY, route: '/api/auth/login/', kind: 'workflow', severity: 'P1', expected: '5 wrong codes in 15 min lock the account (H8): 429, the right password included', actual: `HTTP ${locked.status}` })
      }
      await call(admin.api, 'POST', `/api/users/${S.profileId}/unlock-login/`)
      const open = await apiLogin(ctx)
      expect(open.body.mfa_required, 'after the admin unlock the password step works again').toBe(true)
      expect((await apiVerify(ctx, open.body.mfa_token, await nextCode())).status).toBe(200)
    } finally { await admin.close(); await ctx.dispose() }
  })

  test('admin reset of the user\'s 2FA', async ({ browser }) => {
    test.skip(!S.secret, 'not enrolled')
    const admin = await asUser(browser, 'admin', { desktop: true })
    try {
      // there is no admin "reset 2FA" endpoint or control (apps/users: only forget-devices and
      // unlock-login); a PATCH of mfa_enabled must not switch it off silently either
      const r = await raw(admin.api, 'PATCH', `/api/users/staff/${S.profileId}/`, { mfa_enabled: false })
      const ctx = await mfaSession()
      try {
        const st = await statusOf(ctx)
        if (!st.enabled) {
          flag({ key: 'admin', route: '/api/users/staff/:id/', kind: 'workflow', severity: 'P1', expected: 'mfa_enabled is not an editable profile field', actual: `PATCH ${r.status} switched 2FA off` })
          S.secret = ''
        }
      } finally { await ctx.dispose() }
      finding({ ws: WS, key: 'admin', route: '/users', kind: 'decision', severity: 'P2',
        expected: 'an admin can reset a user\'s 2FA (lost phone and lost backup codes)',
        actual: 'no admin reset exists: the admin can forget saved devices and lift a lock, but a user without phone and backup codes cannot sign in again until 2FA is cleared in the database' })
    } finally { await admin.close() }
  })

  test('2FA off again (password + code)', async () => {
    test.skip(!S.secret, 'not enrolled')
    const ctx = await mfaSession()
    try {
      const wrongPw = await ctx.post('/api/auth/2fa/disable/', { headers: XHR, data: { password: `${PASSWORD}x`, code: totp(S.secret) } })
      expect(wrongPw.status(), 'a wrong password never switches 2FA off').toBe(400)
      const d = await ctx.post('/api/auth/2fa/disable/', { headers: XHR, data: { password: PASSWORD, code: totp(S.secret) } })
      expect(d.status()).toBe(200)
      expect((await statusOf(ctx)).enabled).toBe(false)
      S.secret = ''; S.backup = []; saveCleanup()
    } finally { await ctx.dispose() }
  })
})
