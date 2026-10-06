/**
 * KpiBoardPage.jsx — /kpi-board  (doc 16, Phase 2)
 * Excel-style branch × KPI matrix (تارجت/تحقيق) for a month: actual vs target + pace.
 * Actuals come from KpiActualRollup (build_kpi_rollups); targets from SalesTarget.
 */
import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { kpiApi } from '../api/client'

const MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
const PACE = {
  ahead:   { label: 'متقدّم',  cls: 'text-emerald-700 bg-emerald-50' },
  behind:  { label: 'متأخّر',  cls: 'text-amber-700 bg-amber-50' },
  met:     { label: 'تحقّق',   cls: 'text-emerald-700 bg-emerald-50' },
  missed:  { label: 'لم يتحقق', cls: 'text-red-700 bg-red-50' },
  pending: { label: '—',       cls: 'text-gray-400 bg-gray-50' },
}
const fmt = (n, count) => n == null ? '—'
  : Number(n).toLocaleString('en-US', { maximumFractionDigits: count ? 0 : 0 })

function pctColor(pct) {
  if (pct == null) return 'text-gray-400'
  if (pct >= 100) return 'text-emerald-600 font-bold'
  if (pct >= 90)  return 'text-emerald-600'
  if (pct >= 75)  return 'text-amber-600'
  return 'text-red-600'
}

function CallCenterBlock({ cc }) {
  const metrics = cc.metrics || []
  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-x-auto mt-4">
      <div className="px-4 pt-3 pb-1 font-bold text-gray-800 text-sm">📞 الكول سنتر</div>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-gray-600">
            {metrics.map(m => (
              <th key={m.key} className="px-3 py-2 text-center font-bold border-r border-gray-100" colSpan={3}>{m.label}</th>
            ))}
          </tr>
          <tr className="bg-gray-50/60 text-[11px] text-gray-400">
            {metrics.map(m => (
              <Fragment key={m.key}>
                <th className="px-2 py-1 font-medium border-r border-gray-100">محقق</th>
                <th className="px-2 py-1 font-medium">تارجت</th>
                <th className="px-2 py-1 font-medium">%</th>
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {metrics.map(m => {
              const c = cc.cells[m.key] || {}
              return (
                <Fragment key={m.key}>
                  <td className="px-2 py-2.5 text-center tabular-nums text-gray-800 border-r border-gray-50">{fmt(c.actual, m.is_count)}</td>
                  <td className="px-2 py-2.5 text-center tabular-nums text-gray-400">{fmt(c.target, m.is_count)}</td>
                  <td className={`px-2 py-2.5 text-center tabular-nums ${pctColor(c.pct)}`}>{c.pct == null ? '—' : `${c.pct}%`}</td>
                </Fragment>
              )
            })}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function KpiBoardPage() {
  const now = new Date()
  const [year, setYear]   = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['kpi-board', year, month],
    queryFn: () => kpiApi.board({ year, month }).then(r => r.data),
  })

  const metrics = data?.metrics || []

  return (
    <div className="p-6 max-w-[1400px] mx-auto" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📊 لوحة مؤشرات الفروع</h1>
          <p className="text-sm text-gray-500 mt-0.5">التارجت مقابل المحقق لكل فرع — {MONTHS[month - 1]} {year}</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="input-field !w-auto" value={month} onChange={e => setMonth(+e.target.value)}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input-field !w-auto" value={year} onChange={e => setYear(+e.target.value)}>
            {[year + 1, year, year - 1, year - 2].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
      ) : isError ? (
        <div className="text-center py-16 text-red-400">تعذّر تحميل اللوحة</div>
      ) : !data?.has_data ? (
        <div className="text-center py-16 text-gray-400">
          لا توجد بيانات محسوبة لهذا الشهر.
          <div className="text-xs mt-2 text-gray-400">شغّل <code>build_kpi_rollups --year {year} --month {month}</code></div>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-600">
                <th className="text-right font-bold px-4 py-3 sticky right-0 bg-gray-50">الفرع</th>
                {metrics.map(m => (
                  <th key={m.key} className="px-3 py-3 text-center font-bold border-r border-gray-100" colSpan={3}>
                    {m.label}
                  </th>
                ))}
              </tr>
              <tr className="bg-gray-50/60 text-[11px] text-gray-400">
                <th className="sticky right-0 bg-gray-50/60"></th>
                {metrics.map(m => (
                  <Fragment key={m.key}>
                    <th className="px-2 py-1 font-medium border-r border-gray-100">محقق</th>
                    <th className="px-2 py-1 font-medium">تارجت</th>
                    <th className="px-2 py-1 font-medium">%</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.branches.map(b => (
                <tr key={b.branch_id} className="border-t border-gray-50 hover:bg-gray-50/40">
                  <td className="px-4 py-2.5 sticky right-0 bg-white">
                    <div className="font-bold text-gray-800">{b.name}</div>
                    <div className="text-[11px] text-gray-400">{b.code}</div>
                  </td>
                  {metrics.map(m => {
                    const c = b.cells[m.key] || {}
                    const pace = PACE[c.pace] || {}
                    return (
                      <Fragment key={m.key}>
                        <td className="px-2 py-2.5 text-center tabular-nums text-gray-800 border-r border-gray-50">{fmt(c.actual, m.is_count)}</td>
                        <td className="px-2 py-2.5 text-center tabular-nums text-gray-400">{fmt(c.target, m.is_count)}</td>
                        <td className={`px-2 py-2.5 text-center tabular-nums ${pctColor(c.pct)}`}>
                          {c.pct == null ? '—' : `${c.pct}%`}
                          {c.pace && c.pace !== 'pending' && (
                            <span className={`block text-[9px] rounded px-1 mt-0.5 ${pace.cls}`}>{pace.label}</span>
                          )}
                        </td>
                      </Fragment>
                    )
                  })}
                </tr>
              ))}
              {/* Chain totals */}
              <tr className="border-t-2 border-gray-200 bg-gray-50 font-bold">
                <td className="px-4 py-3 sticky right-0 bg-gray-50 text-gray-900">إجمالى الفروع</td>
                {metrics.map(m => {
                  const c = data.totals[m.key] || {}
                  return (
                    <Fragment key={m.key}>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-900 border-r border-gray-100">{fmt(c.actual, m.is_count)}</td>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-500">{fmt(c.target, m.is_count)}</td>
                      <td className={`px-2 py-3 text-center tabular-nums ${pctColor(c.pct)}`}>{c.pct == null ? '—' : `${c.pct}%`}</td>
                    </Fragment>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {data?.call_center && <CallCenterBlock cc={data.call_center} />}

      <p className="text-[11px] text-gray-400 mt-3">
        القيم المالية بالجنيه · «محقق» من فواتير SOFTECH (صافى بعد المرتجعات) · «تارجت» من الأهداف البيعية.
        الأهداف تُدار من صفحة <a href="/targets" className="text-blue-500 hover:underline">الأهداف البيعية</a>.
      </p>
    </div>
  )
}
