/**
 * SubledgersPage.jsx — «الأستاذ المساعد»
 * Route: /finance/subledgers?tab=suppliers|creditors|notes_payable|customers|employees|partners
 *
 * One tab per sub-ledger: opening / debit / credit / closing per party for a date range, a «بدون طرف» row for
 * lines with no party, and the total. A row opens the account statement filtered to that party. Supplier and
 * customer rows with a confirmed party also link to سداد الموردين / مستحقات التعاقدات. Notes payable are grouped by
 * the month their cheques fall due (expand a month for its cheques). The suppliers tab can set the ledger beside
 * the سداد الموردين balance. Every figure comes from the server.
 */
import { Fragment, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import { money, errOf, rangeOf, saveBlob, PeriodPicker, btnPlain, ErrorBox } from './glUi'

const KINDS = [
  { key: 'suppliers',     label: 'الموردون',     account: '2341' },
  { key: 'creditors',     label: 'الدائنون',     account: '2351' },
  { key: 'notes_payable', label: 'أوراق الدفع',  account: '2343' },
  { key: 'customers',     label: 'العملاء',      account: '1341' },
  { key: 'employees',     label: 'العاملون',     account: '1351' },
  { key: 'partners',      label: 'الشركاء',      account: null },   // rows are accounts: the key is the code
]

const num = 'px-3 py-1.5 text-left font-mono tabular-nums'

/** Where a row's click goes: the account statement filtered to its party (a partner row is an account). */
function statementUrl(kind, row, period) {
  const k = KINDS.find(x => x.key === kind)
  const q = new URLSearchParams({ from: period.from, to: period.to })
  if (kind === 'partners') q.set('code', row.key)
  else {
    q.set('code', k.account)
    if (row.key) q.set('party', row.key)
  }
  return `/finance/ledger?${q}`
}

/** The row's link out (confirmed supplier → سداد الموردين, customer → مستحقات التعاقدات). */
function RowLink({ link }) {
  if (!link) return null
  const supplier = link.party !== undefined
  const to = supplier ? `${link.to}?party=${encodeURIComponent(link.party)}` : `${link.to}?personcode=${encodeURIComponent(link.personcode)}`
  return (
    <Link to={to} onClick={e => e.stopPropagation()} className="text-xs text-blue-700 hover:underline whitespace-nowrap">
      {supplier ? 'سداد الموردين ↗' : 'مستحقات التعاقدات ↗'}
    </Link>
  )
}

function Cheques({ cheques }) {
  return (
    <table className="w-full text-xs bg-gray-50/70">
      <tbody>
        {cheques.map((c, i) => (
          <tr key={`${c.cheque_no}-${i}`} className="border-t border-gray-100">
            <td className="px-6 py-1 font-mono">{c.cheque_no || '—'}</td>
            <td className="px-3 py-1">{c.party || '—'}</td>
            <td className="px-3 py-1">{c.due_date || 'بدون تاريخ استحقاق'}</td>
            <td className={`${num} py-1`} dir="ltr">{money(c.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SubledgerTable({ kind, data, period, link }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState({})
  const rows = useMemo(() => data.rows || [], [data.rows])
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: `gl-subledger-${kind}` })
  const byMonth = kind === 'notes_payable'
  const all = [...sorted, ...(data.unassigned ? [data.unassigned] : []), data.totals]
  const open_ = (r) => { if (!r.is_total && !byMonth) navigate(statementUrl(kind, r, period)) }
  return (
    <table className="w-full text-sm">
      <thead className="bg-gray-50 text-gray-600 text-xs">
        <tr>
          <SortTh {...headerProps('key')} className="text-right px-3 py-2">{kind === 'partners' ? 'الحساب' : byMonth ? 'شهر الاستحقاق' : 'الكود'}</SortTh>
          {!byMonth && <SortTh {...headerProps('name')} className="text-right px-3 py-2">الاسم</SortTh>}
          <SortTh {...headerProps('opening', 'number')} className="text-left px-3 py-2">افتتاحي</SortTh>
          <SortTh {...headerProps('debit', 'number')} className="text-left px-3 py-2">مدين</SortTh>
          <SortTh {...headerProps('credit', 'number')} className="text-left px-3 py-2">دائن</SortTh>
          <SortTh {...headerProps('closing', 'number')} className="text-left px-3 py-2">ختامي</SortTh>
          {link && <th className="px-3 py-2 text-right" data-tour="finance-gl-subledger-link">{kind === 'suppliers' ? 'سداد الموردين' : 'مستحقات التعاقدات'}</th>}
        </tr>
      </thead>
      <tbody>
        {all.map((r, i) => {
          const total = !!r.is_total
          const unassigned = !total && r === data.unassigned
          const cheques = byMonth && !total ? r.cheques || [] : []
          const isOpen = !!open[r.key]
          return (
            <Fragment key={`${r.key ?? 'total'}-${i}`}>
              <tr className={`border-t ${total ? 'border-t-2 border-gray-300 bg-gray-50 font-bold' : 'border-gray-100'} ${unassigned ? 'bg-amber-50/60' : ''} ${total || byMonth ? '' : 'cursor-pointer hover:bg-gray-50'}`}
                  onClick={() => (byMonth && cheques.length ? setOpen(o => ({ ...o, [r.key]: !o[r.key] })) : open_(r))}>
                <td className={`px-3 py-1.5 ${byMonth ? '' : 'font-mono'}`}>
                  {byMonth && !total ? <>{cheques.length ? (isOpen ? '▾ ' : '▸ ') : ''}{r.name} <span className="text-xs text-gray-400">({cheques.length} شيك)</span></> : (r.key || '')}
                </td>
                {!byMonth && <td className="px-3 py-1.5">{r.name}</td>}
                <td className={num} dir="ltr">{money(r.opening)}</td>
                <td className={num} dir="ltr">{money(r.debit)}</td>
                <td className={num} dir="ltr">{money(r.credit)}</td>
                <td className={num} dir="ltr">{money(r.closing)}</td>
                {link && <td className="px-3 py-1.5"><RowLink link={r.link} /></td>}
              </tr>
              {isOpen && cheques.length > 0 && (
                <tr><td colSpan={link ? 6 : 5} className="p-0"><Cheques cheques={cheques} /></td></tr>
              )}
            </Fragment>
          )
        })}
        {!rows.length && !data.unassigned && (
          <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-400">لا أرصدة ولا حركة في هذه الفترة</td></tr>
        )}
      </tbody>
    </table>
  )
}

/** الموردون مقابل سداد الموردين at the end of the range: the ledger's balance beside the A/P reconciliation's. */
function VsApTable({ asOf, perms, setErr }) {
  const q = useQuery({
    queryKey: ['gl', 'suppliers-vs-ap', asOf],
    queryFn: () => glApi.suppliersVsAp({ as_of: asOf }).then(r => r.data),
    enabled: !!asOf,
  })
  const rows = useMemo(() => q.data?.rows || [], [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'gl-suppliers-vs-ap' })
  const exportXlsx = () => saveBlob(glApi.suppliersVsApXlsx({ as_of: asOf }), `الموردون_مقابل_سداد_${asOf}.xlsx`)
    .then(() => setErr(''), (e) => setErr(errOf(e, 'تعذّر التصدير')))
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <div className="flex items-center gap-3 px-3 py-2 text-xs text-gray-500 border-b border-gray-100">
        <span>رصيد الأستاذ (٢٣٤١) مقابل رصيد سداد الموردين في {asOf}</span>
        {perms.export && <button type="button" className={`${btnPlain} ms-auto`} onClick={exportXlsx}>📥 Excel</button>}
      </div>
      <ErrorBox>{q.isError ? errOf(q.error, 'تعذّر تحميل المقارنة') : ''}</ErrorBox>
      {q.isLoading ? <SkeletonTable rows={6} cols={5} /> : (
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs">
            <tr>
              <SortTh {...headerProps('party_code')} className="text-right px-3 py-2">الكود</SortTh>
              <SortTh {...headerProps('name')} className="text-right px-3 py-2">المورد</SortTh>
              <SortTh {...headerProps('gl_balance', 'number')} className="text-left px-3 py-2">رصيد الأستاذ</SortTh>
              <SortTh {...headerProps('ap_balance', 'number')} className="text-left px-3 py-2">رصيد سداد الموردين</SortTh>
              <SortTh {...headerProps('difference', 'number')} className="text-left px-3 py-2">الفرق</SortTh>
              <SortTh {...headerProps('reason')} className="text-right px-3 py-2">ملاحظة</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const diff = r.difference === null || r.difference === undefined ? null : Number(r.difference)
              const off = diff !== null && Math.abs(diff) >= 0.005   // the A/P side carries 3 decimals
              return (
                <tr key={r.party_code} className="border-t border-gray-100">
                  <td className="px-3 py-1.5 font-mono">{r.party_code}</td>
                  <td className="px-3 py-1.5">{r.name}</td>
                  <td className={num} dir="ltr">{money(r.gl_balance)}</td>
                  <td className={num} dir="ltr">{r.ap_balance === null ? '—' : money(r.ap_balance)}</td>
                  <td className={`${num} ${off ? 'text-red-700 font-bold' : 'text-gray-400'}`} dir="ltr">{diff === null ? '—' : money(r.difference)}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-500">{r.reason}</td>
                </tr>
              )
            })}
            {!sorted.length && <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">لا موردين للمقارنة</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function SubledgersPage() {
  const perms = usePermissions('ledger')
  const [params, setParams] = useSearchParams()
  const kind = KINDS.some(k => k.key === params.get('tab')) ? params.get('tab') : 'suppliers'
  useHelpTab(kind)
  const setKind = (k) => { const p = new URLSearchParams(params); p.set('tab', k); setParams(p, { replace: true }) }
  const [period, setPeriod] = useState(() => {
    const from = params.get('from'); const to = params.get('to')
    return from && to ? { kind: 'custom', from, to } : { kind: 'year', ...rangeOf('year') }
  })
  const [vsAp, setVsAp] = useState(false)
  const [err, setErr] = useState('')

  const apiParams = { from: period.from, to: period.to }
  const q = useQuery({
    queryKey: ['gl', 'subledger', kind, apiParams],
    queryFn: () => glApi.subledger(kind, apiParams).then(r => r.data),
    enabled: !!(period.from && period.to),
  })
  const label = KINDS.find(k => k.key === kind).label
  const exportXlsx = () => saveBlob(glApi.subledgerXlsx(kind, apiParams), `الأستاذ_المساعد_${label}_${period.from}_${period.to}.xlsx`)
    .then(() => setErr(''), (e) => setErr(errOf(e, 'تعذّر التصدير')))
  const showVsAp = kind === 'suppliers' && vsAp

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto" data-tour="finance-gl-subledger-tabs">
        {KINDS.map(k => (
          <button key={k.key} type="button" onClick={() => setKind(k.key)}
                  className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${kind === k.key ? 'border-green-600 text-green-700 font-medium' : 'border-transparent text-gray-600 hover:text-gray-900'}`}>
            {k.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <PeriodPicker value={period} onChange={setPeriod} />
        {kind === 'suppliers' && (
          <label className="flex items-center gap-1.5 text-sm text-gray-700">
            <input type="checkbox" checked={vsAp} onChange={e => setVsAp(e.target.checked)} />
            مقارنة بسداد الموردين
          </label>
        )}
        {perms.export && !showVsAp && <button type="button" className={`${btnPlain} ms-auto`} onClick={exportXlsx}>📥 Excel</button>}
      </div>
      <ErrorBox>{err || (q.isError ? errOf(q.error, 'تعذّر تحميل الأستاذ المساعد') : '')}</ErrorBox>

      {showVsAp ? <VsApTable asOf={period.to} perms={perms} setErr={setErr} /> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          {q.isLoading ? <SkeletonTable rows={8} cols={6} /> : q.isError ? null : !q.data ? (
            <EmptyState title="اختر الفترة" sub="" />
          ) : (
            <SubledgerTable key={kind} kind={kind} data={q.data} period={period} link={kind === 'suppliers' || kind === 'customers'} />
          )}
        </div>
      )}
      {!showVsAp && kind !== 'notes_payable' && kind !== 'partners' && (
        <div className="text-xs text-gray-400">اضغط على صف لفتح كشف الحساب لهذا الطرف.</div>
      )}
    </div>
  )
}
