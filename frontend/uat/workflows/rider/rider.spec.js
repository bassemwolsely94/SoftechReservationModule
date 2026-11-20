// W8 rider /rider worked through (docs/uat/runs/w8-plan.md).
//   gate     — every home role: /rider opens iff the live matrix grants `rider` view (after the role
//              review: admin, delivery, supervisor, call center); without it the screen is refused or
//              redirected and /api/delivery/app/my-orders/ answers 403;
//   shell    — the delivery role is sent from /, /dashboard and /m to /rider, and /security to
//              /rider/security (2FA self-service inside the rider shell);
//   journey  — the rider's «طلباتي» (my-orders) and «مساري» (my-route) answer; completing an order
//              with collected cash takes a decimal amount, and junk amounts answer 400 (never 500) and
//              leave the order out for delivery.
// The order is created and assigned through the API (W5a delivery.spec.js drives those screens);
// the cash completion runs through the rider's proof-of-delivery sheet.
import { test, expect } from '@playwright/test'
import { BRANCH_A, userByKey } from '../../lib/users.js'
import { gotoSettled } from '../../lib/page.js'
import { finding } from '../../lib/findings.js'
import {
  WS, HOME, TWINS_B, asUser, live, allows, requireRoleReviewCopy, flag, step, call, raw, clickFor,
  tag, FAKE_PHONE, BASE, scrub, rows, idOf,
} from '../_w8.js'
import { assertReaderCopy } from '../../lib/guard.js'

test.use({ trace: 'off' })
test.describe.configure({ timeout: 10 * 60_000 })

const RIDER = 'delivery'
const RIDER_GEO = { geolocation: { latitude: 30.0619, longitude: 31.2466 }, permissions: ['geolocation'] }
const DRIVER_TAG = 'UAT-W8 سائق'

test.beforeAll(async () => {
  await requireRoleReviewCopy(BASE)
  await assertReaderCopy(BASE)          // the journey writes delivery rows: reader copy, every writer off
})

// ── gate per role ─────────────────────────────────────────────────────────────────────────────────
for (const key of HOME) {
  test(`gate: ${key} on /rider follows the rider grant`, async ({ browser }) => {
    const { page, api, close } = await asUser(browser, key)
    try {
      const l = await live(api)
      const want = allows(l, 'rider', 'view')
      test.skip(want === null, 'rider has no matrix rows on this copy')
      const r = await gotoSettled(page, '/rider')
      const stayed = /^\/rider\/?$/.test(r.finalUrl)
      if (r.status === 'crash') {
        flag({ key, route: '/rider', kind: 'crash', severity: 'P1', expected: '/rider opens or refuses calmly', actual: `crash (${scrub(r.consoleErrors[0] || '')})` })
      } else if (want && (!stayed || r.status === 'refused')) {
        flag({ key, route: '/rider', kind: 'screen', severity: 'P1', expected: `/rider opens (rider:view for ${l.role})`, actual: `${r.status}, landed on ${r.finalUrl}` })
      } else if (!want && stayed && r.status === 'ok') {
        flag({ key, route: '/rider', kind: 'screen', severity: 'P1', expected: `/rider refused or redirected (no rider:view for ${l.role})`, actual: 'the rider screen rendered' })
      }
      const mine = await raw(api, 'GET', '/api/delivery/app/my-orders/')
      if (mine.status >= 500) flag({ key, route: '/api/delivery/app/my-orders/', kind: 'crash', severity: 'P1', expected: 'answers', actual: `HTTP ${mine.status}` })
      if (!want && mine.status === 200) {
        flag({ key, route: '/api/delivery/app/my-orders/', kind: 'workflow', severity: 'P1', expected: 'refused without rider:view', actual: 'HTTP 200' })
      }
      if (want && l.role !== 'delivery' && mine.status === 403 && stayed) {
        // a rider-module holder with no driver profile: the server says so (403 «ليس لديك ملف سائق»);
        // the screen must say it calmly, not sit blank
        const text = (await page.locator('main, #root').first().innerText({ timeout: 5_000 }).catch(() => '')).trim()
        if (text.length < 20) {
          finding({ ws: WS, key, route: '/rider', kind: 'screen', severity: 'P3',
            expected: 'a rider-module holder without a driver profile is told so on /rider', actual: `near-empty screen (${text.length} chars)` })
        }
      }
    } finally { await close() }
  })
}

