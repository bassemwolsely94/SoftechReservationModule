// W5b · POS: order → ready → push, per role that sells (pos:create), on the reader copy.
// Owner approval (2026-11-16, copy only): the push may be completed end to end, because
// settings_uat makes SOFTECH unreachable. Gate: assertReaderCopy() first, and every push reply
// must be a dry run (mode "dry_run", wrote_to_softech false, live false). Either check failing
// = P0 and the whole spec stops.
import { test, expect } from '@playwright/test'
import { BRANCH_A, BRANCH_B } from '../../lib/users.js'
import { WS, TAG, doers, nonDoers, apiAs, flag, expectRefused, brief, readerGate, sameMoney, screenOk, setAbort, getAbort } from './_money.js'
import { finding } from '../../lib/findings.js'

// Tests are independent (a finding in one role does not skip the next); a P0 stops the whole
// file through a run-scoped marker that survives Playwright's worker restart after a failure.
let abort = ''
let item = null
const ROUTE = '/api/pos-orders/'

test.beforeAll(async ({ baseURL }) => {
  abort = getAbort('pos')
  if (abort) return
  if (!(await readerGate(baseURL, 'POS push'))) { abort = 'not a reader copy'; setAbort('pos', abort); return }
  const api = await apiAs(baseURL, 'admin')
  try {
    // A plain stockable item with a price (the one the probe used, else any priced item).
    for (const q of ['88704', 'panadol']) {
      const r = await api.get(`/api/items/?search=${q}&page_size=20`)
      item = (r.body?.results || []).find(i => Number(i.pack_price) > 0 && i.is_stockable && i.softech_id)
      if (item) break
    }
  } finally { await api.dispose() }
})

/** Create → ready → push as `key` in `branch`; returns the order id (or null). */
async function sellAndPush(baseURL, key, branch) {
  const api = await apiAs(baseURL, key)
  try {
    const qty = 2
    const c = await api.post(ROUTE, { branch: branch.id, notes: `${TAG} ${key}`,
      lines: [{ item: item.id, softech_itemcode: item.softech_id, item_name: item.name, qty }] })
    if (c.status !== 201) {
      flag({ key, route: ROUTE, kind: 'workflow', severity: 'P1', expected: 'order created (201)', actual: `HTTP ${c.status} ${brief(c.body)}` })
      return null
    }
    const id = c.body.id

    const r = await api.post(`${ROUTE}${id}/ready/`, {})
    if (r.status !== 200) {
      flag({ key, route: `${ROUTE}${id}/ready/`, kind: 'workflow', severity: 'P1', expected: 'order ready (200)', actual: `HTTP ${r.status} ${brief(r.body)}` })
      return id
    }
    // Totals: each line = qty × sale price × (1 − line discount); header = Σ lines; pay = header.
    const o = r.body
    let sum = 0
    for (const l of o.lines) {
      const want = Number(l.qty) * Number(l.item_sale_price) * (1 - Number(l.cust_discp) / 100)
      sum += Number(l.trans_price_total)
      if (!sameMoney(l.trans_price_total, want, 0.02)) {
        flag({ key, route: `${ROUTE}${id}/ready/`, kind: 'workflow', severity: 'P1',
          expected: `line total ${want.toFixed(2)}`, actual: `line total ${l.trans_price_total}` })
      }
    }
    if (!sameMoney(o.doc_value, sum) || Number(o.doc_value) <= 0) {
      flag({ key, route: `${ROUTE}${id}/ready/`, kind: 'workflow', severity: 'P1',
        expected: `order total ${sum.toFixed(2)} (> 0)`, actual: `doc_value ${o.doc_value}` })
    }
    const paid = (o.payments || []).reduce((s, p) => s + Number(p.amount), 0)
    if (o.payments?.length && !sameMoney(paid, o.doc_value_pay)) {
      flag({ key, route: `${ROUTE}${id}/ready/`, kind: 'workflow', severity: 'P1',
        expected: `tenders = ${o.doc_value_pay}`, actual: `tenders ${paid.toFixed(2)}` })
    }

    // The push: must be a dry run on the copy, whatever is asked for.
    const p = await api.post(`${ROUTE}${id}/push/`, {})
    const dry = p.body && p.body.mode === 'dry_run' && p.body.wrote_to_softech === false && p.body.live === false
    if (p.status === 200 && !dry) {
      abort = `push answered without dry_run: ${brief(p.body)}`
      setAbort('pos', abort)
      finding({ ws: WS, key, route: `${ROUTE}${id}/push/`, kind: 'workflow', severity: 'P0',
        expected: 'push reply is a dry run (mode dry_run, wrote_to_softech false)', actual: brief(p.body) })
      throw new Error(`P0 - ${abort}`)
    }
    if (p.status !== 200) {
      flag({ key, route: `${ROUTE}${id}/push/`, kind: 'workflow', severity: 'P1', expected: 'dry-run push (200)', actual: `HTTP ${p.status} ${brief(p.body)}` })
      return id
    }
    // The plan the writer would send carries the same total the screen showed.
    const planTotal = p.body.plan?.header?.docvalue
    if (!sameMoney(planTotal, o.doc_value)) {
      flag({ key, route: `${ROUTE}${id}/push/`, kind: 'workflow', severity: 'P1',
        expected: `SOFTECH plan docvalue = ${o.doc_value}`, actual: `plan docvalue ${planTotal}` })
    }
    return id
  } finally { await api.dispose() }
}

