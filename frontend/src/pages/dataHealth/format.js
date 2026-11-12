/** Shared formatting for the /data-health tabs (data lifecycle Stage 5). Display only. */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** 1536 → "1.5 KB"; null / undefined → "—". Negative values (a shrink) keep their sign. */
export function fmtBytes(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  let abs = Math.abs(n)
  let i = 0
  while (abs >= 1024 && i < UNITS.length - 1) { abs /= 1024; i += 1 }
  const digits = i === 0 || abs >= 100 ? 0 : 1
  return `${n < 0 ? '-' : ''}${abs.toLocaleString('en-US', { maximumFractionDigits: digits })} ${UNITS[i]}`
}

/** A growth figure with an explicit + for growth; null → "—". */
export function fmtGrowth(value) {
  if (value == null) return '—'
  return value > 0 ? `+${fmtBytes(value)}` : fmtBytes(value)
}

export const fmtInt = v => (v == null ? '—' : Number(v).toLocaleString('en-US'))

/** ISO date or datetime → "12/11/2026" (dates) or "12/11/2026, 09:30" (datetimes); null → "—". */
export function fmtDate(value, withTime = false) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return withTime
    ? d.toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })
    : d.toLocaleDateString('en-GB')
}

export const errText = e => e?.response?.data?.detail || 'حدث خطأ — حاول مرة أخرى'

export const TH = 'text-right px-3 py-2 text-xs text-gray-500 font-semibold whitespace-nowrap'
export const TD = 'px-3 py-2 text-sm'
