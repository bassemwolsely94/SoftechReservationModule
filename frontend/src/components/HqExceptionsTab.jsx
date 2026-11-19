/**
 * «💰 استثناءات الأسبوع» (C32) — the same top-10 list the Sunday digest sends: the biggest open items
 * by EGP across the engines (supplier returns, dead stock, stock audit, A/P exceptions, receipt check),
 * who acts and a link to the screen that acts on it. The server ranks and dedupes; this only shows it.
 * Company-level: the API answers 403 to a branch-bound user.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { insightsApi } from '../api/client'
import SortTh from './SortTh'
import useSortableRows from '../hooks/useSortableRows'

const egp = (v) => Math.round(Number(v) || 0).toLocaleString('en-US')

export default function HqExceptionsTab() {
  const qc = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['hq-exceptions'],
    queryFn: () => insightsApi.exceptions().then(r => r.data),
    retry: false,
  })
  const { sorted, headerProps } = useSortableRows(data?.items || [], { persistKey: 'hq-exceptions' })

  const refresh = async () => {
    setRefreshing(true)
    try {
      const r = await insightsApi.exceptions({ refresh: 1 })
      qc.setQueryData(['hq-exceptions'], r.data)
    } finally { setRefreshing(false) }
  }

  if (error?.response?.status === 403) {
    return <div className="text-sm text-gray-500 py-16 text-center border border-dashed border-gray-200 rounded-2xl">
      استثناءات الأسبوع لمستخدمي كل الفروع (الإدارة والمركز الرئيسي) فقط.</div>
  }
  if (isLoading) return <div className="text-gray-400 text-sm py-8 text-center">جارٍ التحميل…</div>
  if (error) return <div className="text-sm text-red-600 py-8 text-center">تعذّر تحميل القائمة.</div>

  const total = (data?.items || []).reduce((s, r) => s + r.egp, 0)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" data-tour="analytics-insights-exceptions-totals">
        {Object.entries(data?.totals || {}).map(([k, t]) => (
          <Link key={k} to={t.link} className="text-xs rounded-lg border border-gray-200 bg-white px-3 py-1.5 hover:border-gray-300">
            {t.label}: <b className="tabular-nums">{egp(t.egp)} ج</b> <span className="text-gray-400">({t.count})</span>
          </Link>
        ))}
        <button onClick={refresh} disabled={refreshing} data-tour="analytics-insights-exceptions-refresh"
          className="mr-auto text-xs px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-50">
          {refreshing ? 'جارٍ التحديث…' : '🔄 تحديث'}
        </button>
      </div>
      {data?.errors?.length > 0 && (
        <div className="text-xs rounded-lg px-3 py-2 bg-amber-50 text-amber-800 border border-amber-200">
          ⚠️ لم يُقرأ: {data.errors.map(s => data.totals?.[s]?.label || s).join('، ')} — القائمة بدونها.
        </div>
      )}
      {sorted.length === 0 ? (
        <div className="text-gray-400 text-sm py-16 text-center border border-dashed border-gray-200 rounded-2xl">لا توجد استثناءات مفتوحة بقيمة.</div>
      ) : (
        <div className="overflow-x-auto bg-white border border-gray-100 rounded-xl" data-tour="analytics-insights-exceptions-list">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500">
              <tr>
                <SortTh {...headerProps('rank', 'number')} className="px-3 py-2 text-right">#</SortTh>
                <SortTh {...headerProps('title')} className="px-3 py-2 text-right">البند</SortTh>
                <SortTh {...headerProps('egp', 'number')} className="px-3 py-2 text-right">القيمة (ج)</SortTh>
                <SortTh {...headerProps('branch_name')} className="px-3 py-2 text-right">الفرع</SortTh>
                <SortTh {...headerProps('source_label')} className="px-3 py-2 text-right">المصدر</SortTh>
                <SortTh {...headerProps('owner_label')} className="px-3 py-2 text-right">يتصرّف</SortTh>
                <SortTh {...headerProps('since', 'date')} className="px-3 py-2 text-right">منذ</SortTh>
                <th className="px-3 py-2 text-right">افتح</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => (
                <tr key={r.key} className="border-t border-gray-100">
                  <td className="px-3 py-2 tabular-nums text-gray-400">{r.rank}</td>
                  <td className="px-3 py-2 text-gray-800">{r.title}</td>
                  <td className="px-3 py-2 tabular-nums font-semibold">{egp(r.egp)}</td>
                  <td className="px-3 py-2 text-gray-600">{r.branch_name || '—'}</td>
                  <td className="px-3 py-2 text-gray-600">
                    {r.source_label}
                    {r.sources?.length > 1 && (
                      <div className="text-[11px] text-gray-400">
                        يظهر أيضًا في: {r.sources.slice(1).map(s => `${s.label} (${egp(s.egp)} ج)`).join('، ')}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-600">{r.owner_label}</td>
                  <td className="px-3 py-2 tabular-nums text-gray-500">{r.since || '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {(r.sources || [r]).map(s => (
                      <Link key={s.source} to={s.link} className="text-xs text-brand-600 hover:underline ml-2">{s.label || r.source_label} ←</Link>
                    ))}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-gray-200 bg-gray-50 text-xs">
                <td />
                <td className="px-3 py-2 font-semibold text-gray-600">الإجمالي</td>
                <td className="px-3 py-2 tabular-nums font-bold">{egp(total)}</td>
                <td colSpan={5} />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-gray-400">قائمة {data?.as_of} — تُرسَل كل أحد كإشعار للإدارة. لا شيء يُحسب هنا: كل سطر من مخرجات الشاشة المرتبطة به.</p>
    </div>
  )
}
