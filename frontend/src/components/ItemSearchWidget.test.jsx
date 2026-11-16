import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...a) => get(...a) },
  itemsApi: { wildcardSearch: vi.fn() },
}))
vi.mock('./AdvancedItemSearchModal', () => ({ default: () => <div>ADV-MODAL</div> }))
const cam = vi.hoisted(() => ({ on: false, code: '555' }))
vi.mock('./BarcodeScanner', () => ({
  default: ({ onScan }) => <button onClick={() => onScan(cam.code)}>FAKE-SCAN</button>,
  cameraAvailable: () => cam.on,
}))
vi.mock('../hooks/useFeatures', () => ({ default: () => ({ cameraScan: cam.on }) }))

import ItemSearchWidget from './ItemSearchWidget'

const rows = [
  { id: 1, softech_id: '101', name: 'ALPHA ONE', pack_price: '10', total_stock: 5, tier: 'exact' },
  { id: 2, softech_id: '102', name: 'ALPHA TWO', pack_price: '12', total_stock: 0, tier: 'exact' },
  { id: 3, softech_id: '103', name: 'ALPHA THREE', pack_price: '14', total_stock: 3, tier: 'exact' },
]

function setup(props = {}, data = rows) {
  get.mockResolvedValue({ data: { results: data } })
  const onSelect = props.onSelect || vi.fn()
  const utils = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ItemSearchWidget onSelect={onSelect} {...props} />
    </QueryClientProvider>,
  )
  return { onSelect, ...utils }
}

async function type(text) {
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: text } })
  return input
}

describe('ItemSearchWidget default variant on the engine', () => {
  beforeEach(() => { get.mockReset(); cam.on = false; cam.code = '555' })
  afterEach(cleanup)

  it('keeps wildcards and asks for rank=engine', async () => {
    setup()
    await type('vol*50')
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(get).toHaveBeenCalledWith('/items/', { params: { search: 'vol*50', rank: 'engine', page_size: 10 } })
  })

  it('arrow keys move, clamp, and Enter selects the highlighted row', async () => {
    const { onSelect } = setup()
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })   // clamped at the last row
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0]).toBe(rows[2])
  })

  it('Up at the top stays on the first row', async () => {
    const { onSelect } = setup()
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect.mock.calls[0][0]).toBe(rows[0])
  })

  it('Enter with no results selects nothing and does not submit the form', async () => {
    const onSubmit = vi.fn(e => e.preventDefault())
    get.mockResolvedValue({ data: { results: [] } })
    const onSelect = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <form onSubmit={onSubmit}><ItemSearchWidget onSelect={onSelect} /></form>
      </QueryClientProvider>,
    )
    const input = await type('zzzz')
    await screen.findByText(/لا توجد نتائج/)
    const notPrevented = fireEvent.keyDown(input, { key: 'Enter' })
    expect(notPrevented).toBe(false)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('Esc closes the list', async () => {
    setup()
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByText(/THREE/)).toBeNull()
  })

  it('shows the tier chip for an approximate row', async () => {
    setup({}, [{ ...rows[0], tier: 'approx', approx: true }])
    await type('alpa')
    expect(await screen.findByText('تقريبي')).toBeTruthy()
  })

  it('selected card is unchanged and Ctrl+F1 opens the modal', () => {
    setup({ selected: { id: 9, name: 'CHOSEN', softech_id: '9' } })
    expect(screen.getByText(/تغيير/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'F1', ctrlKey: true })
    expect(screen.getByText('ADV-MODAL')).toBeTruthy()
  })

  it('onSelect gets the row exactly as the API returned it', async () => {
    const { onSelect } = setup()
    await type('alpha')
    const el = await screen.findByText(/TWO/)
    fireEvent.mouseDown(el)
    expect(onSelect.mock.calls[0][0]).toBe(rows[1])
  })

  it('Enter on stale rows (new query not answered yet) selects nothing', async () => {
    const { onSelect } = setup()
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    get.mockReturnValue(new Promise(() => {}))   // the next query never answers
    await type('alphb')
    const notPrevented = fireEvent.keyDown(input, { key: 'Enter' })
    expect(notPrevented).toBe(false)
    expect(onSelect).not.toHaveBeenCalled()
  })

  async function scan(row) {
    cam.on = true
    const { onSelect } = setup({}, [row])
    fireEvent.click(screen.getByTitle('مسح الباركود بالكاميرا'))
    fireEvent.click(screen.getByText('FAKE-SCAN'))
    await waitFor(() => expect(get).toHaveBeenCalled())
    await screen.findByText(/ALPHA ONE/)
    return onSelect
  }

  it('a scan resolving to one approx row is not auto-selected', async () => {
    const onSelect = await scan({ ...rows[0], tier: 'approx', approx: true })
    await new Promise(r => setTimeout(r, 50))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it("a scan equal to the row's code is auto-selected", async () => {
    const row = { ...rows[0], softech_id: '555', tier: 'code' }
    cam.on = true
    const { onSelect } = setup({}, [row])
    fireEvent.click(screen.getByTitle('مسح الباركود بالكاميرا'))
    fireEvent.click(screen.getByText('FAKE-SCAN'))
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(row))
  })

  it("a scan equal to the row's barcode in another case is auto-selected", async () => {
    cam.code = 'abc555'
    const row = { ...rows[0], barcode: 'ABC555', tier: 'code' }
    cam.on = true
    const { onSelect } = setup({}, [row])
    fireEvent.click(screen.getByTitle('مسح الباركود بالكاميرا'))
    fireEvent.click(screen.getByText('FAKE-SCAN'))
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(row))
  })

  it("a scan whose digits only start one row's code (code_prefix) is not auto-selected", async () => {
    const onSelect = await scan({ ...rows[0], softech_id: '5551', tier: 'code_prefix', code_prefix: true })
    expect(screen.getByText('بداية الكود')).toBeTruthy()
    await new Promise(r => setTimeout(r, 50))
    expect(onSelect).not.toHaveBeenCalled()
  })
})
