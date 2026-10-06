/**
 * supplyUi.jsx — small shared pieces for the /supply orchestration tabs (doc 24).
 * Display only: every number shown here was computed by the backend engine.
 * Latin digits throughout (module-wide convention — no Arabic-Indic numerals).
 */

const TONES = {
  gray:    'bg-gray-100 text-gray-700 border-gray-200',
  blue:    'bg-blue-100 text-blue-800 border-blue-200',
  indigo:  'bg-indigo-100 text-indigo-800 border-indigo-200',
  amber:   'bg-amber-100 text-amber-800 border-amber-200',
  rose:    'bg-rose-100 text-rose-700 border-rose-200',
  emerald: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  teal:    'bg-teal-100 text-teal-800 border-teal-200',
  violet:  'bg-violet-100 text-violet-800 border-violet-200',
}

export function Chip({ tone = 'gray', children, title }) {
  return (
    <span title={title}
      className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${TONES[tone] || TONES.gray}`}>
      {children}
    </span>
  )
}

export const CASE_STATUS_TONE = {
  detected: 'gray', searching: 'blue', availability_found: 'emerald',
  awaiting_decision: 'amber', transfer_pending: 'indigo', ordered: 'violet',
  partially_fulfilled: 'amber', received: 'teal', fulfilled: 'emerald', cancelled: 'gray',
}

export const TRANSITION_LABEL = {
  transfer_pending: 'تحويل قيد التنفيذ', ordered: 'تم الطلب', partially_fulfilled: 'مُلبّى جزئياً',
  received: 'تم الاستلام', fulfilled: 'مُلبّى ✅', cancelled: 'إلغاء',
}

// Quantity: whole numbers without decimals, else up to 2 — always Latin digits.
export function q(v) {
  if (v === null || v === undefined || v === '') return '—'
  const x = Number(v)
  if (!Number.isFinite(x)) return '—'
  return Math.abs(x - Math.round(x)) < 0.001 ? String(Math.round(x)) : x.toFixed(2).replace(/\.?0+$/, '')
}

export function money(v) {
  if (v === null || v === undefined || v === '') return '—'
  const x = Number(v)
  return Number.isFinite(x) ? x.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'
}

export function pct(v) {
  if (v === null || v === undefined) return '—'
  return `${Math.round(Number(v) * 100)}%`
}

export function fmtDate(d) {
  if (!d) return '—'
  try {
    return new Date(d).toLocaleString('en-GB', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return String(d).slice(0, 16) }
}

export function errText(err, fallback = 'تعذّر تنفيذ العملية') {
  return err?.response?.data?.detail || fallback
}

// One key per user action — a double-click / retry replays the first result server-side.
export function newKey() {
  try { return crypto.randomUUID() } catch { return `${Date.now()}-${Math.random().toString(16).slice(2)}` }
}

export function downloadBlob(data, filename) {
  const url = window.URL.createObjectURL(new Blob([data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export const inputCls = 'border border-line rounded px-2 py-1 text-sm bg-surface text-content'
export const btnPrimary = 'px-3 py-1.5 rounded bg-primary text-white text-sm font-medium disabled:opacity-50'
export const btnGhost = 'px-3 py-1.5 rounded border border-line text-sm text-content hover:border-primary/50 disabled:opacity-50'