// ── delivery role lives on /rider ────────────────────────────────────────────────────────────────
for (const key of [...HOME, ...TWINS_B].filter(k => userByKey(k).role === 'delivery')) {
  test(`shell: ${key} is sent to /rider (and /security to /rider/security)`, async ({ browser }) => {
    const { page, close } = await asUser(browser, key)
    try {
      for (const [route, want] of [['/', /^\/rider\/?$/], ['/dashboard', /^\/rider\/?$/], ['/m', /^\/rider\/?$/],
        ['/reservations', /^\/rider\/?$/], ['/security', /^\/rider\/security\/?$/]]) {
        const r = await gotoSettled(page, route)
        if (!want.test(r.finalUrl)) {
          flag({ key, route, kind: 'screen', severity: 'P1', expected: `delivery role sent to ${want.source.replace(/\\|\^|\$|\?/g, '')}`, actual: `landed on ${r.finalUrl} (${r.status})` })
        }
      }
      const s = await gotoSettled(page, '/rider/security')
      await step(key, '/rider/security', 'the security page opens in the rider shell', async () => {
        expect(s.status).not.toBe('crash')
        await expect(page.locator('[data-tour="general-security-header"]')).toBeVisible({ timeout: 30_000 })
        await expect(page.locator('[data-tour="general-security-status"]')).toBeVisible()
      })
    } finally { await close() }
  })
}

