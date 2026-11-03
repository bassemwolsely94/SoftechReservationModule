/**
 * Explain — the calm on-screen explanation used across PIC Analytics. A one-line plain `hint` is always
 * visible under a card/panel title; «؟ كيف نحسبها» expands 2–5 short `lines` plus one worked `example`
 * in place (no modal). Collapsed by default; open/closed is remembered per `id` in localStorage.
 * Thresholds quoted in the texts must come from the API (data.thresholds), never typed in here.
 */
import { useState } from 'react'

const KEY = id => `pic-explain:${id}`
const read = id => { try { return localStorage.getItem(KEY(id)) === '1' } catch { return false } }
const write = (id, v) => { try { localStorage.setItem(KEY(id), v ? '1' : '0') } catch { /* private mode: stay per-visit */ } }

export default function Explain({ id, hint, lines = [], example, className = '' }) {
  const [open, setOpen] = useState(() => read(id))
  const expandable = lines.length > 0 || !!example
  const toggle = () => { const v = !open; setOpen(v); write(id, v) }
  return (
    <div className={`text-xs text-gray-500 ${className}`}>
      {hint && <span>{hint}</span>}
      {expandable && (
        <>
          {hint && ' '}
          <button type="button" onClick={toggle} aria-expanded={open}
                  className="text-brand-600 hover:underline whitespace-nowrap">
            {open ? '▾' : '؟'} كيف نحسبها
          </button>
        </>
      )}
      {expandable && open && (
        <div className="mt-1.5 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 space-y-1 text-gray-600">
          {lines.map((l, i) => <p key={i}>{l}</p>)}
          {example && <p className="text-gray-700"><span className="font-bold">مثال: </span>{example}</p>}
        </div>
      )}
    </div>
  )
}
