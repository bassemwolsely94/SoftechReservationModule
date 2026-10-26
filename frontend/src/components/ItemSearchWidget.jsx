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
        <button
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

function ResultRow({ item, onSelect }) {
  const primaryBarcode = item.all_barcodes?.[0] || item.barcode || ''
  const price  = fmtPrice(item.pack_price)
  const stock  = item.total_stock !== undefined ? Number(item.total_stock) : null

  return (
    <div
      className="px-3 py-2.5 hover:bg-brand-50 cursor-pointer border-b border-gray-50 last:border-0 transition-colors"
      onMouseDown={e => { e.preventDefault(); onSelect(item) }}
    >
      <div className="font-semibold text-sm text-gray-900 leading-snug">{item.name}</div>
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
  onAlternatives = null,   // eslint-disable-line no-unused-vars
  customerId    = null,
  sheet         = false,
}) {
  const isPos = variant === 'pos'
  const [q, setQ]               = useState('')
  const [open, setOpen]         = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [sel, setSel]           = useState(0)          // pos: highlighted row
  const [previewOn, setPreviewOn] = useState(false)    // pos: side preview / bottom sheet
  const inputRef                = useRef(null)
  const dropdownRef             = useRef(null)

  // Global Ctrl+F1 shortcut → open advanced search modal
  useEffect(() => {
    function onKey(e) {
      if (e.ctrlKey && e.key === 'F1') {
        e.preventDefault()
        if (!disabled) setShowAdvanced(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [disabled])

  // Debounced search via React Query.
  // Strip trailing/leading * so users who type "urosolv*" (ERP habit) still get results.
  // Wildcards in the middle are also stripped — the quick widget uses icontains which
  // already handles partial matches. Full wildcard syntax is available in the advanced modal.
  const [debouncedQ, setDebouncedQ] = useState('')
  useEffect(() => {
    // pos variant keeps * / % (wildcard search rules); the default widget strips them as before.
    const cleaned = isPos ? q.trim() : q.replace(/\*/g, '').trim()
    if (cleaned.replace(/[*%]/g, '').length < 2) { setDebouncedQ(''); return }
    const t = setTimeout(() => setDebouncedQ(cleaned), 280)
    return () => clearTimeout(t)
  }, [q, isPos])

  const { data: found, isFetching } = useQuery({
    queryKey: isPos ? ['item-search-widget', debouncedQ, branchId, 'pos'] : ['item-search-widget', debouncedQ],
    queryFn: () => isPos
      ? itemsApi.wildcardSearch(debouncedQ, branchId, { network: true })
          .then(r => ({ rows: r.data.results || [], asOf: r.data.stock_as_of ?? null }))
      : api.get('/items/', { params: { search: debouncedQ, page_size: 10 } })
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
  useEffect(() => { setSel(0); setPreviewOn(false) }, [debouncedQ, branchId])

  const handleSelect = useCallback((item) => {
    setOpen(false)
    setQ('')
    setDebouncedQ('')
    setPreviewOn(false)
    onSelect(item)
  }, [onSelect])

  const handleAction = useCallback((kind, item, extra) => {
    setOpen(false)
    setQ('')
    setDebouncedQ('')
    setPreviewOn(false)
    onAction?.(kind, item, extra)
  }, [onAction])

  // keep the highlighted row in view while arrowing
  useEffect(() => {
    if (!isPos || !open) return
    dropdownRef.current?.querySelector(`[data-idx="${sel}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [sel, isPos, open, results])

  function onPosKeyDown(e) {
    const listOpen = open && debouncedQ.length >= 2 && results.length > 0
    if (e.key === 'Escape') {
      if (previewOn) { e.preventDefault(); e.stopPropagation(); setPreviewOn(false) }
      else if (open) { e.preventDefault(); e.stopPropagation(); setOpen(false) }
      return
    }
    if (!listOpen) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setPreviewOn(p => !p) }   // physical → key
    else if (e.key === 'Enter') {
      const it = results[Math.min(sel, results.length - 1)]
      if (it) { e.preventDefault(); handleSelect(it) }
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
  if (selected) {
    return (
      <div className={className}>
        <SelectedItemCard item={selected} onClear={handleClear} disabled={disabled} />
        {showAdvanced && (
          <AdvancedItemSearchModal
            onSelect={item => { handleSelect(item); setShowAdvanced(false) }}
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
            onChange={e => { setQ(e.target.value); setOpen(true) }}
            onKeyDown={isPos ? onPosKeyDown : undefined}
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

        {/* Advanced search button (magnifier) */}
        <button
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
          ? 'اسم · كود · باركود · * أو % لأي حروف · ↑↓ تنقّل · Enter إضافة · → معاينة · Esc إغلاق ·'
          : 'اسم · كود · باركود (قارئ ضوئي متوافق) · لا حاجة لـ * (البحث الجزئي تلقائي) ·'}
        <button
          type="button"
          onClick={() => setShowAdvanced(true)}
          disabled={disabled}
          className="text-brand-500 hover:text-brand-700 font-medium disabled:opacity-40"
        >
          🔍 بحث متقدم (Ctrl+F1)
        </button>
        {isPos && hasPosData && <StockAge asOf={stockAsOf} className="ms-auto" />}
      </p>

      {/* Dropdown */}
      {showDropdown && isPos && (
        <div ref={dropdownRef} role="listbox"
             className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 flex overflow-hidden">
          <div className="flex-1 min-w-0 max-h-[34rem] overflow-y-auto">
            {results.length > 0 ? results.map((item, i) => (
              <PosResultRow key={item.softech_id || item.id || i} index={i} item={item}
                hereBranchId={branchId} selected={i === sel}
                onAdd={handleSelect} onAction={handleAction}
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
              <button type="button" onClick={() => handleSelect(results[sel])}
                      className="w-full rounded-lg bg-brand-600 text-white py-2 text-sm font-medium">إضافة للأمر</button>
            </div>
          </div>
        </div>
      )}
      {showDropdown && !isPos && (
        <div
          ref={dropdownRef}
          className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-64 overflow-y-auto"
        >
          {results.length > 0 ? (
            results.map(item => (
              <ResultRow key={item.id} item={item} onSelect={handleSelect} />
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
          onSelect={item => { handleSelect(item); setShowAdvanced(false) }}
          onClose={() => setShowAdvanced(false)}
        />
      )}
    </div>
  )
}
