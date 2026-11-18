import { describe, it, expect } from 'vitest'
import { isExactishRow, isExactCodeRow, EXACTISH_TIERS, CHIP_FLAGS } from './autoAdd'

describe('isExactishRow (queued Enter)', () => {
  it('accepts the plain text / code tiers', () => {
    for (const tier of ['code', 'starts', 'word', 'contains', 'any_order']) {
      expect(isExactishRow({ tier, name: 'X' })).toBe(true)
    }
  })

  it('refuses every fuzzy tier', () => {
    for (const tier of ['learned', 'sound', 'approx', 'ingredient', 'synonym', 'code_prefix', 'code_part']) {
      expect(isExactishRow({ tier, [tier]: true })).toBe(false)
    }
  })

  it('refuses a row with a chip flag even on an exact-ish tier', () => {
    for (const f of CHIP_FLAGS) expect(isExactishRow({ tier: 'contains', [f]: true })).toBe(false)
  })

  it('refuses a missing row or a row without a tier (the default widget rows)', () => {
    expect(isExactishRow(undefined)).toBe(false)
    expect(isExactishRow(null)).toBe(false)
    expect(isExactishRow({ name: 'PANADOL' })).toBe(false)
  })

  it('lists exactly the ruled tiers', () => {
    expect(EXACTISH_TIERS).toEqual(['code', 'starts', 'word', 'contains', 'any_order'])
  })
})

describe('isExactCodeRow (camera scan)', () => {
  it('accepts only an exact code / barcode row', () => {
    expect(isExactCodeRow({ tier: 'code' })).toBe(true)
    for (const tier of ['starts', 'word', 'contains', 'any_order', 'sound', 'approx', 'code_prefix', 'code_part', 'learned']) {
      expect(isExactCodeRow({ tier })).toBe(false)
    }
    expect(isExactCodeRow(null)).toBe(false)
    expect(isExactCodeRow({ tier: 'code', code_part: true })).toBe(false)
    expect(isExactCodeRow({ tier: 'code', code_prefix: true })).toBe(false)
  })
})
