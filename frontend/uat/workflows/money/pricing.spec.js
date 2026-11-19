// W5b · Pricing / discount requests: request → approve (or reject), on the reader copy.
// Owner approval (2026-11-16, copy only): approval may be completed end to end. Gate:
// assertReaderCopy() first; failing = P0 and the spec stops. On the copy the pricing writer is
// off, so the server answers approve with 503 pricing_writes_disabled and the request stays
// pending: that is the guard working, recorded once as a decision (end-to-end not provable here).
import { test, expect } from '@playwright/test'
import { can } from '../../lib/expected.js'
import { finding } from '../../lib/findings.js'
import { WS, TAG, HOME, apiAs, flag, expectRefused, brief, readerGate, screenOk } from './_money.js'

// Each test makes the request it needs, so one role's finding never skips another role's test.

const ROUTE = '/api/pricing-approvals/'
let abort = ''
let item = null

// matrix_permission('approvals', post=('create','approve')): either action lets a role ask.
const askers = HOME.filter(k => can(k, 'approvals', 'create') || can(k, 'approvals', 'approve'))
const nonAskers = HOME.filter(k => !askers.includes(k))

test.beforeAll(async ({ baseURL }) => {
  if (!(await readerGate(baseURL, 'pricing approval'))) { abort = 'not a reader copy'; return }
  const api = await apiAs(baseURL, 'admin')
  try {
    const r = await api.get('/api/items/?search=88704&page_size=20')
    item = (r.body?.results || []).find(i => Number(i.pack_price) > 0) ||
      (await api.get('/api/items/?search=panadol&page_size=20')).body?.results?.find(i => Number(i.pack_price) > 0)
  } finally { await api.dispose() }
})

/** A fresh pending request by the pharmacist (an asker in every seeded matrix). */
async function pharmacistRequest(baseURL) {
  const api = await apiAs(baseURL, 'pharmacist')
  try {
    const r = await api.post(ROUTE, { item: item.id, new_values: { pos_discp: 1 }, reason: `${TAG} pharmacist` })
    return r.status === 201 ? r.body.id : null
  } finally { await api.dispose() }
}

for (const key of askers) {
  test(`${key}: asks for a discount change and sees it pending`, async ({ baseURL }) => {
    test.skip(!!abort, abort)
    const api = await apiAs(baseURL, key)
    try {
      const r = await api.post(ROUTE, { item: item.id, new_values: { pos_discp: 1 }, reason: `${TAG} ${key}` })
      if (r.status !== 201) {
        flag({ key, route: ROUTE, kind: 'workflow', severity: 'P2', expected: 'request created (201) — matrix allows it', actual: `HTTP ${r.status} ${brief(r.body)}` })
        return
      }
      expect(r.body.status).toBe('pending')
      // the request records the price it would change from: the item's current values
      expect(Number(r.body.old_values?.pack_price)).toBeCloseTo(Number(item.pack_price), 2)
      const list = await api.get(ROUTE)
      expect((list.body?.results || []).some(x => x.id === r.body.id), 'own request listed').toBe(true)
      const adm = await apiAs(baseURL, 'admin')
      try { await adm.post(`${ROUTE}${r.body.id}/reject/`, { notes: `${TAG} cleanup` }) } finally { await adm.dispose() }
    } finally { await api.dispose() }
  })
}

