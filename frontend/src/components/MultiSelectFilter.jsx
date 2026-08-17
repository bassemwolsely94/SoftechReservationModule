/**
 * MultiSelectFilter.jsx
 *
 * Compact searchable multi-select dropdown for filter panels (RTL).
 *   options  : [{ code, name }]
 *   selected : array of codes
 *   onChange : (codes[]) => void
 */
import { useState, useRef, useEffect } from 'react'

export default function MultiSelectFilter({ label, options = [], selected = [], onChange, placeholder = 'الكل' }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const toggle = (code) => {
    onChange(selected.includes(code) ? selected.filter(c => c !== code) : [...selected, code])
  }

  const q = search.trim().toLowerCase()
  const filtered = q
    ? options.filter(o => (o.name || '').toLowerCase().includes(q) || String(o.code).toLowerCase().includes(q))
    : options

  const summary = selected.length === 0
    ? placeholder
    : selected.length === 1
      ? (options.find(o => o.code === selected[0])?.name ?? selected[0])
      : `${selected.length} محدد`

  return (
    <div className="relative" ref={ref}>
      {label && <label className="text-xs text-gray-500 block mb-1">{label}</label>}
      <button type="button" onClick={() => setOpen(o => !o)}
        className={`input-field w-full text-sm text-right flex items-center justify-between ${selected.length ? 'text-gray-900' : 'text-gray-400'}`}>
        <span className="truncate">{summary}</span>
        <span className="text-gray-400 text-xs ml-1">▾</span>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-72 overflow-hidden flex flex-col">
          <div className="p-2 border-b border-gray-100">
            <input autoFocus value={search} onChange={e => setSearch(e.target.value)}
              placeholder="بحث..." className="input-field w-full text-sm" />
          </div>
          {selected.length > 0 && (
            <button onClick={() => onChange([])}
              className="text-xs text-red-500 hover:bg-red-50 px-3 py-1.5 text-right border-b border-gray-100">
              مسح التحديد ({selected.length})
            </button>
          )}
          <div className="overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-gray-400 text-center">لا نتائج</div>
            ) : filtered.slice(0, 200).map(o => (
              <label key={o.code} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 cursor-pointer">
                <input type="checkbox" checked={selected.includes(o.code)} onChange={() => toggle(o.code)} />
                <span className="truncate">{o.name}</span>
                <span className="text-gray-300 text-xs mr-auto font-mono">{o.code}</span>
              </label>
            ))}
            {filtered.length > 200 && (
              <div className="px-3 py-2 text-xs text-gray-400 text-center">
                +{filtered.length - 200} أخرى — ضيّق البحث
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
