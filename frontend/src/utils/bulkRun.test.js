// C24 — bulk = the per-row endpoint once per ticked row; partial failure is reported per row.
import { describe, expect, it, vi } from 'vitest'
import { bulkErrorDetail, keepFailedTicked, runEach } from './bulkRun'

describe('runEach', () => {
  it('calls the per-row action once per row, in order', async () => {
    const act = vi.fn().mockResolvedValue({})
    const res = await runEach([{ id: 3 }, { id: 1 }], act)
    expect(act.mock.calls.map(c => c[0].id)).toEqual([3, 1])
    expect(res).toEqual({ done: [3, 1], failed: [] })
  })
  it('a refusal does not stop the others and keeps its reason', async () => {
    const act = vi.fn()
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: 'تم البت فيه بالفعل.' } } })
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce({ response: { status: 403, data: {} } })
    const res = await runEach([{ k: 'a' }, { k: 'b' }, { k: 'c' }], act, r => r.k)
    expect(res.done).toEqual(['b'])
    expect(res.failed).toEqual([{ id: 'a', detail: 'تم البت فيه بالفعل.' }, { id: 'c', detail: 'خطأ 403' }])
  })
  it('nothing ticked calls nothing', async () => {
    const act = vi.fn()
    expect(await runEach([], act)).toEqual({ done: [], failed: [] })
    expect(act).not.toHaveBeenCalled()
  })
})

describe('helpers', () => {
  it('keeps only failed rows ticked', () => {
    expect(keepFailedTicked({ done: [1], failed: [{ id: 2, detail: 'x' }] })).toEqual({ 2: true })
    expect(keepFailedTicked(null)).toEqual({})
  })
  it('reads detail, then error, then status, then offline', () => {
    expect(bulkErrorDetail({ response: { status: 400, data: { error: 'e' } } })).toBe('e')
    expect(bulkErrorDetail({})).toBe('لا يوجد اتصال بالسيرفر')
  })
})
