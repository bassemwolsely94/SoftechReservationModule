// D-25 batch 5 — `notify` lets plain functions (print helpers, module-level onError handlers)
// show a toast instead of window.alert.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ToastProvider, askBar, confirmBar, notify } from './ui'

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

  it('confirmBar / askBar ask in the provider-hosted bottom bar (batch 6)', async () => {
    const native = vi.spyOn(window, 'confirm').mockImplementation(() => true)
    render(<ToastProvider><div /></ToastProvider>)
    let p
    act(() => { p = confirmBar('حذف هذا الجدول؟', { tone: 'danger', confirmLabel: 'حذف' }) })
    const bar = screen.getByRole('alertdialog')
    expect(bar.textContent).toContain('حذف هذا الجدول؟')
    await act(async () => { fireEvent.click(screen.getByText('حذف')) })
    await expect(p).resolves.toBe(true)
    let q
    act(() => { q = askBar('سبب الاستبعاد (اختياري):') })
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'مكرر' } })
    await act(async () => { fireEvent.click(screen.getByText('تأكيد')) })
    await expect(q).resolves.toBe('مكرر')
    expect(native).not.toHaveBeenCalled()
  })

  it('confirmBar without a provider confirms nothing', async () => {
    await expect(confirmBar('x')).resolves.toBe(false)
    await expect(askBar('x')).resolves.toBe(null)
  })

  it('falls back to the console when no provider is mounted (and after it unmounts)', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = render(<ToastProvider><div /></ToastProvider>)
    unmount()
    notify.error('فشل')
    expect(err).toHaveBeenCalledWith('فشل', '')
  })
})
