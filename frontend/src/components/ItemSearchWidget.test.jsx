import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...a) => get(...a) },
  itemsApi: { wildcardSearch: vi.fn() },
}))
vi.mock('./AdvancedItemSearchModal', () => ({
  default: ({ multi, onSelect }) => (
    <div>
      <span>ADV-MODAL</span>
      {multi && <span>MODAL-MULTI</span>}
      <button onClick={() => onSelect(multi ? [{ id: 7, name: 'M7' }, { id: 8, name: 'M8' }] : { id: 7, name: 'M7' })}>
        MODAL-PICK
      </button>
    </div>
  ),
}))
const cam = vi.hoisted(() => ({ on: false, code: '555' }))
vi.mock('./BarcodeScanner', () => ({
  default: ({ onScan }) => <button onClick={() => onScan(cam.code)}>FAKE-SCAN</button>,
  cameraAvailable: () => cam.on,
}))
vi.mock('../hooks/useFeatures', () => ({ default: () => ({ cameraScan: cam.on }) }))

import ItemSearchWidget from './ItemSearchWidget'
import ItemSearchHotkeyProvider from './ItemSearchHotkeyProvider'

const rows = [
  { id: 1, softech_id: '101', name: 'ALPHA ONE', pack_price: '10', total_stock: 5, tier: 'exact' },
  { id: 2, softech_id: '102', name: 'ALPHA TWO', pack_price: '12', total_stock: 0, tier: 'exact' },
  { id: 3, softech_id: '103', name: 'ALPHA THREE', pack_price: '14', total_stock: 3, tier: 'exact' },
]

const withId = r => ({ ...r, item_id: r.id })

