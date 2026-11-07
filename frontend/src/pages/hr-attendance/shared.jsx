/**
 * Small helpers shared by the attendance tabs. Display only — the server decides every rule
 * (who may see or change what, which punches count, what a day is).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../../api/client'

/** Branches for BranchSelect (same query key as useBranchLabels, so one fetch). */
export function useBranchList() {
  const q = useQuery({
    queryKey: ['branch-labels'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
  })
  const d = q.data
  return Array.isArray(d) ? d : (d?.results || [])
}

/** The text of an error whose body is a Blob (a failed file download): read it, then parse the JSON. */
export async function blobErrText(e) {
  const data = e?.response?.data
  if (data && typeof data.text === 'function') {
    try {
      const parsed = JSON.parse(await data.text())
      return errText({ response: { data: parsed } })
    } catch { /* not JSON */ }
  }
  return errText(e)
}

/** Only the fields that changed: '' becomes null for the nullable ones. */
export function changedFields(form, original, nullable = []) {
  const out = {}
  Object.keys(form).forEach(k => {
    const cur = form[k] ?? ''
    const was = original[k] ?? ''
    if (String(cur) !== String(was)) out[k] = cur === '' && nullable.includes(k) ? null : cur
  })
  return out
}

export const inputCls = 'mt-0.5 w-full border border-gray-200 rounded-md px-2 py-1 text-sm bg-white'
export function Field({ label, children }) {
  return <label className="flex flex-col text-xs text-gray-500">{label}{children}</label>
}

export function errText(e) {
  const d = e?.response?.data
  if (!d) return 'حدث خطأ — حاول مرة أخرى'
  if (typeof d === 'string') return d
  if (d.detail) return String(d.detail)
  const first = Object.values(d).flat()[0]
  return typeof first === 'string' ? first : 'حدث خطأ — حاول مرة أخرى'
}

// Datetimes arrive as local wall-clock ISO strings; read the clock part as written (no timezone shift).
export const clock = v => (v ? String(v).slice(11, 16) : '—')
export const stamp = v => (v ? new Date(v).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—')
export const hours = v => (v == null || v === '' ? '—' : Number(v).toFixed(2))
export const hm = minutes => {
  if (minutes == null) return '—'
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`
}
export const isoDay = d => {
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
export const thisMonth = () => isoDay(new Date()).slice(0, 7)

export const WEEKDAY = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
export const weekdayOf = iso => WEEKDAY[new Date(`${iso}T00:00:00`).getDay()]

export function download(res, name) {
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export function Notice({ kind = 'error', children }) {
  if (!children) return null
  const cls = kind === 'error' ? 'text-red-600' : 'text-emerald-700'
  return <span className={`text-xs ${cls}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</span>
}

export function Empty({ children }) {
  return <div className="py-10 text-center text-sm text-gray-400">{children}</div>
}

/** An inline "reason" row: the text a decision needs, then confirm / cancel. No modal. */
export function ReasonRow({ placeholder = 'السبب (مطلوب)', confirmLabel, onConfirm, onCancel, busy, error, children }) {
  const [reason, setReason] = useState('')
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {children}
      <input value={reason} onChange={e => setReason(e.target.value)} placeholder={placeholder} maxLength={255}
        className="flex-1 min-w-[10rem] border border-gray-200 rounded-md px-2 py-1 bg-white" />
      <button type="button" disabled={busy || !reason.trim()} onClick={() => onConfirm(reason.trim())}
        className="px-2.5 py-1 rounded-md bg-primary text-white font-bold disabled:opacity-50">{confirmLabel}</button>
      <button type="button" onClick={onCancel} className="px-2 py-1 rounded-md text-gray-500 hover:bg-gray-100">إلغاء</button>
      <Notice>{error}</Notice>
    </div>
  )
}

export const TH = 'px-3 py-2 text-start font-semibold whitespace-nowrap'
export const BTN = 'px-2.5 py-1 rounded-md text-xs font-bold disabled:opacity-50'
