// W5a stock count: a branch role opens a count session («+ جلسة جديدة») and asks for the stock
// snapshot. The snapshot reads SOFTECH; the copy has no SOFTECH host, so the step must fail
// cleanly (a readable error, no crash) - counting/variance/close cannot run on the copy and are
// recorded as a `decision`. The daily count review (/api/stockcount/daily/*) sits behind
// DAILY_COUNT_ENABLED; when it is off on the copy that is recorded too. Must-refuse: a role with no
// stockcount access opening a session, and a branch role opening one for another branch.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A, BRANCH_B } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import {
  asUser, step, clickFor, call, mustRefuse, firstWho, firstNot, tag, field, scrub, WS, BASE, remember,
} from './_ops.js'

const AREA = 'stockcount'

test.describe('stock count: session → snapshot; daily count review', () => {
  const counter = firstWho(['pharmacist', 'supervisor'], 'stockcount', 'create')
  const reviewer = firstWho(['supervisor', 'quality_manager', 'pharmacist'], 'stockcount', 'view')
  const outsider = firstNot(['salesperson', 'call_center', 'accountant', 'delivery'], 'stockcount', 'create')
  let id = null
  const note = tag('stockcount')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${counter} opens a count session and requests the snapshot`, async ({ browser }) => {
    remember(AREA, null)
    expect(counter).toBeTruthy()
    const { page, close } = await asUser(browser, counter)
    try {
      await step(counter, '/stock-count', 'open a count session', async () => {
        await page.goto('/stock-count')
        const newBtn = page.locator('[data-tour="stockcount-sessions-new"]')
        await page.getByText(/لا توجد جلسات جرد|جلسة/).first().waitFor({ timeout: 60_000 })
        if (await newBtn.count()) {
          await newBtn.click()
          await field(page, 'اسم الجلسة *', 'input').fill(note)
          await field(page, 'كود الفرع *', 'input').fill(BRANCH_A.code)
          await field(page, 'النوع', 'select').selectOption('full')
          await field(page, 'ملاحظات', 'input, textarea').fill(note)
          const { body } = await clickFor(page, page.locator('[data-tour="stockcount-sessions-create"]'), /\/api\/stockcount\/sessions\/$/)
          id = body.id
          expect(body.status).toBe('draft')
        } else {
          // The server lets this role open a session (stockcount:create) but the screen hides the button.
          finding({ ws: WS, key: counter, route: '/stock-count', kind: 'workflow', severity: 'P1',
                    expected: `«+ جلسة جديدة» shown to ${counter} (stockcount:create)`,
                    actual: 'button hidden: StockCountPage wraps it in <CanDo module="admin" action="create">, so only admins can open a count session from the screen; the API (stockcount:create) allows it' })
          const body = await call(page.request, 'POST', '/api/stockcount/sessions/',
                                  { name: note, mode: 'full', branch_code: BRANCH_A.code, notes: note })
          id = body.id
          expect(body.status).toBe('draft')
          await page.reload()
        }
        remember(AREA, { id })
      })
      const route = `/stock-count (session ${id})`
      await step(counter, route, 'request the snapshot (reads SOFTECH)', async () => {
        if (!(await page.locator('[data-tour="stockcount-sessions-snapshot"]').count())) await page.getByText(note).first().click()
        const res = page.waitForResponse(r => /\/generate-snapshot\/$/.test(r.url()), { timeout: 120_000 })
        await page.locator('[data-tour="stockcount-sessions-snapshot"]').click()
        const r = await res
        if (r.status() === 200) return            // a snapshot came back: nothing to record
        expect(r.status() < 500 || r.status() === 503, `no SOFTECH on the copy: a clean 503/4xx, not HTTP ${r.status()}`).toBe(true)
        await expect(page.locator('body')).not.toContainText(/Traceback|Internal Server Error/)
        const raw = await r.text()
        if (/java\.sql|SQLException|JZ\d{3}/.test(raw)) {
          finding({ ws: WS, key: counter, route, kind: 'workflow', severity: 'P3',
                    expected: 'a SOFTECH outage reads as a plain message (core/errors.public_error)',
                    actual: 'the snapshot error shows the raw JDBC driver text (java.sql.SQLException / JZ003 with the connection URL) to the user' })
        }
        finding({ ws: WS, key: counter, route, kind: 'decision', severity: 'P3',
                  expected: 'snapshot → count → variance → close runs end to end',
                  actual: `snapshot needs SOFTECH; the reader copy answered HTTP ${r.status()} (${scrub(await r.text()).slice(0, 120)}), so counting, variance and close were not exercised - check them on the office server` })
      })
    } finally { await close() }
  })

  test(`${reviewer} opens the daily count review board`, async ({ browser }) => {
    const { page, api, close } = await asUser(browser, reviewer)
    try {
      await page.goto('/stock-count')
      await step(reviewer, '/stock-count (daily count)', 'daily count review board', async () => {
        const r = await api.get('/api/stockcount/daily/board/')
        if (r.status() === 404) {
          finding({ ws: WS, key: reviewer, route: '/stock-count (daily count)', kind: 'decision', severity: 'P3',
                    expected: 'daily count review (board → recount/accept/escalate) can be tested',
                    actual: 'daily counts answer 404 on the copy: DAILY_COUNT_ENABLED is off (default). Decide whether it is ON at go-live; if so, test it on the office server' })
          return
        }
        expect([200, 403], `daily board answered ${r.status()}`).toContain(r.status())
      })
    } finally { await close() }
  })

  test(`must-refuse: ${outsider} opening a session; ${counter} opening one for branch B`, async ({ browser }) => {
    for (const [key, code, what, alsoRefused] of [
      [outsider, BRANCH_A.code, 'open a stock count session (no stockcount:create)', []],
      [counter, BRANCH_B.code, `open a stock count session for another branch (${BRANCH_B.code})`, [400]],
    ]) {
      const { page, api, close } = await asUser(browser, key)
      try {
        await page.goto('/dashboard')
        await mustRefuse(api, { key, route: '/stock-count', what, method: 'POST', url: '/api/stockcount/sessions/',
                                data: { name: 'UAT-refusal', mode: 'full', branch_code: code, notes: 'UAT-refusal' }, alsoRefused })
      } finally { await close() }
    }
  })
})
