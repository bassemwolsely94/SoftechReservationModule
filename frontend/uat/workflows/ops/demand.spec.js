// W5a demand: a branch role records a demand («+ تسجيل طلب جديد») with a free-text item, schedules a
// follow-up on it («+ إضافة متابعة» → «جدولة»); a second role completes that follow-up; a role
// that must not schedule follow-ups is refused.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A } from '../../lib/users.js'
import {
  asUser, step, clickFor, mustRefuse, firstWho, firstNot, tag, FAKE_PHONE, pickBranch, BASE, remember, recall,
} from './_ops.js'

const AREA = 'demand'
const tomorrow = () => new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)

test.describe('demand: record → follow-up', () => {
  const recorder = firstWho(['salesperson', 'pharmacist', 'call_center'], 'demand', 'create')
  const closer = firstWho(['pharmacist', 'supervisor'].filter(k => k !== recorder), 'demand', 'edit')
  const outsider = firstNot(['viewer', 'quality_manager', 'accountant', 'delivery'], 'demand', 'edit')
  let id = null
  const note = tag('demand')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${recorder} records a demand and schedules a follow-up`, async ({ browser }) => {
    remember(AREA, null)
    expect(recorder, 'some branch-A role may record demand').toBeTruthy()
    const { page, close } = await asUser(browser, recorder)
    try {
      await step(recorder, '/demand', 'record demand', async () => {
        await page.goto('/demand')
        await page.locator('[data-tour="demand-list-new"]').click()
        const cust = page.locator('[data-tour="demand-list-create-customer"]')
        await cust.getByPlaceholder('01003280328').fill(FAKE_PHONE(2))
        await cust.getByPlaceholder('اسم العميل').fill('عميل UAT')
        const details = page.locator('[data-tour="demand-new-details"]')
        if (await details.getByText('اختر الفرع...').count()) await pickBranch(page, 'اختر الفرع...', BRANCH_A.code)
        await page.locator('[data-tour="demand-list-create-uncoded"]').click()
        await page.getByPlaceholder('اسم الصنف (نص حر)').last().fill(`${note} صنف`)
        await page.getByPlaceholder('أي تفاصيل إضافية...').fill(note)
        const { body } = await clickFor(page, page.locator('[data-tour="demand-list-create-submit"]'), /\/api\/demand\/$/)
        id = body.id; remember(AREA, { id })
        expect(id).toBeTruthy()
      })
      const route = `/demand/${id}`
      await step(recorder, route, 'schedule follow-up', async () => {
        await page.goto(route)
        await page.locator('[data-tour="demand-detail-tabs"]').getByText(/متابع/).first().click()
        await page.locator('[data-tour="demand-detail-followup-add"]').click()
        await page.locator('input[type="date"]').last().fill(tomorrow())
        await page.getByPlaceholder('تفاصيل المتابعة...').fill(note)
        await clickFor(page, page.locator('[data-tour="demand-detail-followup-schedule"]'), /\/schedule-followup\/$/)
        const fus = await (await page.request.get(`/api/demand/${id}/followups/`)).json()
        const list = Array.isArray(fus) ? fus : fus.results || []
        expect(list.length, 'the scheduled follow-up is listed').toBeGreaterThan(0)
      })
    } finally { await close() }
  })

  test(`${closer} completes the follow-up`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no demand from the previous step')
    const { page, close } = await asUser(browser, closer)
    const route = `/demand/${id}`
    try {
      await step(closer, route, 'complete follow-up', async () => {
        await page.goto(route)
        await page.locator('[data-tour="demand-detail-tabs"]').getByText(/متابع/).first().click()
        // «إتمام» asks for notes in a prompt(); asUser() answers it with a UAT- note.
        await clickFor(page, page.locator('[data-tour="demand-detail-followup-complete"]').first(), /\/followups\/\d+\/complete\/$/)
        const fus = await (await page.request.get(`/api/demand/${id}/followups/`)).json()
        const list = Array.isArray(fus) ? fus : fus.results || []
        expect(list.some(f => f.completed_at || f.status === 'completed' || f.is_completed), 'a follow-up shows completed').toBe(true)
      })
    } finally { await close() }
  })

  test(`${outsider} must not schedule a follow-up or record demand`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no demand from the previous step')
    const { page, api, close } = await asUser(browser, outsider)
    try {
      await page.goto('/dashboard')
      await mustRefuse(api, { key: outsider, route: `/demand/${id}`, what: 'POST schedule-followup on a demand',
                              method: 'POST', url: `/api/demand/${id}/schedule-followup/`, data: { hours_from_now: 24, task_type: 'call', note: 'UAT-refusal' } })
      await mustRefuse(api, { key: outsider, route: '/demand', what: 'POST a new demand',
                              method: 'POST', url: '/api/demand/',
                              data: { phone: FAKE_PHONE(9), branch: BRANCH_A.id, notes: 'UAT-refusal', items: [{ item_name_free: 'UAT-refusal', quantity: 1 }] } })
    } finally { await close() }
  })
})