test('admin: approves a pharmacist request (copy: pricing writer off), then rejects it', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  const id = await pharmacistRequest(baseURL)
  test.skip(!id, 'no pharmacist request')
  const api = await apiAs(baseURL, 'admin')
  try {
    const a = await api.post(`${ROUTE}${id}/approve/`, { notes: TAG })
    if (a.status === 503 && a.body?.error_code === 'pricing_writes_disabled') {
      finding({ ws: WS, key: 'admin', route: `${ROUTE}:id/approve/`, kind: 'decision', severity: 'P3',
        expected: 'approval completes end to end on the copy (owner-approved)',
        actual: 'refused 503 pricing_writes_disabled: the pricing writer is off on the reader copy, so approve cannot complete here; guard works, end-to-end needs a writer-on test environment' })
    } else if (a.status !== 200 && a.status !== 207) {
      flag({ key: 'admin', route: `${ROUTE}:id/approve/`, kind: 'workflow', severity: 'P1', expected: 'approve 200/207 or 503 writer-off', actual: `HTTP ${a.status} ${brief(a.body)}` })
    }
    const g = await api.get(`${ROUTE}${id}/`)
    if (g.body?.status === 'pending') {
      const rj = await api.post(`${ROUTE}${id}/reject/`, { notes: `${TAG} cleanup` })
      expect(rj.status, brief(rj.body)).toBe(200)
      expect((await api.get(`${ROUTE}${id}/`)).body?.status).toBe('rejected')
    }
  } finally { await api.dispose() }
})

test('admin: the pricing approvals screen opens', async ({ browser }) => {
  test.skip(!!abort, abort)
  await screenOk(browser, 'admin', '/pricing-approvals', { what: 'pricing approvals screen opens' })
})

test('must be refused: non-admin approvers cannot approve; askers without the right cannot ask', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  const id = await pharmacistRequest(baseURL)
  test.skip(!id, 'no request to act on')
  const matrixSaysYes = []
  for (const key of HOME.filter(k => k !== 'admin')) {
    const api = await apiAs(baseURL, key)
    try {
      const r = await api.post(`${ROUTE}${id}/approve/`, { notes: TAG })
      expectRefused(r, { key, route: `${ROUTE}:id/approve/`, what: 'approving a price/discount change (admin only)' })
      if (r.status === 403 && can(key, 'approvals', 'approve')) matrixSaysYes.push(key)
    } finally { await api.dispose() }
  }
  const adm = await apiAs(baseURL, 'admin')
  try { await adm.post(`${ROUTE}${id}/reject/`, { notes: `${TAG} cleanup` }) } finally { await adm.dispose() }
  if (matrixSaysYes.length) {
    finding({ ws: WS, key: matrixSaysYes.join(','), route: `${ROUTE}:id/approve/`, kind: 'decision', severity: 'P3',
      expected: 'roles with approvals:approve in the matrix may approve pricing requests',
      actual: 'refused: pricing approve is hard-coded admin-only (IsAdminRole), stricter than the role matrix' })
  }
  for (const key of nonAskers) {
    const api = await apiAs(baseURL, key)
    try {
      expectRefused(await api.post(ROUTE, { item: item.id, new_values: { pos_discp: 1 }, reason: TAG }),
        { key, route: ROUTE, what: 'asking for a discount change' })
    } finally { await api.dispose() }
  }
})

test('must be refused: admin approving their own pricing request', async ({ baseURL }) => {
  test.skip(!!abort, abort)
  const api = await apiAs(baseURL, 'admin')
  try {
    const c = await api.post(ROUTE, { item: item.id, new_values: { pos_discp: 1 }, reason: `${TAG} self` })
    expect(c.status, brief(c.body)).toBe(201)
    const a = await api.post(`${ROUTE}${c.body.id}/approve/`, { notes: `${TAG} self` })
    if (a.status === 200 || a.status === 207) {
      flag({ key: 'admin', route: `${ROUTE}:id/approve/`, kind: 'workflow', severity: 'P0',
        expected: 'own pricing request cannot be approved by its requester', actual: `self-approval allowed (HTTP ${a.status})` })
    } else if (a.status === 503) {
      // Refused only because the writer is off: the code has no requester ≠ approver check.
      finding({ ws: WS, key: 'admin', route: `${ROUTE}:id/approve/`, kind: 'decision', severity: 'P1',
        expected: 'own pricing request refused by a requester ≠ approver rule',
        actual: 'refused only by the writer-off guard (503); approve_request has no requester check, so with the writer on an admin can approve their own price change (P0 if confirmed)' })
    }
    await api.post(`${ROUTE}${c.body.id}/reject/`, { notes: `${TAG} cleanup` })
  } finally { await api.dispose() }
})
