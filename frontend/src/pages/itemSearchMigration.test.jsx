// S3 Task 5 — the old ItemSearchInput sites now use ItemSearchWidget. Only how the item is
// found changes: every save call and its payload stay exactly as before.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// a stand-in widget: shows its mode / exactCodeOnly and exposes its onSelect so a test can "pick"
const widget = vi.hoisted(() => ({ props: [] }))
vi.mock('../components/ItemSearchWidget', () => ({
  default: (props) => {
    widget.props.push(props)
    return <div data-testid="item-box" data-mode={props.mode || 'single'}
                data-exact={props.exactCodeOnly ? '1' : '0'} />
  },
}))
vi.mock('../api/client', () => ({
  default: { get: vi.fn() },
  invoicesApi: {
    lineMatches: vi.fn(() => Promise.resolve({ data: [] })),
    updateLine: vi.fn(() => Promise.resolve({ data: {} })),
    learnMapping: vi.fn(() => Promise.resolve({ data: {} })),
  },
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [] })) },
  replacementApi: {
    get: vi.fn(), patientSales: vi.fn(() => Promise.resolve({ data: { results: [] } })),
    create: vi.fn(),
  },
  insuranceApi: {
    itemOverrideLookup: vi.fn(() => Promise.resolve({ data: { found: true, item_name: 'NEW', pack_price: 12, current_category: 'local' } })),
    editLine: vi.fn(() => Promise.resolve({ data: {} })),
    prescriptionLines: vi.fn(() => Promise.resolve({ data: [] })),
  },
}))
vi.mock('../store/authStore', () => ({ default: (sel) => {
  const s = { user: { role: 'pharmacist', branch_id: 3 } }
  return typeof sel === 'function' ? sel(s) : s
} }))

const { InvoiceLineRow } = await import('./InvoicePage')
const { default: ReplacementNewCasePage } = await import('./ReplacementNewCasePage')
const { RxRow } = await import('./InsuranceClaimDetailPage')
const { invoicesApi, insuranceApi } = await import('../api/client')

const lastOnSelect = () => widget.props[widget.props.length - 1].onSelect
const A = { id: 1, item_id: 1, softech_id: '101', name: 'ALPHA', pack_price: 10 }
const B = { id: 2, item_id: 2, softech_id: '102', name: 'BETA', pack_price: 20 }
const C = { id: 3, item_id: 3, softech_id: '103', name: 'GAMMA', pack_price: 30 }

const withClient = (ui) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>
)

describe('invoice line re-match (single)', () => {
  afterEach(() => { cleanup(); widget.props = []; invoicesApi.updateLine.mockClear() })

  it('a pick sends updateLine(..., {item: <id>, is_confirmed: true}) exactly as before', async () => {
    const line = { id: 55, raw_name: 'X', quantity: 1 }
    render(<InvoiceLineRow line={line} invoiceId={7} editable onUpdated={() => {}}
                           onDelete={() => {}} onNotify={() => {}} openReq={{ id: 55 }} />)
    const box = await screen.findByTestId('item-box')
    expect(box.dataset.mode).toBe('single')
    await act(async () => { await lastOnSelect()(B) })
    expect(invoicesApi.updateLine).toHaveBeenCalledTimes(1)
    expect(invoicesApi.updateLine).toHaveBeenCalledWith(7, 55, { item: 2, is_confirmed: true })
  })
})

describe('replacement new case — extra items (multi)', () => {
  afterEach(() => { cleanup(); widget.props = [] })

  it('ticking 2 adds 2 rows; a repeat inside or across batches adds none', () => {
    render(withClient(<ReplacementNewCasePage />))
    const box = screen.getByTestId('item-box')
    expect(box.dataset.mode).toBe('multi')
    act(() => lastOnSelect()([A, B, A]))        // A twice in one batch
    expect(screen.getByText('ALPHA')).toBeTruthy()
    expect(screen.getByText('BETA')).toBeTruthy()
    act(() => lastOnSelect()([B, C]))           // B already in the list
    expect(screen.getAllByText('ALPHA')).toHaveLength(1)
    expect(screen.getAllByText('BETA')).toHaveLength(1)
    expect(screen.getByText('GAMMA')).toBeTruthy()
    expect(screen.getAllByText('حذف')).toHaveLength(3)
  })
})

