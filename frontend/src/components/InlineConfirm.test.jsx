// D-25 / FE-9 — the shared calm replacements for window.confirm / prompt.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ConfirmButton, useConfirm, ARM_MS } from './InlineConfirm'

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('ConfirmButton (inline two-step)', () => {
  it('the first click arms the same button; only the second runs the action', () => {
    const onConfirm = vi.fn()
    render(<ConfirmButton onConfirm={onConfirm} confirmLabel="حذف؟">حذف</ConfirmButton>)
    const btn = screen.getByRole('button')
    fireEvent.click(btn)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(btn.textContent).toBe('حذف؟')
    expect(btn.dataset.armed).toBe('1')
    expect(btn.className).toContain('bg-red-600')
    fireEvent.click(btn)
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(btn.textContent).toBe('حذف')            // back to normal after running
  })

  it('disarms by itself after 4 s, so a late click only arms it again', () => {
    vi.useFakeTimers()
    const onConfirm = vi.fn()
    render(<ConfirmButton onConfirm={onConfirm}>إلغاء</ConfirmButton>)
    const btn = screen.getByRole('button')
    fireEvent.click(btn)
    act(() => { vi.advanceTimersByTime(ARM_MS + 10) })
    expect(btn.dataset.armed).toBe('0')
    fireEvent.click(btn)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(btn.dataset.armed).toBe('1')
  })

  it('a disabled button never arms or runs', () => {
    const onConfirm = vi.fn()
    render(<ConfirmButton disabled onConfirm={onConfirm}>حذف</ConfirmButton>)
    const btn = screen.getByRole('button')
    fireEvent.click(btn); fireEvent.click(btn)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('never calls the native dialog', () => {
    const native = vi.spyOn(window, 'confirm')
    render(<ConfirmButton onConfirm={() => {}}>حذف</ConfirmButton>)
    fireEvent.click(screen.getByRole('button')); fireEvent.click(screen.getByRole('button'))
    expect(native).not.toHaveBeenCalled()
  })
})

function Harness({ onResult, mode = 'confirm', opts }) {
  const { confirm, ask, ui } = useConfirm()
  return (
    <div>
      {ui}
      <button onClick={async () => onResult(await (mode === 'ask' ? ask : confirm)('متابعة؟', opts))}>go</button>
    </div>
  )
}

describe('useConfirm (non-modal bar)', () => {
  it('confirm → true on «تأكيد», and the bar closes', async () => {
    const onResult = vi.fn()
    render(<Harness onResult={onResult} />)
    fireEvent.click(screen.getByText('go'))
    const bar = screen.getByRole('alertdialog')
    expect(bar.getAttribute('aria-modal')).toBe('false')   // no backdrop, page stays usable
    expect(bar.textContent).toContain('متابعة؟')
    await act(async () => { fireEvent.click(screen.getByText('تأكيد')) })
    expect(onResult).toHaveBeenCalledWith(true)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('confirm → false on «إلغاء» and on Esc', async () => {
    const onResult = vi.fn()
    render(<Harness onResult={onResult} />)
    fireEvent.click(screen.getByText('go'))
    await act(async () => { fireEvent.click(screen.getByText('إلغاء')) })
    expect(onResult).toHaveBeenLastCalledWith(false)
    fireEvent.click(screen.getByText('go'))
    await act(async () => { fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' }) })
    expect(onResult).toHaveBeenLastCalledWith(false)
  })

  it('Enter confirms; a danger tone paints the confirm button red', async () => {
    const onResult = vi.fn()
    render(<Harness onResult={onResult} opts={{ tone: 'danger', confirmLabel: 'حذف نهائياً' }} />)
    fireEvent.click(screen.getByText('go'))
    expect(screen.getByText('حذف نهائياً').className).toContain('bg-red-600')
    await act(async () => { fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Enter' }) })
    expect(onResult).toHaveBeenCalledWith(true)
  })

  it('ask (prompt replacement) returns the typed text, or null on cancel', async () => {
    const onResult = vi.fn()
    render(<Harness mode="ask" onResult={onResult} />)
    fireEvent.click(screen.getByText('go'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'اتصلت بالعميل' } })
    await act(async () => { fireEvent.click(screen.getByText('تأكيد')) })
    expect(onResult).toHaveBeenLastCalledWith('اتصلت بالعميل')
    fireEvent.click(screen.getByText('go'))
    await act(async () => { fireEvent.click(screen.getByText('إلغاء')) })
    expect(onResult).toHaveBeenLastCalledWith(null)
  })

  it('a required input keeps «تأكيد» disabled until something is typed', () => {
    render(<Harness mode="ask" onResult={() => {}} opts={{ input: { required: true } }} />)
    fireEvent.click(screen.getByText('go'))
    expect(screen.getByText('تأكيد').disabled).toBe(true)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'سبب' } })
    expect(screen.getByText('تأكيد').disabled).toBe(false)
  })

  it('a second request settles the first one as cancelled', async () => {
    const results = []
    render(<Harness onResult={(v) => results.push(v)} />)
    fireEvent.click(screen.getByText('go'))
    await act(async () => { fireEvent.click(screen.getByText('go')) })
    expect(results).toEqual([false])
    expect(screen.getAllByRole('alertdialog')).toHaveLength(1)
  })
})
