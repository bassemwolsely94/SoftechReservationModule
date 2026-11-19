// W5b · Vouchers: issue → validate (discount worked out right) → OTP. The OTP step is NOT run:
// there is no test hook exposing the code, and generate-otp addresses a customer's phone, so the
// flow stops before "OTP sent" and the rest is a decision for the owner. Validation uses a dummy
// number (01000000000), never a customer's; the voucher is cancelled at the end.
import { test } from '@playwright/test'
import { BRANCH_A } from '../../lib/users.js'
import { finding } from '../../lib/findings.js'
import { WS, TAG, HOME, doers, apiAs, flag, expectRefused, brief, sameMoney, screenOk } from './_money.js'
import { can } from '../../lib/expected.js'

const V = '/api/vouchers/vouchers/'
const DUMMY = '01000000000'
const PCT = 5
const ORDER = 300
let voucherId = null
const issuers = doers('vouchers', 'create').filter(k => k !== 'admin')
const checkers = doers('vouchers', 'approve').filter(k => k !== 'admin')   // who may run the OTP step

// The issuer creates a fresh 5% voucher for branch A (per worker; cancelled in afterAll).
test.beforeAll(async ({ baseURL }) => {
  if (!issuers.length) return
  const key = issuers.includes('supervisor') ? 'supervisor' : issuers[0]
  const api = await apiAs(baseURL, key)
  try {
    const r = await api.post(V, { title: `${TAG} voucher`, voucher_category: 'public', voucher_type: 'discount_pct',
      discount_pct: String(PCT), valid_from: new Date().toISOString().slice(0, 10), max_uses: 1, branch: BRANCH_A.id })
    if (r.status !== 201) {
      flag({ key, route: V, kind: 'workflow', severity: 'P1', expected: 'voucher created (201)', actual: `HTTP ${r.status} ${brief(r.body)}` })
      return
    }
    voucherId = r.body.id
  } finally { await api.dispose() }
})

for (const key of checkers) {
  test(`${key}: validates the voucher on a ${ORDER} order: discount = ${PCT}%`, async ({ baseURL, browser }) => {
    test.skip(!voucherId, 'no voucher')
    const api = await apiAs(baseURL, key)
    try {
      const r = await api.post(`${V}${voucherId}/validate/`, { phone: DUMMY, order_amount: ORDER })
      if (r.status !== 200 || !r.body?.eligible) {
        flag({ key, route: `${V}:id/validate/`, kind: 'workflow', severity: 'P1', expected: 'voucher eligible', actual: `HTTP ${r.status} ${brief(r.body)}` })
        return
      }
      const want = ORDER * PCT / 100
      if (!sameMoney(r.body.discount_amount, want)) {
        flag({ key, route: `${V}:id/validate/`, kind: 'workflow', severity: 'P1', expected: `discount ${want.toFixed(2)}`, actual: `discount ${r.body.discount_amount}` })
      }
    } finally { await api.dispose() }
    await screenOk(browser, key, '/vouchers', { severity: 'P2', what: 'vouchers screen opens' })
  })
}

test('OTP step: stops before "OTP sent" (no test hook)', async () => {
  finding({ ws: WS, key: checkers.join(',') || 'pharmacist', route: '/api/vouchers/vouchers/:id/generate-otp/', kind: 'decision', severity: 'P2',
    expected: 'voucher OTP → verify → document completed end to end in UAT',
    actual: 'not run: no test hook exposes the OTP and generate-otp targets a real phone. Also: the plain OTP is inside the reply to the staff screen (whatsapp_url text and qr_code, apps/vouchers/models.py:408), so staff can see the code without the customer. Owner to decide: a UAT test phone/hook, and whether staff should see the code' })
})

test('must be refused: roles without vouchers:approve cannot start the OTP; without view cannot validate', async ({ baseURL }) => {
  test.skip(!voucherId, 'no voucher')
  for (const key of HOME.filter(k => k !== 'admin' && !can(k, 'vouchers', 'approve'))) {
    const api = await apiAs(baseURL, key)
    try {
      // an unusable phone: the permission check runs first, and nothing can ever be sent to it
      expectRefused(await api.post(`${V}${voucherId}/generate-otp/`, { phone: 'x' }), { key, route: `${V}:id/generate-otp/`, what: 'starting a voucher OTP' })
      if (!can(key, 'vouchers', 'view')) {
        expectRefused(await api.post(`${V}${voucherId}/validate/`, { phone: DUMMY, order_amount: ORDER }), { key, route: `${V}:id/validate/`, what: 'validating a voucher' })
      }
    } finally { await api.dispose() }
  }
})

test.afterAll(async ({ baseURL }) => {
  if (!voucherId) return
  const key = issuers.includes('supervisor') ? 'supervisor' : 'admin'
  const api = await apiAs(baseURL, key)
  try {
    const r = await api.post(`${V}${voucherId}/cancel/`, { reason: `${TAG} cleanup` })
    if (r.status === 403 && key !== 'admin' && can(key, 'vouchers', 'edit')) {
      finding({ ws: WS, key, route: `${V}:id/cancel/`, kind: 'decision', severity: 'P3',
        expected: 'vouchers:edit lets the role cancel a voucher (matrix)', actual: 'refused 403 "manager or admin role required": hard-coded role check, stricter than the matrix' })
      const adm = await apiAs(baseURL, 'admin')
      try { await adm.post(`${V}${voucherId}/cancel/`, { reason: `${TAG} cleanup` }) } finally { await adm.dispose() }
    }
  } finally { await api.dispose() }
})
