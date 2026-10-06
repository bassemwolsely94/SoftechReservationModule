/**
 * DeliveryAnalyticsPage.jsx
 * F10 Driver Performance | F11 Area Heatmap | F12 Shift Report | F14 CSAT
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { deliveryApi, branchesApi } from '../api/client'

const fmt     = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const _today  = () => new Date().toISOString().slice(0, 10)
const _daysAgo = d => { const dt = new Date(); dt.setDate(dt.getDate() - d); return dt.toISOString().slice(0, 10) }

function ScoreStar({ score }) {
  return (
    <div className="flex gap-0.5">
      {[1,2,3,4,5].map(i => (
        <span key={i} className={`text-sm ${i <= score ? 'text-amber-400' : 'text-gray-200'}`}>★</span>
      ))}
    </div>
  )
}

// ── F10 Driver Performance ─────────────────────────────────────────────────────
function DriverPerformanceTab({ dateFrom, dateTo, branchId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['driver-perf', dateFrom, dateTo, branchId],
    queryFn: () => deliveryApi.driverPerformance({ date_from: dateFrom, date_to: dateTo, branch: branchId || undefined }).then(r => r.data),
  })

  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (!data?.drivers?.length) return <div className="text-center py-12 text-gray-400">لا يوجد بيانات سائقين للفترة المحددة</div>

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs">
            <tr>
              <th className="text-right px-4 py-3 font-semibold text-gray-600">السائق</th>
              <th className="text-center px-3 py-3 font-semibold text-gray-600">إجمالي</th>
              <th className="text-center px-3 py-3 font-semibold text-green-600">مُسلَّم</th>
              <th className="text-center px-3 py-3 font-semibold text-red-500">فشل</th>
              <th className="text-center px-3 py-3 font-semibold text-gray-600">معدل النجاح</th>
              <th className="text-center px-3 py-3 font-semibold text-blue-600">متوسط الوقت</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">نقدي محصَّل</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.drivers.map(d => (
              <tr key={d.driver_id} className="hover:bg-gray-50/50">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-800">{d.driver_name}</div>
                  {d.driver_mobile && <div className="text-xs text-gray-400 font-mono">{d.driver_mobile}</div>}
                </td>
                <td className="px-3 py-3 text-center font-mono text-gray-700">{d.total}</td>
                <td className="px-3 py-3 text-center font-mono text-green-700 font-semibold">{d.delivered}</td>
                <td className="px-3 py-3 text-center font-mono text-red-500">{d.failed}</td>
                <td className="px-3 py-3 text-center">
                  <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
                    d.success_rate >= 90 ? 'bg-green-50 text-green-700' :
                    d.success_rate >= 75 ? 'bg-amber-50 text-amber-700' :
                    'bg-red-50 text-red-600'
                  }`}>
                    {fmt(d.success_rate, 1)}%
                  </div>
                </td>
                <td className="px-3 py-3 text-center text-gray-600">
                  {d.avg_mins ? `${fmt(d.avg_mins, 0)} د` : '—'}
                </td>
                <td className="px-4 py-3 text-left font-mono text-gray-700">{fmt(d.cash_collected, 2)} ج.م</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── F11 Area Heatmap ──────────────────────────────────────────────────────────
function AreaHeatmapTab({ dateFrom, dateTo, branchId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['area-heatmap', dateFrom, dateTo, branchId],
    queryFn: () => deliveryApi.areaHeatmap({ date_from: dateFrom, date_to: dateTo, branch: branchId || undefined }).then(r => r.data),
  })

  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (!data?.by_governorate?.length) return <div className="text-center py-12 text-gray-400">لا توجد بيانات مناطق</div>

  const maxOrders = Math.max(...data.by_governorate.map(r => r.orders), 1)

  return (
    <div className="space-y-6">
      {/* Governorate bars */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">الطلبات حسب المحافظة</h3>
        <div className="space-y-2">
          {data.by_governorate.map(gov => (
            <div key={gov.governorate} className="flex items-center gap-3">
              <span className="text-sm text-gray-700 w-32 shrink-0 text-right">{gov.governorate}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-6 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-brand-500 to-brand-600 rounded-full flex items-center justify-end pr-2 transition-all"
                  style={{ width: `${Math.max(2, (gov.orders / maxOrders) * 100)}%` }}
                >
                  <span className="text-white text-xs font-mono">{gov.orders}</span>
                </div>
              </div>
              <div className="text-xs text-gray-500 w-24 shrink-0 text-left">
                {fmt(gov.revenue, 0)} ج.م
              </div>
              <div className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${
                gov.success_rate >= 85 ? 'bg-green-50 text-green-600' : 'bg-amber-50 text-amber-600'
              }`}>
                {fmt(gov.success_rate, 0)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Top areas table */}
      {data.by_area?.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">أكثر المناطق طلبات (أعلى 20)</h3>
          <div className="grid grid-cols-2 gap-2">
            {data.by_area.map((area, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2 text-xs">
                <div>
                  <span className="font-medium text-gray-700">{area.area}</span>
                  <span className="text-gray-400 mr-1">· {area.governorate}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-gray-600">{area.orders} طلب</span>
                  <span className="text-brand-600 font-mono">{fmt(area.revenue, 0)} ج.م</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── F12 Shift Report ──────────────────────────────────────────────────────────
function ShiftReportTab({ dateFrom, dateTo, branchId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['shift-report', dateFrom, dateTo, branchId],
    queryFn: () => deliveryApi.shiftReport({ date_from: dateFrom, date_to: dateTo, branch: branchId || undefined }).then(r => r.data),
  })

  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (!data?.shifts) return <div className="text-center py-12 text-gray-400">لا توجد بيانات</div>

  const maxShift = Math.max(...data.shifts.map(s => s.orders), 1)
  const maxHour  = Math.max(...(data.hourly || []).map(h => h.orders), 1)

  return (
    <div className="space-y-6">
      {data.peak_shift && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-800">
          ⚡ ذروة الطلبات: <strong>{data.peak_shift}</strong>
        </div>
      )}

      {/* Shift bars */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {data.shifts.map(shift => (
          <div key={shift.shift} className="bg-white rounded-xl border border-gray-200 p-4 text-center">
            <div className="text-xl mb-1">{shift.label.split(' ')[0]}</div>
            <div className="text-xs text-gray-400 mb-2">{shift.hours}</div>
            <div className="text-2xl font-bold font-mono text-gray-800">{shift.orders}</div>
            <div className="text-xs text-gray-500">طلب</div>
            <div className="text-xs font-mono text-brand-600 mt-1">{fmt(shift.revenue, 0)} ج.م</div>
            {/* Mini bar */}
            <div className="mt-2 bg-gray-100 rounded-full h-1.5">
              <div className="h-full bg-brand-500 rounded-full"
                style={{ width: `${Math.max(2, (shift.orders / maxShift) * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* Hourly chart */}
      {data.hourly && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع الطلبات بالساعة</h3>
          <div className="flex items-end gap-0.5 h-24">
            {data.hourly.map(h => (
              <div key={h.hour} className="flex-1 flex flex-col items-center gap-0.5">
                <div
                  className="w-full bg-brand-400 rounded-t"
                  style={{ height: `${Math.max(2, (h.orders / maxHour) * 80)}px` }}
                  title={`${h.hour}:00 — ${h.orders} طلب`}
                />
                {h.hour % 4 === 0 && (
                  <span className="text-[9px] text-gray-400">{h.hour}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── F14 CSAT Report ───────────────────────────────────────────────────────────
function CSATTab({ dateFrom, dateTo, branchId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['csat-report', dateFrom, dateTo, branchId],
    queryFn: () => deliveryApi.csatReport({ date_from: dateFrom, date_to: dateTo, branch: branchId || undefined }).then(r => r.data),
  })

  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (!data) return null

  const totalDist = Object.values(data.distribution || {}).reduce((s, n) => s + n, 0) || 1

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-center">
          <div className="text-3xl font-bold text-amber-700">{fmt(data.avg_score, 1)}</div>
          <div className="text-sm text-amber-600 mt-1">متوسط التقييم</div>
          <ScoreStar score={Math.round(data.avg_score)} />
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-center">
          <div className="text-3xl font-bold text-blue-700">{fmt(data.total)}</div>
          <div className="text-sm text-blue-600 mt-1">إجمالي التقييمات</div>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
          <div className="text-3xl font-bold text-green-700">{fmt(data.wa_pending)}</div>
          <div className="text-sm text-green-600 mt-1">واتساب معلق الإرسال</div>
        </div>
      </div>

      {/* Score distribution */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع التقييمات</h3>
        <div className="space-y-2">
          {[5,4,3,2,1].map(score => {
            const count = data.distribution?.[String(score)] || 0
            const pct = Math.round((count / totalDist) * 100)
            return (
              <div key={score} className="flex items-center gap-3">
                <ScoreStar score={score} />
                <div className="flex-1 bg-gray-100 rounded-full h-5 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      score >= 4 ? 'bg-green-400' : score === 3 ? 'bg-amber-400' : 'bg-red-400'
                    }`}
                    style={{ width: `${Math.max(1, pct)}%` }}
                  />
                </div>
                <span className="text-sm font-mono text-gray-600 w-16 text-left">{count} ({pct}%)</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Low score orders */}
      {data.low_scores?.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-red-600 mb-3">⚠️ تقييمات منخفضة (1-2 ⭐)</h3>
          <div className="space-y-2">
            {data.low_scores.map((item, i) => (
              <div key={i} className="bg-red-50 rounded-lg p-3 border border-red-100">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">{item['order__customer_name']}</span>
                  <ScoreStar score={item.score} />
                </div>
                <div className="text-xs text-gray-500 space-x-3">
                  <span className="font-mono">{item['order__order_number']}</span>
                  <span className="mr-3">{item['order__customer_phone']}</span>
                </div>
                {item.feedback && (
                  <p className="text-xs text-gray-600 mt-1 bg-white rounded p-2">{item.feedback}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MAIN PAGE
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const TABS = [
  { id: 'drivers',  label: '🚴 أداء السائقين',   component: DriverPerformanceTab },
  { id: 'heatmap',  label: '🗺️ خريطة المناطق',   component: AreaHeatmapTab      },
  { id: 'shifts',   label: '⏰ تقرير الورديات',   component: ShiftReportTab      },
  { id: 'csat',     label: '⭐ رضا العملاء',      component: CSATTab             },
]

export default function DeliveryAnalyticsPage() {
  const [activeTab, setActiveTab]  = useState('drivers')
  const [dateFrom,  setDateFrom]   = useState(_daysAgo(30))
  const [dateTo,    setDateTo]     = useState(_today())
  const [branchId,  setBranchId]   = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data?.results || r.data || []),
    staleTime: 300_000,
  })

  const ActiveComponent = TABS.find(t => t.id === activeTab)?.component || null

  return (
    <div className="p-6 space-y-5 max-w-screen-xl mx-auto" dir="rtl">

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">تحليلات التوصيل</h1>
          <p className="text-sm text-gray-500 mt-0.5">أداء السائقين · المناطق · الورديات · رضا العملاء</p>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap items-center gap-3">
        {[
          {l:'اليوم',f:_today(),t:_today()},
          {l:'٧ أيام',f:_daysAgo(7),t:_today()},
          {l:'٣٠ يوم',f:_daysAgo(30),t:_today()},
          {l:'٩٠ يوم',f:_daysAgo(90),t:_today()},
        ].map(r => (
          <button key={r.l} onClick={() => { setDateFrom(r.f); setDateTo(r.t) }}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              dateFrom===r.f && dateTo===r.t ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
            }`}>
            {r.l}
          </button>
        ))}
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
          className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none" />
        <span className="text-gray-400 text-xs">—</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
          className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none" />
        <select value={branchId} onChange={e => setBranchId(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none">
          <option value="">كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>
      </div>

      {/* Tab navigation */}
      <div className="flex border-b border-gray-200 gap-1">
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {ActiveComponent && (
          <ActiveComponent dateFrom={dateFrom} dateTo={dateTo} branchId={branchId} />
        )}
      </div>
    </div>
  )
}
