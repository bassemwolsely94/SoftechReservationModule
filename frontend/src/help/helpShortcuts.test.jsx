import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'

vi.mock('../api/client', () => ({ helpApi: {}, default: {} }))
import useHelpStore from './helpStore'
import { useHelpShortcuts } from './HelpPanel'

function Probe() { useHelpShortcuts(); return null }
const press = (init) => {
  const ev = new KeyboardEvent('keydown', { key: 'F1', cancelable: true, ...init })
  window.dispatchEvent(ev)
  return ev
}

describe('help F1 shortcuts', () => {
  afterEach(() => { cleanup(); useHelpStore.getState().close() })

  it('Ctrl+F1 does not toggle help and is not prevented by it', () => {
    render(<Probe />)
    const ev = press({ ctrlKey: true })
    expect(useHelpStore.getState().isOpen).toBe(false)
    expect(ev.defaultPrevented).toBe(false)
  })

  it('plain F1 still toggles help', () => {
    render(<Probe />)
    press({})
    expect(useHelpStore.getState().isOpen).toBe(true)
    press({})
    expect(useHelpStore.getState().isOpen).toBe(false)
  })
})
