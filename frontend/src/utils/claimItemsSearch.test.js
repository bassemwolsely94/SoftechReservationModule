import { describe, expect, it } from 'vitest'
import { filterClaimItems } from './claimItemsSearch'

const items = [
  { item_code: '10023', item_name: 'PANADOL EXTRA' },
  { item_code: '20045', item_name: 'VOLTAREN 50' },
]
const names = rows => rows.map(r => r.item_name)

describe('filterClaimItems', () => {
  it('contains takes wildcards and any word order', () => {
    expect(names(filterClaimItems(items, 'pan*xtra'))).toEqual(['PANADOL EXTRA'])
    expect(names(filterClaimItems(items, '50 voltaren'))).toEqual(['VOLTAREN 50'])
  })
  it('notcontains keeps the rows that do not match', () => {
    expect(names(filterClaimItems(items, 'pan*', 'notcontains'))).toEqual(['VOLTAREN 50'])
  })
  it('a wildcards-only query is no filter, in contains and notcontains alike', () => {
    for (const q of ['*', '%', ' * % ', ''])
      for (const mode of ['contains', 'notcontains'])
        expect(filterClaimItems(items, q, mode), `${mode} ${q}`).toHaveLength(2)
  })
  it('begins / ends compare literally, scoped to code or name', () => {
    expect(names(filterClaimItems(items, '200', 'begins', 'code'))).toEqual(['VOLTAREN 50'])
    expect(names(filterClaimItems(items, 'extra', 'ends', 'name'))).toEqual(['PANADOL EXTRA'])
    expect(filterClaimItems(items, '200', 'begins', 'name')).toHaveLength(0)
  })
})
