// C24 — «مبيعات فائتة»: tick «new» rows and reject them with one reason; each row is its own call.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/client', () => ({ missedSalesApi: { list: vi.fn(), reject: vi.fn() } }))
vi.mock('../help/useHelpTab', () => ({ default: () => {} }))
vi.mock('../components/DataFreshnessBar', () => ({ default: () => null }))

const { missedSalesApi } = await import('../api/client')
const { default: MissedSalesPage, canBulkReject } = await import('./MissedSalesPage')

const ROWS = [
  { id: 11, status: 'new', item_name: 'بانادول', item_code: '1', customer_name: 'أ', qty: 1, value: 10, seen_at: '2026-11-19T08:00:00Z' },
  { id: 12, status: 'new', item_name: 'كونجستال', item_code: '2', customer_name: 'ب', qty: 1, value: 20, seen_at: '2026-11-19T09:00:00Z' },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><MissedSalesPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  missedSalesApi.list.mockResolvedValue({ data: { results: ROWS } })
})
afterEach(cleanup)

describe('canBulkReject', () => {
  it('needs rows and a reason; «other» needs a note', () => {
    expect(canBulkReject(0, 'not_wanted', '')).toBe(false)
    expect(canBulkReject(2, '', '')).toBe(false)
    expect(canBulkReject(2, 'not_wanted', '')).toBe(true)
    expect(canBulkReject(2, 'other', ' ')).toBe(false)
    expect(canBulkReject(2, 'other', 'x')).toBe(true)
  })
})

describe('MissedSalesPage bulk reject', () => {
  it('rejects every ticked row through the per-row endpoint and reports a refusal', async () => {
    missedSalesApi.reject
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: 'تم البت فيه بالفعل.' } } })
    renderPage()
    await screen.findByText('بانادول')
    expect(screen.queryByTestId('missed-sales-bulk-bar')).toBeNull()
    fireEvent.click(screen.getByLabelText('تحديد الكل'))
    const bar = await screen.findByTestId('missed-sales-bulk-bar')
    fireEvent.change(bar.querySelector('select'), { target: { value: 'not_wanted' } })
    fireEvent.click(screen.getByText('رفض المحدد (2)'))
    await waitFor(() => expect(missedSalesApi.reject).toHaveBeenCalledTimes(2))
    expect(missedSalesApi.reject.mock.calls).toEqual([[11, 'not_wanted', ''], [12, 'not_wanted', '']])
    const note = await screen.findByTestId('missed-sales-bulk-result')
    expect(note.textContent).toContain('تم رفض 1')
    expect(note.textContent).toContain('تم البت فيه بالفعل.')
  })
})
