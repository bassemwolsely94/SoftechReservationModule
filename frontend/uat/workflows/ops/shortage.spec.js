// W5a shortage list: a branch role opens a list («+ قائمة جديدة»), adds a free-text item and
// submits it («shortage-list-submit»). Must-refuse: a view-only role creating a list, and the same
// branch role opening a list for another branch.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A, BRANCH_B } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import {
  asUser, step, clickFor, call, mustRefuse, WS, firstWho, firstNot, tag, pickBranch, field, BASE, remember,
} from './_ops.js'

const AREA = 'shortage'

test.describe('shortage list: open → add item → submit', () => {
  const owner = firstWho(['pharmacist', 'salesperson'], 'shortage', 'create')
  const outsider = firstNot(['viewer', 'quality_manager', 'accountant', 'delivery'], 'shortage', 'create')
  let id = null
  const note = tag('shortage')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${owner} opens a shortage list, adds an item and submits it`, async ({ browser }) => {
    remember(AREA, null)
    expect(owner).toBeTruthy()
    const { page, close } = await asUser(browser, owner)
    try {
      await step(owner, '/shortage', 'open a new list', async () => {
        await page.goto('/shortage')
        await page.getByRole('button', { name: /\+ قائمة جديدة/ }).first().click()
        if (await page.getByText('اختر الفرع...', { exact: true }).count()) await pickBranch(page, 'اختر الفرع...', BRANCH_A.code)
        await page.getByPlaceholder('مثال: زيارة المندوب — مايو 2026').fill(note)
        await field(page, 'ملاحظات', 'textarea').fill(note)
        const { body } = await clickFor(page, page.locator('[data-tour="shortage-list-create-save"]'), /\/api\/shortage\/lists\/$/)
        id = body?.id
        if (!id) {
          // The create answer has no id (ShortageListCreateSerializer fields = branch/title/notes), so the
          // screen calls onCreated(undefined) and the new list does not open. Find it by its UAT title.
          finding({ ws: WS, key: owner, route: '/shortage', kind: 'workflow', severity: 'P2',
                    expected: 'after «+ قائمة جديدة» → حفظ the new list opens, ready for items',
                    actual: 'POST /api/shortage/lists/ answers 201 without the new id (create serializer has only branch/title/notes); the screen calls onCreated(undefined), so the user must find and open the list by hand' })
          const found = await call(page.request, 'GET', `/api/shortage/lists/?search=${encodeURIComponent(note)}`)
          id = (found.results || found).find(l => l.title === note)?.id
          const shownWithoutReload = await page.getByText(note).count()
          if (!shownWithoutReload) await page.reload()
          await page.getByText(note).first().click()
          if (!shownWithoutReload) {
            finding({ ws: WS, key: owner, route: '/shortage', kind: 'workflow', severity: 'P2',
                      expected: 'the new list appears in the lists column right after saving',
                      actual: 'the new list is missing from the lists column until the page is reloaded (same create flow: no id → no refetch/select)' })
          }
        }
        remember(AREA, { id })
        expect(id, 'the new list exists').toBeTruthy()
      })
      const route = `/shortage?list=${id}`
      await step(owner, route, 'add a free-text item', async () => {
        await page.getByPlaceholder('مثال: أموكسيسيلين 500مج').fill('أموكسيسيلين 500مج UAT')
        await clickFor(page, page.locator('[data-tour="shortage-list-add-text"]'), /\/api\/shortage\/lists\/\d+\/add-item\/$/)
      })
      await step(owner, route, 'submit the list', async () => {
        // «إرسال» asks in the inline confirm bar; asUser() answers it (uat/lib/inlineConfirmAnswerer.js).
        await clickFor(page, page.locator('[data-tour="shortage-list-submit"]'), /\/api\/shortage\/lists\/\d+\/submit\/$/)
        const l = await (await page.request.get(`/api/shortage/lists/${id}/`)).json()
        expect(l.status).toBe('submitted')
      })
    } finally { await close() }
  })

  test(`must-refuse: ${outsider} opening a list; ${owner} opening one for branch B`, async ({ browser }) => {
    for (const [key, branch, what, alsoRefused] of [
      [outsider, BRANCH_A.id, 'create a shortage list (no shortage:create)', []],
      [owner, BRANCH_B.id, `create a shortage list for another branch (${BRANCH_B.code})`, [400]],
    ]) {
      const { page, api, close } = await asUser(browser, key)
      try {
        await page.goto('/dashboard')
        // the branch-scope rule answers 400 (validation) by design; a 201 is the failure
        await mustRefuse(api, { key, route: '/shortage', what, method: 'POST', url: '/api/shortage/lists/',
                                data: { branch, title: 'UAT-refusal', notes: 'UAT-refusal' }, alsoRefused })
      } finally { await close() }
    }
  })
})
