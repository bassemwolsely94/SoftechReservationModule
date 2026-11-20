import { describe, it, expect } from 'vitest'
import { canPickAnyBranch } from './branchAccess'

describe('canPickAnyBranch', () => {
  it('admin may pick any branch', () => {
    expect(canPickAnyBranch({ role: 'admin' })).toBe(true)
  })
  it('the server flag can_pick_any_branch opens the picker for any role', () => {
    for (const role of ['supervisor', 'quality_manager', 'accountant', 'purchasing']) {
      expect(canPickAnyBranch({ role, can_pick_any_branch: true })).toBe(true)
    }
  })
  it('a branch-bound user without the flag may not', () => {
    expect(canPickAnyBranch({ role: 'supervisor', can_pick_any_branch: false })).toBe(false)
    expect(canPickAnyBranch({ role: 'pharmacist' })).toBe(false)
  })
  it('handles no user', () => {
    expect(canPickAnyBranch(null)).toBe(false)
    expect(canPickAnyBranch(undefined)).toBe(false)
  })
})
