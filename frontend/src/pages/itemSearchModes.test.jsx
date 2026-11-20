// S3 Task 4 — call sites hand ItemSearchWidget their selection mode, and a `multi` site turns
// the ONE onSelect(items[]) into its own per-item add (with its own dedupe).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  catalogIntelApi: {
    bundles: vi.fn(() => Promise.resolve({ data: [
      { id: 9, name: 'BOX', discount_type: 'none', is_active: true,
        items: [{ id: 50, item: 1, item_name: 'ALPHA', quantity: 1 }] },
      { id: 10, name: 'CASE', discount_type: 'none', is_active: true, items: [] },
    ] })),
    addBundleItem: vi.fn(() => Promise.resolve({ data: {} })),
  },
  recommendationsApi: {},
  enrichmentApi: {},
  vouchersApi: { create: vi.fn(() => Promise.resolve({ data: { id: 77 } })) },
  customersApi: {},
  transfersApi: { create: vi.fn(), submit: vi.fn() },
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [] })) },
}))
vi.mock('../store/authStore', () => ({ default: () => ({ user: { role: 'pharmacist', branch_id: 3 } }) }))
vi.mock('../components/PhoneAlertToggle', () => ({ default: () => null }))
vi.mock('../components/ui', () => ({ useToast: () => () => {} }))
vi.mock('../components/CustomerSearchWidget', () => ({ default: () => null }))
vi.mock('./vouchers/GiftCouponsTab', () => ({ default: () => null }))

const { ItemPick } = await import('./OffersPage')
const { default: MobileNewTransferPage } = await import('./mobile/MobileNewTransferPage')
const { BundlesTab } = await import('./CatalogIntelligencePage')
const { CreateVoucherModal } = await import('./VouchersPage')
const { catalogIntelApi, vouchersApi } = await import('../api/client')
const { default: usePermissionStore } = await import('../store/permissionStore')

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

const withClient = (ui) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>
)

// let queued mutations, promise callbacks and React updates run to the end before asserting
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 50)) })

describe('catalog-intelligence bundle items (multi)', () => {
  // adding items is a catalog edit (final review I4: the controls follow the grant)
  beforeEach(() => usePermissionStore.setState({ permissions: { catalog: { view: true, edit: true } }, seeded: ['catalog'] }))
  afterEach(() => {
    cleanup(); widget.props = []
    catalogIntelApi.addBundleItem.mockReset()
    catalogIntelApi.addBundleItem.mockImplementation(() => Promise.resolve({ data: {} }))
  })

  it('POSTs only the new items, once each: an existing member and a repeat are skipped', async () => {
    render(withClient(<BundlesTab />))
    fireEvent.click(await screen.findByText('BOX'))
    expect(screen.getByTestId('item-box').dataset.mode).toBe('multi')
    act(() => lastOnSelect()([A, B, C, B]))      // A is already in the bundle; B is picked twice
    await waitFor(() => expect(catalogIntelApi.addBundleItem).toHaveBeenCalledTimes(2))
    await settle()
    expect(catalogIntelApi.addBundleItem).toHaveBeenCalledTimes(2)
    expect(catalogIntelApi.addBundleItem.mock.calls).toEqual([
      [9, { item: 2, quantity: 1 }],
      [9, { item: 3, quantity: 1 }],
    ])
  })

  it('a batch of existing members only sends nothing', async () => {
    render(withClient(<BundlesTab />))
    fireEvent.click(await screen.findByText('BOX'))
    act(() => lastOnSelect()([A, A]))
    await settle()
    expect(catalogIntelApi.addBundleItem).not.toHaveBeenCalled()
  })

  it('a failed add shows its error on that bundle only', async () => {
    catalogIntelApi.addBundleItem.mockImplementation(() => Promise.reject(new Error('boom')))
    render(withClient(<BundlesTab />))
    fireEvent.click(await screen.findByText('BOX'))
    act(() => lastOnSelect()([B]))
    expect(await screen.findByText(/تعذّرت إضافة «BETA»/)).toBeTruthy()
    fireEvent.click(screen.getByText('CASE'))      // another bundle
    await settle()
    expect(screen.queryByText(/تعذّرت إضافة/)).toBeNull()
    fireEvent.click(screen.getByText('BOX'))       // back: the error belongs to BOX
    expect(await screen.findByText(/تعذّرت إضافة «BETA»/)).toBeTruthy()
  })
})

describe('voucher eligible items (multi)', () => {
  afterEach(() => { cleanup(); widget.props = []; vouchersApi.create.mockClear() })

  it('adds only new items, once each, to applicable_items', async () => {
    render(withClient(<CreateVoucherModal onClose={() => {}} onCreate={() => {}} />))
    expect(screen.getByTestId('item-box').dataset.mode).toBe('multi')
    act(() => lastOnSelect()([A]))
    act(() => lastOnSelect()([B, A, B, C]))      // A already applicable; B twice in the batch
    fireEvent.change(screen.getByPlaceholderText(/مثال: خصم/), { target: { value: 'T' } })
    fireEvent.click(screen.getByText('✓ إنشاء القسيمة'))
    await waitFor(() => expect(vouchersApi.create).toHaveBeenCalledTimes(1))
    expect(vouchersApi.create.mock.calls[0][0].applicable_items).toEqual([1, 2, 3])
  })
})

describe('catalog-intelligence bundles for a view-only role (final review I4)', () => {
  beforeEach(() => usePermissionStore.setState({ permissions: { catalog: { view: true } }, seeded: ['catalog'] }))
  afterEach(() => { cleanup(); widget.props = [] })

  it('reads the bundle without the add / remove / new controls', async () => {
    render(withClient(<BundlesTab />))
    fireEvent.click(await screen.findByText('BOX'))
    await settle()
    expect(widget.props.length).toBe(0)
    expect(document.querySelector('[data-tour="catalog-intelligence-bundle-new"]')).toBeNull()
    expect(document.querySelector('[data-tour="catalog-intelligence-bundle-remove-item"]')).toBeNull()
  })
})
