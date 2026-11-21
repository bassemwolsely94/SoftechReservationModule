import { describe, it, expect } from 'vitest'
import { canResetMfa } from './mfaReset'

const admin = { id: 1, role: 'admin' }

describe('canResetMfa', () => {
  it('shows for an admin on another user with 2FA on', () => {
    expect(canResetMfa(admin, { id: 2, mfa_enabled: true })).toBe(true)
  })
  it('hides when the user has no 2FA', () => {
    expect(canResetMfa(admin, { id: 2, mfa_enabled: false })).toBe(false)
    expect(canResetMfa(admin, { id: 2 })).toBe(false)
  })
  it('hides on the admin\'s own row', () => {
    expect(canResetMfa(admin, { id: 1, mfa_enabled: true })).toBe(false)
  })
  it('hides for anyone but an admin', () => {
    for (const role of ['supervisor', 'pharmacist', 'viewer']) {
      expect(canResetMfa({ id: 9, role }, { id: 2, mfa_enabled: true })).toBe(false)
    }
  })
  it('hides without a user or a row', () => {
    expect(canResetMfa(null, { id: 2, mfa_enabled: true })).toBe(false)
    expect(canResetMfa(admin, null)).toBe(false)
  })
})
