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
})
