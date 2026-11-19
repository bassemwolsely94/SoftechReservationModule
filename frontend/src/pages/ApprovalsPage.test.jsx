import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/client', () => ({
  approvalsApi: { pending: vi.fn(), requests: vi.fn(), decide: vi.fn() },
}))
vi.mock('../help/useHelpTab', () => ({ default: () => {} }))

const { approvalsApi } = await import('../api/client')
const { default: ApprovalsPage } = await import('./ApprovalsPage')
const { decideMany, canBulkDecide } = await import('./approvalsBulk')

// Full audit FE-10: approvals are ticked and decided together, and the grid has the keyboard.
const ROWS = [
  { id: 1, title: 'إجازة أحمد', workflow_name: 'إجازات', requested_by_name: 'أحمد', status: 'pending', requested_at: '2026-11-18T08:00:00Z' },
  { id: 2, title: 'سلفة منى', workflow_name: 'سلف', requested_by_name: 'منى', status: 'pending', requested_at: '2026-11-18T09:00:00Z' },
  { id: 3, title: 'عزل دفعة', workflow_name: 'جودة', requested_by_name: 'سارة', status: 'in_review', requested_at: '2026-11-18T10:00:00Z' },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><ApprovalsPage /></MemoryRouter></QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  approvalsApi.pending.mockResolvedValue({ data: ROWS })
  approvalsApi.decide.mockResolvedValue({ data: {} })
})
afterEach(cleanup)

describe('decideMany', () => {
  it('decides each id in order through the single-decision call', async () => {
    const decide = vi.fn().mockResolvedValue({})
    const res = await decideMany([3, 1], { decision: 'approved', notes: 'ok' }, decide)
    expect(decide.mock.calls).toEqual([[3, { decision: 'approved', notes: 'ok' }], [1, { decision: 'approved', notes: 'ok' }]])
    expect(res).toEqual({ done: [3, 1], failed: [] })
  })

  it('a refusal does not stop the others and keeps its reason', async () => {
    const decide = vi.fn()
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce({ response: { status: 400, data: { detail: 'لست المعتمد لهذه الخطوة.' } } })
      .mockRejectedValueOnce({})
    const res = await decideMany([1, 2, 3], { decision: 'approved' }, decide)
    expect(res.done).toEqual([1])
    expect(res.failed).toEqual([{ id: 2, detail: 'لست المعتمد لهذه الخطوة.' }, { id: 3, detail: 'لا يوجد اتصال بالسيرفر' }])
  })

  it('a rejection needs a reason; nothing ticked decides nothing', () => {
    expect(canBulkDecide('approved', 2, '')).toBe(true)
    expect(canBulkDecide('rejected', 2, '  ')).toBe(false)
    expect(canBulkDecide('rejected', 2, 'ناقص مستند')).toBe(true)
    expect(canBulkDecide('approved', 0, 'x')).toBe(false)
  })
})

describe('ApprovalsPage bulk + keyboard', () => {
  it('ticks two rows and approves them in one action', async () => {
    renderPage()
    fireEvent.click(await screen.findByLabelText('تحديد إجازة أحمد'))
    fireEvent.click(screen.getByLabelText('تحديد عزل دفعة'))
    fireEvent.click(screen.getByRole('button', { name: /موافقة على المحدد \(2\)/ }))
    await waitFor(() => expect(approvalsApi.decide).toHaveBeenCalledTimes(2))
    expect(approvalsApi.decide.mock.calls.map(c => c[0]).sort()).toEqual([1, 3])
    expect(approvalsApi.decide.mock.calls[0][1]).toEqual({ decision: 'approved', notes: '' })
    expect(await screen.findByTestId('approvals-bulk-result')).toHaveProperty('textContent', expect.stringContaining('تمت الموافقة على 2'))
  })

  it('bulk reject stays disabled until a reason is written, then sends it', async () => {
    renderPage()
    fireEvent.click(await screen.findByLabelText('تحديد سلفة منى'))
    const reject = screen.getByRole('button', { name: /رفض المحدد/ })
    expect(reject.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('ملاحظة للقرار الجماعي'), { target: { value: 'تجاوز الحد' } })
    expect(reject.disabled).toBe(false)
    fireEvent.click(reject)
    await waitFor(() => expect(approvalsApi.decide).toHaveBeenCalledWith(2, { decision: 'rejected', notes: 'تجاوز الحد' }))
  })

  it('a refused row stays ticked with its reason', async () => {
    approvalsApi.decide.mockImplementation(id => (id === 2
      ? Promise.reject({ response: { status: 400, data: { detail: 'لا يمكن اعتماد طلبك بنفسك.' } } })
      : Promise.resolve({ data: {} })))
    renderPage()
    fireEvent.click(await screen.findByLabelText('تحديد الكل'))
    fireEvent.click(screen.getByRole('button', { name: /موافقة على المحدد \(3\)/ }))
    const result = await screen.findByTestId('approvals-bulk-result')
    expect(result.textContent).toContain('تعذّر 1')
    expect(result.textContent).toContain('سلفة منى — لا يمكن اعتماد طلبك بنفسك.')
    expect(screen.getByLabelText('تحديد سلفة منى').checked).toBe(true)
    expect(screen.getByLabelText('تحديد إجازة أحمد').checked).toBe(false)
  })

  it('keyboard: ↓ Space ticks, Ctrl+A ticks all, Enter opens the decision and Enter confirms', async () => {
    renderPage()
    await screen.findByLabelText('تحديد إجازة أحمد')
    const grid = screen.getByTestId('approvals-grid')
    grid.focus()
    fireEvent.keyDown(grid, { code: 'ArrowDown' })
    fireEvent.keyDown(grid, { code: 'Space' })
    const rowsChecked = () => ROWS.map(r => screen.getByLabelText(`تحديد ${r.title}`).checked)
    expect(rowsChecked().filter(Boolean)).toHaveLength(1)
    fireEvent.keyDown(grid, { code: 'KeyA', ctrlKey: true })
    expect(rowsChecked()).toEqual([true, true, true])

    fireEvent.keyDown(grid, { code: 'Enter' })
    const dialog = await screen.findByRole('dialog', { name: 'اتخاذ قرار' })
    const confirm = within(dialog).getByRole('button', { name: 'تأكيد القرار' })
    expect(document.activeElement).toBe(confirm)
    fireEvent.click(confirm)
    await waitFor(() => expect(approvalsApi.decide).toHaveBeenCalledTimes(1))
    expect(approvalsApi.decide.mock.calls[0][1]).toEqual({ decision: 'approved', notes: '' })
  })

  it('Esc closes the decision window without deciding', async () => {
    renderPage()
    fireEvent.click((await screen.findAllByRole('button', { name: 'اتخاذ قرار' }))[0])
    const dialog = screen.getByRole('dialog', { name: 'اتخاذ قرار' })
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(approvalsApi.decide).not.toHaveBeenCalled()
  })

  it('history has no ticks and no bulk bar', async () => {
    approvalsApi.requests.mockResolvedValue({ data: { results: [{ ...ROWS[0], status: 'approved' }] } })
    renderPage()
    await screen.findByLabelText('تحديد إجازة أحمد')
    fireEvent.click(screen.getByRole('button', { name: 'السجل' }))
    await screen.findByText('موافق عليه')
    expect(screen.queryByTestId('approvals-bulk-bar')).toBeNull()
    expect(screen.queryByLabelText('تحديد إجازة أحمد')).toBeNull()
  })
})
