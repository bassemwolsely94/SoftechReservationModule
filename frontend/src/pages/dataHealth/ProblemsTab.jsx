/**
 * Problems tab (المشكلات) of /data-health: open data problems as counts only, with the change since the
 * previous measurement, who owns each, and a link to the screen where it is fixed. Nothing is fixed here.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { dataHealthApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { TD, TH, errText, fmtDate, fmtInt } from './format'

function Change({ value }) {
  if (value == null || value === 0) return <span className="text-gray-400">—</span>
  // more open problems is worse
  return <span className={value > 0 ? 'text-red-600' : 'text-emerald-700'} dir="ltr">{value > 0 ? `+${fmtInt(value)}` : fmtInt(value)}</span>
}

export default function ProblemsTab({ refreshing }) {
  const q = useQuery({
    queryKey: ['data-health', 'problems'],
    queryFn: () => dataHealthApi.problems().then(r => r.data),
    refetchInterval: refreshing ? 4000 : false,
  })
  const rows = q.data?.problems || []
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'data-health-problems' })

  if (q.isLoading) return <p className="text-sm text-gray-500">جارٍ التحميل…</p>
  if (q.isError) return <p className="text-sm text-red-600">{errText(q.error)}</p>
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        أعداد فقط، من آخر قياس ({fmtDate(q.data.as_of, true)}). هذه الشاشة لا تصلح شيئًا: الإصلاح من الشاشة المرتبطة.
        «—» في العدد يعني أن هذا العدد لم يُحسب في آخر قياس.
      </p>
      <div className="card p-0 overflow-x-auto" data-tour="data-health-main-problems">
        <table className="w-full">
          <thead className="bg-gray-50"><tr>
            <SortTh {...h('label_ar', 'text')} className={TH}>المشكلة</SortTh>
            <SortTh {...h('count', 'number')} className={TH}>العدد</SortTh>
            <SortTh {...h('change', 'number')} className={TH}>التغير</SortTh>
            <SortTh {...h('owner_role_ar', 'text')} className={TH}>المسؤول</SortTh>
            <th className={TH}>ملاحظة</th>
            <th className={TH}><span className="sr-only">رابط</span></th>
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(p => (
              <tr key={p.key}>
                <td className={TD}>{p.label_ar}</td>
                <td className={`${TD} tabular-nums font-semibold`}>{fmtInt(p.count)}</td>
                <td className={`${TD} tabular-nums`}><Change value={p.change} /></td>
                <td className={TD}>{p.owner_role_ar}</td>
                <td className={`${TD} text-xs text-gray-500`}>{p.note_ar || ''}</td>
                <td className={TD}>
                  {p.link ? <Link to={p.link} className="text-brand-700 hover:underline text-xs whitespace-nowrap">فتح الشاشة</Link> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
