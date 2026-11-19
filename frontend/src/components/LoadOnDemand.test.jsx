import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import LoadOnDemand from './LoadOnDemand'

// Full audit FE-19: a shell piece is loaded on first use, and that first use still opens it.
function FakePalette() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = e => { if (e.ctrlKey && e.key === 'k') setOpen(v => !v) }
    const onOpen = e => setOpen(e.detail?.who || true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('fake:open', onOpen)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('fake:open', onOpen) }
  }, [])
  return open ? <div>palette open {String(open)}</div> : <div>palette closed</div>
}

const isKey = e => e.ctrlKey && e.key === 'k'
afterEach(cleanup)

describe('LoadOnDemand', () => {
  it('loads nothing until it is wanted', async () => {
    const load = vi.fn(() => Promise.resolve({ default: FakePalette }))
    render(<LoadOnDemand load={load} events={['fake:open']} keys={isKey} />)
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', ctrlKey: true })) })
    expect(load).not.toHaveBeenCalled()
    expect(screen.queryByText(/palette/)).toBeNull()
  })

  it('the first shortcut loads the piece and opens it; later ones go straight to it', async () => {
    const load = vi.fn(() => Promise.resolve({ default: FakePalette }))
    render(<LoadOnDemand load={load} events={['fake:open']} keys={isKey} />)
    const first = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true })
    await act(async () => { window.dispatchEvent(first) })
    expect(first.defaultPrevented).toBe(true)                 // the browser's own Ctrl+K is held back
    expect(await screen.findByText('palette open true')).toBeTruthy()
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })) })
    expect(screen.getByText('palette closed')).toBeTruthy()   // toggled by the piece itself, not reopened
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('an open event is replayed with its detail', async () => {
    render(<LoadOnDemand load={() => Promise.resolve({ default: FakePalette })} events={['fake:open']} />)
    await act(async () => { window.dispatchEvent(new CustomEvent('fake:open', { detail: { who: 'customer-7' } })) })
    expect(await screen.findByText('palette open customer-7')).toBeTruthy()
  })
})
