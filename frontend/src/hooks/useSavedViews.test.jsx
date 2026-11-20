// C23 — saved views: only known keys are applied, the default applies once, saves send known keys only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  personalApi: { savedViews: vi.fn(), createSavedView: vi.fn(), updateSavedView: vi.fn(), deleteSavedView: vi.fn() },
}))
const { personalApi } = await import('../api/client')
const { default: useSavedViews, pickKnown, defaultView } = await import('./useSavedViews')
const { default: SavedViewsMenu } = await import('../components/SavedViewsMenu')

const KEYS = ['branch', 'action']
const VIEWS = [
  { id: 1, name: 'فرعي', filters: { branch: ['101'], action: 'move', evil: 1 }, is_default: true, mine: true, shared: false },
  { id: 2, name: 'مشترك', filters: { branch: ['102'] }, is_default: false, mine: false, shared: true, owner_name: 'منى' },
]

function wrapper({ children }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  personalApi.savedViews.mockResolvedValue({ data: { results: VIEWS } })
  personalApi.createSavedView.mockResolvedValue({ data: { id: 9, name: 'جديد' } })
  personalApi.updateSavedView.mockResolvedValue({ data: {} })
  personalApi.deleteSavedView.mockResolvedValue({})
})
afterEach(cleanup)

describe('helpers', () => {
  it('pickKnown keeps only the screen keys', () => {
    expect(pickKnown({ branch: [1], evil: 2 }, KEYS)).toEqual({ branch: [1] })
    expect(pickKnown(null, KEYS)).toEqual({})
  })
  it('the default is only ever one of my own views', () => {
    expect(defaultView(VIEWS).id).toBe(1)
    expect(defaultView([{ ...VIEWS[1], is_default: true }])).toBeNull()
  })
})

describe('useSavedViews', () => {
  it('applies the default once, with unknown keys dropped', async () => {
    const applyFilters = vi.fn()
    const { result, rerender } = renderHook(
      () => useSavedViews('batches.near_expiry', { keys: KEYS, getFilters: () => ({}), applyFilters }), { wrapper })
    await waitFor(() => expect(applyFilters).toHaveBeenCalledTimes(1))
    expect(applyFilters).toHaveBeenCalledWith({ branch: ['101'], action: 'move' })
    expect(result.current.activeId).toBe(1)
    rerender()
    expect(applyFilters).toHaveBeenCalledTimes(1)
  })

  it('saves only the screen keys of the current filters', async () => {
    const { result } = renderHook(() => useSavedViews('batches.near_expiry', {
      keys: KEYS, getFilters: () => ({ branch: ['103'], action: '', secret: 'x' }), applyFilters: () => {} }), { wrapper })
    await act(() => result.current.save({ name: 'جديد', isDefault: true, shared: true }))
    expect(personalApi.createSavedView).toHaveBeenCalledWith({
      screen: 'batches.near_expiry', name: 'جديد', filters: { branch: ['103'], action: '' }, is_default: true, shared: true })
  })

  it('shows the server refusal', async () => {
    personalApi.createSavedView.mockRejectedValueOnce({ response: { data: { detail: 'يوجد عرض بنفس الاسم.' } } })
    const { result } = renderHook(() => useSavedViews('transits', { keys: KEYS, getFilters: () => ({}), applyFilters: () => {} }), { wrapper })
    await act(() => result.current.save({ name: 'x' }))
    expect(result.current.error).toBe('يوجد عرض بنفس الاسم.')
  })
})

describe('SavedViewsMenu', () => {
  function Harness({ applyFilters }) {
    const sv = useSavedViews('batches.near_expiry', { keys: KEYS, getFilters: () => ({}), applyFilters })
    return <SavedViewsMenu sv={sv} />
  }
  it('lists views, applies a shared one, and deletes only on the second press', async () => {
    const applyFilters = vi.fn()
    render(<Harness applyFilters={applyFilters} />, { wrapper })
    await waitFor(() => expect(applyFilters).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('saved-views-button'))
    expect(screen.getByText('منى')).toBeTruthy()
    fireEvent.click(screen.getByText('مشترك'))
    expect(applyFilters).toHaveBeenLastCalledWith({ branch: ['102'] })
    fireEvent.click(screen.getByTestId('saved-views-button'))
    const del = screen.getByLabelText('حذف')                      // only my own view has actions
    fireEvent.click(del)
    expect(personalApi.deleteSavedView).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('حذف'))
    await waitFor(() => expect(personalApi.deleteSavedView).toHaveBeenCalledWith(1))
  })
})
