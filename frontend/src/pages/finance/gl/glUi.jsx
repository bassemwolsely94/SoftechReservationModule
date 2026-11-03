/**
 * glUi.jsx — small shared pieces of the general-ledger screens («الحسابات العامة»).
 *
 * The server decides every number (balances, totals, approval). These helpers only
 * format what it returns and read the {code, detail} error shape.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../../../api/client'
import useBranchLabels from '../../../hooks/useBranchLabels'

export const OPENING_DATE = '2026-01-01'

/** Decimal string → "1,234.50"; empty / zero → '' when `blankZero`. Display only. */
export function money(v, { blankZero = false } = {}) {
  if (v === null || v === undefined || v === '') return blankZero ? '' : '0.00'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  if (blankZero && n === 0) return ''
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Ratio as the server sends it (a fraction, 0.2345) → "23.45%". */
export const pct = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? '—'
  : `${(Number(v) * 100).toFixed(2)}%`)

/** Server message for a failed call: {code, detail} → detail; DRF field errors → first one. */
export function errOf(e, fallback = 'تعذّر تنفيذ الطلب') {
  const d = e?.response?.data
  if (!d) return e?.message === 'Network Error' ? 'تعذّر الاتصال بالسيرفر' : fallback
  if (typeof d === 'string') return fallback
  if (d.detail) return String(d.detail)
  const first = Object.values(d).flat()[0]
  return typeof first === 'string' ? first : fallback
}

export const listOf = (data) => (Array.isArray(data) ? data : (data?.results || []))

export const todayIso = () => new Date().toISOString().slice(0, 10)

export async function saveBlob(promise, filename) {
  const res = await promise
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.URL.revokeObjectURL(url)
}

export const STATUS = {
  draft:    { label: 'مسودة',  cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  approved: { label: 'معتمد',  cls: 'bg-green-50 text-green-700 border-green-200' },
  reversed: { label: 'معكوس',  cls: 'bg-gray-100 text-gray-600 border-gray-200' },
}

export const BOOKS = {
  general: 'عام',
  cash:    'نقدي',
  credit:  'آجل',
  opening: 'افتتاحي',
  closing: 'إقفال',
}

export const NATURE = { debit: 'مدين', credit: 'دائن' }

export const SECTION = { balance_sheet: 'الميزانية', trading: 'المتاجرة', pl: 'الأرباح والخسائر' }

export function StatusPill({ status }) {
  const s = STATUS[status] || { label: status || '—', cls: 'bg-gray-50 text-gray-500 border-gray-200' }
  return <span className={`inline-block px-2 py-0.5 rounded-full border text-xs ${s.cls}`}>{s.label}</span>
}

/**
 * Our branches (Django ids, which the ledger stores) with "code · name" labels — never a bare code.
 *   const { branches, labelOf } = useGlBranches()
 */
export function useGlBranches() {
  const bl = useBranchLabels()
  const q = useQuery({
    queryKey: ['branches', 'gl'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => listOf(r.data)),
    staleTime: 30 * 60 * 1000,
  })
  const branches = q.data || []
  const byId = useMemo(() => Object.fromEntries(branches.map(b => [String(b.id), b])), [branches])
  const labelOf = (id, fallbackName) => {
    if (id === null || id === undefined || id === '') return ''
    const b = byId[String(id)]
    if (b) return bl(b.softech_branch_id) || b.name_ar || b.name
    return fallbackName || ''
  }
  return { branches, labelOf }
}

/** A line's account as {code, name} whatever shape the server nests it in. */
export function accountOf(line) {
  const a = line?.account
  if (a && typeof a === 'object') return { code: a.code, name: a.name }
  return { code: line?.account_code ?? a ?? '', name: line?.account_name ?? '' }
}

/** Date-range presets for report filters. */
export function rangeOf(kind, anchor = todayIso()) {
  const [y, m] = anchor.split('-').map(Number)
  const pad = (n) => String(n).padStart(2, '0')
  const last = (yy, mm) => new Date(yy, mm, 0).getDate()
  if (kind === 'month') return { from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last(y, m))}` }
  if (kind === 'quarter') {
    const q0 = Math.floor((m - 1) / 3) * 3 + 1
    return { from: `${y}-${pad(q0)}-01`, to: `${y}-${pad(q0 + 2)}-${pad(last(y, q0 + 2))}` }
  }
  if (kind === 'year') return { from: `${y}-01-01`, to: `${y}-12-31` }
  return null
}

export const inputCls = 'border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-1 focus:ring-green-500'
export const btnCls = 'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
export const btnPrimary = `${btnCls} bg-green-600 text-white border-green-600 hover:bg-green-700`
export const btnPlain = `${btnCls} bg-white text-gray-700 border-gray-300 hover:bg-gray-50`

export function ErrorBox({ children }) {
  if (!children) return null
  return <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 text-sm px-3 py-2">{children}</div>
}

/** Period picker shared by the reports: month / quarter / year / custom. */
export function PeriodPicker({ value, onChange, dataTour }) {
  const { kind, from, to } = value
  const pick = (k) => {
    if (k === 'custom') onChange({ kind: k, from, to })
    else onChange({ kind: k, ...rangeOf(k, from || todayIso()) })
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-tour={dataTour}>
      <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
        {[['month', 'شهر'], ['quarter', 'ربع'], ['year', 'سنة'], ['custom', 'مخصص']].map(([k, l]) => (
          <button key={k} type="button" onClick={() => pick(k)}
                  className={`px-3 py-1.5 ${kind === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{l}</button>
        ))}
      </div>
      <label className="text-xs text-gray-500">من</label>
      <input type="date" className={inputCls} value={from} min={OPENING_DATE}
             onChange={e => onChange({ kind: kind === 'custom' ? 'custom' : kind, ...(kind === 'custom' ? { from: e.target.value, to } : rangeOf(kind, e.target.value)) })} />
      <label className="text-xs text-gray-500">إلى</label>
      <input type="date" className={inputCls} value={to} disabled={kind !== 'custom'}
             onChange={e => onChange({ kind, from, to: e.target.value })} />
    </div>
  )
}
