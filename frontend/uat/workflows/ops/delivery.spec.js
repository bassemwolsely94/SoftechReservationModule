// W5a delivery dispatch: the call center creates a delivery order («+ طلب جديد»), assigns the
// branch rider («تكليف سائق»), and the rider runs it on /rider: «قبول الطلب» → «انطلقت 🚚» →
// «تم التسليم ✅» with proof of delivery. The copy has no rider linked to a UAT user, so a
// supervisor first registers one (DeliveryDriver linked to uat_delivery, name UAT-…).
// Must-refuse: the branch-B rider acting on this branch-A order; a role without delivery:assign
// assigning it; the rider role creating an order.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import {
  asUser, step, clickFor, call, mustRefuse, WS, firstWho, firstNot, tag, FAKE_PHONE, field, BASE, scrub, remember, recall,
} from './_ops.js'

const AREA = 'delivery'
const DRIVER_NAME = 'UAT-W5a سائق الفرع'
// Rider steps record the phone's location; pretend the rider stands in central Cairo.
const RIDER_GEO = { geolocation: { latitude: 30.0619, longitude: 31.2466 }, permissions: ['geolocation'] }

test.describe('delivery: create → assign → rider delivers', () => {
  const manager = firstWho(['supervisor'], 'delivery', 'create')
  const dispatcher = firstWho(['call_center', 'supervisor', 'pharmacist'], 'delivery', 'assign')
  const creator = firstWho(['call_center', 'pharmacist', 'salesperson'], 'delivery', 'create')
  const rider = 'delivery'
  const noAssign = firstNot(['salesperson', 'viewer', 'quality_manager'], 'delivery', 'assign')
  let id = null, number = null, driverId = null
  let note = tag('delivery')
  let customer = `${note} عميل`

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${manager} registers the branch rider (linked to the UAT delivery user)`, async ({ browser }) => {
    remember(AREA, null)
    remember(AREA, { note, customer })
    const r = await asUser(browser, rider)
    let riderProfileId
    try {
      await r.page.goto('/rider')
      riderProfileId = (await call(r.api, 'GET', '/api/auth/me/')).id
    } finally { await r.close() }
    const { page, api, close } = await asUser(browser, manager)
    try {
      await page.goto('/delivery')
      await step(manager, '/delivery (drivers)', 'register a rider', async () => {
        const found = await call(api, 'GET', `/api/delivery/drivers/?search=${encodeURIComponent('UAT-W5a')}`)
        const mine = (found.results || found).find(d => d.staff_profile === riderProfileId)
        if (mine) { driverId = mine.id; remember(AREA, { driverId }); return }
        const d = await call(api, 'POST', '/api/delivery/drivers/', {
          full_name: DRIVER_NAME, mobile: FAKE_PHONE(3), staff_profile: riderProfileId,
          branch: BRANCH_A.id, vehicle_type: 'motorcycle', status: 'active', notes: note })
        driverId = d.id; remember(AREA, { driverId })
      })
    } finally { await close() }
  })

  test(`${creator} creates a delivery order and ${dispatcher} assigns the rider`, async ({ browser }) => {
    expect(creator && dispatcher).toBeTruthy()
    const c = await asUser(browser, creator)
    try {
      await step(creator, '/delivery', 'create delivery order («+ طلب جديد»)', async () => {
        const { page } = c
        await page.goto('/delivery')
        await page.locator('[data-tour="delivery-dashboard-new"]').click()
        const form = page.locator('[data-tour="delivery-dashboard-new-form"]')
        await field(form, 'الفرع *', 'select').selectOption(String(BRANCH_A.id))
        await field(form, 'اسم العميل *', 'input').fill(customer)
        await field(form, 'الهاتف', 'input').fill(FAKE_PHONE(4))
        await field(form, 'العنوان التفصيلي', 'input, textarea').fill('UAT عنوان تجريبي')
        await field(form, 'قيمة الطلب (ج.م) *', 'input').fill('50')
        await field(form, 'ملاحظات', 'input, textarea').fill(note)
        const { body } = await clickFor(page, page.locator('[data-tour="delivery-dashboard-new-submit"]'), /\/api\/delivery\/$/)
        // the create answer carries the write fields only (no id) - find the order by its UAT name
        const found = await call(page.request, 'GET', `/api/delivery/?search=${encodeURIComponent(note)}`)
        const o = (found.results || found).find(x => x.customer_name === customer)
        id = body?.id || o?.id; number = body?.order_number || o?.order_number
        remember(AREA, { id, number })
        expect(id, 'the new order is listed').toBeTruthy()
      })
    } finally { await c.close() }

    id ??= recall(AREA).id; number ??= recall(AREA).number; driverId ??= recall(AREA).driverId; note = recall(AREA).note ?? note; customer = recall(AREA).customer ?? customer
    test.skip(!id, 'no order to assign')
    const d = await asUser(browser, dispatcher)
    try {
      await step(dispatcher, '/delivery', 'assign rider («تكليف سائق»)', async () => {
        const { page } = d
        await page.goto('/delivery')
        await page.locator('[data-tour="delivery-dashboard-search"]').fill(note)
        const row = page.locator('div.px-5.py-4', { hasText: number })
        await row.waitFor({ timeout: 20_000 }).catch(() => {})
        if (!(await row.count())) {
          // The dashboard's default «today» is new Date().toISOString() = the UTC date: after midnight
          // Cairo (before 02:00/03:00) it filters on yesterday and hides the new order.
          const local = new Date().toLocaleDateString('en-CA')
          if (local !== new Date().toISOString().slice(0, 10)) {
            finding({ ws: WS, key: dispatcher, route: '/delivery', kind: 'workflow', severity: 'P2',
                      expected: 'an order created now shows on the delivery dashboard (default range = today)',
                      actual: 'between 00:00 and 02:00 Cairo the dashboard hides new orders: _today() in DeliveryDashboard.jsx uses toISOString() (UTC date), so the default range is yesterday' })
          }
          await page.locator('[data-tour="delivery-dashboard-dates"]').click()
          await page.locator('input[type="date"]').first().fill(local)
          await page.locator('input[type="date"]').nth(1).fill(local)
        }
        await row.getByRole('button', { name: 'تكليف سائق' }).click()
        const picker = field(page, 'اختر من قائمة السائقين', 'select')
        // the picker appears once the active-drivers list has loaded; a typed name alone is not linked
        // to the rider's account, so the order would never reach /rider
        await picker.waitFor({ timeout: 20_000 })
        await picker.selectOption(String(driverId))
        await clickFor(page, page.locator('[data-tour="delivery-dashboard-assign-submit"]'), /\/api\/delivery\/\d+\/assign\/$/)
        const o = await call(page.request, 'GET', `/api/delivery/${id}/`)
        expect(o.status).toBe('assigned')
      })
    } finally { await d.close() }
  })

  test(`must-refuse: delivery@B accepting it, ${noAssign} assigning it, ${rider} creating an order`, async ({ browser }) => {
    id ??= recall(AREA).id; number ??= recall(AREA).number; driverId ??= recall(AREA).driverId; note = recall(AREA).note ?? note; customer = recall(AREA).customer ?? customer
    test.skip(!id, 'no order from the previous step')
    const checks = [
      ['delivery@B', 'accept a branch-A order assigned to another rider', 'POST', `/api/delivery/${id}/accept/`, {}],
      [noAssign, 'assign a rider (no delivery:assign)', 'POST', `/api/delivery/${id}/assign/`, { driver_name: 'UAT-refusal' }],
      [rider, 'create a delivery order (rider role)', 'POST', '/api/delivery/', { branch: BRANCH_A.id, customer_name: 'UAT-refusal', notes: 'UAT-refusal' }],
    ]
    for (const [key, what, method, url, data] of checks) {
      const { page, api, close } = await asUser(browser, key)
      try {
        await page.goto(key.startsWith('delivery') ? '/rider' : '/dashboard')
        await mustRefuse(api, { key, route: '/delivery', what, method, url, data })
      } finally { await close() }
    }
  })

  test(`${rider} accepts, leaves and delivers on /rider`, async ({ browser }) => {
    id ??= recall(AREA).id; number ??= recall(AREA).number; driverId ??= recall(AREA).driverId; note = recall(AREA).note ?? note; customer = recall(AREA).customer ?? customer
    test.skip(!id, 'no order from the previous step')
    const { page, close } = await asUser(browser, rider, RIDER_GEO)
    const status = async () => (await call(page.request, 'GET', `/api/delivery/${id}/`)).status
    try {
      await page.goto('/rider')
      const card = page.locator('[data-tour="delivery-driver-stops"] > div', { hasText: customer })
      for (const [label, action, want] of [['قبول الطلب', 'accept', 'driver_accepted'], ['انطلقت 🚚', 'dispatch', 'out_for_delivery']]) {
        await step(rider, '/rider', `rider «${label}»`, async () => {
          await expect(card, 'the assigned order shows on the rider screen').toBeVisible({ timeout: 45_000 })
          await clickFor(page, card.locator('[data-tour="delivery-driver-next"]'), new RegExp(`/api/delivery/${id}/${action}/$`))
          await expect.poll(status).toBe(want)
        })
      }
      await step(rider, '/rider', 'rider «تم التسليم ✅» with proof of delivery', async () => {
        await card.locator('[data-tour="delivery-driver-deliver"]').click()
        await page.locator('[data-tour="delivery-driver-pod-recipient"]').fill('UAT مستلم')
        await page.locator('[data-tour="delivery-driver-pod-cash"]').fill('50')
        await page.getByPlaceholder('مثال: سُلّم للبواب').fill(note)
        try {
          await clickFor(page, page.locator('[data-tour="delivery-driver-pod-confirm"]'), new RegExp(`/api/delivery/${id}/complete/$`))
        } catch (e) {
          // A 5xx after the status was saved leaves a half-done delivery: say so separately.
          if (await status() === 'delivered') {
            finding({ ws: WS, key: rider, route: '/rider', kind: 'workflow', severity: 'P1',
                      expected: 'proof of delivery is all-or-nothing: delivered + cash collection record, or nothing',
                      actual: `order ${number} was saved as delivered although the call failed (${scrub(e.message).slice(0, 120)}); for a cash order the cash collection record is then missing and the rider sees an error` })
          }
          throw e
        }
        await expect.poll(status).toBe('delivered')
      })
    } finally { await close() }
  })
})
