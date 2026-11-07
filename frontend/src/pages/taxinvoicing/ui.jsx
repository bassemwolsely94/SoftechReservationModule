/**
 * Shared pieces of the Tax Invoicing screens (doc 36). Display only: every rule lives on the server,
 * and a refused action comes back here as its `detail` and `issues`.
 */
import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useSortableRows from '../../hooks/useSortableRows'

export const fmt = (v, d = 2) => (v == null || v === '' ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }))
export const fmtInt = v => Number(v || 0).toLocaleString('en-US')
export const fmtTime = v => (v ? new Date(v).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—')
export const fmtDate = v => (v ? String(v).slice(0, 10) : '—')
export const errText = e => e?.response?.data?.detail || 'حدث خطأ، حاول مرة أخرى'

export const INPUT = 'border border-gray-200 rounded-md px-2 py-1 text-sm bg-white disabled:bg-gray-50 disabled:text-gray-500'

export const DOC_STATUS_TONE = {
  draft: 'bg-gray-100 text-gray-700 border-gray-200',
  approved: 'bg-sky-50 text-sky-700 border-sky-200',
  submitting: 'bg-amber-50 text-amber-800 border-amber-200',
  uncertain: 'bg-amber-50 text-amber-800 border-amber-300',
  submitted: 'bg-sky-50 text-sky-700 border-sky-200',
  valid: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  invalid: 'bg-red-50 text-red-700 border-red-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
}
export const LINE_STATUS_TONE = {
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  exempt: 'bg-sky-50 text-sky-700 border-sky-200',
  uncoded: 'bg-red-50 text-red-700 border-red-200',
  pending: 'bg-amber-50 text-amber-800 border-amber-200',
  excluded: 'bg-gray-100 text-gray-600 border-gray-200',
}
export const RECEIPT_STATUS_TONE = {
  held: 'bg-amber-50 text-amber-800 border-amber-200',
  by_invoice: 'bg-gray-100 text-gray-600 border-gray-200',
  ready: 'bg-sky-50 text-sky-700 border-sky-200',
  issued: 'bg-sky-50 text-sky-700 border-sky-200',
  submitting: 'bg-amber-50 text-amber-800 border-amber-200',
  uncertain: 'bg-amber-50 text-amber-800 border-amber-300',
  submitted: 'bg-sky-50 text-sky-700 border-sky-200',
  accepted: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
}

export function Badge({ tone, children }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full border text-[11px] whitespace-nowrap ${tone || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
      {children}
    </span>
  )
}

export function Btn({ variant = 'outline', className = '', children, ...rest }) {
  const look = {
    primary: 'bg-primary text-white border-primary',
    outline: 'bg-white text-gray-700 border-gray-300 hover:border-primary/50',
    danger: 'bg-white text-red-700 border-red-300',
    success: 'bg-emerald-600 text-white border-emerald-600',
  }[variant]
  return (
    <button type="button" className={`px-3 py-1.5 rounded-md border text-xs font-bold disabled:opacity-50 disabled:cursor-not-allowed ${look} ${className}`} {...rest}>
      {children}
    </button>
  )
}

export function Field({ label, hint, className = '', children }) {
  return (
    <label className={`flex flex-col gap-0.5 text-xs text-gray-500 ${className}`}>
      {label}
      {children}
      {hint && <span className="text-[11px] text-gray-400">{hint}</span>}
    </label>
  )
}

export function Section({ title, hint, actions, children, ...rest }) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl p-4" {...rest}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div>
            <h3 className="font-bold text-gray-900">{title}</h3>
            {hint && <p className="text-xs text-gray-500 mt-0.5">{hint}</p>}
          </div>
          {actions && <div className="ms-auto flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Notice({ tone = 'amber', children, ...rest }) {
  const look = {
    amber: 'bg-amber-50 border-amber-200 text-amber-900',
    red: 'bg-red-50 border-red-200 text-red-800',
    green: 'bg-emerald-50 border-emerald-200 text-emerald-800',
    gray: 'bg-gray-50 border-gray-200 text-gray-700',
  }[tone]
  return <div className={`rounded-lg border px-3 py-2 text-sm ${look}`} {...rest}>{children}</div>
}

export const Loading = () => <div className="py-10 text-center text-gray-400">جاري التحميل…</div>
export const Failed = ({ error }) => <div className="py-10 text-center text-red-600">{errText(error)}</div>

/**
 * One server action with its result line. Every success reloads the module's queries, so what the
 * screen shows is always the server's answer, never a local guess.
 *   const act = useAction()
 *   act.run(() => api.approve(id), 'تم الاعتماد')
 *   <ActionMsg msg={act.msg} />
 */
export function useAction() {
  const qc = useQueryClient()
  const [msg, setMsg] = useState(null)
  const m = useMutation({
    mutationFn: ({ call }) => call(),
    onMutate: () => setMsg(null),
    onSuccess: (res, { ok, then }) => {
      const text = typeof ok === 'function' ? ok(res.data) : ok
      if (text) setMsg({ ok: true, text })
      qc.invalidateQueries({ queryKey: ['tax-invoicing'] })
      then?.(res.data)
    },
    onError: e => setMsg({ ok: false, text: errText(e), issues: e?.response?.data?.issues }),
  })
  return {
    run: (call, ok, then) => m.mutate({ call, ok, then }),
    pending: m.isPending,
    msg,
  }
}

export function ActionMsg({ msg }) {
  if (!msg) return null
  return (
    <div role="status" className={`text-xs ${msg.ok ? 'text-emerald-700' : 'text-red-700'}`}>
      {msg.text}
      {msg.issues?.length > 0 && (
        <ul className="mt-1 list-disc ms-4">{msg.issues.map((i, n) => <li key={n}>{i.message}</li>)}</ul>
      )}
    </div>
  )
}

/**
 * Sortable, keyboard-driven grid. Rows sort in the browser (the lists are capped on the server).
 *   columns: [{ key, label, type: 'text'|'number'|'date', value(row), render(row), className, sortable }]
 *   onOpen(row) runs on a row click or Enter; renderOpen(row) draws under the row whose key is openKey.
 */
export function Grid({ columns, rows, getKey = r => r.id, defaultSort = null, onOpen, openKey = null, renderOpen, empty = 'لا توجد بيانات', ...rest }) {
  const getValue = useCallback((row, key) => {
    const col = columns.find(c => c.key === key)
    return col?.value ? col.value(row) : row?.[key]
  }, [columns])
  const { sorted, headerProps } = useSortableRows(rows, { defaultSort, getValue })
  const kb = useGridKeyboard({ rows: sorted, getKey, onConfirm: onOpen })
  const click = (e, row) => {
    if (!onOpen || e.target.closest('button,a,input,select,textarea,label')) return
    onOpen(row)
  }
  return (
    <div {...kb.containerProps} {...rest}
      className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
            {columns.map(c => (
              <SortTh key={c.key} {...(c.sortable === false ? {} : headerProps(c.key, c.type || 'text'))}
                className="px-2 py-2 font-semibold whitespace-nowrap text-right">{c.label}</SortTh>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr><td colSpan={columns.length} className="py-8 text-center text-gray-400">{empty}</td></tr>
          )}
          {sorted.map(row => {
            const key = getKey(row)
            const rp = kb.rowProps(row)
            return [
              <tr key={key} {...rp} onClick={e => click(e, row)}
                className={`border-b border-gray-100 ${onOpen ? 'cursor-pointer hover:bg-gray-50' : ''} ${rp.className}`}>
                {columns.map(c => (
                  <td key={c.key} className={`px-2 py-2 align-top ${c.className || ''}`}>
                    {c.render ? c.render(row) : (row[c.key] ?? '—')}
                  </td>
                ))}
              </tr>,
              openKey === key && renderOpen && (
                <tr key={`${key}-open`} className="bg-gray-50/60 border-b border-gray-100">
                  <td colSpan={columns.length} className="px-3 py-3">{renderOpen(row)}</td>
                </tr>
              ),
            ]
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Active branches for a select: value = the SOFTECH code, label from the shared branch list. */
export function useBranchOptions() {
  const q = useQuery({
    queryKey: ['branch-labels'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
  })
  const rows = Array.isArray(q.data) ? q.data : (q.data?.results || [])
  return rows
    .map(b => ({ code: String(b.softech_branch_id ?? b.code ?? '').trim(), name: b.name_ar || b.name || '' }))
    .filter(b => b.code)
}
