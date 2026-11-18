// W5a transfers: branch A requests stock from branch B («📤 حفظ وتقديم»), branch B approves
// («اعتماد»), marks it sent to ERP (status only - nothing is written to SOFTECH; the copy has no
// SOFTECH host) and records the dispatch, branch A confirms receipt («🏁 تأكيد الاستلام»).
// Must-refuse: the requesting side approving its own request, and a view-only role approving.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A, BRANCH_B } from '../../lib/users.js'
import {
  asUser, step, clickFor, mustRefuse, firstWho, firstNot, tag, pickBranch, BASE, remember, recall,
} from './_ops.js'

const AREA = 'transfers'
const ACTION = a => new RegExp(`/api/transfers/\\d+/${a}/$`)

test.describe('transfers: request → approve → receive', () => {
  const requester = firstWho(['pharmacist', 'salesperson'], 'transfers', 'create')
  const approverB = firstWho(['pharmacist@B'], 'transfers', 'approve')
  const outsider = firstNot(['viewer', 'quality_manager', 'call_center', 'accountant'], 'transfers', 'approve')
  let id = null
  const note = tag('transfer')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  const status = async (page) => (await (await page.request.get(`/api/transfers/${id}/`)).json()).status

  test(`${requester} (branch A) requests a transfer from branch B and submits it`, async ({ browser }) => {
    remember(AREA, null)
    expect(requester).toBeTruthy()
    const { page, close } = await asUser(browser, requester)
    try {
      await step(requester, '/transfers/new', 'create + submit transfer request', async () => {
        await page.goto('/transfers/new')
        const branches = page.locator('[data-tour="transfers-new-branches"]').first()
        if (await branches.getByText('اختر الفرع الطالب...').count()) await pickBranch(page, 'اختر الفرع الطالب...', BRANCH_A.code)
        await pickBranch(page, 'اختر الفرع المصدر...', BRANCH_B.code)
        const items = page.locator('[data-tour="transfers-new-items"]')
        await items.getByPlaceholder(/ابحث باسم الصنف أو الكود أو الباركود/).fill('panadol')
        // first catalogue hit in the dropdown (rendered under the search box)
        const hit = items.getByText(/PANADOL/i).first()
        await hit.click()
        await items.getByPlaceholder('الكمية').first().fill('1')
        await page.getByPlaceholder('سبب الطلب، أولوية، تفاصيل إضافية...').fill(note)
        const sendNow = page.locator('[data-tour="transfers-new-send-now"] input[type="checkbox"]')
        if (await sendNow.count() && !(await sendNow.isChecked())) await sendNow.check()
        const { body } = await clickFor(page, page.locator('[data-tour="transfers-new-submit"]'), /\/api\/transfers\/$/)
        id = body.id; remember(AREA, { id })
        await expect.poll(() => status(page), { timeout: 30_000 }).toBe('pending')
      })
    } finally { await close() }
  })

  test(`must-refuse: ${requester} approving its own request, ${outsider} approving`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no transfer from the previous step')
    for (const key of [requester, outsider]) {
      const { page, api, close } = await asUser(browser, key)
      try {
        await page.goto('/dashboard')
        await mustRefuse(api, { key, route: `/transfers/${id}`, what: key === requester
          ? 'approve a transfer its own branch requested (requesting side)' : 'approve a transfer (view-only on transfers)',
          method: 'POST', url: `/api/transfers/${id}/approve/`, data: {} })
      } finally { await close() }
    }
  })

  test(`${approverB} (branch B) approves, sends to ERP and records the dispatch`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no transfer from the previous step')
    expect(approverB, 'pharmacist@B may approve transfers').toBeTruthy()
    const { page, close } = await asUser(browser, approverB)
    const route = `/transfers/${id}`
    try {
      await page.goto(route)
      await step(approverB, route, 'approve («اعتماد»)', async () => {
        await page.locator('[data-tour="transfers-detail-approve"]').click()
        await clickFor(page, page.locator('[data-tour="transfers-detail-approve-confirm"]'), ACTION('approve'))
        await expect.poll(() => status(page)).toBe('approved')
      })
      await step(approverB, route, 'send to ERP («🚀 إرسال للـ ERP», status only)', async () => {
        await page.locator('[data-tour="transfers-detail-send-erp"]').click()
        await page.getByPlaceholder('مرجع ERP (اختياري)...').fill(note)
        await clickFor(page, page.locator('[data-tour="transfers-detail-send-erp-confirm"]'), ACTION('send-to-erp'))
        await expect.poll(() => status(page)).toBe('sent_to_erp')
      })
      await step(approverB, route, 'record dispatch («🚚 تسجيل الإرسال»)', async () => {
        await page.locator('[data-tour="transfers-detail-dispatch"]').click()
        await page.getByPlaceholder('اسم مندوب التوصيل *').fill(`${note} مندوب`)
        await clickFor(page, page.locator('[data-tour="transfers-detail-dispatch-confirm"]'), ACTION('record-dispatch'))
      })
    } finally { await close() }
  })

  test(`${requester} (branch A) confirms receipt`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no transfer from the previous step')
    const { page, close } = await asUser(browser, requester)
    const route = `/transfers/${id}`
    try {
      await step(requester, route, 'receive («🏁 تأكيد الاستلام»)', async () => {
        await page.goto(route)
        await page.locator('[data-tour="transfers-detail-receive"]').click()
        await clickFor(page, page.locator('[data-tour="transfers-detail-receive-confirm"]'), ACTION('complete'))
        await expect.poll(() => status(page)).toBe('completed')
      })
    } finally { await close() }
  })
})
