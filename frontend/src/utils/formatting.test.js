// Money and number formatting. Display only — the server decides every amount — but a wrong
// format on a till or a ledger reads as a wrong amount, so the shapes are pinned here.
import { describe, expect, it } from 'vitest'
import { money as posMoney } from '../hooks/usePosOrder'
import { money as glMoney, pct as glPct } from '../pages/finance/gl/glUi'
import { money as supplyMoney, q as supplyQty, pct as supplyPct } from '../pages/supply/supplyUi'
import { fmt, fmtPct } from '../components/pic-analytics/KpiCards'
import { toNumber } from '../hooks/sortCompare'

describe('POS money (usePosOrder)', () => {
  it('always two decimals, Latin digits, thousands commas', () => {
    expect(posMoney(1234.5)).toBe('1,234.50')
    expect(posMoney('99.999')).toBe('100.00')
    expect(posMoney(0)).toBe('0.00')
  })
  it('empty / null reads as 0.00, never NaN', () => {
    expect(posMoney(null)).toBe('0.00')
    expect(posMoney(undefined)).toBe('0.00')
    expect(posMoney('')).toBe('0.00')
  })
  it('negative amounts (returns / credits) keep their sign', () => {
    expect(posMoney(-12.3)).toBe('-12.30')
  })
})

describe('GL money (finance)', () => {
  it('formats the server decimal string', () => {
    expect(glMoney('1234567.891')).toBe('1,234,567.89')
    expect(glMoney('-0.5')).toBe('-0.50')
  })
  it('blankZero hides zeros and blanks, otherwise 0.00', () => {
    expect(glMoney('0', { blankZero: true })).toBe('')
    expect(glMoney(null, { blankZero: true })).toBe('')
    expect(glMoney(null)).toBe('0.00')
  })
  it('a non-number is shown as sent, not as NaN', () => {
    expect(glMoney('n/a')).toBe('n/a')
  })
  it('ratios are percentages with two decimals', () => {
    expect(glPct(0.2345)).toBe('23.45%')
    expect(glPct(null)).toBe('—')
  })
})

describe('supply money / quantity', () => {
  it('money: up to two decimals, a dash when empty or not a number', () => {
    expect(supplyMoney(1500)).toBe('1,500')
    expect(supplyMoney(12.345)).toBe('12.35')
    expect(supplyMoney('')).toBe('—')
    expect(supplyMoney('abc')).toBe('—')
  })
  it('quantity: whole numbers without decimals, else two places trimmed', () => {
    expect(supplyQty(3)).toBe('3')
    expect(supplyQty(2.9996)).toBe('3')
    expect(supplyQty(1.5)).toBe('1.5')
    expect(supplyQty(1.333333)).toBe('1.33')
    expect(supplyQty(null)).toBe('—')
  })
  it('pct rounds a fraction to a whole percent', () => {
    expect(supplyPct(0.456)).toBe('46%')
  })
})

describe('analytics numbers (KpiCards)', () => {
  it('fixed decimals, dash for missing', () => {
    expect(fmt(1234.567)).toBe('1,235')
    expect(fmt(1234.567, 2)).toBe('1,234.57')
    expect(fmt(null)).toBe('—')
    expect(fmt('x')).toBe('—')
    expect(fmtPct(12.34)).toBe('12.3%')
  })
})

describe('reading numbers back (sortCompare.toNumber)', () => {
  it.each([
    ['1,234.5', 1234.5],
    ['٣٢٫٥', 32.5],
    ['1,5', 1.5],
    ['12%', 12],
    [' -7 ', -7],
    [42, 42],
  ])('%s → %s', (input, out) => expect(toNumber(input)).toBe(out))

  it.each(['5 د', '', 'abc', null, NaN])('%s is not a number', (input) => expect(toNumber(input)).toBeNull())
})
