/**
 * ItemSearchWidget.jsx
 *
 * Shared barcode-scanner-aware item search component.
 * Used by: NewReservationPage, NewTransferPage, and any other module with item search.
 *
 * Features:
 *  - Searches name, scientific name, softech_id, primary barcode, AND all barcodes
 *    from the itembarcodes table (physical scanner compatible)
 *  - Shows a rich dropdown: name + itemcode + barcode + price + network stock
 *  - After selection: shows an info card with all details
 *  - Clear / change button to reset
 *
 * Props:
 *  onSelect(item)        — called when an item is chosen from the dropdown
 *  onClear()             — called when user clears selection (optional)
 *  selected              — currently selected item object (or null)
 *  placeholder           — custom input placeholder
 *  showStockBadge        — whether to show total-stock badge in dropdown (default: true)
 *  className             — extra classes on the root wrapper
 *  autoFocus             — auto-focus the input on mount
 *  disabled              — disable the widget
 *  mode                  — default variant only:
 *                          'single' (default) pick one; the parent shows it via `selected` (card + «تغيير»)
 *                          'list'   every pick calls onSelect(item); the box clears, keeps focus and
 *                                   drops the old rows (a fast second Enter adds nothing)
 *                          'multi'  rows get a checkbox; Ctrl+Space ticks the highlighted row (a plain
 *                                   Space types — names have spaces); Enter adds the ticked rows (or
 *                                   the highlighted one) as ONE onSelect(items[]); Ctrl+F1 opens the
 *                                   modal with `multi`
 *  exactCodeOnly         — Enter before any ↑/↓ picks only an exact code row (isExactCodeRow);
 *                          other rows stay listed for a click / arrow + Enter
 *  Every item handed to onSelect carries `id` and `item_id`, equal (withItemId) — except the POS
 *  variant, which passes its softech-search rows as-is (they already carry both).
 *
 * POS variant (variant="pos", used by /pos and /m/pos only — default rendering is untouched):
 *  branchId              — current branch (PK); results carry its stock + network branch pills
 *  onAction(kind, item, extra) — kind 'transfer' | 'reserve' | 'demand' (row next-action buttons)
 *  onAlternatives(item)  — reserved for the alternatives wave
 *  customerId            — current customer, for «آخر شراء لهذا العميل» in the preview
 *  sheet                 — mobile: preview opens as a bottom sheet instead of a side panel
 *  Keys: ↑/↓ move · Enter add · ArrowRight toggles the preview · Esc closes preview, then list.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import api, { itemsApi } from '../api/client'
import AdvancedItemSearchModal from './AdvancedItemSearchModal'
import PosResultRow from '../pos/search/PosResultRow'
import PosItemPreview from '../pos/search/PosItemPreview'
import StockAge from '../pos/search/StockAge'
import { isExactishRow, isExactCodeRow } from '../pos/search/autoAdd'
import BarcodeScanner, { cameraAvailable } from './BarcodeScanner'
import useFeatures from '../hooks/useFeatures'
import SearchTierChip from './SearchTierChip'
import Highlight from './Highlight'
import { useItemSearchRegistration } from './ItemSearchHotkeyProvider'
import { withItemId, useTicked } from './itemSearchPick'

// A scanned code matches an item when it is the item's code, its primary barcode or one of its
// extra barcodes (shape differs between the default and the POS search results). Case does not
// matter: a few barcodes carry letters, and one real one is stored in lower case.
function matchesCode(item, code) {
  const norm = v => String(v ?? '').trim().toUpperCase()
  const c = norm(code)
  if (!c || !item) return false
  if (norm(item.softech_id) === c || norm(item.barcode) === c) return true
  const extra = item.barcodes || item.all_barcodes || []
  return extra.some(b => norm(b?.barcode ?? b) === c)
}

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtPrice(v) {
  const n = parseFloat(v)
  if (!n) return null
  return n.toFixed(2)
}

function BarcodeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-50">
      <rect x="2" y="4" width="3" height="16"/><rect x="7" y="4" width="1" height="16"/>
      <rect x="10" y="4" width="2" height="16"/><rect x="14" y="4" width="1" height="16"/>
      <rect x="17" y="4" width="3" height="16"/>
    </svg>
  )
}

// ── Selected item card ─────────────────────────────────────────────────────────

function SelectedItemCard({ item, onClear, disabled }) {
  const primaryBarcode = item.all_barcodes?.[0] || item.barcode || ''
  const price  = fmtPrice(item.pack_price)
  const stock  = item.total_stock !== undefined ? Number(item.total_stock) : null

  const stockColor = stock === null ? 'gray'
    : stock > 10 ? 'green'
    : stock > 0  ? 'amber'
    :              'red'

  return (
    <div className="flex items-start justify-between gap-3 bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3">
      <div className="flex-1 min-w-0 space-y-1">
        {/* Name */}
        <div className="font-bold text-sm text-gray-900 leading-snug">{item.name}</div>
        {item.name_scientific && (
          <div className="text-xs text-gray-500 italic">{item.name_scientific}</div>
        )}
        {/* Code + Barcode + Price + Stock */}
        <div className="flex flex-wrap items-center gap-1.5 mt-1">
          {/* Itemcode */}
          <span className="inline-flex items-center gap-1 text-[11px] font-mono font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">
            كود: {item.softech_id}
          </span>
          {/* Primary barcode */}
          {primaryBarcode && (
            <span className="inline-flex items-center gap-1 text-[11px] font-mono text-gray-600 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded">
              <BarcodeIcon /> {primaryBarcode}
            </span>
          )}
          {/* Additional barcodes */}
          {item.all_barcodes?.slice(1).map(bc => (
            <span key={bc} className="inline-flex items-center gap-1 text-[10px] font-mono text-gray-400 bg-gray-50 border border-gray-200 px-1.5 py-0.5 rounded">
              {bc}
            </span>
          ))}
          {/* Price */}
          {price && (
            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
              💰 {price} ج.م
            </span>
          )}
          {/* Stock */}
          {stock !== null && (
            <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded border ${
              stockColor === 'green' ? 'text-green-700 bg-green-50 border-green-200' :
              stockColor === 'amber' ? 'text-amber-700 bg-amber-50 border-amber-200' :
                                      'text-red-700 bg-red-50 border-red-200'
            }`}>
              📦 {stock > 0 ? `${stock} وحدة` : 'نفد من المخزون'}
            </span>
          )}
        </div>
      </div>
      {!disabled && (
        <button data-tour="item-search-change"
          type="button"
          onClick={onClear}
          className="flex-shrink-0 text-xs text-gray-400 hover:text-red-500 transition-colors mt-0.5 font-medium"
          title="تغيير الصنف"
        >
          ✕ تغيير
        </button>
      )}
    </div>
  )
}

// ── Dropdown result row ────────────────────────────────────────────────────────

function ResultRow({ item, onSelect, index, selected, query, multi = false, ticked = false }) {
  const primaryBarcode = item.all_barcodes?.[0] || item.barcode || ''
  const price  = fmtPrice(item.pack_price)
  const stock  = item.total_stock !== undefined ? Number(item.total_stock) : null

  // multi: a click ticks / unticks the row (onSelect is the toggle there)
  return (
    <div
      data-idx={index}
      role="option"
      aria-selected={!!selected}
      className={`px-3 py-2.5 hover:bg-brand-50 cursor-pointer border-b border-gray-50 last:border-0 transition-colors ${selected ? 'bg-brand-50' : ''}`}
      onMouseDown={e => { e.preventDefault(); onSelect(item) }}
    >
      <div className="font-semibold text-sm text-gray-900 leading-snug">
        {multi && (
          <input type="checkbox" readOnly tabIndex={-1} checked={ticked}
            aria-label="تحديد" className="me-1.5 align-middle rounded pointer-events-none" />
        )}
        <Highlight text={item.name} query={query} />
        <SearchTierChip row={item} />
      </div>
      {item.name_scientific && (
        <div className="text-[10px] text-gray-400 italic mb-0.5">{item.name_scientific}</div>
      )}
      <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
        <span className="text-[11px] font-mono font-bold text-blue-600">
          {item.softech_id}
        </span>
        {primaryBarcode && (
          <span className="inline-flex items-center gap-1 text-[11px] font-mono text-gray-500">
            <BarcodeIcon /> {primaryBarcode}
          </span>
        )}
        {price && (
          <span className="text-[11px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
            💰 {price} ج.م
          </span>
        )}
        {stock !== null && stock > 0 && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${
            stock > 10 ? 'text-green-600 bg-green-50' :
            stock > 0  ? 'text-amber-600 bg-amber-50' : 'text-red-500'
          }`}>
            📦 {stock} وحدة
          </span>
        )}
        {stock === 0 && (
          <span className="text-[11px] text-red-500">📦 نفد</span>
        )}
      </div>
    </div>
  )
}

