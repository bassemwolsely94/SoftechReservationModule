/**
 * components/BranchSelect.jsx
 *
 * Searchable branch picker.
 * Supports querying by softech_branch_id, code, or Arabic/English name.
 *
 * Props:
 *   value        – selected branch Django id (string or number); "" = nothing selected
 *   onChange(id) – called with the branch Django id as a string (or "" to clear)
 *   branches     – array of branch objects from the API
 *   placeholder  – text shown when nothing is selected  (default: "اختر الفرع...")
 *   allLabel     – if provided, a first "all" option is shown with this label
 *                  (useful for filter bars, e.g. allLabel="كل الفروع")
 *   className    – extra class(es) on the outer wrapper div
 *   disabled     – boolean
 *   size         – "sm" (filter bars) | "md" (forms, default)
 */
import { useState, useRef, useEffect } from 'react'

export default function BranchSelect({
  value       = '',
  onChange,
  branches    = [],
  placeholder = 'اختر الفرع...',
  allLabel    = null,
  className   = '',
  disabled    = false,
  size        = 'md',
}) {
  const [query,  setQuery]  = useState('')
  const [open,   setOpen]   = useState(false)
  const wrapRef  = useRef()
  const inputRef = useRef()

  const selected = branches.find(b => String(b.id) === String(value)) ?? null

  // Close when clicking outside
  useEffect(() => {
    function onDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  // Filter list
  const filtered = branches.filter(b => {
    if (!query) return true
    const q = query.toLowerCase()
    return (
      b.softech_branch_id?.toLowerCase().includes(q) ||
      b.code?.toLowerCase().includes(q) ||
      b.name?.toLowerCase().includes(q) ||
      (b.name_ar || '').includes(query)
    )
  })

  function openDropdown() {
    if (disabled) return
    setOpen(true)
    setQuery('')
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  function pick(id) {
    onChange(String(id))
    setOpen(false)
    setQuery('')
  }

  function clear(e) {
    e.stopPropagation()
    onChange('')
    setOpen(false)
    setQuery('')
  }

  // ── Sizing ──────────────────────────────────────────────────────────────────
  const fieldCls = size === 'sm'
    ? 'border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm min-h-[34px]'
    : 'input-field min-h-[38px]'

  return (
    <div ref={wrapRef} className={`relative ${className}`}>

      {/* ── Trigger / display ─────────────────────────────────────────────── */}
      <div
        className={`${fieldCls} flex items-center gap-2 cursor-pointer select-none
          ${disabled ? 'bg-gray-50 cursor-not-allowed opacity-60' : 'bg-white'}
          ${open     ? 'border-brand-400 ring-1 ring-brand-200' : ''}
        `}
        onClick={openDropdown}
      >
        {open ? (
          /* Search input */
          <input
            ref={inputRef}
            className="flex-1 outline-none bg-transparent text-sm placeholder-gray-400"
            placeholder="ابحث بالكود أو الاسم..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onClick={e => e.stopPropagation()}
            dir="rtl"
          />
        ) : selected ? (
          /* Selected branch display */
          <>
            <span className="font-mono text-xs text-brand-700 bg-brand-50 border border-brand-100 px-1.5 py-0.5 rounded flex-shrink-0">
              {selected.softech_branch_id}
            </span>
            <span className="flex-1 text-sm text-gray-800 truncate">
              {selected.name_ar || selected.name}
            </span>
            {!disabled && (
              <button
                type="button"
                onMouseDown={clear}
                className="text-gray-300 hover:text-gray-500 flex-shrink-0 leading-none text-xs"
                tabIndex={-1}
              >
                ✕
              </button>
            )}
          </>
        ) : (
          /* Placeholder */
          <>
            <span className="flex-1 text-sm text-gray-400">{placeholder}</span>
            <span className="text-gray-300 text-xs">▼</span>
          </>
        )}
      </div>

      {/* ── Dropdown ──────────────────────────────────────────────────────── */}
      {open && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-64 overflow-y-auto"
          style={{ minWidth: '220px' }}>

          {/* "All" option */}
          {allLabel && (
            <div
              className={`flex items-center gap-2 px-3 py-2.5 cursor-pointer hover:bg-gray-50 border-b border-gray-100
                ${value === '' ? 'font-semibold text-brand-700 bg-brand-50' : 'text-gray-600'}`}
              onMouseDown={() => pick('')}
            >
              <span className="text-sm">{allLabel}</span>
            </div>
          )}

          {/* Branch options */}
          {filtered.length === 0 ? (
            <div className="px-4 py-3 text-sm text-gray-400 text-center">لا توجد نتائج</div>
          ) : filtered.map(b => (
            <div
              key={b.id}
              className={`flex items-center gap-2.5 px-3 py-2.5 cursor-pointer hover:bg-brand-50
                border-b border-gray-50 last:border-0 transition-colors
                ${String(b.id) === String(value) ? 'bg-brand-50' : ''}`}
              onMouseDown={() => pick(b.id)}
            >
              <span className="font-mono text-xs text-brand-700 bg-brand-50 border border-brand-100 px-1.5 py-0.5 rounded flex-shrink-0">
                {b.softech_branch_id}
              </span>
              <span className="text-sm text-gray-800 flex-1">{b.name_ar || b.name}</span>
              {String(b.id) === String(value) && (
                <span className="text-brand-500 text-xs">✓</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
