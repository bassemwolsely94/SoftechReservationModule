import { describe, expect, it } from 'vitest'
import { entryTotals, lacksAccount } from './EntryEditor'

const line = (account_code, debit = '', credit = '') => ({ account_code, debit, credit })

describe('entryTotals (UAT W5b P3: «متوازن» with a line that has no account)', () => {
  it('a balanced entry with every account chosen is balanced', () => {
    const t = entryTotals([line('1101', '100'), line('2101', '', '100')])
    expect(t).toMatchObject({ debit: 100, credit: 100, diff: 0, missingAccount: 0, balanced: true })
  })

  it('equal sides but a line without an account is not balanced', () => {
    const t = entryTotals([line('1101', '100'), line('', '', '100')])
    expect(t.diff).toBe(0)
    expect(t.missingAccount).toBe(1)
    expect(t.balanced).toBe(false)
  })

  it('an empty line (no account, no amount) does not count', () => {
    const t = entryTotals([line('1101', '50'), line('2101', '', '50'), line('', '', '')])
    expect(t.missingAccount).toBe(0)
    expect(t.balanced).toBe(true)
  })

  it('nothing entered is not balanced', () => {
    expect(entryTotals([line(''), line('')]).balanced).toBe(false)
  })

  it('sums in cents, so 0.1 + 0.2 balances 0.3', () => {
    const t = entryTotals([line('1', '0.1'), line('2', '0.2'), line('3', '', '0.3')])
    expect(t.diff).toBe(0)
    expect(t.balanced).toBe(true)
  })

  it('lacksAccount: blank-space code with an amount lacks one; a zero amount does not', () => {
    expect(lacksAccount(line('  ', '10'))).toBe(true)
    expect(lacksAccount(line('', '0', '0'))).toBe(false)
  })
})
