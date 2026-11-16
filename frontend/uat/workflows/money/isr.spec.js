// W5b · Supply / ISR review: the purchasing desk proposes an ISR for branch A from the local engine
// run (rule "engine", 3 lines: read-only, no SOFTECH), the value adds up, a second person approves
// it (اعتماد, a local status change), and the proposer approving their own proposal is checked.
// The ISR push (the SOFTECH write) is never called. Every proposal made here is cancelled.
import { test, expect } from '@playwright/test'
import { BRANCH_A, userByKey } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import { WS, TAG, HOME, apiAs, flag, brief, sameMoney, screenOk } from './_money.js'
import { can } from '../../lib/expected.js'

const PUSHES = '/api/purchasing/isr/pushes/'
const PROPOSE = '/api/purchasing/isr/propose/'
// approve needs purchasing approve + supply-write (admin / purchasing role / SOFTECH supply group)
const deskers = HOME.filter(k => k !== 'admin' && can(k, 'purchasing', 'approve'))

async function propose(api, key) {
  const r = await api.post(PROPOSE, { branch: BRANCH_A.code, rule: 'engine', max_lines: 3, notes: TAG })
  if (r.status !== 201) {
    flag({ key, route: PROPOSE, kind: 'workflow', severity: 'P1', expected: 'ISR proposal from the engine run (201)', actual: `HTTP ${r.status} ${brief(r.body)}` })
    return null
  }
  return r.body
}

for (const key of deskers) {
  test(`${key}: proposes an ISR, its value = Σ qty × cost, a second person (admin) approves it`, async ({ baseURL, browser }) => {
    const api = await apiAs(baseURL, key)
    let p
    try {
      p = await propose(api, key)
      test.skip(!p, 'no proposal')
      expect(p.status).toBe('proposed')
      const d = (await api.get(`${PUSHES}${p.id}/`)).body
      const sum = (d.lines || []).reduce((s, l) => s + Number(l.itemqty) * Number(l.itemcostprice), 0)
      if (!sameMoney(sum, d.docvalue, 0.05) || (d.lines || []).length !== Number(d.line_count)) {
        flag({ key, route: `${PUSHES}:id/`, kind: 'workflow', severity: 'P1',
          expected: `ISR value = Σ qty × cost = ${sum.toFixed(2)} over ${d.lines?.length} lines`, actual: `docvalue ${d.docvalue}, line_count ${d.line_count}` })
      }
      const rv = await api.get(`${PUSHES}${p.id}/push-review/`)
      if (rv.status === 502) {
        // push review compares with live SOFTECH stock: not available on the copy
        finding({ ws: WS, key, route: `${PUSHES}:id/push-review/`, kind: 'decision', severity: 'P3',
          expected: 'push review opens', actual: 'needs live SOFTECH (502 on the copy, which has none); not testable here' })
        if (/SQLException|UnknownHost|java\./.test(JSON.stringify(rv.body))) {
          finding({ ws: WS, key, route: `${PUSHES}:id/push-review/`, kind: 'workflow', severity: 'P3',
            expected: 'a plain error message (core/errors.public_error)', actual: 'the error shown to the user carries the raw JDBC exception text (java.sql.SQLException / host name)' })
        }
      } else if (rv.status !== 200) {
        flag({ key, route: `${PUSHES}:id/push-review/`, kind: 'workflow', severity: 'P2', expected: 'push review opens (200)', actual: `HTTP ${rv.status} ${brief(rv.body)}` })
      }
    } finally { await api.dispose() }

    const adm = await apiAs(baseURL, 'admin')
    try {
      const ap = await adm.post(`${PUSHES}${p.id}/approve/`, { notes: TAG })
      if (ap.status !== 200) {
        flag({ key: 'admin', route: `${PUSHES}:id/approve/`, kind: 'workflow', severity: 'P1', expected: 'ISR approved by a second person (200)', actual: `HTTP ${ap.status} ${brief(ap.body)}` })
      } else {
        const after = (await adm.get(`${PUSHES}${p.id}/`)).body
        if (!after.approved_by || !after.approved_at) flag({ key: 'admin', route: `${PUSHES}:id/approve/`, kind: 'workflow', severity: 'P2', expected: 'approval stamped (approved_by/at)', actual: `approved_by=${after.approved_by} at=${after.approved_at}` })
        // approving twice is refused
        const again = await adm.post(`${PUSHES}${p.id}/approve/`, { notes: TAG })
        if (again.status < 300) flag({ key: 'admin', route: `${PUSHES}:id/approve/`, kind: 'workflow', severity: 'P1', expected: 'second approval of an approved ISR refused', actual: `HTTP ${again.status}` })
      }
      // an approved, unpushed ISR blocks the next proposal for the same route: cancel it now
      await adm.post(`${PUSHES}${p.id}/cancel/`, { reason: `${TAG} cleanup` })
    } finally { await adm.dispose() }

    await screenOk(browser, key, '/supply', { what: 'supply screen opens' })
  })

  test(`must be refused: ${key} approving their own ISR proposal`, async ({ baseURL }) => {
    const api = await apiAs(baseURL, key)
    try {
      const p = await propose(api, key)
      test.skip(!p, 'no proposal')
      const ap = await api.post(`${PUSHES}${p.id}/approve/`, { notes: `${TAG} self` })
      if (ap.status === 200) {
        flag({ key, route: `${PUSHES}:id/approve/`, kind: 'workflow', severity: 'P0',
          expected: 'the proposer cannot approve their own ISR (maker ≠ checker)', actual: 'self-approval allowed (HTTP 200): approve does not compare created_by with the approver' })
      }
      await api.post(`${PUSHES}${p.id}/cancel/`, { reason: `${TAG} cleanup` })
    } finally { await api.dispose() }
  })
}

