/**
 * CustomerSearchWidget.jsx
 *
 * Shared customer/PIC search picker.
 * Used by: NewReservationPage, DemandPage, VouchersPage, CallCenterPage, and any other
 * module that needs to attach a customer to a record.
 *
 * Props:
 *   selected     — customer object | null  { id, name, phone, softech_pic, customer_type_label }
 *   onSelect     — (customer | null) => void
 *   placeholder  — string (default: 'ابحث بالاسم أو الهاتف أو كود PIC...')
 *   allowManual  — bool: show "enter phone manually" fallback for walk-ins not in system
 *   required     — bool: show asterisk on no-result hint
 *   className    — extra wrapper classes
 *   disabled     — bool
 */
import { useState, useRef, useEffect } from 'react'
import { customersApi } from '../api/client'

function PersonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-50 shrink-0">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
      <circle cx="12" cy="7" r="4"/>
    </svg>
  )
}

// ── Selected customer card ─────────────────────────────────────────────────────

function SelectedCard({ customer, onClear, disabled }) {
  return (
    <div className="flex items-start justify-between gap-3 bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-3">
      <div className="flex-1 min-w-0 space-y-1">
        <div className="font-bold text-sm text-indigo-900 leading-snug">{customer.name}</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {customer.phone && (
            <a
              href={`tel:${customer.phone}`}
              className="inline-flex items-center gap-1 text-[11px] text-gray-600 bg-white border border-gray-200 px-2 py-0.5 rounded hover:bg-gray-50"
              onClick={e => e.stopPropagation()}
            >
              📞 {customer.phone}
            </a>
          )}
          {customer.softech_pic && (
            <span className="inline-flex items-center gap-1 text-[11px] font-mono font-bold text-indigo-700 bg-indigo-100 border border-indigo-200 px-2 py-0.5 rounded">
              PIC: {customer.softech_pic}
            </span>
          )}
          {customer.customer_type_label && (
            <span className="text-[11px] text-gray-500 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded">
              {customer.customer_type_label}
            </span>
          )}
        </div>
      </div>
      {!disabled && (
        <button
          type="button"
          onClick={onClear}
          className="flex-shrink-0 text-xs text-gray-400 hover:text-red-500 transition-colors mt-0.5 font-medium"
          title="تغيير العميل"
        >
          ✕ تغيير
        </button>
      )}
    </div>
  )
}

// ── Result row ────────────────────────────────────────────────────────────────

function ResultRow({ customer, onSelect }) {
  return (
    <div
      className="px-3 py-2.5 hover:bg-indigo-50 cursor-pointer border-b border-gray-50 last:border-0 transition-colors"
      onMouseDown={e => { e.preventDefault(); onSelect(customer) }}
    >
      <div className="font-semibold text-sm text-gray-900 leading-snug">{customer.name}</div>
      <div className="flex flex-wrap items-center gap-2 mt-0.5">
        {customer.phone && (
          <span className="text-[11px] text-gray-500 font-mono">{customer.phone}</span>
        )}
        {customer.softech_pic && (
          <span className="text-[11px] font-mono text-indigo-600">PIC: {customer.softech_pic}</span>
        )}
        {customer.customer_type_label && (
          <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
            {customer.customer_type_label}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main widget ───────────────────────────────────────────────────────────────

export default function CustomerSearchWidget({
  selected     = null,
  onSelect,
  placeholder  = 'ابحث بالاسم أو الهاتف أو كود PIC...',
  allowManual  = false,
  required     = false,
  className    = '',
  disabled     = false,
}) {
  const [query,       setQuery]       = useState('')
  const [results,     setResults]     = useState([])
  const [searching,   setSearching]   = useState(false)
  const [open,        setOpen]        = useState(false)
  const [manualMode,  setManualMode]  = useState(false)
  const [manualPhone, setManualPhone] = useState('')
  const debounceRef = useRef(null)
  const inputRef    = useRef(null)
  const dropRef     = useRef(null)

  useEffect(() => {
    if (query.length < 2) { setResults([]); setOpen(false); return }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await customersApi.list({ search: query, page_size: 10 })
        setResults(r.data.results || r.data)
        setOpen(true)
      } catch { setResults([]) }
      finally { setSearching(false) }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query])

  // Close on outside click
  useEffect(() => {
    function handler(e) {
      if (
        dropRef.current && !dropRef.current.contains(e.target) &&
        inputRef.current && !inputRef.current.contains(e.target)
      ) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleSelect(c) {
    onSelect(c)
    setQuery('')
    setResults([])
    setOpen(false)
  }

  function handleClear() {
    onSelect(null)
    setQuery('')
    setResults([])
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  function confirmManual() {
    if (!manualPhone.trim()) return
    onSelect({ id: null, name: 'عميل غير مسجل', phone: manualPhone.trim(), softech_pic: null })
    setManualMode(false)
    setManualPhone('')
  }

  if (selected) {
    return (
      <div className={className}>
        <SelectedCard customer={selected} onClear={handleClear} disabled={disabled} />
      </div>
    )
  }

  if (allowManual && manualMode) {
    return (
      <div className={`space-y-2 ${className}`}>
        <input
          className="input-field w-full"
          value={manualPhone}
          onChange={e => setManualPhone(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') confirmManual() }}
          placeholder="01xxxxxxxxx"
          dir="ltr"
          autoFocus
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={confirmManual}
            disabled={!manualPhone.trim()}
            className="btn-primary text-xs py-1.5 px-4 disabled:opacity-40"
          >
            تأكيد الرقم
          </button>
          <button
            type="button"
            onClick={() => setManualMode(false)}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            ← البحث بدلاً من ذلك
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={`relative ${className}`} dir="rtl">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          className="input-field w-full ps-9 disabled:bg-gray-100 disabled:cursor-not-allowed"
          placeholder={placeholder}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => { if (results.length > 0) setOpen(true) }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          disabled={disabled}
          autoComplete="off"
        />
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          <PersonIcon />
        </span>
        {searching && (
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2">
            <span className="w-3.5 h-3.5 border-2 border-brand-200 border-t-brand-500 rounded-full animate-spin block" />
          </span>
        )}
      </div>

      {/* Dropdown */}
      {open && (
        <div
          ref={dropRef}
          className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-56 overflow-y-auto"
        >
          {results.length > 0 ? (
            results.map(c => (
              <ResultRow key={c.id} customer={c} onSelect={handleSelect} />
            ))
          ) : !searching ? (
            <div className="px-4 py-3 text-sm text-gray-400 text-center space-y-1">
              <div>لا توجد نتائج</div>
              {allowManual && (
                <button
                  type="button"
                  onMouseDown={e => { e.preventDefault(); setManualMode(true); setOpen(false) }}
                  className="text-xs text-indigo-600 hover:underline block w-full"
                >
                  أدخل رقم الهاتف يدوياً ←
                </button>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* Footer hint */}
      {!query && (
        <p className="text-[11px] text-gray-400 mt-1 flex items-center gap-1">
          <PersonIcon />
          {required ? 'مطلوب — ' : ''}
          اسم · هاتف · كود PIC
          {allowManual && (
            <>
              {' · '}
              <button
                type="button"
                onClick={() => setManualMode(true)}
                disabled={disabled}
                className="text-indigo-500 hover:text-indigo-700 font-medium disabled:opacity-40"
              >
                أدخل هاتف يدوياً
              </button>
            </>
          )}
        </p>
      )}
    </div>
  )
}
