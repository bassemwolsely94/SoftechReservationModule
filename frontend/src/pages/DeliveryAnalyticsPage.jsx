/**
 * DeliveryAnalyticsPage.jsx
 * F10 Driver Performance | F11 Area Heatmap | F12 Shift Report | F14 CSAT | C20 Small orders
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { deliveryApi, branchesApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import SortTh from '../components/SortTh'
import useSortableRows from '../hooks/useSortableRows'
import BranchMultiSelect from '../components/BranchMultiSelect'

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

  // every driver is loaded → sort in the browser (hook before the early returns)
  const drivers = useSortableRows(data?.drivers || [], { getValue: (d, k) => (k === 'name' ? d.driver_name : d[k]) })

  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (!data?.drivers?.length) return <div className="text-center py-12 text-gray-400">لا يوجد بيانات سائقين للفترة المحددة</div>

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-gray-200" data-tour="delivery-analytics-drivers">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs">
            <tr>
              <SortTh {...drivers.headerProps('name', 'text')} className="text-right px-4 py-3 font-semibold text-gray-600">السائق</SortTh>
              <SortTh {...drivers.headerProps('total', 'number')} className="text-center px-3 py-3 font-semibold text-gray-600">إجمالي</SortTh>
              <SortTh {...drivers.headerProps('delivered', 'number')} className="text-center px-3 py-3 font-semibold text-green-600">مُسلَّم</SortTh>
              <SortTh {...drivers.headerProps('failed', 'number')} className="text-center px-3 py-3 font-semibold text-red-500">فشل</SortTh>
              <SortTh {...drivers.headerProps('success_rate', 'number')} className="text-center px-3 py-3 font-semibold text-gray-600">معدل النجاح</SortTh>
              <SortTh {...drivers.headerProps('avg_mins', 'number')} className="text-center px-3 py-3 font-semibold text-blue-600">متوسط الوقت</SortTh>
              <SortTh {...drivers.headerProps('cash_collected', 'number')} className="text-left px-4 py-3 font-semibold text-gray-600">نقدي محصَّل</SortTh>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {drivers.sorted.map(d => (
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

// ── C20 Small orders + fee-less invoices (report only) ──────────────────────
function SmallOrdersTab({ dateFrom, dateTo, branchId }) {
  const params = { date_from: dateFrom, date_to: dateTo, branch: branchId || undefined }
  const { data, isLoading, isError } = useQuery({
    queryKey: ['delivery-small-orders', dateFrom, dateTo, branchId],
    queryFn: () => deliveryApi.smallOrders(params).then(r => r.data),
  })
  const [busy, setBusy] = useState(false)
  const { sorted, headerProps: hp } = useSortableRows(data?.orders || [], { defaultSort: { key: 'margin', dir: 'asc', type: 'number' } })
  const exportXlsx = async () => {
    setBusy(true)
    try {
      const res = await deliveryApi.smallOrdersExcel(params)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `delivery_small_orders_${dateFrom}_${dateTo}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } finally { setBusy(false) }
  }
  if (isLoading) return <div className="text-center py-12 text-gray-400 animate-pulse">جاري التحميل…</div>
  if (isError || !data) return <div className="text-center py-12 text-gray-400">تعذّر تحميل التقرير</div>
  const t = data.totals
  const flag = (on, label, tone) => (on ? <span className={`text-[11px] px-1.5 py-0.5 rounded-full ${tone}`}>{label}</span> : null)
  return (
    <div className="space-y-4">
      <div className="text-xs text-gray-600 leading-6 bg-gray-50 border border-gray-200 rounded-lg p-2">
        فواتير بيع قناة التوصيل (90). «صغير» = أصناف أقل من {fmt(data.rules.small_order_egp)} ج.
        «أقل من أجر الطيار» = هامش الأصناف + الرسوم أقل من {fmt(data.rules.rider_per_fee_unit)} ج لكل وحدة رسوم.
        «بدون رسوم» = مفيش سطر «D.L.V.»، و«غير مفسَّر» لو نفس العميل مالوش فاتورة برسوم في نفس اليوم أو يوم قبل/بعد.
        للمتابعة بس — أي حد أدنى للطلب أو رسوم قرار المالك.
      </div>
      <div className="flex flex-wrap items-center gap-3" data-tour="delivery-analytics-small-orders">
        <span className="text-sm">طلبات: <b>{fmt(t.orders)}</b></span>
        <span className="text-sm text-amber-700">صغيرة: <b>{fmt(t.small)}</b></span>
        <span className="text-sm text-rose-700">أقل من أجر الطيار: <b>{fmt(t.below_rider)}</b></span>
        <span className="text-sm text-gray-700">بدون رسوم: <b>{fmt(t.feeless)}</b> — غير مفسَّرة <b>{fmt(t.feeless_unexplained)}</b></span>
        <button onClick={exportXlsx} disabled={busy}
          className="ms-auto px-3 py-1.5 text-xs rounded-lg border border-gray-300 hover:border-brand-400 disabled:opacity-50">
          {busy ? '…' : '⬇ Excel'}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-right">
          <thead className="bg-gray-50 text-gray-600">
            <tr><th className="px-2 py-1.5">الفرع</th><th className="px-2 py-1.5">طلبات</th><th className="px-2 py-1.5">صغيرة</th>
              <th className="px-2 py-1.5">أقل من أجر الطيار</th><th className="px-2 py-1.5">بدون رسوم</th>
              <th className="px-2 py-1.5">غير مفسَّرة</th><th className="px-2 py-1.5">الرسوم (ج)</th></tr>
          </thead>
          <tbody className="divide-y">
            {data.by_branch.map(b => (
              <tr key={b.branch_id}>
                <td className="px-2 py-1">{b.branch_name || b.branch_code}</td>
                <td className="px-2 py-1 font-mono">{fmt(b.orders)}</td><td className="px-2 py-1 font-mono">{fmt(b.small)}</td>
                <td className="px-2 py-1 font-mono">{fmt(b.below_rider)}</td><td className="px-2 py-1 font-mono">{fmt(b.feeless)}</td>
                <td className="px-2 py-1 font-mono">{fmt(b.feeless_unexplained)}</td><td className="px-2 py-1 font-mono">{fmt(b.fees)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!sorted.length ? <div className="text-center py-6 text-gray-400">لا توجد طلبات مُعلَّمة في الفترة</div> : (
        <div className="overflow-x-auto">
          {t.shown < t.flagged && <p className="text-xs text-gray-500 mb-1">يظهر أول {fmt(t.shown)} من {fmt(t.flagged)} — الباقي في Excel.</p>}
          <table className="w-full text-xs text-right">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <SortTh {...hp('day', 'text')} className="px-2 py-1.5">التاريخ</SortTh>
                <SortTh {...hp('branch_name', 'text')} className="px-2 py-1.5">الفرع</SortTh>
                <SortTh {...hp('docnumber', 'text')} className="px-2 py-1.5">الفاتورة</SortTh>
                <SortTh {...hp('customer', 'text')} className="px-2 py-1.5">العميل</SortTh>
                <SortTh {...hp('goods', 'number')} className="px-2 py-1.5">الأصناف (ج)</SortTh>
                <SortTh {...hp('fee', 'number')} className="px-2 py-1.5">الرسوم</SortTh>
                <SortTh {...hp('margin', 'number')} className="px-2 py-1.5">الهامش + الرسوم</SortTh>
                <th className="px-2 py-1.5">ليه</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sorted.map(r => (
                <tr key={r.invoice_id}>
                  <td className="px-2 py-1 whitespace-nowrap">{r.day}</td>
                  <td className="px-2 py-1">{r.branch_name || r.branch_code}</td>
                  <td className="px-2 py-1 font-mono">{r.docnumber}</td>
                  <td className="px-2 py-1">{r.customer}</td>
                  <td className="px-2 py-1 font-mono">{fmt(r.goods, 2)}</td>
                  <td className="px-2 py-1 font-mono">{fmt(r.fee, 2)}</td>
                  <td className="px-2 py-1 font-mono">{fmt(r.margin, 2)}</td>
                  <td className="px-2 py-1 whitespace-nowrap flex gap-1">
                    {flag(r.small, 'صغير', 'bg-amber-100 text-amber-800')}
                    {flag(r.below_rider, 'أقل من أجر الطيار', 'bg-rose-100 text-rose-700')}
                    {flag(r.feeless_unexplained, 'بدون رسوم', 'bg-gray-100 text-gray-700')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
  { id: 'small',    label: '💸 طلبات صغيرة وبدون رسوم', component: SmallOrdersTab },
]

export default function DeliveryAnalyticsPage() {
  const [activeTab, setActiveTab]  = useState('drivers')
  useHelpTab(activeTab)
  const [dateFrom,  setDateFrom]   = useState(_daysAgo(30))
  const [dateTo,    setDateTo]     = useState(_today())
  const [branchIds, setBranchIds]  = useState([])   // multi-select: nothing ticked = all
  const branchId = branchIds.join(',')              // the tabs send it as ?branch=3,7 ('' = all)

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
          <h1 className="text-2xl font-bold text-gray-800" data-tour="delivery-analytics-header">تحليلات التوصيل</h1>
          <p className="text-sm text-gray-500 mt-0.5">أداء السائقين · المناطق · الورديات · رضا العملاء</p>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap items-center gap-3" data-tour="delivery-analytics-filters">
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
        <BranchMultiSelect branches={branches} selected={branchIds} onChange={setBranchIds}
          dataTour="delivery-analytics-branch" />
      </div>

      {/* Tab navigation */}
      <div className="flex border-b border-gray-200 gap-1" data-tour="delivery-analytics-tabs">
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
      <div className="bg-white rounded-xl border border-gray-200 p-5" data-tour="delivery-analytics-content">
        {ActiveComponent && (
          <ActiveComponent dateFrom={dateFrom} dateTo={dateTo} branchId={branchId} />
        )}
      </div>
    </div>
  )
}
