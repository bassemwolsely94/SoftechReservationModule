import { useEffect } from 'react'

/*
 * usePosHotkeys — SOFTECH-parity keyboard control for the Indirect-POS screen.
 * Makes the on-screen shortcut labels REAL so a cashier trained on SOFTECH keeps their
 * muscle memory:
 *   Ctrl+F2/F3/F4 → channel (نقدى / توصيل / تعاقد)
 *   Ctrl+2/3/4    → tab (الأصناف / السداد / بيانات التعاقد)
 *   F2            → focus the item-search box (add a line — SOFTECH types in the empty row)
 *   F4 / Delete   → delete the selected line
 *   F9            → preview the send (dry-run — never writes to SOFTECH)
 *   F10           → live send to the cashier (only when the writer is enabled)
 *   ArrowUp/Down  → move the selected line (only when not editing a field)
 * (Ctrl+F1 advanced search is handled inside ItemSearchWidget.)
 *
 * `enabled` is false while a modal/overlay is open so shortcuts don't fire underneath it.
 */
const isEditable = (el) => {
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

export default function usePosHotkeys(P, { enabled = true, onOpenUnits } = {}) {
  useEffect(() => {
    if (!enabled) return
    const onKey = (e) => {
      const k = e.key
      const el = document.activeElement
      const editing = isEditable(el)
      // a plain letter shortcut must not fire while typing in a TEXT/search field (numbers are ok)
      const inTextField = el && ((el.tagName === 'INPUT' && ['text', 'search', ''].includes((el.getAttribute('type') || 'text').toLowerCase())) || el.tagName === 'TEXTAREA' || el.isContentEditable)

      // Q → enter the selected line's quantity in strips/units (SOFTECH's Q modal)
      if ((k === 'q' || k === 'Q') && onOpenUnits && !inTextField && !e.ctrlKey && !e.altKey && !e.metaKey) {
        if (P.selected >= 0 && P.selected < P.lines.length) { e.preventDefault(); onOpenUnits(); return }
      }

      // ── Ctrl combos (safe to fire even while a field is focused) ──
      // channel allowed for this seller? (server-filtered custTypes; empty = show all)
      const okChan = (v) => !P.custTypes?.length || P.custTypes.some(t => t.channel === v || t.key === v)
      if (e.ctrlKey && !e.altKey && !e.metaKey) {
        // channel = نوع العميل (custType); setCustType cascades to channel + entity reset
        if (k === 'F2') { e.preventDefault(); if (okChan('cash')) P.setCustType('cash'); return }
        if (k === 'F3') { e.preventDefault(); if (okChan('delivery')) P.setCustType('delivery'); return }
        if (k === 'F4') { e.preventDefault(); if (okChan('contract')) P.setCustType('contract'); return }
        if (k === '2')  { e.preventDefault(); P.setActiveTab('items'); return }
        if (k === '3')  { e.preventDefault(); P.setActiveTab('payment'); return }
        if (k === '4')  { e.preventDefault(); P.setActiveTab('contract'); return }
        return
      }

      // ── plain function/nav keys ──
      if (k === 'F2') {                       // add a line → focus the item search
        e.preventDefault()
        P.setActiveTab('items')
        setTimeout(() => document.querySelector('#pos-item-search input')?.focus(), 0)
        return
      }
      if (k === 'F4') {                       // delete the selected line
        e.preventDefault()
        if (P.selected >= 0 && P.selected < P.lines.length) P.removeLine(P.selected)
        return
      }
      if (k === 'F9') {                       // preview the send (dry-run — never writes to SOFTECH)
        e.preventDefault()
        if (!P.busy && P.lines.length) P.submit(false)
        return
      }
      if (k === 'F10') {                      // live send to cashier — only when the writer is enabled
        e.preventDefault()
        if (!P.busy && P.lines.length && P.ref?.writer_enabled) P.submit(true)
        return
      }
      if (k === 'Delete' && !editing) {       // Delete only outside a field (would eat text otherwise)
        if (P.selected >= 0 && P.selected < P.lines.length) { e.preventDefault(); P.removeLine(P.selected) }
        return
      }
      if ((k === 'ArrowDown' || k === 'ArrowUp') && !editing && P.lines.length) {
        e.preventDefault()
        const n = P.lines.length
        const cur = P.selected < 0 ? (k === 'ArrowDown' ? -1 : 0) : P.selected
        const next = k === 'ArrowDown' ? Math.min(cur + 1, n - 1) : Math.max(cur - 1, 0)
        P.setSelected(next)
        return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, onOpenUnits, P.selected, P.lines.length, P.busy, P.setCustType, P.setActiveTab, P.removeLine, P.setSelected, P.submit, P.ref])
}
