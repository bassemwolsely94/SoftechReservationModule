/**
 * AccountStatementPage.jsx — «كشف حساب»
 * Route: /finance/ledger?code=&from=&to=&party=
 *
 * One account's approved movements with opening balance, running balance and closing
 * balance (all from the server). A row opens its entry in the side panel.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import EntryEditor, { AccountPicker } from './EntryEditor'
import {
  money, errOf, listOf, rangeOf, saveBlob, PeriodPicker,
  inputCls, btnPlain, ErrorBox,
} from './glUi'

/** Signed balance → "1,234.00 مدين" / "… دائن". */
function side(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (n === 0) return '0.00'
  return `${money(Math.abs(n))} ${n > 0 ? 'مدين' : 'دائن'}`
}

export default function AccountStatementPage() {
  const perms = usePermissions('ledger')
  const [params, setParams] = useSearchParams()
  const code = params.get('code') || ''
  const party = params.get('party') || ''
  const [period, setPeriod] = useState(() => {
    const from = params.get('from'); const to = params.get('to')
    return from && to ? { kind: 'custom', from, to } : { kind: 'year', ...rangeOf('year') }
  })
  const [partyDraft, setPartyDraft] = useState(party)
  const [openEntry, setOpenEntry] = useState(null)
  const [err, setErr] = useState('')

  const setParam = (k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v); else p.delete(k)
    setParams(p, { replace: true })
  }

  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'all-active'],
    queryFn: () => glApi.accounts({ page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accounts = accountsQ.data || []
  const account = accounts.find(a => String(a.code) === code)

  const apiParams = { code, from: period.from, to: period.to, party: party || undefined }
  const q = useQuery({
    queryKey: ['gl', 'account-statement', apiParams],
    queryFn: () => glApi.accountStatement(apiParams).then(r => r.data),
    enabled: !!(code && period.from && period.to),
  })
  const lines = useMemo(() => q.data?.lines || [], [q.data])
  // default = the server's date / number order, which the running balance follows
  const { sorted, headerProps } = useSortableRows(lines)

  const exportXlsx = () => saveBlob(glApi.accountStatementXlsx(apiParams), `كشف_حساب_${code}_${period.from}_${period.to}.xlsx`)
    .then(() => setErr(''), (e) => setErr(errOf(e, 'تعذّر التصدير')))

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex flex-wrap items-center gap-2" data-tour="finance-gl-statement-filters">
        <div className="w-80">
          <AccountPicker value={code} name={account?.name || ''} accounts={accounts}
                         onPick={a => setParam('code', a.code)} />
        </div>
        <input className={`${inputCls} w-32`} placeholder="كود الطرف" value={partyDraft}
               onChange={e => setPartyDraft(e.target.value)}
               onBlur={() => setParam('party', partyDraft.trim())}
               onKeyDown={e => { if (e.key === 'Enter') setParam('party', partyDraft.trim()) }} />
        <PeriodPicker value={period} onChange={setPeriod} />
        {perms.export && code && <button type="button" className={`${btnPlain} ms-auto`} onClick={exportXlsx}>📥 Excel</button>}
      </div>
      <ErrorBox>{err || (q.isError ? errOf(q.error, 'تعذّر تحميل كشف الحساب') : '')}</ErrorBox>

      {!code ? <EmptyState title="اختر حساباً" sub="ابحث بالكود أو الاسم لعرض كشف الحساب" /> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          {q.isLoading ? <SkeletonTable rows={8} cols={6} /> : q.isError ? null : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs">
                <tr>
                  <SortTh {...headerProps('date', 'date')} className="text-right px-3 py-2">التاريخ</SortTh>
                  <SortTh {...headerProps('number')} className="text-right px-3 py-2">رقم القيد</SortTh>
                  <SortTh {...headerProps('description')} className="text-right px-3 py-2">البيان</SortTh>
                  <SortTh {...headerProps('debit', 'number')} className="text-left px-3 py-2">مدين</SortTh>
                  <SortTh {...headerProps('credit', 'number')} className="text-left px-3 py-2">دائن</SortTh>
                  <SortTh {...headerProps('running_balance', 'number')} className="text-left px-3 py-2">الرصيد</SortTh>
                </tr>
              </thead>
              <tbody>
                <tr className="bg-gray-50 text-gray-700">
                  <td className="px-3 py-1.5" colSpan={5}>رصيد أول المدة ({period.from})</td>
                  <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{side(q.data?.opening_balance)}</td>
                </tr>
                {sorted.map((l, i) => (
                  <tr key={`${l.entry_id}-${i}`} className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
                      onClick={() => setOpenEntry(l.entry_id)}>
                    <td className="px-3 py-1.5">{l.date}</td>
                    <td className="px-3 py-1.5 font-mono">{l.number}</td>
                    <td className="px-3 py-1.5">{l.description}</td>
                    <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(l.debit, { blankZero: true })}</td>
                    <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(l.credit, { blankZero: true })}</td>
                    <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{side(l.running_balance)}</td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">لا حركة معتمدة في هذه الفترة</td></tr>
                )}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold">
                  <td className="px-3 py-2" colSpan={5}>رصيد آخر المدة ({period.to})</td>
                  <td className="px-3 py-2 text-left font-mono tabular-nums" dir="ltr">{side(q.data?.closing_balance)}</td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}

      {openEntry && <EntryEditor key={openEntry} entryId={openEntry} onClose={() => setOpenEntry(null)} />}
    </div>
  )
}