// ── Main widget ────────────────────────────────────────────────────────────────

export default function ItemSearchWidget({
  onSelect,
  onClear,
  selected      = null,
  placeholder   = 'ابحث باسم الصنف أو الكود أو الباركود...',
  showStockBadge = true,
  className     = '',
  autoFocus     = false,
  disabled      = false,
  variant       = 'default',
  branchId      = null,
  onAction      = null,
  onAlternatives = null,   // pos variant: F7 / row button → verified alternatives panel
  customerId    = null,
  sheet         = false,
  mode          = 'single',  // default variant: 'single' | 'list' | 'multi' (the POS adds = list by nature)
  exactCodeOnly = false,
}) {
  const isPos = variant === 'pos'
  const isList  = !isPos && mode === 'list'
  const isMulti = !isPos && mode === 'multi'
  const { ticked, toggle: toggleTick, isTicked, clear: clearTicks } = useTicked()
  const [moved, setMoved] = useState(false)          // exactCodeOnly: ↑/↓ used on this result set
  const [q, setQ]               = useState('')
  const [open, setOpen]         = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [sel, setSel]           = useState(0)          // pos: highlighted row
  const [previewOn, setPreviewOn] = useState(false)    // pos: side preview / bottom sheet
  const inputRef                = useRef(null)
  const dropdownRef             = useRef(null)

  // Ctrl+F1 is owned by ItemSearchHotkeyProvider (one listener per page).
  useItemSearchRegistration({
    open: () => setShowAdvanced(true),
    disabled,
    inputRef,
  })

  // Debounced search via React Query.
  // `*` / `%` are kept (system wildcard rules, applied by the server's engine ranking).
  const [debouncedQ, setDebouncedQ] = useState('')
  useEffect(() => {
    // both variants keep * / % (wildcard search rules); the default widget uses the engine ranking
    const cleaned = q.trim()
    if (cleaned.replace(/[*%]/g, '').length < 2) { setDebouncedQ(''); return }
    const t = setTimeout(() => setDebouncedQ(cleaned), 280)
    return () => clearTimeout(t)
  }, [q])

  const { data: found, isFetching, isPlaceholderData } = useQuery({
    queryKey: isPos ? ['item-search-widget', debouncedQ, branchId, 'pos'] : ['item-search-widget', debouncedQ, 'engine'],
    queryFn: () => isPos
      ? itemsApi.wildcardSearch(debouncedQ, branchId, { network: true, noLive: true })
          .then(r => ({ rows: r.data.results || [], asOf: r.data.stock_as_of ?? null }))
      : api.get('/items/', { params: { search: debouncedQ, rank: 'engine', page_size: 10 } })
          .then(r => ({ rows: r.data.results || r.data, asOf: null })),
    enabled: debouncedQ.length >= 2,
    staleTime: 15_000,
    keepPreviousData: true,
  })
  const results = found?.rows || []
  const stockAsOf = found?.asOf ?? null
  const hasPosData = isPos && found !== undefined

  // Close dropdown on outside click
  useEffect(() => {
    function handler(e) {
      if (
        dropdownRef.current && !dropdownRef.current.contains(e.target) &&
        inputRef.current && !inputRef.current.contains(e.target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // new result set → highlight the first row, close the preview
  useEffect(() => { setSel(0); setPreviewOn(false); setMoved(false) }, [debouncedQ, branchId])

  // pos: the rows on screen belong to an OLDER query while the debounce/fetch catches up, so an
  // Enter pressed then is queued for the typed text and acts only on ITS fresh first row (a scanner
  // typing a code + Enter adds that code's item, never the previous result's highlighted row).
  const typedQ = q.trim()
  const resultsStale = typedQ !== debouncedQ || isFetching || !!isPlaceholderData
  const [enterFor, setEnterFor] = useState(null)

  // empties the box and drops the old rows; list / multi keep the focus for the next pick
  const resetBox = useCallback(() => {
    setOpen(false)
    setQ('')
    setDebouncedQ('')
    setPreviewOn(false)
    if (isList || isMulti) inputRef.current?.focus()
  }, [isList, isMulti])

  const handleSelect = useCallback((item) => {
    resetBox()
    if (isPos) { onSelect(item); return }               // POS: its own add path, row untouched
    if (isMulti) onSelect([withItemId(item)])
    else onSelect(withItemId(item))
  }, [onSelect, resetBox, isPos, isMulti])

  // multi: one onSelect(items[]) with the ticked rows, then a clean box
  const addItems = useCallback((items) => {
    if (!items.length) return
    resetBox()
    clearTicks()
    onSelect(items.map(withItemId))
  }, [onSelect, resetBox, clearTicks])

  // what the advanced-search modal hands back: an array in multi, one item otherwise
  // multi: the modal's rows join the inline ticks (inline first, deduped by id) in ONE onSelect
  const onModalSelect = useCallback((picked) => {
    setShowAdvanced(false)
    if (Array.isArray(picked)) {
      const merged = []
      const seen = new Set()
      for (const it of [...ticked, ...picked].map(withItemId)) {
        if (seen.has(it.id)) continue
        seen.add(it.id)
        merged.push(it)
      }
      addItems(merged)
    } else handleSelect(picked)
  }, [ticked, addItems, handleSelect])

  // 📷 camera scan (CAMERA_SCAN_ENABLED): the code goes into the search; once that code's own
  // results are in, an exact barcode/code match (or a single result) is chosen like a click.
  const { cameraScan } = useFeatures()
  const showCamera = cameraScan && cameraAvailable() && !disabled
  const [scanning, setScanning] = useState(false)
  const [scanFor, setScanFor]   = useState(null)
  const [scanMiss, setScanMiss] = useState('')

  function onCameraCode(code) {
    setScanning(false)
    setScanMiss('')
    setQ(code)
    setOpen(true)
    setScanFor(code)
  }

  useEffect(() => {
    if (scanFor == null) return
    if (typedQ !== scanFor) { setScanFor(null); return }
    if (resultsStale) return
    setScanFor(null)
    const exact = results.filter(it => matchesCode(it, scanFor))
    if (exact.length === 1) handleSelect(exact[0])
    // a single row the scanned code didn't match field-by-field: the POS takes it only when the
    // server says it is an exact code / barcode hit (safety rule 4 — never a fuzzy row); the
    // both variants: engine rows carry a tier, so only an exact code hit is taken unseen — a
    // `code_prefix` row (the scanned digits only START its code) waits for a click
    else if (!exact.length && results.length === 1 && isExactCodeRow(results[0])) handleSelect(results[0])
    else if (!results.length) setScanMiss(scanFor)
  }, [scanFor, typedQ, resultsStale, results])   // eslint-disable-line react-hooks/exhaustive-deps

  const handleAction = useCallback((kind, item, extra) => {
    setOpen(false)
    setQ('')
    setDebouncedQ('')
    setPreviewOn(false)
    onAction?.(kind, item, extra)
  }, [onAction])

  // the queued Enter fires once the typed query's own rows are in
  useEffect(() => {
    if (enterFor == null) return
    if (typedQ !== enterFor) { setEnterFor(null); return }       // typing went on → drop it
    if (resultsStale) return
    setEnterFor(null)
    // only a plain code / name hit is added unseen (safety rule 4): a sound / approx /
    // ingredient / synonym / learned row is shown highlighted and waits for the cashier's Enter
    if (isExactishRow(results[0])) handleSelect(results[0])
    else if (results.length) { setSel(0); setOpen(true) }
  }, [enterFor, typedQ, resultsStale, results])   // eslint-disable-line react-hooks/exhaustive-deps

  // keep the highlighted row in view while arrowing
  useEffect(() => {
    if (!open) return
    dropdownRef.current?.querySelector(`[data-idx="${sel}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [sel, open, results])

  function onPosKeyDown(e) {
    const listOpen = open && debouncedQ.length >= 2 && results.length > 0
    if (e.key === 'Escape') {
      if (previewOn) { e.preventDefault(); e.stopPropagation(); setPreviewOn(false) }
      else if (open) { e.preventDefault(); e.stopPropagation(); setOpen(false) }
      return
    }
    if (e.key === 'Enter' && resultsStale) {
      e.preventDefault()
      if (typedQ.replace(/[*%]/g, '').length >= 2) setEnterFor(typedQ)
      return
    }
    if (!listOpen) return
    if (e.key === 'F7' && onAlternatives) {           // F7 (also stops Chrome's caret-browsing prompt)
      const it = results[Math.min(sel, results.length - 1)]
      if (it) { e.preventDefault(); e.stopPropagation(); setOpen(false); onAlternatives(it) }
      return
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setPreviewOn(p => !p) }   // physical → key
    else if (e.key === 'Enter') {
      const it = results[Math.min(sel, results.length - 1)]
      if (it) { e.preventDefault(); handleSelect(it) }
    }
  }

  // default variant: ↑/↓ move the highlight (clamped), Enter picks it, Esc closes — no preview,
  // F7 or queued Enter (those are POS-only)
  function onDefaultKeyDown(e) {
    const listOpen = open && debouncedQ.length >= 2
    if (e.key === 'Escape') {
      if (open) { e.preventDefault(); e.stopPropagation(); setOpen(false) }
      return
    }
    // multi: Ctrl+Space ticks the highlighted row; a plain Space is left alone (it types)
    if (isMulti && e.ctrlKey && (e.code === 'Space' || e.key === ' ')) {
      e.preventDefault()
      if (listOpen && !resultsStale) toggleTick(results[Math.min(sel, results.length - 1)])
      return
    }
    // multi: ticked rows were chosen one by one on screen, so Enter adds them even mid-typing
    if (isMulti && e.key === 'Enter' && ticked.length) {
      e.preventDefault()
      addItems(ticked)
      return
    }
    if (e.key === 'Enter' && resultsStale) {
      // the rows on screen may belong to an older query: never pick one unseen (no queued Enter here)
      e.preventDefault()
      return
    }
    if (!listOpen) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setMoved(true); setSel(s => Math.min(s + 1, Math.max(results.length - 1, 0))) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setMoved(true); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()   // never submit an enclosing form while the list is open
      const it = results[Math.min(sel, results.length - 1)]
      if (!it) return
      // exactCodeOnly: an Enter nobody aimed (no ↑/↓) takes only an exact code row
      if (exactCodeOnly && !moved && !isExactCodeRow(it)) return
      if (isMulti) addItems([it])
      else handleSelect(it)
    }
  }

  const handleClear = useCallback(() => {
    setQ('')
    setDebouncedQ('')
    setOpen(false)
    onClear?.()
    // Re-focus so user can search immediately
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [onClear])

  // ── Rendered ──────────────────────────────────────────────────────────────
  if (selected && !isList && !isMulti) {
    return (
      <div className={className}>
        <SelectedItemCard item={selected} onClear={handleClear} disabled={disabled} />
        {showAdvanced && (
          <AdvancedItemSearchModal
            onSelect={onModalSelect}
            onClose={() => setShowAdvanced(false)}
          />
        )}
      </div>
    )
  }

  const showDropdown = open && debouncedQ.length >= 2

  return (
    <div className={`relative ${className}`}>
      {/* Input row: search field + advanced search button */}
      <div className="flex items-center gap-1.5">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            className="input-field w-full ps-9 disabled:bg-gray-100 disabled:cursor-not-allowed"
            placeholder={placeholder}
            value={q}
            onChange={e => { setQ(e.target.value); setOpen(true); setScanMiss('') }}
            onKeyDown={isPos ? onPosKeyDown : onDefaultKeyDown}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            autoFocus={autoFocus}
            disabled={disabled}
            autoComplete="off"
            dir="rtl"
          />
          {/* Barcode scanner icon hint */}
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
            <BarcodeIcon />
          </span>
          {/* Loading spinner */}
          {isFetching && debouncedQ.length >= 2 && (
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2">
              <span className="w-3.5 h-3.5 border-2 border-brand-200 border-t-brand-500 rounded-full animate-spin block" />
            </span>
          )}
        </div>

        {showCamera && (
          <button type="button" data-tour="item-search-camera"
            onClick={() => setScanning(true)}
            title="مسح الباركود بالكاميرا"
            aria-label="مسح الباركود بالكاميرا"
            className="flex-shrink-0 flex items-center justify-center w-9 h-9 border border-gray-300 rounded-lg text-gray-500 hover:text-brand-600 hover:border-brand-400 hover:bg-brand-50 transition-colors"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
          </button>
        )}

        {/* Advanced search button (magnifier) */}
        <button data-tour="item-search-advanced"
          type="button"
          onClick={() => setShowAdvanced(true)}
          disabled={disabled}
          title="البحث المتقدم (Ctrl+F1)"
          className="flex-shrink-0 flex items-center justify-center w-9 h-9 border border-gray-300 rounded-lg text-gray-400 hover:text-brand-600 hover:border-brand-400 hover:bg-brand-50 transition-colors disabled:opacity-40 disabled:pointer-events-none"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </button>
      </div>

      {/* Hint */}
      <p className="text-[11px] text-gray-400 mt-1 flex items-center gap-1 flex-wrap">
        <BarcodeIcon />
        {isPos
          ? 'اسم · كود · باركود · * أو % لأي حروف · ↑↓ تنقّل · Enter إضافة · → معاينة · F7 بدائل · Esc إغلاق ·'
          : isMulti
            ? 'اسم · كود · باركود · * أو % لأي حروف · ↑↓ تنقّل · Ctrl+مسافة تحديد · Enter إضافة ·'
            : 'اسم · كود · باركود (قارئ ضوئي متوافق) · * أو % لأي حروف · ↑↓ تنقّل · Enter اختيار ·'}
        <button data-tour="item-search-advanced"
          type="button"
          onClick={() => setShowAdvanced(true)}
          disabled={disabled}
          className="text-brand-500 hover:text-brand-700 font-medium disabled:opacity-40"
        >
          🔍 بحث متقدم (Ctrl+F1)
        </button>
        {isMulti && ticked.length > 0 && (
          <button data-tour="item-search-add-ticked" type="button"
            onMouseDown={e => { e.preventDefault(); addItems(ticked) }}
            className="ms-auto text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded px-2 py-0.5">
            إضافة المحدد ({ticked.length})
          </button>
        )}
        {isPos && hasPosData && <StockAge asOf={stockAsOf} className="ms-auto" />}
      </p>
      {scanMiss && (
        <p className="text-xs text-amber-700 mt-1">
          لم يُعثر على الباركود <span dir="ltr" className="tabular-nums">{scanMiss}</span> — جرّب البحث بالاسم
        </p>
      )}
      {scanning && <BarcodeScanner onScan={onCameraCode} onClose={() => setScanning(false)} />}

      {/* Dropdown */}
      {showDropdown && isPos && (
        <div ref={dropdownRef} role="listbox"
             className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 flex overflow-hidden">
          <div className="flex-1 min-w-0 max-h-[34rem] overflow-y-auto">
            {results.length > 0 ? results.map((item, i) => (
              <PosResultRow key={item.softech_id || item.id || i} index={i} item={item}
                hereBranchId={branchId} selected={i === sel}
                onAdd={handleSelect} onAction={handleAction}
                onAlternatives={onAlternatives ? (it) => { setOpen(false); onAlternatives(it) } : null}
                onPreview={() => { if (sel === i) setPreviewOn(p => !p); else { setSel(i); setPreviewOn(true) } }} />
            )) : (
              <div className="px-4 py-4 text-sm text-gray-400 text-center">
                {isFetching ? 'جارٍ البحث...' : 'لا توجد نتائج — جرب باسم مختلف أو الكود أو الباركود'}
              </div>
            )}
          </div>
          {previewOn && !sheet && results[sel] && (
            <PosItemPreview item={results[sel]} hereBranchId={branchId} customerId={customerId}
              className="w-72 shrink-0 border-s border-gray-100 bg-white max-h-[34rem] overflow-y-auto" />
          )}
        </div>
      )}
      {isPos && previewOn && sheet && results[sel] && (
        <div className="fixed inset-0 z-40 flex items-end bg-black/30" onMouseDown={() => setPreviewOn(false)}>
          <div className="w-full bg-white rounded-t-2xl max-h-[75vh] overflow-y-auto" onMouseDown={e => e.stopPropagation()}>
            <PosItemPreview item={results[sel]} hereBranchId={branchId} customerId={customerId} />
            <div className="p-3 pt-0">
              <button data-tour="item-search-add-to-order" type="button" onClick={() => handleSelect(results[sel])}
                      className="w-full rounded-lg bg-brand-600 text-white py-2 text-sm font-medium">إضافة للأمر</button>
            </div>
          </div>
        </div>
      )}
      {showDropdown && !isPos && (
        <div
          ref={dropdownRef}
          role="listbox"
          className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-64 overflow-y-auto"
        >
          {results.length > 0 ? (
            results.map((item, i) => (
              <ResultRow key={item.id} item={item} onSelect={isMulti ? toggleTick : handleSelect}
                index={i} selected={i === sel} query={debouncedQ}
                multi={isMulti} ticked={isMulti && isTicked(item)} />
            ))
          ) : (
            <div className="px-4 py-4 text-sm text-gray-400 text-center">
              {isFetching ? 'جارٍ البحث...' : 'لا توجد نتائج — جرب باسم مختلف أو الكود أو الباركود'}
            </div>
          )}
        </div>
      )}

      {/* Advanced search modal */}
      {showAdvanced && (
        <AdvancedItemSearchModal
          multi={isMulti}
          onSelect={onModalSelect}
          onClose={() => setShowAdvanced(false)}
        />
      )}
    </div>
  )
}
