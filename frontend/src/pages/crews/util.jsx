/** Shared bits of the /crews tabs (crews piece 2a). Display only — the server decides every rule. */
import { useMemo, useState } from 'react'

const pad = n => String(n).padStart(2, '0')
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** Local today / first of this month / N days ago as YYYY-MM-DD. */
export const todayIso = () => iso(new Date())
export const monthStartIso = () => { const d = new Date(); d.setDate(1); return iso(d) }
export const daysAgoIso = n => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d) }

/** ISO date → "13/11/2026"; datetime → with time; empty → "—". */
export function fmtDate(value, withTime = false) {
  if (!value) return '—'
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(d.getTime())) return '—'
  return withTime ? d.toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : d.toLocaleDateString('en-GB')
}

export const fmtInt = v => (v == null ? '—' : Number(v).toLocaleString('en-US'))
export const fmtMoney = v => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }))
export const fmtShare = v => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)

/** The server's refusal: {detail} or serializer field errors, joined. */
export function errText(e) {
  const d = e?.response?.data
  if (!d) return e ? 'حدث خطأ — حاول مرة أخرى' : ''
  if (typeof d === 'string') return 'حدث خطأ — حاول مرة أخرى'
  if (d.detail) return d.detail
  return Object.values(d).flat().map(x => (typeof x === 'string' ? x : JSON.stringify(x))).join(' · ')
}

export const TH = 'text-right px-3 py-2 text-xs text-gray-500 font-semibold whitespace-nowrap'
export const TD = 'px-3 py-2 text-sm'
export const INPUT = 'border border-gray-300 rounded-md px-2 py-1 text-sm bg-white'
export const BTN = 'px-3 py-1.5 rounded-md text-sm border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50'
export const BTN_PRIMARY = 'px-3 py-1.5 rounded-md text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50'

export const STATUS = {
  active: { label: 'سارية', cls: 'bg-emerald-50 text-emerald-700' },
  future: { label: 'تبدأ لاحقًا', cls: 'bg-blue-50 text-blue-700' },
  ended:  { label: 'منتهية', cls: 'bg-gray-100 text-gray-500' },
  voided: { label: 'ملغاة', cls: 'bg-gray-100 text-gray-500 line-through' },
}

export function StatusChip({ status }) {
  const s = STATUS[status] || { label: status, cls: 'bg-gray-100 text-gray-600' }
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs whitespace-nowrap ${s.cls}`}>{s.label}</span>
}

/** Rows that no longer apply stay visible, faded. */
export const isFaded = row => row.status === 'ended' || row.status === 'voided'

export function OffPayrollBadge() {
  return <span className="ms-1 inline-block rounded bg-amber-50 text-amber-800 px-1.5 py-0.5 text-[11px] whitespace-nowrap">خارج كشف الرواتب</span>
}

/**
 * ChipPicker — a multi-select shown as chips. Picked values show as removable chips; typing filters
 * the remaining options, shown as clickable chips under the box. No popup.
 *   options: [{ value, label }]
 */
export function ChipPicker({ label, options, value, onChange, disabled = false, limit = 30 }) {
  const [q, setQ] = useState('')
  const picked = new Set(value)
  const byValue = useMemo(() => Object.fromEntries(options.map(o => [String(o.value), o.label])), [options])
  const rest = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const taken = new Set(value)
    return options.filter(o => !taken.has(o.value) && (!needle || String(o.label).toLowerCase().includes(needle)))
  }, [options, value, q])
  const toggle = v => onChange(picked.has(v) ? value.filter(x => x !== v) : [...value, v])
  return (
    <div className="space-y-1">
      <div className="text-xs font-semibold text-gray-600">{label}</div>
      <div className="flex flex-wrap gap-1">
        {value.length === 0 && <span className="text-xs text-gray-400">الكل (بلا شرط)</span>}
        {value.map(v => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-brand-50 text-brand-800 px-2 py-0.5 text-xs">
            {byValue[String(v)] || v}
            {!disabled && (
              <button type="button" onClick={() => toggle(v)} className="text-brand-700 hover:text-red-600" aria-label="إزالة">×</button>
            )}
          </span>
        ))}
      </div>
      {!disabled && (
        <>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث…" className={`${INPUT} w-full`} />
          <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
            {rest.slice(0, limit).map(o => (
              <button key={o.value} type="button" onClick={() => toggle(o.value)}
                      className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-700 hover:bg-gray-50">
                + {o.label}
              </button>
            ))}
            {rest.length > limit && <span className="text-xs text-gray-400">… اكتب للبحث ({rest.length - limit} أخرى)</span>}
          </div>
        </>
      )}
    </div>
  )
}
