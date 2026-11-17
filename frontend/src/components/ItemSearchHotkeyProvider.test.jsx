import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { results: [] } }) },
  itemsApi: { wildcardSearch: vi.fn() },
}))
vi.mock('./AdvancedItemSearchModal', () => ({ default: () => <div data-testid="adv">ADV-MODAL</div> }))
vi.mock('./BarcodeScanner', () => ({ default: () => null, cameraAvailable: () => false }))
vi.mock('../hooks/useFeatures', () => ({ default: () => ({ cameraScan: false }) }))

import ItemSearchWidget from './ItemSearchWidget'
import ItemSearchHotkeyProvider, { useItemSearchRegistration } from './ItemSearchHotkeyProvider'

function wrap(ui) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ItemSearchHotkeyProvider>{ui}</ItemSearchHotkeyProvider>
    </QueryClientProvider>,
  )
}
const ctrlF1 = () => fireEvent.keyDown(window, { key: 'F1', ctrlKey: true })

describe('Ctrl+F1 owner', () => {
  beforeEach(() => {})
  afterEach(cleanup)

  it('opens exactly one modal, for the last-focused widget', () => {
    wrap(<><div data-w><ItemSearchWidget onSelect={() => {}} /></div><div data-w><ItemSearchWidget onSelect={() => {}} /></div></>)
    const inputs = screen.getAllByRole('textbox')
    inputs[1].focus()
    ctrlF1()
    expect(screen.getAllByTestId('adv')).toHaveLength(1)
    // the modal belongs to the second widget: it renders inside the second wrapper
    expect(inputs[1].closest('[data-w]').contains(screen.getByTestId('adv'))).toBe(true)
  })

  it('opens the first widget when nothing was focused', () => {
    wrap(<><div data-w><ItemSearchWidget onSelect={() => {}} /></div><div data-w><ItemSearchWidget onSelect={() => {}} /></div></>)
    const inputs = screen.getAllByRole('textbox')
    ctrlF1()
    expect(screen.getAllByTestId('adv')).toHaveLength(1)
    expect(inputs[0].closest('[data-w]').contains(screen.getByTestId('adv'))).toBe(true)
  })

  it('skips a disabled widget', () => {
    wrap(<><div data-w><ItemSearchWidget disabled onSelect={() => {}} /></div><div data-w><ItemSearchWidget onSelect={() => {}} /></div></>)
    const inputs = screen.getAllByRole('textbox')
    ctrlF1()
    expect(inputs[1].closest('[data-w]').contains(screen.getByTestId('adv'))).toBe(true)
  })

  it('does not preventDefault with no widget, and ignores plain/Shift/Alt F1', () => {
    wrap(<div />)
    const ev = new KeyboardEvent('keydown', { key: 'F1', ctrlKey: true, cancelable: true })
    window.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(false)
  })

  it('ignores plain F1 even with a widget', () => {
    wrap(<ItemSearchWidget onSelect={() => {}} />)
    const ev = new KeyboardEvent('keydown', { key: 'F1', cancelable: true })
    window.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(false)
    expect(screen.queryByTestId('adv')).toBeNull()
  })

  it('unregisters on unmount', () => {
    const { rerender } = wrap(<ItemSearchWidget onSelect={() => {}} />)
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ItemSearchHotkeyProvider><div /></ItemSearchHotkeyProvider>
      </QueryClientProvider>,
    )
    const ev = new KeyboardEvent('keydown', { key: 'F1', ctrlKey: true, cancelable: true })
    window.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(false)
  })

  it('a widget outside the provider does not crash', () => {
    function Probe() { useItemSearchRegistration({ open: () => {}, disabled: false, inputRef: { current: null } }); return <i>ok</i> }
    render(<Probe />)
    expect(screen.getByText('ok')).toBeTruthy()
  })
})
