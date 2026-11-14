/**
 * History tab (السجل) of /crews: for a period (default the last 12 months, three years at most — the
 * server checks), each person's membership spans and every audited change (who, when, before / after).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { crewsApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { INPUT, OffPayrollBadge, TD, TH, daysAgoIso, errText, fmtDate, todayIso } from './util'

function Snapshot({ label, data }) {
  if (!data || (typeof data === 'object' && Object.keys(data).length === 0)) return null
  return (
    <div>
      <div className="text-[11px] text-gray-500">{label}</div>
      <pre className="text-[11px] bg-gray-50 rounded p-1 whitespace-pre-wrap break-all" dir="ltr">{JSON.stringify(data, null, 1)}</pre>
    </div>
  )
}

export default function CrewHistory({ crewId }) {
  const [start, setStart] = useState(daysAgoIso(365))
  const [end, setEnd] = useState(todayIso())
  const q = useQuery({
    queryKey: ['crews', 'history', crewId, start, end],
    queryFn: () => crewsApi.history(crewId, { start, end }).then(r => r.data),
    enabled: !!start && !!end,
  })
  const spans = useSortableRows(q.data?.spans || [], { persistKey: 'crews-history-spans' })
  const changes = useSortableRows(q.data?.changes || [], { persistKey: 'crews-history-changes' })

  return (
    <div className="space-y-4" data-tour="crews-history">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-gray-600">من</span>
        <input type="date" className={INPUT} value={start} max={end} onChange={e => setStart(e.target.value)} />
        <span className="text-gray-600">إلى</span>
        <input type="date" className={INPUT} value={end} min={start} onChange={e => setEnd(e.target.value)} />
      </div>
      {q.isLoading && <p className="text-sm text-gray-500">جارٍ التحميل…</p>}
      {q.isError && <p className="text-sm text-red-600">{errText(q.error)}</p>}
      {q.data && (
        <>
          <section className="card p-0 overflow-x-auto">
            <h3 className="px-3 pt-3 text-sm font-bold text-gray-800">فترات العضوية</h3>
            <table className="w-full">
              <thead className="bg-gray-50"><tr>
                <SortTh {...spans.headerProps('name', 'text')} className={TH}>الشخص</SortTh>
                <SortTh {...spans.headerProps('from', 'date')} className={TH}>من</SortTh>
                <SortTh {...spans.headerProps('to', 'date')} className={TH}>إلى</SortTh>
              </tr></thead>
              <tbody className="divide-y divide-gray-100">
                {spans.sorted.map(s => (
                  <tr key={`${s.key}-${s.from}`}>
                    <td className={TD}>{s.name || s.key}{s.off_payroll && <OffPayrollBadge />}</td>
                    <td className={`${TD} whitespace-nowrap`}>{fmtDate(s.from)}</td>
                    <td className={`${TD} whitespace-nowrap`}>{fmtDate(s.to)}</td>
                  </tr>
                ))}
                {spans.sorted.length === 0 && <tr><td colSpan={3} className={`${TD} text-gray-500`}>لا عضوية في هذه الفترة.</td></tr>}
              </tbody>
            </table>
          </section>
          <section className="card p-0 overflow-x-auto">
            <h3 className="px-3 pt-3 text-sm font-bold text-gray-800">التغييرات</h3>
            <table className="w-full">
              <thead className="bg-gray-50"><tr>
                <SortTh {...changes.headerProps('at', 'date')} className={TH}>متى</SortTh>
                <SortTh {...changes.headerProps('user_name', 'text')} className={TH}>مَن</SortTh>
                <SortTh {...changes.headerProps('action_label', 'text')} className={TH}>التغيير</SortTh>
                <th className={TH}>قبل / بعد</th>
              </tr></thead>
              <tbody className="divide-y divide-gray-100">
                {changes.sorted.map((c, i) => (
                  <tr key={`${c.at}-${i}`} className="align-top">
                    <td className={`${TD} whitespace-nowrap text-xs`}>{fmtDate(c.at, true)}</td>
                    <td className={TD}>{c.user_name || '—'}</td>
                    <td className={TD}>{c.action_label}{c.note && <div className="text-xs text-gray-500">{c.note}</div>}</td>
                    <td className={`${TD} min-w-64`}>
                      {(c.old_data || c.new_data) ? (
                        <details>
                          <summary className="cursor-pointer text-xs text-brand-700">عرض</summary>
                          <div className="grid gap-1 md:grid-cols-2 mt-1">
                            <Snapshot label="قبل" data={c.old_data} />
                            <Snapshot label="بعد" data={c.new_data} />
                          </div>
                        </details>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
                {changes.sorted.length === 0 && <tr><td colSpan={4} className={`${TD} text-gray-500`}>لا تغييرات في السجل.</td></tr>}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  )
}
