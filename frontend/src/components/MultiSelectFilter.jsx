/**
 * MultiSelectFilter.jsx
 *
 * Compact searchable multi-select dropdown for filter panels (RTL).
 *   options  : [{ code, name }]
 *   selected : array of codes
 *   onChange : (codes[]) => void
 *   showCode : show the code beside each name (default true)
 *   menuClassName : extra classes for the open list (e.g. 'min-w-[420px]' for long names)
 *   allLabel : summary text when nothing is ticked (alias of placeholder)
 *
 * Nothing ticked = no filter ("الكل"). «تحديد الظاهر» ticks every option the search shows.
 */
import { useState, useRef, useEffect } from 'react'
import { wildcardMatch } from '../utils/wildcard'

export default function MultiSelectFilter({ label, options = [], selected = [], onChange, placeholder = 'الكل',
  allLabel, showCode = true, menuClassName = '', disabled = false, className = '', dataTour }) {
  const none = allLabel ?? placeholder
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [])

  const toggle = (code) => {
    onChange(selected.includes(code) ? selected.filter(c => c !== code) : [...selected, code])
  }

  const q = search.trim().toLowerCase()
  const filtered = q
    ? options.filter(o => wildcardMatch(o.name, q) || String(o.code).toLowerCase().includes(q))
    : options

  const tickShown = () => {
    const add = filtered.slice(0, 200).map(o => o.code).filter(c => !selected.includes(c))
    if (add.length) onChange([...selected, ...add])
  }

  const summary = selected.length === 0
    ? none
    : selected.length === 1
      ? (options.find(o => o.code === selected[0])?.name ?? selected[0])
      : `${selected.length} محدد`

  return (
    <div className={`relative ${className}`} ref={ref} data-tour={dataTour}>
      {label && <label className="text-xs text-gray-500 block mb-1">{label}</label>}
      <button type="button" disabled={disabled} onClick={() => setOpen(o => !o)} aria-expanded={open}
        title={selected.length > 1 ? options.filter(o => selected.includes(o.code)).map(o => o.name).join('، ') : undefined}
        className={`input-field w-full text-sm text-right flex items-center justify-between disabled:opacity-50 ${selected.length ? 'text-gray-900 font-medium' : 'text-gray-400'}`}>
        <span className="truncate">{summary}</span>
        <span className="text-gray-400 text-xs ml-1">▾</span>
      </button>
      {open && (
        <div className={`absolute z-30 mt-1 w-full ${menuClassName} max-w-[calc(100vw-2rem)] bg-white border border-gray-200 rounded-lg shadow-lg max-h-80 overflow-hidden flex flex-col`}>
          <div className="p-2 border-b border-gray-100">
            <input autoFocus value={search} onChange={e => setSearch(e.target.value)}
              placeholder="بحث..." className="input-field w-full text-sm" />
          </div>
          <div className="flex items-center justify-between border-b border-gray-100 text-xs">
            <button type="button" onClick={tickShown} disabled={!filtered.length}
              className="text-blue-600 hover:bg-blue-50 px-3 py-1.5 disabled:opacity-40">
              تحديد الظاهر ({Math.min(filtered.length, 200)})
            </button>
            {selected.length > 0 && (
              <button type="button" onClick={() => onChange([])}
                className="text-red-500 hover:bg-red-50 px-3 py-1.5">
                مسح التحديد ({selected.length})
              </button>
            )}
          </div>
          <div className="overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-gray-400 text-center">لا نتائج</div>
            ) : filtered.slice(0, 200).map(o => (
              <label key={o.code} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 cursor-pointer">
                <input type="checkbox" checked={selected.includes(o.code)} onChange={() => toggle(o.code)} />
                <span className={showCode ? 'truncate' : ''}>{o.name}</span>
                {showCode && <span className="text-gray-300 text-xs mr-auto font-mono">{o.code}</span>}
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
