import { describe, it, expect } from 'vitest'
import { canPickAnyBranch } from './branchAccess'

describe('canPickAnyBranch', () => {
  it('admin may pick any branch', () => {
    expect(canPickAnyBranch({ role: 'admin' })).toBe(true)
  })
  it('the all-branches flag opens the picker for any role', () => {
    for (const role of ['supervisor', 'quality_manager', 'accountant', 'purchasing']) {
      expect(canPickAnyBranch({ role, access_all_branches: true })).toBe(true)
    }
  })
  it('a branch-bound user without the flag may not', () => {
    expect(canPickAnyBranch({ role: 'supervisor', access_all_branches: false })).toBe(false)
    expect(canPickAnyBranch({ role: 'pharmacist' })).toBe(false)
  })
  it('handles no user', () => {
    expect(canPickAnyBranch(null)).toBe(false)
    expect(canPickAnyBranch(undefined)).toBe(false)
  })
})
