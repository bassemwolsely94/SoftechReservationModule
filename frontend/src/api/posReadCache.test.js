// C27 / P-06 — fewer POS requests, same answers.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cachedGet, clearPosRefCache, refCacheKey, suggestItemsKey, POS_REF_TTL_MS } from './posReadCache'
import { reconcileSuggestedLines } from '../hooks/usePosOrder'

describe('cachedGet (POS reference reads)', () => {
  beforeEach(() => clearPosRefCache())

  it('asks the server once within the TTL and returns the same answer', async () => {
    const get = vi.fn(async () => ({ data: { types: [1] } }))
    let t = 1000
    const now = () => t
    const a = await cachedGet('/pos-orders/customer-types/', { get, now })
    t += POS_REF_TTL_MS - 1
    const b = await cachedGet('/pos-orders/customer-types/', { get, now })
    expect(get).toHaveBeenCalledTimes(1)
    expect(b).toBe(a)
  })

  it('asks again after the TTL', async () => {
    const get = vi.fn(async () => ({ data: {} }))
    let t = 0
    const now = () => t
    await cachedGet('/branches/', { get, now })
    t += POS_REF_TTL_MS + 1
    await cachedGet('/branches/', { get, now })
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('shares one request between concurrent callers', async () => {
    const get = vi.fn(() => new Promise(r => setTimeout(() => r({ data: 1 }), 5)))
    await Promise.all([cachedGet('/branches/', { get }), cachedGet('/branches/', { get })])
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('never keeps a failure', async () => {
    const get = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce({ data: 2 })
    await expect(cachedGet('/branches/', { get })).rejects.toThrow('down')
    await expect(cachedGet('/branches/', { get })).resolves.toEqual({ data: 2 })
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('drops an answer the caller does not want kept (a "could not read" note)', async () => {
    const get = vi.fn(async () => ({ data: { stores: [], note: 'x' } }))
    const keep = d => !d?.note
    await cachedGet('/pos-orders/branch-stores/', { params: { branch: 3 }, get, keep })
    await Promise.resolve()
    await cachedGet('/pos-orders/branch-stores/', { params: { branch: 3 }, get, keep })
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('keys by user and params, so another user or branch never shares an answer', () => {
    expect(refCacheKey('/b/', { branch: 1 }, '7')).not.toBe(refCacheKey('/b/', { branch: 1 }, '8'))
    expect(refCacheKey('/b/', { branch: 1 }, '7')).not.toBe(refCacheKey('/b/', { branch: 2 }, '7'))
    expect(refCacheKey('/b/', { a: 1, b: 2 }, '7')).toBe(refCacheKey('/b/', { b: 2, a: 1 }, '7'))
  })
})

describe('discount-suggest request key', () => {
  it('ignores line order, duplicates, quantities and blank codes', () => {
    const a = [{ softech_itemcode: '963', qty: 1 }, { softech_itemcode: '404', qty: 2 }]
    const b = [{ softech_itemcode: '404', qty: 9 }, { softech_itemcode: '963' }, { softech_itemcode: '404' }, {}]
    expect(suggestItemsKey(a)).toBe(suggestItemsKey(b))
    expect(suggestItemsKey(a)).toBe('404,963')
  })
  it('changes when the item set changes', () => {
    expect(suggestItemsKey([{ softech_itemcode: '1' }])).not.toBe(suggestItemsKey([{ softech_itemcode: '1' }, { softech_itemcode: '2' }]))
  })
})

describe('reconcileSuggestedLines (moved verbatim — same results)', () => {
  const data = { suggestions: { A: 10, B: null }, caps: { A: 8, B: 5 }, ceiling: 15 }
  it('contract rate is capped by the per-item cap', () => {
    const [a] = reconcileSuggestedLines([{ softech_itemcode: 'A', cust_discp: 0 }], data)
    expect(a.cust_discp).toBe(8)
  })
  it('no suggestion → 0 (retail is cap-only, nothing auto-applies)', () => {
    const [b] = reconcileSuggestedLines([{ softech_itemcode: 'B', cust_discp: 4 }], data)
    expect(b.cust_discp).toBe(0)
  })
  it('a hand-set % is kept, but never above the cap', () => {
    const [m1, m2] = reconcileSuggestedLines([
      { softech_itemcode: 'B', cust_discp: 3, disc_manual: true },
      { softech_itemcode: 'B', cust_discp: 7, disc_manual: true }], data)
    expect(m1.cust_discp).toBe(3)
    expect(m2.cust_discp).toBe(5)
  })
  it('an item with no cap falls back to the ceiling, then 100', () => {
    const [c] = reconcileSuggestedLines([{ softech_itemcode: 'C', cust_discp: 50, disc_manual: true }], data)
    expect(c.cust_discp).toBe(15)
    const [d] = reconcileSuggestedLines([{ softech_itemcode: 'C', cust_discp: 50, disc_manual: true }], { suggestions: {} })
    expect(d.cust_discp).toBe(50)
  })
  it('a line already right is returned as the same object (no re-render churn)', () => {
    const l = { softech_itemcode: 'A', cust_discp: 8 }
    expect(reconcileSuggestedLines([l], data)[0]).toBe(l)
  })
  it('a duplicate line of a known item gets the same discount as the first (cache reuse is safe)', () => {
    const out = reconcileSuggestedLines([{ softech_itemcode: 'A', cust_discp: 8 }, { softech_itemcode: 'A', cust_discp: 0 }], data)
    expect(out.map(l => l.cust_discp)).toEqual([8, 8])
  })
})

describe('usePosOrder wiring', () => {
  const src = readFileSync(join(process.cwd(), 'src/hooks/usePosOrder.js'), 'utf8')
  it('debounces discount-suggest and drops a stale answer', () => {
    expect(src).toMatch(/SUGGEST_DEBOUNCE_MS\)/)
    expect(src).toMatch(/signal: ctl\.signal/)
  })
  it('still reads the seller reference fresh (never cached)', () => {
    expect(src).toMatch(/api\.get\('\/pos-orders\/reference\/'\)/)
    expect(src).not.toMatch(/cachedGet\('\/pos-orders\/reference\/'/)
  })
})