// ── the rider's journey: my orders, my route, cash completion ────────────────────────────────────
test.describe('journey: assigned order → my orders / my route → delivered with collected cash', () => {
  test('delivery rider completes a cash order; junk amounts answer 400', async ({ browser }) => {
    const note = tag('rider')
    const customer = `${note} عميل`
    // 1. the rider's driver profile (the copy has none linked to a UAT user): supervisor registers it
    const rd = await asUser(browser, RIDER, RIDER_GEO)
    const riderProfileId = (await call(rd.api, 'GET', '/api/auth/me/')).id
    await rd.close()
    let driverId, orderId
    const sup = await asUser(browser, 'supervisor', { desktop: true })
    try {
      await step('supervisor', '/delivery (drivers)', 'register / reuse the UAT rider', async () => {
        const found = rows(await call(sup.api, 'GET', `/api/delivery/drivers/?search=${encodeURIComponent('UAT')}`))
        const mine = found.find(d => d.staff_profile === riderProfileId)
        driverId = mine?.id ?? idOf(await call(sup.api, 'POST', '/api/delivery/drivers/', {
          full_name: DRIVER_TAG, mobile: FAKE_PHONE(3), staff_profile: riderProfileId,
          branch: BRANCH_A.id, vehicle_type: 'motorcycle', status: 'active', notes: note }))
        if (!driverId) driverId = rows(await call(sup.api, 'GET', `/api/delivery/drivers/?search=${encodeURIComponent('UAT')}`)).find(d => d.staff_profile === riderProfileId)?.id
        expect(driverId, 'the rider has a driver profile').toBeTruthy()
      })
    } finally { await sup.close() }

    // 2. call center creates a cash order of 49.75 for branch A and assigns the rider
    const cc = await asUser(browser, 'call_center', { desktop: true })
    try {
      await step('call_center', '/delivery', 'create + assign a cash order', async () => {
        const body = await call(cc.api, 'POST', '/api/delivery/', {
          source_type: 'call_center', branch: BRANCH_A.id, customer_name: customer, customer_phone: FAKE_PHONE(4),
          delivery_address: 'UAT عنوان تجريبي', total_value: 49.75, delivery_fees: 0, payment_method: 'cash', notes: note })
        orderId = idOf(body) ?? rows(await call(cc.api, 'GET', `/api/delivery/?search=${encodeURIComponent(note)}`)).find(o => o.customer_name === customer)?.id
        expect(orderId, 'the new order is listed').toBeTruthy()
        await call(cc.api, 'POST', `/api/delivery/${orderId}/assign/`, { driver_id: driverId })
        expect((await call(cc.api, 'GET', `/api/delivery/${orderId}/`)).status).toBe('assigned')
      })
    } finally { await cc.close() }

    // 3. the rider: my orders + my route answer and carry the order; accept + leave
    const { page, api, close } = await asUser(browser, RIDER, RIDER_GEO)
    const status = async () => (await call(api, 'GET', `/api/delivery/${orderId}/`)).status
    try {
      await step(RIDER, '/rider', '«طلباتي» and «مساري» answer', async () => {
        const mine = rows(await call(api, 'GET', '/api/delivery/app/my-orders/'))
        expect(mine.some(o => o.id === orderId), 'the assigned order is in my-orders').toBe(true)
        const route = await call(api, 'GET', '/api/delivery/app/my-route/')
        expect(route && typeof route === 'object', 'my-route answers an object (a route, or {route: null, orders: []})').toBe(true)
      })
      await step(RIDER, '/rider', 'accept and leave', async () => {
        await gotoSettled(page, '/rider')
        const card = page.locator('[data-tour="delivery-driver-stops"] > div', { hasText: customer })
        for (const [action, want] of [['accept', 'driver_accepted'], ['dispatch', 'out_for_delivery']]) {
          await expect(card, 'the assigned order shows on the rider screen').toBeVisible({ timeout: 45_000 })
          await clickFor(page, card.locator('[data-tour="delivery-driver-next"]'), new RegExp(`/api/delivery/${orderId}/${action}/$`))
          await expect.poll(status).toBe(want)
        }
      })

      // 4. junk amounts: 400, never 500, and the order stays out for delivery
      for (const junk of ['abc', '-5', 'NaN', 'Infinity', '1e999', '12.345', '1,000', '٥٠..٥', '99999999999', true]) {
        const r = await raw(api, 'POST', `/api/delivery/${orderId}/complete/`, { collected_amount: junk, recipient_name: 'UAT' })
        const shown = typeof junk === 'string' ? junk.replace(/\d{8,}/g, '#') : String(junk)
        if (r.status >= 500) {
          flag({ key: RIDER, route: '/api/delivery/:id/complete/', kind: 'crash', severity: 'P1', expected: `collected_amount "${shown}" → 400`, actual: `HTTP ${r.status}` })
        } else if (r.status !== 400) {
          flag({ key: RIDER, route: '/api/delivery/:id/complete/', kind: 'workflow', severity: 'P1', expected: `collected_amount "${shown}" refused with 400`, actual: `HTTP ${r.status} ${scrub(JSON.stringify(r.body))}` })
        }
        const now = await status()
        if (now !== 'out_for_delivery') {
          flag({ key: RIDER, route: '/api/delivery/:id/complete/', kind: 'workflow', severity: 'P1', expected: 'a refused amount writes nothing', actual: `order is ${now} after collected_amount "${shown}"` })
          break
        }
      }

      // 5. the decimal amount through the proof-of-delivery sheet
      await step(RIDER, '/rider', '«تم التسليم ✅» with 49.75 collected', async () => {
        await gotoSettled(page, '/rider')
        const card = page.locator('[data-tour="delivery-driver-stops"] > div', { hasText: customer })
        await expect(card).toBeVisible({ timeout: 45_000 })
        await card.locator('[data-tour="delivery-driver-deliver"]').click()
        await page.locator('[data-tour="delivery-driver-pod-recipient"]').fill('UAT مستلم')
        await page.locator('[data-tour="delivery-driver-pod-cash"]').fill('49.75')
        await page.getByPlaceholder('مثال: سُلّم للبواب').fill(note)
        await clickFor(page, page.locator('[data-tour="delivery-driver-pod-confirm"]'), new RegExp(`/api/delivery/${orderId}/complete/$`))
        await expect.poll(status).toBe('delivered')
        const o = await call(api, 'GET', `/api/delivery/${orderId}/`)
        expect(Number(o.collected_amount), 'collected amount kept to the piastre').toBe(49.75)
      })
    } finally { await close() }
  })
})
