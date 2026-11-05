import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import useSortableRows from './useSortableRows'
import useGridKeyboard from './useGridKeyboard'

const ROWS = [
  { id: 1, name: 'باراسيتامول', net: 50, date: '2026-01-03' },
  { id: 2, name: 'أموكسيسيلين', net: 200, date: '2026-01-01' },
  { id: 3, name: 'Zinc', net: null, date: '' },
  { id: 4, name: 'فيتامين 10', net: 5, date: '2026-01-02' },
  { id: 5, name: 'فيتامين 9', net: 75, date: '2026-01-05' },
]
const ids = rows => rows.map(r => r.id)

beforeEach(() => sessionStorage.clear())

describe('useSortableRows', () => {
  it('keeps the arrival order without a default sort', () => {
    const { result } = renderHook(() => useSortableRows(ROWS))
    expect(ids(result.current.sorted)).toEqual([1, 2, 3, 4, 5])
    expect(result.current.sort).toBeNull()
  })

  it('numbers: first click descending, empties last either way, third click back to arrival order', () => {
    const { result } = renderHook(() => useSortableRows(ROWS))
    act(() => result.current.headerProps('net', 'number').onSort())
    expect(ids(result.current.sorted)).toEqual([2, 5, 1, 4, 3])
    expect(result.current.headerProps('net', 'number')).toMatchObject({ active: true, dir: 'desc', ariaSort: 'descending' })
    act(() => result.current.toggle('net', 'number'))
    expect(ids(result.current.sorted)).toEqual([4, 1, 5, 2, 3])
    act(() => result.current.toggle('net', 'number'))
    expect(ids(result.current.sorted)).toEqual([1, 2, 3, 4, 5])
  })

  it('text: ascending first, numbers inside names compared naturally', () => {
    const { result } = renderHook(() => useSortableRows(ROWS))
    act(() => result.current.toggle('name', 'text'))
    const order = result.current.sorted.map(r => r.name)
    expect(order.indexOf('فيتامين 9')).toBeLessThan(order.indexOf('فيتامين 10'))
  })

  it('dates sort by time, empty last', () => {
    const { result } = renderHook(() => useSortableRows(ROWS))
    act(() => result.current.toggle('date', 'date'))
    expect(ids(result.current.sorted)).toEqual([5, 1, 4, 2, 3])
  })

  it('a default sort applies until the user picks another', () => {
    const { result } = renderHook(() => useSortableRows(ROWS, { defaultSort: { key: 'net', dir: 'asc' } }))
    expect(ids(result.current.sorted)).toEqual([4, 1, 5, 2, 3])
  })

  it('getValue sorts on the raw value, not the display', () => {
    const getValue = (r, k) => (k === 'len' ? r.name.length : r[k])
    const { result } = renderHook(() => useSortableRows(ROWS, { getValue }))
    act(() => result.current.toggle('len', 'number'))
    expect(result.current.sorted[0].name).toBe('باراسيتامول')
  })

  it('remembers the choice per table, and ignores a remembered key the table no longer has', () => {
    const first = renderHook(() => useSortableRows(ROWS, { persistKey: 't1' }))
    act(() => first.result.current.toggle('net', 'number'))
    const again = renderHook(() => useSortableRows(ROWS, { persistKey: 't1' }))
    expect(again.result.current.sort).toMatchObject({ key: 'net', dir: 'desc' })
    const narrowed = renderHook(() => useSortableRows(ROWS, { persistKey: 't1', keys: ['name'] }))
    expect(narrowed.result.current.sort).toBeNull()
  })

  it('a corrupt remembered value is ignored', () => {
    sessionStorage.setItem('sort:t2', '{"key":1,"dir":"sideways"}')
    const { result } = renderHook(() => useSortableRows(ROWS, { persistKey: 't2' }))
    expect(result.current.sort).toBeNull()
  })

  it('does not change the rows it was given', () => {
    const rows = [...ROWS]
    const { result } = renderHook(() => useSortableRows(rows))
    act(() => result.current.toggle('net', 'number'))
    expect(ids(rows)).toEqual([1, 2, 3, 4, 5])
  })
})

function key(code, extra = {}) {
  return { code, target: document.body, defaultPrevented: false, ctrlKey: false, metaKey: false,
           preventDefault: vi.fn(), stopPropagation: vi.fn(), ...extra }
}

