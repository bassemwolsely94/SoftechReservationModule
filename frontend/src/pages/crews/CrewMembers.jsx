/**
 * Members tab (الأعضاء) of /crews: who is in the selected crew on a chosen day (default today).
 * Sortable, with the review-grid keyboard (↑↓ to move). Off-payroll members carry the badge.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { crewsApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import SortTh from '../../components/SortTh'
import { INPUT, OffPayrollBadge, TD, TH, errText, todayIso } from './util'

const getKey = m => m.key
const SOURCE = { rule: 'قاعدة', manual: 'يدوي' }
const getValue = (m, k) => (k === 'codes' ? (m.softech_usercodes || []).join(' ')
  : k === 'exts' ? (m.extensions || []).join(' ') : k === 'source' ? SOURCE[m.source] || m.source : m[k])

export default function CrewMembers({ crewId }) {
  const [day, setDay] = useState(todayIso())
  const q = useQuery({
    queryKey: ['crews', 'members', crewId, day],
    queryFn: () => crewsApi.members(crewId, day).then(r => r.data),
  })
  const rows = q.data || []
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'crews-members', getValue })
  const kb = useGridKeyboard({ rows: sorted, getKey })

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-gray-600">في يوم</span>
        <input type="date" className={INPUT} value={day} onChange={e => setDay(e.target.value || todayIso())} />
        <span className="text-xs text-gray-500">{q.isLoading ? '…' : `${rows.length} شخصًا`}</span>
      </label>
      {q.isError && <p className="text-sm text-red-600">{errText(q.error)}</p>}
      <div {...kb.containerProps} className={`card p-0 overflow-x-auto ${kb.containerProps.className}`} data-tour="crews-members-grid">
        <table className="w-full">
          <thead className="bg-gray-50"><tr>
            <SortTh {...h('name', 'text')} className={TH}>الاسم</SortTh>
            <SortTh {...h('hr_number', 'text')} className={TH}>الرقم الوظيفي</SortTh>
            <SortTh {...h('job_title', 'text')} className={TH}>الوظيفة</SortTh>
            <SortTh {...h('branch_label', 'text')} className={TH}>الفرع</SortTh>
            <SortTh {...h('codes', 'text')} className={TH}>أكواد المستخدم</SortTh>
            <SortTh {...h('exts', 'text')} className={TH}>الأرقام الداخلية</SortTh>
            <SortTh {...h('source', 'text')} className={TH}>المصدر</SortTh>
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(m => (
              <tr key={m.key} {...kb.rowProps(m)}>
                <td className={TD}>{m.name || m.key}{m.off_payroll && <OffPayrollBadge />}</td>
                <td className={`${TD} tabular-nums`}>{m.hr_number || '—'}</td>
                <td className={TD}>{m.job_title || '—'}</td>
                <td className={TD}>{m.branch_label || '—'}</td>
                <td className={`${TD} text-xs`} dir="ltr">{(m.softech_usercodes || []).join(', ') || '—'}</td>
                <td className={`${TD} text-xs`} dir="ltr">{(m.extensions || []).join(', ') || '—'}</td>
                <td className={TD}>{SOURCE[m.source] || m.source}</td>
              </tr>
            ))}
            {!q.isLoading && rows.length === 0 && (
              <tr><td colSpan={7} className={`${TD} text-gray-500`}>لا أعضاء في هذا اليوم.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
