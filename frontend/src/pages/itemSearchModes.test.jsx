// S3 Task 4 — call sites hand ItemSearchWidget their selection mode, and a `multi` site turns
// the ONE onSelect(items[]) into its own per-item add (with its own dedupe).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// a stand-in widget: shows its mode and exposes its onSelect so a test can "pick"
const widget = vi.hoisted(() => ({ props: [] }))
vi.mock('../components/ItemSearchWidget', () => ({
  default: (props) => {
    widget.props.push(props)
    return <div data-testid="item-box" data-mode={props.mode || 'single'} />
  },
}))
vi.mock('../api/client', () => ({
  default: { get: vi.fn() },
  offersApi: {},
  transfersApi: { create: vi.fn(), submit: vi.fn() },
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [] })) },
}))
vi.mock('../store/authStore', () => ({ default: () => ({ user: { role: 'pharmacist', branch_id: 3 } }) }))
vi.mock('../components/PhoneAlertToggle', () => ({ default: () => null }))
vi.mock('../components/ui', () => ({ useToast: () => () => {} }))

const { ItemPick } = await import('./OffersPage')
const { default: MobileNewTransferPage } = await import('./mobile/MobileNewTransferPage')

const lastOnSelect = () => widget.props[widget.props.length - 1].onSelect
const A = { id: 1, item_id: 1, softech_id: '101', name: 'ALPHA' }
const B = { id: 2, item_id: 2, softech_id: '102', name: 'BETA' }
const C = { id: 3, item_id: 3, softech_id: '103', name: 'GAMMA' }

describe('offers item scope (multi)', () => {
  afterEach(() => { cleanup(); widget.props = [] })

  it('opens the box in multi mode and adds every ticked item in one change', () => {
    const onChange = vi.fn()
    render(<ItemPick label="x" value={[]} onChange={onChange} />)
    expect(screen.getByTestId('item-box').dataset.mode).toBe('multi')
    act(() => lastOnSelect()([A, B, A]))         // A twice: deduped
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith([1, 2])
  })

  it('skips items already in scope and keeps the existing ones', () => {
    const onChange = vi.fn()
    render(<ItemPick label="x" value={[1]} onChange={onChange} />)
    act(() => lastOnSelect()([A, C]))
    expect(onChange).toHaveBeenCalledWith([1, 3])
  })

  it('the gift item (single) stays single', () => {
    const onChange = vi.fn()
    render(<ItemPick label="x" value={[]} onChange={onChange} single />)
    expect(screen.getByTestId('item-box').dataset.mode).toBe('single')
    act(() => lastOnSelect()(B))
    expect(onChange).toHaveBeenCalledWith([2])
  })
})

describe('mobile new transfer (list)', () => {
  afterEach(() => { cleanup(); widget.props = [] })

  it('opens the box in list mode; two picks make two lines, a repeat adds none', () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><MobileNewTransferPage /></MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByTestId('item-box').dataset.mode).toBe('list')
    act(() => lastOnSelect()(A))
    act(() => lastOnSelect()(B))
    act(() => lastOnSelect()(A))
    expect(screen.getByText('ALPHA')).toBeTruthy()
    expect(screen.getByText('BETA')).toBeTruthy()
    expect(screen.getAllByText(/^كود:/)).toHaveLength(2)
  })
})