test('must be refused: roles without ISR write cannot propose or approve', async ({ baseURL }) => {
  // a target: proposed and approved by the desk, so an allowed role would get 400, a refused one 403
  let target = null
  const desk = await apiAs(baseURL, deskers[0] || 'admin')
  const adm = await apiAs(baseURL, 'admin')
  try {
    const p = await propose(desk, deskers[0] || 'admin')
    if (p) { await adm.post(`${PUSHES}${p.id}/approve/`, { notes: TAG }); target = p.id }
  } finally { await desk.dispose(); await adm.dispose() }
  for (const key of HOME.filter(k => k !== 'admin' && !deskers.includes(k))) {
    const api = await apiAs(baseURL, key)
    try {
      const pr = await api.post(PROPOSE, { branch: BRANCH_A.code, rule: 'engine', max_lines: 1, notes: TAG })
      if (pr.status === 201) {
        flag({ key, route: PROPOSE, kind: 'workflow', severity: 'P1', expected: 'ISR proposal refused', actual: 'proposal created (201)' })
      }
      if (target) {
        // an allowed role would get 400 (not proposed any more); refused ones 403
        const r = await api.post(`${PUSHES}${target}/approve/`, { notes: TAG })
        if (r.status !== 403 && r.status !== 401) {
          flag({ key, route: `${PUSHES}:id/approve/`, kind: 'workflow', severity: 'P1', expected: 'ISR approve refused (403)', actual: `passed the permission check (HTTP ${r.status})` })
        }
      }
    } finally { await api.dispose() }
  }
  if (target) {
    const a2 = await apiAs(baseURL, 'admin')
    try { await a2.post(`${PUSHES}${target}/cancel/`, { reason: `${TAG} cleanup` }) } finally { await a2.dispose() }
  }
})

test.afterAll(async ({ baseURL }) => {
  // cancel every open ISR the UAT users made on the copy (only UAT users create them here)
  const uat = new Set(HOME.map(k => userByKey(k).username))
  const adm = await apiAs(baseURL, 'admin')
  try {
    const l = await adm.get(PUSHES)
    for (const r of l.body?.results || []) {
      if (uat.has(r.created_by) && ['proposed', 'approved'].includes(r.status)) {
        await adm.post(`${PUSHES}${r.id}/cancel/`, { reason: `${TAG} cleanup` })
      }
    }
  } finally { await adm.dispose() }
})
