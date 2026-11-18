// W5b · Insurance claim review on a real draft claim of the copy: totals add up, a line is signed
// off (and un-signed), the claim moves draft → ready → draft. Plus the lock check: a locked
// (submitted) claim must not be reopened just by changing its status.
import { test, expect } from '@playwright/test'
import { finding } from '../../lib/findings.js'
import { WS, TAG, HOME, doers, apiAs, flag, expectRefused, brief, sameMoney, screenOk } from './_money.js'
import { can } from '../../lib/expected.js'

const CLAIMS = '/api/insurance/claims/'
const reviewers = doers('insurance', 'edit').filter(k => k !== 'admin')
const finalizers = doers('insurance', 'finalize').filter(k => k !== 'admin')

/** The newest unlocked draft claim with prescriptions (each test picks it itself). */
async function pickClaim(api) {
  const list = await api.get(`${CLAIMS}?status=draft&page_size=20`)
  const c = (list.body?.results || []).find(x => !x.is_locked && Number(x.final_rx_count) > 0)
  return c ? c.id : null
}

for (const key of reviewers) {
  test(`${key}: opens a draft claim, the totals add up, signs off a line`, async ({ baseURL, browser }) => {
    const api = await apiAs(baseURL, key)
    let claimId
    try {
      const list = await api.get(`${CLAIMS}?status=draft&page_size=5`)
      expect(list.status, brief(list.body)).toBe(200)
      claimId = await pickClaim(api)
      test.skip(!claimId, 'no unlocked draft claim with prescriptions on the copy')
      const c = (await api.get(`${CLAIMS}${claimId}/`)).body

      // claim header: net = gross − discount; and = Σ effective net of the included prescriptions
      if (!sameMoney(Number(c.final_gross_before) - Number(c.final_total_discount), c.final_net_after)) {
        flag({ key, route: `/insurance/claims/${claimId}`, kind: 'workflow', severity: 'P1',
          expected: `net = gross − discount (${c.final_gross_before} − ${c.final_total_discount})`, actual: `net ${c.final_net_after}` })
      }
      const inc = c.prescriptions.filter(r => !r.is_excluded)
      const sumNet = inc.reduce((s, r) => s + Number(r.effective_net_after), 0)
      const sumGross = inc.reduce((s, r) => s + Number(r.gross_before), 0)
      // per-prescription rounding: allow 1 piastre per prescription
      if (!sameMoney(sumNet, c.final_net_after, 0.01 * inc.length)) {
        flag({ key, route: `/insurance/claims/${claimId}`, kind: 'workflow', severity: 'P1',
          expected: `claim net = Σ prescriptions ${sumNet.toFixed(2)}`, actual: `claim net ${c.final_net_after}` })
      }
      if (!sameMoney(sumGross, c.final_gross_before, 0.01 * inc.length) && !c.manual_rx?.length && !c.supplements?.length) {
        flag({ key, route: `/insurance/claims/${claimId}`, kind: 'workflow', severity: 'P1',
          expected: `claim gross = Σ prescriptions ${sumGross.toFixed(2)}`, actual: `claim gross ${c.final_gross_before}` })
      }
      if (inc.length !== Number(c.final_rx_count)) {
        flag({ key, route: `/insurance/claims/${claimId}`, kind: 'workflow', severity: 'P2',
          expected: `rx count ${inc.length} (included)`, actual: `final_rx_count ${c.final_rx_count}` })
      }

      // sign off one line, then take the sign-off back
      let signed = false
      for (const rx of inc.slice(0, 5)) {
        const lines = await api.get(`${CLAIMS}${claimId}/prescriptions/${rx.id}/lines/`)
        const arr = Array.isArray(lines.body) ? lines.body : (lines.body?.results || lines.body?.lines || [])
        if (!arr.length) continue
        const url = `${CLAIMS}${claimId}/prescriptions/${rx.id}/lines/${arr[0].id}/review/`
        const on = await api.post(url, { approved: true, note: TAG })
        if (on.status !== 200) {
          flag({ key, route: `${CLAIMS}:id/…/review/`, kind: 'workflow', severity: 'P1', expected: 'line signed off (200)', actual: `HTTP ${on.status} ${brief(on.body)}` })
        }
        await api.post(url, { approved: false, note: `${TAG} undo` })
        signed = true
        break
      }
      if (!signed) finding({ ws: WS, key, route: `/insurance/claims/${claimId}`, kind: 'decision', severity: 'P3', expected: 'claim lines to sign off', actual: 'no prescription lines returned for the first 5 prescriptions' })
    } finally { await api.dispose() }

    await screenOk(browser, key, `/insurance/claims/${claimId}`, { what: 'claim screen opens for a reviewer' })
  })
}

for (const key of finalizers) {
  test(`${key}: moves the claim draft → ready → draft; a locked claim is not reopened`, async ({ baseURL }) => {
    const api = await apiAs(baseURL, key)
    const claimId = await pickClaim(api)
    test.skip(!claimId, 'no claim picked')
    const url = `${CLAIMS}${claimId}/change-status/`
    try {
      const r1 = await api.post(url, { status: 'ready', notes: TAG })
      expect(r1.status, brief(r1.body)).toBe(200)
      const r2 = await api.post(url, { status: 'draft', notes: TAG })
      expect(r2.status, brief(r2.body)).toBe(200)

      // lock it (submitted), then try to walk it back to draft
      const lk = await api.post(url, { status: 'submitted', notes: TAG })
      expect(lk.status, brief(lk.body)).toBe(200)
      expect((await api.get(`${CLAIMS}${claimId}/`)).body?.is_locked).toBe(true)
      const back = await api.post(url, { status: 'draft', notes: `${TAG} reopen` })
      if (back.status === 200) {
        finding({ ws: WS, key, route: '/api/insurance/claims/:id/change-status/', kind: 'decision', severity: 'P2',
          expected: 'a submitted (locked) claim cannot go back to draft without an unlock step',
          actual: 'change-status accepted submitted → draft: no transition rule or lock check on status changes' })
      }
      // leave the copy as found: draft
      if ((await api.get(`${CLAIMS}${claimId}/`)).body?.status !== 'draft') await api.post(url, { status: 'draft', notes: TAG })
    } finally { await api.dispose() }
  })
}

test('must be refused: roles without insurance rights cannot open or move claims', async ({ baseURL }) => {
  const adm = await apiAs(baseURL, 'admin')
  const claimId = await pickClaim(adm)
  await adm.dispose()
  test.skip(!claimId, 'no claim picked')
  for (const key of HOME.filter(k => k !== 'admin' && !can(k, 'insurance', 'view'))) {
    const api = await apiAs(baseURL, key)
    try {
      expectRefused(await api.get(`${CLAIMS}${claimId}/`), { key, route: '/api/insurance/claims/:id/', what: 'opening an insurance claim' })
      expectRefused(await api.post(`${CLAIMS}${claimId}/change-status/`, { status: 'ready', notes: TAG }),
        { key, route: '/api/insurance/claims/:id/change-status/', what: 'changing a claim status' })
    } finally { await api.dispose() }
  }
})
