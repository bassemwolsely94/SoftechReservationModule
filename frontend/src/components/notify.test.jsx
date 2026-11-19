// D-25 batch 5 — `notify` lets plain functions (print helpers, module-level onError handlers)
// show a toast instead of window.alert.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { ToastProvider, notify } from './ui'

afterEach(() => { cleanup(); vi.restoreAllMocks(); document.getElementById('toast-root')?.remove() })

describe('notify', () => {
  it('shows a toast through the mounted ToastProvider, never window.alert', () => {
    const root = document.createElement('div'); root.id = 'toast-root'; document.body.appendChild(root)
    const native = vi.spyOn(window, 'alert').mockImplementation(() => {})
    render(<ToastProvider><div /></ToastProvider>)
    act(() => { notify.warning('يرجى السماح بالنوافذ المنبثقة للطباعة') })
    expect(screen.getByText('يرجى السماح بالنوافذ المنبثقة للطباعة')).toBeTruthy()
    act(() => { notify.error('تعذّر تنفيذ الإجراء', 'سبب') })
    expect(screen.getByText('تعذّر تنفيذ الإجراء')).toBeTruthy()
    expect(screen.getByText('سبب')).toBeTruthy()
    expect(native).not.toHaveBeenCalled()
  })

  it('falls back to the console when no provider is mounted (and after it unmounts)', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = render(<ToastProvider><div /></ToastProvider>)
    unmount()
    notify.error('فشل')
    expect(err).toHaveBeenCalledWith('فشل', '')
  })
})
