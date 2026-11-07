/**
 * DaysTab — one employee, one month, day by day: first punch, last punch, hours, flags.
 * A row expands inline to the raw punches and the machine each came from.
 *
 * A day with no punches is neutral text («بدون بصمات»). Today with no punches yet is shown muted
 * as today — it is not a problem. This page never says «absent»: that is HR's decision.
 */
import { Fragment, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import { Empty, TH, clock, errText, hm, hours, isoDay, weekdayOf } from './shared'

const KEYS = ['work_date', 'first_in', 'last_out', 'worked_minutes', 'punch_count']
const DEFAULT_SORT = { key: 'work_date', dir: 'asc', type: 'date' }
const getValue = (d, key) => (key === 'first_in' || key === 'last_out' ? (d[key] || null) : d[key])

const INFO_KIND = { leave: 'إجازة', permit: 'إذن' }

function Flags({ d, today }) {
  if (d.no_punches) {
    return d.work_date === today
      ? <span className="text-gray-400">اليوم — لا بصمات حتى الآن</span>
      : <span className="text-gray-500">بدون بصمات</span>
  }
  if (!d.punch_count) return <span className="text-gray-400">—</span>
  return d.needs_review
    ? <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">بصمة واحدة — تحتاج مراجعة</span>
    : <span className="text-gray-400">—</span>
}

export default function DaysTab({ employeeId, month, setMonth, employees, onPick }) {
  const [open, setOpen] = useState(() => new Set())
  const today = isoDay(new Date())
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'days', employeeId, month],
    enabled: !!employeeId,
    queryFn: () => hrAttendanceApi.employeeDays(employeeId, { month }).then(r => r.data),
  })
  const days = useMemo(() => data?.days || [], [data])
  const { sorted, headerProps } = useSortableRows(days, {
    defaultSort: DEFAULT_SORT, getValue, persistKey: 'hr-attendance-days', keys: KEYS })
  const toggle = date => setOpen(prev => {
    const next = new Set(prev)
    if (next.has(date)) next.delete(date); else next.add(date)
    return next
  })
  const emp = data?.employee
  const totals = data?.totals

  return (
    <div>
      <div className="flex flex-wrap items-end gap-2 mb-3 text-sm" data-tour="hr-attendance-days-filters">
        <label className="flex flex-col text-xs text-gray-500">الموظف
          <select value={employeeId || ''} onChange={e => onPick(e.target.value ? Number(e.target.value) : null)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white min-w-[14rem]">
            <option value="">اختر موظفاً…</option>
            {employees.map(e => <option key={e.id} value={e.id}>{e.hr_number} · {e.name_ar}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-500">الشهر
          <input type="month" value={month} onChange={e => e.target.value && setMonth(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
        </label>
      </div>

      {!employeeId && <Empty>اختر موظفاً، أو اضغط على صفه في تبويب «الشهر».</Empty>}
      {employeeId && isLoading && <Empty>جاري التحميل…</Empty>}
      {employeeId && error && <div className="py-10 text-center text-sm text-red-600">{errText(error)}</div>}

      {emp && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-tour="hr-attendance-days-summary">
            <span className="font-bold text-gray-900">{emp.name_ar}</span>
            <span className="text-gray-500">{emp.hr_number}</span>
            {emp.branch_name && <span className="text-gray-500">{emp.branch_name}</span>}
            {emp.hold_resolution && <span className="text-amber-700 text-xs">بصماته معلّقة: {emp.hold_reason}</span>}
            <span className="ms-auto text-xs text-gray-600">
              أيام بها بصمات {totals.days_with_punches} · ساعات {hours(totals.worked_hours)}
              {totals.expected_hours != null && ` من ${hours(totals.expected_hours)}`}
              {' · '}تحتاج مراجعة {totals.days_needing_review}
            </span>
          </div>
          <div data-tour="hr-attendance-days-grid" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
                  <SortTh className={TH} {...headerProps('work_date', 'date')}>اليوم</SortTh>
                  <SortTh className={TH} {...headerProps('first_in', 'text')}>أول بصمة</SortTh>
                  <SortTh className={TH} {...headerProps('last_out', 'text')}>آخر بصمة</SortTh>
                  <SortTh className={TH} {...headerProps('worked_minutes', 'number')}>الساعات</SortTh>
                  <SortTh className={TH} {...headerProps('punch_count', 'number')}>البصمات</SortTh>
                  <th className={TH}>الماكينة</th>
                  <th className={TH}>ملاحظات</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(d => {
                  const isToday = d.work_date === today
                  const expandable = d.raw?.length > 0
                  return (
                    <Fragment key={d.work_date}>
                      <tr onClick={expandable ? () => toggle(d.work_date) : undefined}
                        className={`border-b border-gray-100 ${expandable ? 'cursor-pointer hover:bg-gray-50' : ''} ${isToday ? 'bg-sky-50/40' : ''}`}>
                        <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                          {expandable && <span className="text-gray-400 me-1">{open.has(d.work_date) ? '▾' : '▸'}</span>}
                          {d.work_date} <span className="text-gray-400 text-xs">{weekdayOf(d.work_date)}</span>
                          {isToday && <span className="ms-1 text-xs text-sky-700">اليوم</span>}
                        </td>
                        <td className="px-3 py-2 tabular-nums">{clock(d.first_in)}</td>
                        <td className="px-3 py-2 tabular-nums">{clock(d.last_out)}</td>
                        <td className="px-3 py-2 tabular-nums">{d.punch_count > 1 ? hm(d.worked_minutes) : '—'}</td>
                        <td className="px-3 py-2 tabular-nums">{d.punch_count || '—'}</td>
                        <td className="px-3 py-2 text-gray-600">{d.machines?.join('، ') || '—'}</td>
                        <td className="px-3 py-2 text-xs">
                          <Flags d={d} today={today} />
                          {(d.info || []).map((i, n) => (
                            <span key={n} className="ms-2 px-1.5 py-0.5 rounded bg-sky-50 text-sky-800 border border-sky-200">
                              {INFO_KIND[i.kind] || ''} {i.label}</span>
                          ))}
                        </td>
                      </tr>
                      {open.has(d.work_date) && (
                        <tr className="bg-gray-50/70 border-b border-gray-100">
                          <td colSpan={7} className="px-6 py-2">
                            <ul className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-700" data-tour="hr-attendance-days-raw">
                              {d.raw.map((r, n) => (
                                <li key={n} className={r.counted ? '' : 'text-gray-400 line-through'}
                                  title={r.counted ? '' : 'بصمة مكررة خلال دقيقتين — لا تُحسب'}>
                                  <span className="tabular-nums">{clock(r.at)}</span> · {r.machine || '—'}
                                </li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