function setup(props = {}, data = rows) {
  get.mockResolvedValue({ data: { results: data } })
  const onSelect = props.onSelect || vi.fn()
  const utils = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ItemSearchHotkeyProvider><ItemSearchWidget onSelect={onSelect} {...props} /></ItemSearchHotkeyProvider>
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
    expect(onSelect.mock.calls[0][0]).toEqual(withId(rows[2]))
  })

  it('Up at the top stays on the first row', async () => {
    const { onSelect } = setup()
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect.mock.calls[0][0]).toEqual(withId(rows[0]))
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

  it('onSelect gets the row as the API returned it, plus item_id equal to id', async () => {
    const { onSelect } = setup()
    await type('alpha')
    const el = await screen.findByText(/TWO/)
    fireEvent.mouseDown(el)
    expect(onSelect.mock.calls[0][0]).toEqual(withId(rows[1]))
    expect(onSelect.mock.calls[0][0].item_id).toBe(2)
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
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(withId(row)))
  })

  it("a scan equal to the row's barcode in another case is auto-selected", async () => {
    cam.code = 'abc555'
    const row = { ...rows[0], barcode: 'ABC555', tier: 'code' }
    cam.on = true
    const { onSelect } = setup({}, [row])
    fireEvent.click(screen.getByTitle('مسح الباركود بالكاميرا'))
    fireEvent.click(screen.getByText('FAKE-SCAN'))
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(withId(row)))
  })

  it("a scan whose digits only start one row's code (code_prefix) is not auto-selected", async () => {
    const onSelect = await scan({ ...rows[0], softech_id: '5551', tier: 'code_prefix', code_prefix: true })
    expect(screen.getByText('بداية الكود')).toBeTruthy()
    await new Promise(r => setTimeout(r, 50))
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('ItemSearchWidget modes', () => {
  beforeEach(() => { get.mockReset(); cam.on = false; cam.code = '555' })
  afterEach(cleanup)

  async function pickByEnter(input, text) {
    fireEvent.change(input, { target: { value: text } })
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'Enter' })
  }

  it('single (default) still shows the selected card', () => {
    setup({ selected: { id: 9, name: 'CHOSEN', softech_id: '9' } })
    expect(screen.getByText('CHOSEN')).toBeTruthy()
  })

  it('list: two picks in a row, box empty and focused after each, stale Enter adds nothing', async () => {
    const { onSelect } = setup({ mode: 'list' })
    const input = screen.getByRole('textbox')
    input.focus()
    await pickByEnter(input, 'alpha')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(input.value).toBe('')
    expect(document.activeElement).toBe(input)
    expect(screen.queryByText(/THREE/)).toBeNull()
    fireEvent.keyDown(input, { key: 'Enter' })        // right after the pick
    expect(onSelect).toHaveBeenCalledTimes(1)
    await pickByEnter(input, 'alph')
    expect(onSelect).toHaveBeenCalledTimes(2)
    expect(input.value).toBe('')
    expect(document.activeElement).toBe(input)
    for (const [it] of onSelect.mock.calls) expect(it.item_id).toBe(it.id)
  })

  it('list: a modal pick also goes to onSelect as one item', () => {
    const { onSelect } = setup({ mode: 'list' })
    fireEvent.keyDown(window, { key: 'F1', ctrlKey: true })
    expect(screen.queryByText('MODAL-MULTI')).toBeNull()
    fireEvent.click(screen.getByText('MODAL-PICK'))
    expect(onSelect).toHaveBeenCalledWith({ id: 7, name: 'M7', item_id: 7 })
  })

  it('multi: a typed space stays in the box and ticks nothing', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'vol' } })
    const notPrevented = fireEvent.keyDown(input, { key: ' ', code: 'Space' })
    expect(notPrevented).toBe(true)
    fireEvent.change(input, { target: { value: 'vol ren' } })
    expect(input.value).toBe('vol ren')
    await screen.findByText(/THREE/)
    expect(screen.getAllByRole('checkbox').every(c => !c.checked)).toBe(true)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('multi: Ctrl+Space ticks two rows, Enter adds them as one array, then clears', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'alpha' } })
    await screen.findByText(/THREE/)
    expect(fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })).toBe(false)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })
    expect(screen.getAllByRole('checkbox').map(c => c.checked)).toEqual([true, false, true])
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledTimes(1)
    const items = onSelect.mock.calls[0][0]
    expect(items.map(i => i.id)).toEqual([1, 3])
    for (const it of items) expect(it.item_id).toBe(it.id)
    expect(input.value).toBe('')
    expect(screen.queryByText(/THREE/)).toBeNull()
  })

  it('multi: Enter with nothing ticked adds the highlighted row as a one-item array', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'alpha' } })
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith([withId(rows[1])])
  })

  it('multi: clicking a row ticks it and the add button sends the ticked rows', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'alpha' } })
    fireEvent.mouseDown(await screen.findByText(/TWO/))
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.mouseDown(screen.getByText('إضافة المحدد (1)'))
    expect(onSelect).toHaveBeenCalledWith([withId(rows[1])])
  })

  it('multi: Ctrl+F1 opens the modal with multi and its array goes to onSelect once', () => {
    const { onSelect } = setup({ mode: 'multi' })
    fireEvent.keyDown(window, { key: 'F1', ctrlKey: true })
    expect(screen.getByText('MODAL-MULTI')).toBeTruthy()
    fireEvent.click(screen.getByText('MODAL-PICK'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0]).toEqual([
      { id: 7, name: 'M7', item_id: 7 }, { id: 8, name: 'M8', item_id: 8 },
    ])
  })

  it('exactCodeOnly: Enter on a code_prefix row picks nothing', async () => {
    const { onSelect } = setup({ exactCodeOnly: true },
      [{ ...rows[0], softech_id: '5551', tier: 'code_prefix', code_prefix: true }])
    const input = await type('555')
    await screen.findByText(/ALPHA ONE/)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).not.toHaveBeenCalled()
    expect(screen.getByText(/ALPHA ONE/)).toBeTruthy()   // still listed for a click
  })

  it('exactCodeOnly: Enter on an exact code row picks it', async () => {
    const row = { ...rows[0], softech_id: '555', tier: 'code' }
    const { onSelect } = setup({ exactCodeOnly: true }, [row])
    const input = await type('555')
    await screen.findByText(/ALPHA ONE/)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(withId(row))
  })

  it('exactCodeOnly: a name row is picked only after the highlight is moved', async () => {
    const { onSelect } = setup({ exactCodeOnly: true })
    const input = await type('alpha')
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(withId(rows[1]))
  })

  it('multi: Ctrl+F1 modal items merge with inline ticks (inline first, deduped) in one call', async () => {
    const data = [{ id: 7, softech_id: '107', name: 'ALPHA SEVEN', tier: 'exact' }, rows[0]]
    const { onSelect } = setup({ mode: 'multi' }, data)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'alpha' } })
    await screen.findByText(/SEVEN/)
    fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })   // tick id 7
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })   // tick id 1
    fireEvent.keyDown(window, { key: 'F1', ctrlKey: true })
    fireEvent.click(screen.getByText('MODAL-PICK'))                         // modal gives 7, 8
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0].map(i => i.id)).toEqual([7, 1, 8])
    for (const it of onSelect.mock.calls[0][0]) expect(it.item_id).toBe(it.id)
    expect(input.value).toBe('')
    expect(screen.queryByText(/إضافة المحدد/)).toBeNull()                   // inline ticks cleared
  })

  it('multi: Ctrl+Space with the list closed ticks nothing and does not crash', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    expect(fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })).toBe(false)
    fireEvent.change(input, { target: { value: 'alpha' } })
    await screen.findByText(/THREE/)
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })
    expect(screen.queryByText(/إضافة المحدد/)).toBeNull()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('multi: Ctrl+Space on stale rows ticks nothing', async () => {
    const { onSelect } = setup({ mode: 'multi' })
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'alpha' } })
    await screen.findByText(/THREE/)
    get.mockReturnValue(new Promise(() => {}))   // the next query never answers
    fireEvent.change(input, { target: { value: 'alphb' } })
    fireEvent.keyDown(input, { key: ' ', code: 'Space', ctrlKey: true })
    expect(screen.queryByText(/إضافة المحدد/)).toBeNull()
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('withItemId', () => {
  it('id wins when a row carries both and they differ; both end up equal', async () => {
    const { withItemId } = await import('./itemSearchPick')
    expect(withItemId({ id: 5, item_id: 9, name: 'X' })).toEqual({ id: 5, item_id: 5, name: 'X' })
    expect(withItemId({ item_id: 9 })).toEqual({ id: 9, item_id: 9 })
    expect(withItemId({ id: 4 })).toEqual({ id: 4, item_id: 4 })
    const same = { id: 3, item_id: 3 }
    expect(withItemId(same)).toBe(same)
  })
})
