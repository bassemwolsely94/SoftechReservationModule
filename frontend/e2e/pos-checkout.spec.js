// D-18 server-side POS checkout (docs/architecture/39_POS_SERVER_CHECKOUT.md §4.5).
// settings_e2e turns POS_SERVER_CHECKOUT on for the SECOND test branch (992) only, so this spec runs the
// new path there while branch 991 keeps today's path (also guarded by flows.spec.js). POS_WRITER_ENABLED
// and WRITER_INSTANCE are False in the e2e settings: every checkout is a dry run; nothing reaches SOFTECH.
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

const OLD_PATH = /\/api\/(pos-orders\/\d+\/(ready|push)\/|offers\/apply-to-order\/)/
const CHECKOUT = /\/api\/pos-orders\/checkout\/$/
const PREVIEW = /\/api\/pos-orders\/checkout\/preview\/$/

async function branchId(page, code) {
  const res = await page.request.get('/api/branches/')
  const data = await res.json()
  const b = (data.results || data).find(x => String(x.softech_branch_id) === code)
  expect(b, `test branch ${code}`).toBeTruthy()
  return b.id
}

async function openPos(page, code) {
  const id = await branchId(page, code)
  await page.addInitScript(v => { window.localStorage.setItem('pos_branch', v) }, String(id))
  await page.goto('/pos')
}

async function addItem(page) {
  const search = page.getByPlaceholder(/صنف|بحث/).first()
  await search.fill('E2E PARA')
  await page.getByText('E2E PARACETAMOL 500MG 20 TAB').first().click()
}

const submitButton = page => page.getByRole('button', { name: /جاهز|تجهيز|F9/ }).first()

function watch(page) {
  const seen = { old: [], checkout: [] }
  page.on('request', (r) => {
    if (OLD_PATH.test(r.url())) seen.old.push(r.url())
    if (CHECKOUT.test(r.url()) && r.method() === 'POST') seen.checkout.push(r.postDataJSON())
  })
  return seen
}

test.describe('POS server checkout (switch on for branch 992)', () => {
  test.use({ storageState: stateFile('admin') })

  test('one checkout call, server totals, dry-run plan — no ready/push/apply-to-order', async ({ page }) => {
    const seen = watch(page)
    await openPos(page, '992')
    const preview = page.waitForResponse(r => PREVIEW.test(r.url()))
    await addItem(page)
    const q = await (await preview).json()
    const due = page.getByTestId('pos-due')
    if (await due.count()) await expect(due).toContainText(Number(q.totals.due).toFixed(2))

    const done = page.waitForResponse(r => CHECKOUT.test(r.url()))
    await submitButton(page).click()
    const res = await done
    expect(res.status(), await res.text()).toBe(200)
    const body = await res.json()
    expect(body.softech.mode).toBe('dry_run')
    expect(body.softech.wrote_to_softech).toBe(false)
    expect(body.totals.due).toBe(q.totals.due)
    expect(body.plan.header.docvalue).toBe(body.totals.net)

    expect(seen.checkout).toHaveLength(1)
    expect(seen.checkout[0].checkout).toMatchObject({ mode: 'dry_run', tender_intent: { kind: 'default' } })
    expect(seen.checkout[0].checkout.confirm).toBeUndefined()
    expect(seen.checkout[0].checkout.expected_due).toBe(q.totals.due)
    expect(seen.old).toEqual([])
  })

  test('a total that changed since the preview is refused, the basket kept, nothing saved', async ({ page }) => {
    const id = await branchId(page, '992')
    const count = async () => {
      const d = await (await page.request.get(`/api/pos-orders/?branch=${id}`)).json()
      return d.count ?? (d.results || d).length
    }
    const before = await count()
    await openPos(page, '992')
    const preview = page.waitForResponse(r => PREVIEW.test(r.url()))
    await addItem(page)
    await preview
    await page.route(CHECKOUT, async (route) => {
      const body = route.request().postDataJSON()
      body.checkout.expected_due = '0.01'          // as if the price moved after the preview
      await route.continue({ postData: JSON.stringify(body) })
    })
    const done = page.waitForResponse(r => CHECKOUT.test(r.url()))
    await submitButton(page).click()
    const res = await done
    expect(res.status()).toBe(409)
    expect((await res.json()).totals_changed).toBe(true)
    await expect(page.getByText(/تغيّر المطلوب/).first()).toBeVisible()
    await expect(page.getByText('E2E PARACETAMOL 500MG 20 TAB').first()).toBeVisible()   // basket kept
    expect(await count()).toBe(before)                                                  // nothing saved
  })

  test('a lost reply is answered from the same order on retry', async ({ page }) => {
    await openPos(page, '992')
    const preview = page.waitForResponse(r => PREVIEW.test(r.url()))
    await addItem(page)
    await preview
    let dropped = false
    await page.route(CHECKOUT, async (route) => {
      if (dropped) return route.continue()
      dropped = true
      await route.fetch()                          // the server did the work…
      return route.abort()                         // …and the reply never arrived
    })
    await submitButton(page).click()
    await expect.poll(() => dropped).toBe(true)
    const done = page.waitForResponse(r => CHECKOUT.test(r.url()))
    await submitButton(page).click()
    const res = await done
    expect(res.status(), await res.text()).toBe(200)
    expect((await res.json()).replayed).toBe(true)
  })

  test('a double click makes one order', async ({ page }) => {
    await openPos(page, '992')
    const preview = page.waitForResponse(r => PREVIEW.test(r.url()))
    await addItem(page)
    await preview
    const replies = []
    page.on('response', async (r) => {
      if (CHECKOUT.test(r.url())) replies.push(await r.json().catch(() => ({})))
    })
    await submitButton(page).dblclick()
    await expect.poll(() => replies.length).toBeGreaterThan(0)
    const ids = new Set(replies.map(r => r.order_id).filter(Boolean))
    expect(ids.size).toBeLessThanOrEqual(1)
  })
})

test.describe('POS today\'s path where the switch is off (branch 991)', () => {
  test.use({ storageState: stateFile('admin') })

  test('the old request sequence still runs and checkout/ is never called', async ({ page }) => {
    const seen = watch(page)
    await page.route(/\/api\/pos-orders\/\d+\/push\//, route => route.abort())   // stop at ready
    await openPos(page, '991')
    await addItem(page)
    const ready = page.waitForResponse(r => /\/api\/pos-orders\/\d+\/ready\//.test(r.url()))
    await submitButton(page).click()
    expect((await ready).status()).toBe(200)
    expect(seen.checkout).toEqual([])
  })
})
