import { describe, expect, it } from 'vitest'
import { cairoDate, cairoDaysAgo } from './cairoDate'

describe('cairoDate', () => {
  it('00:30 Cairo is already the new day while UTC is still yesterday', () => {
    // 2026-11-16T22:30Z = 2026-11-17 00:30 in Cairo (UTC+2 in November)
    const at = new Date('2026-11-16T22:30:00Z')
    expect(at.toISOString().slice(0, 10)).toBe('2026-11-16')
    expect(cairoDate(at)).toBe('2026-11-17')
  })

  it('daytime matches the UTC date', () => {
    expect(cairoDate(new Date('2026-11-17T10:00:00Z'))).toBe('2026-11-17')
  })

  it('days-ago counts back from the Cairo day, across month ends', () => {
    const at = new Date('2026-11-30T22:30:00Z')           // 2026-12-01 00:30 Cairo
    expect(cairoDaysAgo(0, at)).toBe('2026-12-01')
    expect(cairoDaysAgo(1, at)).toBe('2026-11-30')
    expect(cairoDaysAgo(7, at)).toBe('2026-11-24')
  })
})
