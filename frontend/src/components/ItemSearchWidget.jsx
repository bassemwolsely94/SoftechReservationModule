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
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import AdvancedItemSearchModal from './AdvancedItemSearchModal'

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
}) {
  const [q, setQ]               = useState('')
  const [open, setOpen]         = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
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
    const cleaned = q.replace(/\*/g, '').trim()
    if (cleaned.length < 2) { setDebouncedQ(''); return }
    const t = setTimeout(() => setDebouncedQ(cleaned), 280)
    return () => clearTimeout(t)
  }, [q])

  const { data: results = [], isFetching } = useQuery({
    queryKey: ['item-search-widget', debouncedQ],
    queryFn: () =>
      api.get('/items/', { params: { search: debouncedQ, page_size: 10 } })
        .then(r => r.data.results || r.data),
    enabled: debouncedQ.length >= 2,
    staleTime: 15_000,
    keepPreviousData: true,
  })

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

  const handleSelect = useCallback((item) => {
    setOpen(false)
    setQ('')
    setDebouncedQ('')
    onSelect(item)
  }, [onSelect])

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
        اسم · كود · باركود (قارئ ضوئي متوافق) · لا حاجة لـ * (البحث الجزئي تلقائي) ·
        <button
          type="button"
          onClick={() => setShowAdvanced(true)}
          disabled={disabled}
          className="text-brand-500 hover:text-brand-700 font-medium disabled:opacity-40"
        >
          🔍 بحث متقدم (Ctrl+F1)
        </button>
      </p>

      {/* Dropdown */}
      {showDropdown && (
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
