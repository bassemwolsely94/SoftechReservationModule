// W5a call-center case: an agent opens a case for a known branch-A customer («فتح حالة جديدة»),
// starts work on it, resolves it («✅ حل الحالة») and closes it («🔒 إغلاق»).
// Must-refuse: a branch role with no callcenter access opening or resolving a case.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { reference } from '../../lib/expected.js'
import { finding } from '../../lib/findings.js'
import {
  asUser, step, clickFor, call, mustRefuse, WS, firstWho, firstNot, tag, field, BASE, remember, recall,
} from './_ops.js'

const AREA = 'callcenter'
const CASE = a => new RegExp(`/api/callcenter/cases/\\d+/${a}/$`)

test.describe('call-center case: open → work → resolve → close', () => {
  const agent = firstWho(['call_center', 'supervisor'], 'callcenter', 'create')
  const outsider = firstNot(['pharmacist', 'salesperson', 'viewer', 'accountant'], 'callcenter', 'create')
  const cust = (reference('A').customers || []).find(c => c.name && c.name.trim().length >= 4)
  let id = null
  const note = tag('case')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${agent} opens, works, resolves and closes a case`, async ({ browser }) => {
    remember(AREA, null)
    expect(agent).toBeTruthy()
    expect(cust, 'a branch-A reference customer with a name').toBeTruthy()
    const { page, close } = await asUser(browser, agent)
    const status = async () => (await call(page.request, 'GET', `/api/callcenter/cases/${id}/`)).status
    try {
      await step(agent, '/callcenter/cases', 'open a new case', async () => {
        await page.goto('/callcenter/cases')
        await page.locator('[data-tour="callcenter-cases-new"]').click()
        // search by the customer's name (never type or log the phone)
        await page.getByPlaceholder('010xxxxxxxx أو اسم العميل...').fill(cust.name.trim().slice(0, 30))
        await page.locator('[data-tour="callcenter-cases-new-search"]').click()
        await page.locator('[data-tour="callcenter-cases-new-pick"]').first().click()
        await field(page, 'التصنيف', 'select').selectOption('inquiry')
        await page.getByPlaceholder('اكتب عنواناً موجزاً...').fill(note)
        await field(page, 'الوصف', 'textarea').fill(`${note} - حالة اختبار قبول`)
        const { body } = await clickFor(page, page.locator('[data-tour="callcenter-cases-new-submit"]'), /\/api\/callcenter\/cases\/$/)
        id = body?.id
        if (!id) {
          // The create answer has no id, so CasesPage runs setSelectedCase(undefined): the new case does
          // not open. Open it from the (refreshed) list instead.
          finding({ ws: WS, key: agent, route: '/callcenter/cases', kind: 'workflow', severity: 'P2',
                    expected: 'after «فتح حالة جديدة» → حفظ the new case opens for work',
                    actual: 'POST /api/callcenter/cases/ answers without the new id, so the screen selects nothing (setSelectedCase(undefined)); the agent must find and open the case in the list' })
          const found = await call(page.request, 'GET', `/api/callcenter/cases/?search=${encodeURIComponent(note)}`)
          id = (found.results || found).find(c => c.title === note)?.id
        }
        remember(AREA, { id })
        expect(id, 'the new case exists').toBeTruthy()
      })
      const route = `/callcenter/cases (case ${id})`
      const open = async () => {
        if (await page.locator('[data-tour="callcenter-cases-actions"]').count()) return
        await page.locator('[data-tour="callcenter-cases-card"]', { hasText: note }).first().click()
      }
      await step(agent, route, 'start work on the case', async () => {
        await open()
        await clickFor(page, page.locator('[data-tour="callcenter-cases-start"]'), CASE('assign'))
        await expect.poll(status).toBe('working')
      })
      await step(agent, route, 'resolve («✅ حل الحالة»)', async () => {
        await page.locator('[data-tour="callcenter-cases-resolve"]').click()
        await page.getByPlaceholder('اشرح طريقة الحل...').fill(`${note} تم الرد على الاستفسار`)
        await clickFor(page, page.locator('[data-tour="callcenter-cases-resolve-confirm"]'), CASE('resolve'))
        await expect.poll(status).toBe('resolved')
      })
      await step(agent, route, 'close («🔒 إغلاق»)', async () => {
        await clickFor(page, page.locator('[data-tour="callcenter-cases-close"]'), CASE('close'))
        await expect.poll(status).toBe('closed')
      })
    } finally { await close() }
  })

  test(`must-refuse: ${outsider} opening or resolving a case`, async ({ browser }) => {
    expect(outsider).toBeTruthy()
    const { page, api, close } = await asUser(browser, outsider)
    try {
      await page.goto('/dashboard')
      await mustRefuse(api, { key: outsider, route: '/callcenter/cases', what: 'open a call-center case (no callcenter access)',
                              method: 'POST', url: '/api/callcenter/cases/',
                              data: { customer: cust?.id, title: 'UAT-refusal', category: 'inquiry', description: 'UAT-refusal' } })
      id ??= recall(AREA).id
      if (id) {
        await mustRefuse(api, { key: outsider, route: `/callcenter/cases (case ${id})`, what: 'resolve a call-center case',
                                method: 'POST', url: `/api/callcenter/cases/${id}/resolve/`, data: { resolution: 'UAT-refusal' } })
      }
    } finally { await close() }
  })
})
