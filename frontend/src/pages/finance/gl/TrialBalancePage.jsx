/**
 * TrialBalancePage.jsx — «ميزان المراجعة»
 * Route: /finance/trial-balance
 *
 * Opening / period / closing debit-credit per account (or per group) from approved
 * entries. Totals come from the server. Clicking an account opens its statement for
 * the same range. Excel needs ledger.export.
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import SortTh from '../../../components/SortTh'
import BranchSelect from '../../../components/BranchSelect'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import {
  money, errOf, rangeOf, saveBlob, useGlBranches, PeriodPicker,
  btnPlain, ErrorBox,
} from './glUi'

const COLS = [
  ['opening_debit', 'افتتاحي مدين'], ['opening_credit', 'افتتاحي دائن'],
  ['period_debit', 'حركة مدين'], ['period_credit', 'حركة دائن'],
  ['closing_debit', 'ختامي مدين'], ['closing_credit', 'ختامي دائن'],
]

/** {rows, totals} or a plain list whose totals row has no code. */
function split(data) {
  if (!data) return { rows: [], totals: null }
  if (!Array.isArray(data)) return { rows: data.rows || [], totals: data.totals || null }
  const isTotal = (r) => r.is_total || r.code === 'total' || (!r.code && !r.group && !r.name)
  return { rows: data.filter(r => !isTotal(r)), totals: data.find(isTotal) || null }
}

export default function TrialBalancePage() {
  const navigate = useNavigate()
  const perms = usePermissions('ledger')
  const { branches } = useGlBranches()
  const [period, setPeriod] = useState(() => ({ kind: 'year', ...rangeOf('year') }))
  const [branch, setBranch] = useState('')
  const [by, setBy] = useState('account')
  const [err, setErr] = useState('')

  const params = { from: period.from, to: period.to, branch: branch || undefined, by }
  const q = useQuery({
    queryKey: ['gl', 'trial-balance', params],
    queryFn: () => glApi.trialBalance(params).then(r => r.data),
    enabled: !!(period.from && period.to),
  })
  const { rows, totals } = useMemo(() => split(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: `gl-tb-${by}` })
  const balanced = totals?.balanced === true     // decided by the server

  const toStatement = (code) => navigate(`/finance/ledger?code=${encodeURIComponent(code)}&from=${period.from}&to=${period.to}`)
  const exportXlsx = () => saveBlob(glApi.trialBalanceXlsx(params), `ميزان_المراجعة_${period.from}_${period.to}.xlsx`)
    .then(() => setErr(''), (e) => setErr(errOf(e, 'تعذّر التصدير')))

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        <div data-tour="finance-gl-tb-period"><PeriodPicker value={period} onChange={setPeriod} /></div>
        <BranchSelect size="sm" className="w-48" branches={branches} value={branch} allLabel="كل الفروع" placeholder="كل الفروع" onChange={setBranch} />
        <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
          {[['account', 'بالحساب'], ['group', 'بالمجموعة']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setBy(k)}
                    className={`px-3 py-1.5 ${by === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{l}</button>
          ))}
        </div>
        {perms.export && <button type="button" className={`${btnPlain} ms-auto`} onClick={exportXlsx}>📥 Excel</button>}
      </div>
      <ErrorBox>{err || (q.isError ? errOf(q.error, 'تعذّر تحميل ميزان المراجعة') : '')}</ErrorBox>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        {q.isLoading ? <SkeletonTable rows={10} cols={8} /> : q.isError ? null : !sorted.length ? (
          <EmptyState title="لا توجد حركة معتمدة في هذه الفترة" />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                {by === 'account' && <SortTh {...headerProps('code')} className="text-right px-3 py-2">الكود</SortTh>}
                <SortTh {...headerProps(by === 'account' ? 'name' : 'group')} className="text-right px-3 py-2">
                  {by === 'account' ? 'الحساب' : 'المجموعة'}
                </SortTh>
                {by === 'account' && <SortTh {...headerProps('group')} className="text-right px-3 py-2">المجموعة</SortTh>}
                {COLS.map(([k, l]) => <SortTh key={k} {...headerProps(k, 'number')} className="text-left px-3 py-2">{l}</SortTh>)}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr key={r.code || r.group || i} className="border-t border-gray-100 hover:bg-gray-50">
                  {by === 'account' && (
                    <td className="px-3 py-1.5 font-mono">
                      <button type="button" className="text-green-700 hover:underline" onClick={() => toStatement(r.code)} title="كشف حساب">{r.code}</button>
                    </td>
                  )}
                  <td className="px-3 py-1.5">{by === 'account' ? r.name : (r.group || r.name)}</td>
                  {by === 'account' && <td className="px-3 py-1.5 text-gray-500 text-xs">{r.group}</td>}
                  {COLS.map(([k]) => (
                    <td key={k} className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(r[k], { blankZero: true })}</td>
                  ))}
                </tr>
              ))}
            </tbody>
            {totals && (
              <tfoot>
                <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold">
                  <td className="px-3 py-2" colSpan={by === 'account' ? 3 : 1}>
                    الإجمالي {balanced ? <span className="text-green-700 text-xs font-normal">✓ متوازن</span>
                      : <span className="text-red-600 text-xs">غير متوازن</span>}
                  </td>
                  {COLS.map(([k]) => (
                    <td key={k} className="px-3 py-2 text-left font-mono tabular-nums" dir="ltr">{money(totals[k])}</td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>
    </div>
  )
}
