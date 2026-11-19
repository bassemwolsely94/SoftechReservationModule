// D-18 server checkout — the hook's new branch: switch → path, intent → request body, reply → screen state.
import { describe, expect, it } from 'vitest'
import { checkoutBody, checkoutOutcome, serverCheckoutOn, tenderIntentFor } from './usePosOrder'

describe('serverCheckoutOn', () => {
  it('is off without the opt-in (mobile POS) or without reference data', () => {
    expect(serverCheckoutOn(false, { server_checkout_branch_ids: null }, 3)).toBe(false)
    expect(serverCheckoutOn(true, null, 3)).toBe(false)
  })
  it('follows the server list: null = every branch, [] or missing = off', () => {
    expect(serverCheckoutOn(true, { server_checkout_branch_ids: null }, 3)).toBe(true)
    expect(serverCheckoutOn(true, { server_checkout_branch_ids: [] }, 3)).toBe(false)
    expect(serverCheckoutOn(true, {}, 3)).toBe(false)
    expect(serverCheckoutOn(true, { server_checkout_branch_ids: [3] }, '3')).toBe(true)
    expect(serverCheckoutOn(true, { server_checkout_branch_ids: [4] }, '3')).toBe(false)
  })
})

describe('tenderIntentFor', () => {
  const cash = (amount) => ({ pay_type: 'cash', amount })
  const credit = (amount) => ({ pay_type: 'credit', amount })
  it('a plain sale is the channel default — tender amounts are not sent', () => {
    expect(tenderIntentFor({ docKind: 'sale', isClaim: false, patientPayment: '', tenders: [cash(412.75)] }))
      .toEqual({ kind: 'default' })
  })
  it('the patient co-pay on a claim channel becomes patient_copay', () => {
    expect(tenderIntentFor({ docKind: 'sale', isClaim: true, patientPayment: '50', tenders: [] }))
      .toEqual({ kind: 'patient_copay', patient: '50.00' })
  })
  it('a blank co-pay leaves the contract rule to the server', () => {
    expect(tenderIntentFor({ docKind: 'sale', isClaim: true, patientPayment: '', tenders: [cash(10)] }))
      .toEqual({ kind: 'default' })
  })
  it('a credit amount becomes credit_portion; the cash part is worked out by the server', () => {
    expect(tenderIntentFor({ docKind: 'sale', isClaim: false, patientPayment: '',
                             tenders: [cash(1), credit(60), credit(40)] }))
      .toEqual({ kind: 'credit_portion', credit: '100.00' })
  })
  it('a return ignores tenders (the refund is the sale own rows)', () => {
    expect(tenderIntentFor({ docKind: 'return', isClaim: true, patientPayment: '5', tenders: [credit(9)] }))
      .toEqual({ kind: 'default' })
  })
})

describe('checkoutBody', () => {
  const payload = { client_token: 't', branch: 3, channel: 'cash', lines: [] }
  it('dry run carries no confirm', () => {
    const b = checkoutBody(payload, { live: false, expectedDue: '412.75', intent: { kind: 'default' } })
    expect(b).toEqual({ ...payload, checkout: { mode: 'dry_run', expected_due: '412.75',
                                                 tender_intent: { kind: 'default' }, tender_extras: {} } })
  })
  it('live sends confirm and the total the cashier saw, as text', () => {
    const b = checkoutBody(payload, { live: true, expectedDue: 412.75, intent: { kind: 'default' } })
    expect(b.checkout.mode).toBe('live')
    expect(b.checkout.confirm).toBe(true)
    expect(b.checkout.expected_due).toBe('412.75')
    expect(b.client_token).toBe('t')
  })
})

describe('checkoutOutcome', () => {
  it('maps the server reply to what the screen does', () => {
    expect(checkoutOutcome({ busy: true })).toBe('busy')
    expect(checkoutOutcome({ queued: true, status: 'queued' })).toBe('queued')
    expect(checkoutOutcome({ status: 'pushed', softech: { docnumber: 7901 } })).toBe('sent')
    expect(checkoutOutcome({ status: 'pushed', replayed: true })).toBe('sent')
    expect(checkoutOutcome({ status: 'ready', plan: {} })).toBe('dry_run')
  })
})
