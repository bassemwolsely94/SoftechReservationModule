// D-25 / FE-9 — the live send (F10) and the parked-basket delete keep their second step as a second
// press, not window.confirm. The audit's test: F10 F10 → one push, and no native dialog.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { POS_ARM_MS, twoStepGate } from './usePosOrder'

// the hook's passGate in miniature: arm on a miss, go ahead (and disarm) on a hit
function presses(times, key = 'live') {
  let armed = null
  const sent = []
  for (const t of times) {
    if (twoStepGate(armed, key, t)) { armed = null; sent.push(t) }
    else armed = { key, at: t }
  }
  return sent
}

describe('twoStepGate (POS live send / parked delete)', () => {
  it('one press only arms — nothing is sent', () => {
    expect(presses([1000])).toEqual([])
  })
  it('F10 F10 within 4 s sends exactly once', () => {
    expect(presses([1000, 1800])).toEqual([1800])
  })
  it('a third quick press after a send only arms again (no double push)', () => {
    expect(presses([1000, 1500, 1900])).toEqual([1500])
  })
  it('a second press after the window has expired re-arms instead of sending', () => {
    expect(presses([1000, 1000 + POS_ARM_MS + 1])).toEqual([])
    expect(presses([1000, 1000 + POS_ARM_MS + 1, 1000 + POS_ARM_MS + 500])).toEqual([1000 + POS_ARM_MS + 500])
  })
  it('the arm is per key: arming one parked basket does not delete another', () => {
    const armed = { key: 'parked:a', at: 1000 }
    expect(twoStepGate(armed, 'parked:b', 1200)).toBe(false)
    expect(twoStepGate(armed, 'parked:a', 1200)).toBe(true)
    expect(twoStepGate(armed, 'live', 1200)).toBe(false)
  })
  it('usePosOrder no longer calls window.confirm for the send or the parked delete', () => {
    const src = readFileSync(join(process.cwd(), 'src/hooks/usePosOrder.js'), 'utf8')
    expect(src).not.toMatch(/window\.confirm\s*\(/)
    expect(src.match(/passGate\('live'\)/g)).toHaveLength(2)        // both checkout paths
  })
})