describe('useGridKeyboard', () => {
  const setup = (opts = {}) => {
    const handlers = { onToggle: vi.fn(), onConfirm: vi.fn(), onOpen: vi.fn(), onSelectAll: vi.fn(), ...opts }
    const hook = renderHook(props => useGridKeyboard({ rows: props.rows, getKey: r => r.id, ...handlers }),
      { initialProps: { rows: ROWS } })
    const press = (code, extra) => {
      const e = key(code, extra)
      act(() => hook.result.current.containerProps.onKeyDown(e))
      return e
    }
    return { hook, handlers, press, active: () => hook.result.current.active }
  }

  it('↓ / ↑ / J / K / Home / End move the active row inside the grid', () => {
    const { press, active } = setup()
    press('ArrowDown'); expect(active()).toBe(1)
    press('ArrowDown'); press('KeyJ'); expect(active()).toBe(3)
    press('ArrowUp'); expect(active()).toBe(2)
    press('KeyK'); press('KeyK'); expect(active()).toBe(1)
    press('End'); expect(active()).toBe(5)
    press('ArrowDown'); expect(active()).toBe(5)
    press('Home'); expect(active()).toBe(1)
  })

  it('Space ticks, Enter confirms, M opens the picker, Ctrl+A selects all', () => {
    const { press, handlers } = setup()
    press('ArrowDown')
    const e = press('Space')
    expect(handlers.onToggle).toHaveBeenCalledWith(ROWS[0])
    expect(e.preventDefault).toHaveBeenCalled()
    press('Enter'); expect(handlers.onConfirm).toHaveBeenCalledWith(ROWS[0])
    press('NumpadEnter'); expect(handlers.onConfirm).toHaveBeenCalledTimes(2)
    press('KeyM'); expect(handlers.onOpen).toHaveBeenCalledWith(ROWS[0])
    press('KeyA', { ctrlKey: true }); expect(handlers.onSelectAll).toHaveBeenCalledOnce()
  })

  it('Enter with advanceOnConfirm moves to the next row', () => {
    const { press, active } = setup({ advanceOnConfirm: true })
    press('ArrowDown'); press('Enter')
    expect(active()).toBe(2)
  })

  it('no active row: Space / Enter do nothing', () => {
    const { press, handlers } = setup()
    const e = press('Space')
    press('Enter')
    expect(handlers.onToggle).not.toHaveBeenCalled()
    expect(handlers.onConfirm).not.toHaveBeenCalled()
    expect(e.preventDefault).not.toHaveBeenCalled()
  })

  it('typing in an input, textarea or select is left alone; a checkbox still drives the grid', () => {
    const { press, handlers, active } = setup()
    press('ArrowDown')
    for (const tag of ['input', 'textarea', 'select']) {
      const el = document.createElement(tag)
      const e = press('Space', { target: el })
      expect(e.preventDefault).not.toHaveBeenCalled()
    }
    press('ArrowDown', { target: Object.assign(document.createElement('input'), { type: 'text' }) })
    expect(active()).toBe(1)
    const box = Object.assign(document.createElement('input'), { type: 'checkbox' })
    press('Space', { target: box })
    expect(handlers.onToggle).toHaveBeenCalledOnce()
  })

  it('Ctrl+J / Ctrl+K / Ctrl+M stay with the browser', () => {
    const { press, active, handlers } = setup()
    press('KeyJ', { ctrlKey: true }); expect(active()).toBeNull()
    press('ArrowDown')
    press('KeyM', { ctrlKey: true }); expect(handlers.onOpen).not.toHaveBeenCalled()
  })

  it('disabled or already-handled events are ignored', () => {
    const { press, active } = setup()
    press('ArrowDown', { defaultPrevented: true })
    expect(active()).toBeNull()
    const off = renderHook(() => useGridKeyboard({ rows: ROWS, getKey: r => r.id, enabled: false }))
    act(() => off.result.current.containerProps.onKeyDown(key('ArrowDown')))
    expect(off.result.current.active).toBeNull()
  })

  it('the active row falls back to none when it leaves the rows (filter changed)', () => {
    const { hook, press, active } = setup()
    press('End'); expect(active()).toBe(5)
    hook.rerender({ rows: ROWS.slice(0, 2) })
    expect(active()).toBeNull()
  })

  it('rowProps marks the active row and a mouse-down makes a row active', () => {
    const { hook } = setup()
    act(() => hook.result.current.rowProps(ROWS[2]).onMouseDown())
    expect(hook.result.current.active).toBe(3)
    expect(hook.result.current.rowProps(ROWS[2])).toMatchObject({ 'data-kb-active': 'true', 'aria-selected': true })
    expect(hook.result.current.rowProps(ROWS[1])['data-kb-active']).toBeUndefined()
    expect(hook.result.current.containerProps.tabIndex).toBe(0)
  })

  it('Escape calls onClose when given', () => {
    const onClose = vi.fn()
    const { press } = setup({ onClose })
    press('ArrowDown'); press('Escape')
    expect(onClose).toHaveBeenCalledWith(ROWS[0])
  })
})
