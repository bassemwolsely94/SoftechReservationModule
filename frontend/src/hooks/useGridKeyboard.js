/**
 * useGridKeyboard — one keyboard flow for every review grid where rows are ticked,
 * approved and matched (supplier availability, WhatsApp branch requests, supplier
 * invoices, shortage lists, insurance line review…):
 *
 *   ↑ / ↓ (or K / J)  move the active row          Home / End  first / last row
 *   Space             tick / untick the row        Ctrl+A      tick all visible rows
 *   Enter             approve / confirm the row    M           open the match picker
 *   Esc               close the picker / leave the grid
 *
 * Keys use `event.code`, so they work on the Arabic keyboard layout too (M = «ة»). They
 * act only while focus is inside the grid and never while typing in an input, select or
 * textarea. The grid container gets `tabIndex=0`, so clicking a row or tabbing in enables
 * the keys. Handlers are optional — a grid without an "approve" simply ignores Enter.
 *
 *   const kb = useGridKeyboard({ rows, getKey: r => r.id, onToggle, onConfirm, onOpen, onSelectAll })
 *   <div {...kb.containerProps}> … <tr {...kb.rowProps(r)}> …
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const TYPING = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

export const ACTIVE_ROW = '[&>td]:shadow-[inset_0_2px_0_rgb(var(--c-brand-600)),inset_0_-2px_0_rgb(var(--c-brand-600))]'
const ACTIVE_BLOCK = 'ring-2 ring-inset ring-primary/60'      // rows built from <div>s

export default function useGridKeyboard({
  rows, getKey, onToggle, onConfirm, onOpen, onClose, onSelectAll, enabled = true,
  advanceOnConfirm = false,      // Enter confirms and moves to the next row (review flow)
}) {
  const [active, setActive] = useState(null)
  const containerRef = useRef(null)
  const rowRefs = useRef(new Map())
  const idx = rows.findIndex(r => getKey(r) === active)

  // keep the active row visible while moving
  useEffect(() => {
    const el = active != null ? rowRefs.current.get(active) : null
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' })
  }, [active])

  // the active row disappeared (filter / search changed) → fall back to the nearest one
  useEffect(() => {
    if (active != null && idx < 0) setActive(null)
  }, [active, idx])

  const move = useCallback((to) => {
    if (!rows.length) return
    const n = Math.max(0, Math.min(rows.length - 1, to))
    setActive(getKey(rows[n]))
  }, [rows, getKey])

  const onKeyDown = useCallback((e) => {
    if (!enabled || e.defaultPrevented) return
    const t = e.target
    // typing somewhere → leave the keys alone (a ticked checkbox / a button still counts
    // as "in the grid", so the flow continues after a mouse click on them)
    const clickable = t?.tagName === 'INPUT' && ['checkbox', 'radio', 'button'].includes(t.type)
    if (t && ((TYPING.has(t.tagName) && !clickable) || t.isContentEditable)) return
    const row = idx >= 0 ? rows[idx] : null
    const code = e.code
    const handled = () => { e.preventDefault(); e.stopPropagation() }
    if (code === 'ArrowDown' || (code === 'KeyJ' && !e.ctrlKey && !e.metaKey)) { handled(); move(idx < 0 ? 0 : idx + 1) }
    else if (code === 'ArrowUp' || (code === 'KeyK' && !e.ctrlKey && !e.metaKey)) { handled(); move(idx < 0 ? 0 : idx - 1) }
    else if (code === 'Home') { handled(); move(0) }
    else if (code === 'End') { handled(); move(rows.length - 1) }
    else if (code === 'KeyA' && (e.ctrlKey || e.metaKey) && onSelectAll) { handled(); onSelectAll() }
    else if (code === 'Space' && row && onToggle) { handled(); onToggle(row) }
    else if ((code === 'Enter' || code === 'NumpadEnter') && row && onConfirm) {
      handled()
      onConfirm(row)
      if (advanceOnConfirm) move(idx + 1)
    }
    else if (code === 'KeyM' && !e.ctrlKey && !e.metaKey && row && onOpen) { handled(); onOpen(row) }
    else if (code === 'Escape') {
      if (onClose) { handled(); onClose(row) } else containerRef.current?.blur()
    }
  }, [enabled, idx, rows, move, onToggle, onConfirm, onOpen, onClose, onSelectAll, advanceOnConfirm])

  const rowProps = useCallback((r, { block = false } = {}) => {
    const key = getKey(r)
    const on = key === active
    return {
      ref: (el) => { if (el) rowRefs.current.set(key, el); else rowRefs.current.delete(key) },
      'data-kb-active': on ? 'true' : undefined,
      'aria-selected': on || undefined,
      onMouseDown: () => setActive(key),
      // a frame drawn on the cells (outline on <tr> isn't reliable), so it stacks with the
      // row's own state colour instead of replacing it
      className: on ? (block ? ACTIVE_BLOCK : ACTIVE_ROW) : '',
    }
  }, [active, getKey])

  return {
    active, setActive, rowProps,
    containerProps: { ref: containerRef, tabIndex: 0, onKeyDown,
                      className: 'focus:outline-none focus-visible:ring-1 focus-visible:ring-primary/40' },
  }
}

/** The one-line hint shown under a keyboard-enabled grid. */
export const GRID_KEYS_HINT = '⌨ ↑↓ تنقل · مسافة تحديد · Enter تأكيد · M مطابقة · Ctrl+A تحديد الكل'