for (const key of doers('pos', 'create')) {
  test(`${key}: sells in their branch, order ready, push is a dry run with the same total`, async ({ baseURL }) => {
    test.skip(!!abort, abort)
    expect(item, 'a priced item on the copy').toBeTruthy()
    const id = await sellAndPush(baseURL, key, BRANCH_A)
    // tidy: cancel the order on the copy (not asserted)
    if (id) { const a = await apiAs(baseURL, key); await a.post(`${ROUTE}${id}/cancel/`, { reason: TAG }); await a.dispose() }
  })
}

test('pharmacist@B: sells in branch B with a dry-run push', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  const id = await sellAndPush(baseURL, 'pharmacist@B', BRANCH_B)
  if (id) { const a = await apiAs(baseURL, 'pharmacist@B'); await a.post(`${ROUTE}${id}/cancel/`, { reason: TAG }); await a.dispose() }
})

test('pharmacist: the POS screen opens', async ({ browser }) => {
  test.skip(!!abort, abort)
  await screenOk(browser, 'pharmacist', '/pos', { what: 'POS screen opens' })
})

test('must be refused: roles without pos:create cannot sell or push', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  // an order to try to push: made by the pharmacist
  const ph = await apiAs(baseURL, 'pharmacist')
  const c = await ph.post(ROUTE, { branch: BRANCH_A.id, notes: `${TAG} refusal target`,
    lines: [{ item: item.id, softech_itemcode: item.softech_id, item_name: item.name, qty: 1 }] })
  expect(c.status).toBe(201)
  const target = c.body.id
  try {
    for (const key of nonDoers('pos', 'create').filter(k => k !== 'admin')) {
      const api = await apiAs(baseURL, key)
      try {
        expectRefused(await api.post(ROUTE, { branch: BRANCH_A.id, notes: TAG,
          lines: [{ item: item.id, softech_itemcode: item.softech_id, item_name: item.name, qty: 1 }] }),
          { key, route: ROUTE, what: 'creating a POS order' })
        expectRefused(await api.post(`${ROUTE}${target}/push/`, {}), { key, route: `${ROUTE}:id/push/`, what: 'pushing a POS order' })
      } finally { await api.dispose() }
    }
  } finally {
    await ph.post(`${ROUTE}${target}/cancel/`, { reason: TAG }); await ph.dispose()
  }
})

test('must be refused: a branch-B seller cannot sell for branch A or push its orders', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  const ph = await apiAs(baseURL, 'pharmacist')
  const c = await ph.post(ROUTE, { branch: BRANCH_A.id, notes: `${TAG} cross-branch target`,
    lines: [{ item: item.id, softech_itemcode: item.softech_id, item_name: item.name, qty: 1 }] })
  expect(c.status).toBe(201)
  const b = await apiAs(baseURL, 'pharmacist@B')
  try {
    expectRefused(await b.post(ROUTE, { branch: BRANCH_A.id, notes: TAG,
      lines: [{ item: item.id, softech_itemcode: item.softech_id, item_name: item.name, qty: 1 }] }),
      { key: 'pharmacist@B', route: ROUTE, what: 'selling for another branch', kind: 'branch' })
    expectRefused(await b.post(`${ROUTE}${c.body.id}/push/`, {}),
      { key: 'pharmacist@B', route: `${ROUTE}:id/push/`, what: "pushing another branch's order", kind: 'branch' })
  } finally {
    await b.dispose()
    await ph.post(`${ROUTE}${c.body.id}/cancel/`, { reason: TAG }); await ph.dispose()
  }
})
