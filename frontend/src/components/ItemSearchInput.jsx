/**
 * ItemSearchInput.jsx
 *
 * SOFTECH-style wildcard item search with debounce.
 *
 * Features:
 *   • Supports * wildcard anywhere: "pan*500", "*cillin", "am*"
 *   • Falls back to PG catalog when SOFTECH is unavailable
 *   • Shows: item name, scientific name, stock at branch (optional)
 *   • Keyboard navigation (↑↓ Enter Esc)
 *   • Renders as a fully controlled dropdown
 *
 * Props:
 *   value        {string}   — current text value
 *   onChange     {fn}       — (text) => void
 *   onSelect     {fn}       — (item) => void  item = { softech_id, name, name_scientific, unit_sale_price, item_id, qty_at_branch, source }
 *   branchId     {number}   — if given, shows stock at that branch
 *   placeholder  {string}
 *   disabled     {bool}
 *   className    {string}
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { itemsApi } from '../api/client'

const DEBOUNCE_MS = 300

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

export default function ItemSearchInput({
  value = '',
  onChange,
  onSelect,
  branchId = null,
  placeholder = 'ابحث عن صنف... (يدعم * مثل: pan*، *cillin)',
  disabled = false,
  className = '',
}) {
  const [results, setResults]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [open, setOpen]         = useState(false)
  const [highlighted, setHL]    = useState(0)
  const [error, setError]       = useState('')
  const inputRef                = useRef(null)
  const listRef                 = useRef(null)
  const debouncedQ              = useDebounce(value, DEBOUNCE_MS)

  // Search when debounced query changes
  useEffect(() => {
    const q = (debouncedQ || '').trim()
    if (q.length < 2) {
      setResults([])
      setOpen(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')

    itemsApi.wildcardSearch(q, branchId)
      .then(({ data }) => {
        if (cancelled) return
        setResults(data.results || [])
        setOpen(true)
        setHL(0)
      })
      .catch(() => {
        if (cancelled) return
        setError('تعذّر البحث — تحقق من الاتصال')
        setResults([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [debouncedQ, branchId])

  // Keyboard navigation
  const handleKey = useCallback((e) => {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHL(h => Math.min(h + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHL(h => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (results[highlighted]) pick(results[highlighted])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }, [open, results, highlighted])

  // Scroll highlighted item into view
  useEffect(() => {
    if (listRef.current) {
      const el = listRef.current.children[highlighted]
      el?.scrollIntoView({ block: 'nearest' })
    }
  }, [highlighted])

  const pick = (item) => {
    onSelect?.(item)
    onChange?.(item.name)
    setOpen(false)
    setResults([])
    inputRef.current?.blur()
  }

  const stockBadge = (qty) => {
    if (qty === null || qty === undefined) return null
    const color = qty >= 5 ? 'bg-green-100 text-green-800'
                : qty > 0  ? 'bg-yellow-100 text-yellow-800'
                           : 'bg-red-100 text-red-800'
    const label = qty >= 5 ? 'متوفر' : qty > 0 ? 'محدود' : 'نفد'
    return (
      <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${color}`}>
        {qty > 0 ? `${qty} ${label}` : label}
      </span>
    )
  }

  return (
    <div className={`relative ${className}`} dir="rtl">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={e => { onChange?.(e.target.value); setOpen(true) }}
          onKeyDown={handleKey}
          onFocus={() => { if (results.length > 0) setOpen(true) }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          className={`w-full border rounded-lg px-3 py-2 text-sm pr-9 focus:outline-none focus:ring-2 focus:ring-brand-400 focus:border-brand-400 disabled:bg-gray-50 disabled:text-gray-400 ${error ? 'border-red-400' : 'border-gray-300'}`}
        />
        {/* Search icon / spinner */}
        <div className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          {loading
            ? <span className="w-4 h-4 border-2 border-brand-300 border-t-brand-600 rounded-full animate-spin inline-block" />
            : <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
          }
        </div>
        {/* Clear button */}
        {value && !disabled && (
          <button
            type="button"
            onMouseDown={e => { e.preventDefault(); onChange?.(''); setResults([]); setOpen(false) }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Wildcard hint */}
      {!open && !loading && (
        <p className="text-xs text-gray-400 mt-0.5">
          يدعم الحرف البديل (*) — مثال: <span className="font-mono">pan*</span>، <span className="font-mono">*cillin</span>، <span className="font-mono">am*500</span>
        </p>
      )}

      {/* Error */}
      {error && <p className="text-xs text-red-500 mt-0.5">{error}</p>}

      {/* Dropdown */}
      {open && results.length > 0 && (
        <ul
          ref={listRef}
          className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg max-h-72 overflow-y-auto text-sm"
        >
          {results.map((item, i) => (
            <li
              key={item.softech_id || i}
              onMouseDown={e => { e.preventDefault(); pick(item) }}
              className={`px-3 py-2.5 cursor-pointer border-b last:border-0 transition-colors ${i === highlighted ? 'bg-brand-50' : 'hover:bg-gray-50'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-900 truncate">{item.name}</div>
                  {item.name_scientific && (
                    <div className="text-xs text-gray-500 truncate italic">{item.name_scientific}</div>
                  )}
                  <div className="flex items-center gap-2 mt-0.5">
                    {item.softech_id && (
                      <span className="text-xs text-gray-400 font-mono">{item.softech_id}</span>
                    )}
                    {item.source === 'pg_catalog' && (
                      <span className="text-xs text-gray-300 bg-gray-100 px-1 rounded">قاعدة البيانات</span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {item.unit_sale_price > 0 && (
                    <span className="text-xs font-semibold text-brand-700">
                      {Number(item.unit_sale_price).toFixed(2)} ج.م
                    </span>
                  )}
                  {branchId && stockBadge(item.qty_at_branch)}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {open && !loading && results.length === 0 && (value || '').length >= 2 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3 text-sm text-gray-500 text-center">
          لا توجد نتائج — جرّب استخدام * للبحث الموسّع
        </div>
      )}
    </div>
  )
}
