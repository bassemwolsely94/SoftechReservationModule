/**
 * MonthTab — one row per employee with the month's totals (display only, no pay).
 * A row click opens that employee's Days tab in place (no modal). The server sorts.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useServerSort from '../../hooks/useServerSort'
import { BTN, Empty, Notice, TH, blobErrText, download, errText, hours } from './shared'

const SORT_KEYS = ['hr_number', 'name_ar', 'department', 'days_with_punches', 'worked_hours',
                   'expected_hours', 'days_needing_review', 'days_no_punches']

export default function MonthTab({ month, setMonth, access, onOpen }) {
  const [status, setStatus] = useState('active')
  const [ordering, setOrdering] = useState('')
  const [exportErr, setExportErr] = useState('')
  const [exporting, setExporting] = useState(false)
  const { headerProps } = useServerSort(ordering, setOrdering, { allowed: SORT_KEYS, defaultOrdering: '' })
  const params = { month, status, ordering: ordering || undefined }
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'month', month, status, ordering],
    queryFn: () => hrAttendanceApi.month(params).then(r => r.data),
  })
  const rows = data?.rows || []

  async function exportXlsx() {
    setExporting(true); setExportErr('')
    try {
      const res = await hrAttendanceApi.exportMonth({ month, status })
      download(res, `attendance-${month}.xlsx`)
    } catch (e) { setExportErr(await blobErrText(e)) }
    setExporting(false)
  }

  return (
    <div>
      <div className="flex flex-wrap items-end gap-2 mb-3 text-sm" data-tour="hr-attendance-month-filters">
        <label className="flex flex-col text-xs text-gray-500">الشهر
          <input type="month" value={month} onChange={e => e.target.value && setMonth(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
        </label>
        <label className="flex flex-col text-xs text-gray-500">الموظفون
          <select value={status} onChange={e => setStatus(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
            <option value="active">على رأس العمل</option>
            <option value="left">تركوا العمل</option>
            <option value="">الكل</option>
          </select>
        </label>
        {access.can_export && (
          <button type="button" data-tour="hr-attendance-export" onClick={exportXlsx} disabled={exporting}
            className={`${BTN} bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 py-1.5`}>
            {exporting ? '⏳ جارٍ التجهيز…' : '📥 تصدير Excel'}
          </button>
        )}
        <Notice>{exportErr}</Notice>
      </div>

      <div data-tour="hr-attendance-month-grid" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('hr_number', 'text')}>الرقم الوظيفي</SortTh>
              <SortTh className={TH} {...headerProps('name_ar', 'text')}>الاسم</SortTh>
              <SortTh className={TH} {...headerProps('department', 'text')}>القسم</SortTh>
              <SortTh className={TH} {...headerProps('days_with_punches', 'number')}>أيام بها بصمات</SortTh>
              <SortTh className={TH} {...headerProps('worked_hours', 'number')}>ساعات العمل</SortTh>
              <SortTh className={TH} {...headerProps('expected_hours', 'number')}>الساعات المتوقعة</SortTh>
              <SortTh className={TH} {...headerProps('days_needing_review', 'number')}>تحتاج مراجعة</SortTh>
              <SortTh className={TH} {...headerProps('days_no_punches', 'number')}>بدون بصمات</SortTh>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} onClick={() => onOpen(r.id)} tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter') onOpen(r.id) }}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" title="فتح أيام الموظف">
                <td className="px-3 py-2 tabular-nums">{r.hr_number}</td>
                <td className="px-3 py-2 font-medium text-gray-900">{r.name_ar}</td>
                <td className="px-3 py-2 text-gray-600">{r.department || '—'}</td>
                <td className="px-3 py-2 tabular-nums">{r.days_with_punches}</td>
                <td className="px-3 py-2 tabular-nums">{hours(r.worked_hours)}</td>
                <td className="px-3 py-2 tabular-nums text-gray-600">{hours(r.expected_hours)}</td>
                <td className={`px-3 py-2 tabular-nums ${r.days_needing_review ? 'text-amber-700 font-bold' : 'text-gray-400'}`}>
                  {r.days_needing_review}</td>
                <td className="px-3 py-2 tabular-nums text-gray-500">{r.days_no_punches}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading && <Empty>جاري التحميل…</Empty>}
        {error && <div className="py-10 text-center text-sm text-red-600">{errText(error)}</div>}
        {!isLoading && !error && rows.length === 0 && <Empty>لا يوجد موظفون بهذه الفلاتر</Empty>}
      </div>
    </div>
  )
}