describe('insurance claim line re-code (single, name box)', () => {
  afterEach(() => {
    cleanup(); widget.props = []
    insuranceApi.itemOverrideLookup.mockClear(); insuranceApi.editLine.mockClear()
  })

  const rx = { id: 9, sequence: 1, lines: [
    { id: 5, softech_itemcode: '111', item_name: 'OLD', quantity: 1, unit_price: 10, line_total: 10,
      discount_amt: 0, discount_pct: 0, net_amount: 10 },
  ] }
  const openEditor = () => {
    render(<table><tbody>
      <RxRow rx={rx} claimId={4} discPcts={{}} onRefresh={() => {}} />
    </tbody></table>)
    fireEvent.click(screen.getByText(/بنود/))
    fireEvent.click(screen.getByText(/تفعيل تعديل البنود/))
  }

  it('a pick fills the code and runs the same lookup as «بحث»; the save payload is unchanged', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    openEditor()
    expect(screen.queryByTestId('item-box')).toBeNull()      // closed until «بالاسم» on this line
    fireEvent.click(screen.getByText('بالاسم'))
    const box = screen.getByTestId('item-box')
    expect(box.dataset.mode).toBe('single')
    expect(box.dataset.exact).toBe('0')       // Enter picks the highlighted row like every name box
    await act(async () => { lastOnSelect()(B) })
    expect(insuranceApi.itemOverrideLookup).toHaveBeenCalledWith('102')
    expect(screen.getByDisplayValue('102')).toBeTruthy()
    expect(screen.queryByTestId('item-box')).toBeNull()      // the box closes after the pick
    fireEvent.click(screen.getByText('حفظ'))
    await waitFor(() => expect(insuranceApi.editLine).toHaveBeenCalledTimes(1))
    expect(insuranceApi.editLine).toHaveBeenCalledWith(4, 9, 5, { item_code: '102', unit_price: 12 })
  })

  it('typing a code by hand + «بحث» still works and saves the same shape', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    openEditor()
    fireEvent.change(screen.getByDisplayValue('111'), { target: { value: '102' } })
    await act(async () => { fireEvent.click(screen.getByText('بحث')) })
    expect(insuranceApi.itemOverrideLookup).toHaveBeenCalledWith('102')
    fireEvent.click(screen.getByText('حفظ'))
    await waitFor(() => expect(insuranceApi.editLine).toHaveBeenCalledTimes(1))
    expect(insuranceApi.editLine).toHaveBeenCalledWith(4, 9, 5, { item_code: '102', unit_price: 12 })
  })

  describe('price follows the looked-up item unless typed by hand', () => {
    const priceOf = (code) => ({ found: true, item_name: 'N' + code, pack_price: code === 'A' ? 20 : 30, current_category: 'local' })
    const lookup = async (code) => {
      insuranceApi.itemOverrideLookup.mockImplementationOnce(() => Promise.resolve({ data: priceOf(code) }))
      fireEvent.change(screen.getByPlaceholderText('كود جديد'), { target: { value: code } })
      await act(async () => { fireEvent.click(screen.getByText('بحث')) })
    }
    const save = async () => {
      fireEvent.click(screen.getByText('حفظ'))
      await waitFor(() => expect(insuranceApi.editLine).toHaveBeenCalledTimes(1))
    }

    it('A then B (no typing) saves the pack price of B', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      openEditor()
      await lookup('A'); await lookup('B')
      await save()
      expect(insuranceApi.editLine).toHaveBeenCalledWith(4, 9, 5, { item_code: 'B', unit_price: 30 })
    })

    it('A, typed price 15, then B keeps 15', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      openEditor()
      await lookup('A')
      fireEvent.change(screen.getByDisplayValue('20'), { target: { value: '15' } })
      await lookup('B')
      await save()
      expect(insuranceApi.editLine).toHaveBeenCalledWith(4, 9, 5, { item_code: 'B', unit_price: '15' })
    })

    it('A, typed 15, look up A again keeps 15', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      openEditor()
      await lookup('A')
      fireEvent.change(screen.getByDisplayValue('20'), { target: { value: '15' } })
      await lookup('A')
      await save()
      expect(insuranceApi.editLine).toHaveBeenCalledWith(4, 9, 5, { item_code: 'A', unit_price: '15' })
    })
  })
})
