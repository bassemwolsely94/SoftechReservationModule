import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...a) => get(...a) },
  itemsApi: { wildcardSearch: vi.fn() },
}))
vi.mock('./AdvancedItemSearchModal', () => ({ default: () => <div>ADV-MODAL</div> }))
vi.mock('./BarcodeScanner', () => ({ default: () => null, cameraAvailable: () => false }))

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
  beforeEach(() => get.mockReset())
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
})
