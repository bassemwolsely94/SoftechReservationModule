import { describe, expect, it } from 'vitest'
import { helpChipPosition, isPhoneShell } from './chipPlacement'

describe('help chip placement (UAT W8: it covered the submit of /m/*/new forms)', () => {
  it('phone shells put it under the header, never at the bottom', () => {
    for (const p of ['/m', '/m/reservations/new', '/m/qa', '/rider']) {
      expect(isPhoneShell(p)).toBe(true)
      expect(helpChipPosition(p)).not.toMatch(/bottom/)
      expect(helpChipPosition(p)).toMatch(/top-/)
    }
  })
  it('desktop pages keep the bottom-start corner', () => {
    for (const p of ['/', '/reservations', '/media', '/riders-report']) {
      expect(isPhoneShell(p)).toBe(false)
      expect(helpChipPosition(p)).toMatch(/bottom-/)
    }
  })
})
