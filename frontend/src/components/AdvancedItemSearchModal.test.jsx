import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const get = vi.fn()
vi.mock('../api/client', () => ({ default: { get: (...a) => get(...a) } }))

import AdvancedItemSearchModal from './AdvancedItemSearchModal'

const rows = [
  { id: 1, softech_id: '101', name: 'ALPHA ONE', pack_price: '10', unit_price: '1', total_stock: 5,
    tier: 'exact' },
  { id: 2, softech_id: '102', name: 'ALPHA TWO', pack_price: '12', unit_price: '2', total_stock: 0,
    tier: 'sound', sound: true },
]

function setup() {
  get.mockImplementation((url = '') => Promise.resolve({
    data: url.includes('filter-options') ? {} : { count: rows.length, results: rows },
  }))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdvancedItemSearchModal onSelect={vi.fn()} onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

const itemCalls = () => get.mock.calls.filter(([u]) => u === '/items/')
const lastItemParams = () => itemCalls().at(-1)[1].params

async function search(text) {
  const box = screen.getByPlaceholderText(/urosolv/)
  if (text) fireEvent.change(box, { target: { value: text } })
  fireEvent.click(screen.getByText('بحث'))
  await waitFor(() => expect(itemCalls().length).toBeGreaterThan(0))
}

describe('AdvancedItemSearchModal on the engine', () => {
  beforeEach(() => get.mockReset())
  afterEach(cleanup)

  it('sends rank engine when text typed, and not otherwise', async () => {
    setup()
    await search('alpha')
    expect(lastItemParams().rank).toBe('engine')
    expect(lastItemParams().search).toBe('alpha')

    cleanup(); get.mockReset(); setup()
    await search('')
    expect(lastItemParams()).not.toHaveProperty('rank')
  })

  it('one character (wildcards not counted) keeps the plain search, without rank', async () => {
    setup()
    await search('a')
    expect(lastItemParams().search).toBe('a')
    expect(lastItemParams()).not.toHaveProperty('rank')

    cleanup(); get.mockReset(); setup()
    await search('*a%')
    expect(lastItemParams()).not.toHaveProperty('rank')

    cleanup(); get.mockReset(); setup()
    await search('ab')
    expect(lastItemParams().rank).toBe('engine')
  })

  it('shows the tier chip in the results name cell', async () => {
    setup()
    await search('alpha')
    expect(await screen.findByText('بالنطق')).toBeTruthy()
  })

  it('sends no ordering until a column header is clicked, then sends it', async () => {
    setup()
    await search('alpha')
    expect(lastItemParams()).not.toHaveProperty('ordering')
    fireEvent.click(await screen.findByText('سعر العبوة'))
    await waitFor(() => expect(lastItemParams().ordering).toBe('pack_price'))
  })

  it('helper text matches the engine rules', () => {
    setup()
    expect(document.body.textContent).not.toContain('بالاسم فقط')
    expect(document.body.textContent).toContain('أقرب نتيجة أولاً')
  })
})

describe('AdvancedItemSearchModal pick modes', () => {
  beforeEach(() => get.mockReset())
  afterEach(cleanup)

  function mount(props) {
    get.mockImplementation((url = '') => Promise.resolve({
      data: url.includes('filter-options') ? {} : { count: rows.length, results: rows },
    }))
    const onSelect = vi.fn()
    const onClose = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AdvancedItemSearchModal onSelect={onSelect} onClose={onClose} {...props} />
      </QueryClientProvider>,
    )
    return { onSelect, onClose }
  }

  it('without multi: a row click picks one item and closes, no checkboxes', async () => {
    const { onSelect, onClose } = mount()
    await search('alpha')
    fireEvent.click(await screen.findByText(/TWO/))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0]).toMatchObject({ id: 2, item_id: 2 })
    expect(onClose).toHaveBeenCalled()
    cleanup()
    mount()
    await search('alpha')
    await screen.findByText(/TWO/)
    expect(screen.queryByText(/إضافة المحدد/)).toBeNull()
    expect(screen.queryAllByLabelText(/تحديد/)).toHaveLength(0)
  })

  it('with multi: tick 2, the add button sends one array of 2', async () => {
    const { onSelect, onClose } = mount({ multi: true })
    await search('alpha')
    await screen.findByText(/TWO/)
    const boxes = screen.getAllByLabelText(/تحديد/)
    fireEvent.click(boxes[0])
    fireEvent.click(boxes[1])
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('إضافة المحدد (2)'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    const items = onSelect.mock.calls[0][0]
    expect(items.map(i => i.id)).toEqual([1, 2])
    for (const it of items) expect(it.item_id).toBe(it.id)
    expect(onClose).toHaveBeenCalled()
  })

  it('with multi: a row click ticks instead of picking', async () => {
    const { onSelect } = mount({ multi: true })
    await search('alpha')
    fireEvent.click(await screen.findByText(/ONE/))
    expect(onSelect).not.toHaveBeenCalled()
    expect(screen.getByText('إضافة المحدد (1)')).toBeTruthy()
  })

  it('with multi: Space ticks the focused row in the grid, Enter adds', async () => {
    const { onSelect } = mount({ multi: true })
    await search('alpha')
    await screen.findByText(/TWO/)
    const grid = screen.getByTestId('adv-results')
    grid.focus()
    fireEvent.keyDown(grid, { key: 'ArrowDown', code: 'ArrowDown' })
    fireEvent.keyDown(grid, { key: ' ', code: 'Space' })
    fireEvent.keyDown(grid, { key: 'ArrowDown', code: 'ArrowDown' })
    fireEvent.keyDown(grid, { key: ' ', code: 'Space' })
    expect(screen.getByText('إضافة المحدد (2)')).toBeTruthy()
    fireEvent.keyDown(grid, { key: 'Enter', code: 'Enter' })
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0].map(i => i.id)).toEqual([1, 2])
  })

  it('with multi: Space typed in the search box types and ticks nothing', async () => {
    mount({ multi: true })
    await search('alpha')
    await screen.findByText(/TWO/)
    const box = screen.getByPlaceholderText(/urosolv/)
    fireEvent.keyDown(box, { key: 'ArrowDown', code: 'ArrowDown' })
    const notPrevented = fireEvent.keyDown(box, { key: ' ', code: 'Space' })
    expect(notPrevented).toBe(true)
    expect(screen.getByText('إضافة المحدد (0)')).toBeTruthy()
  })
})
