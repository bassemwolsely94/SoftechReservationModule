/**
 * ReservationsAnalyticsPage.jsx
 * Route: /analytics/reservations
 *
 * Aggregated analytics for the reservations module:
 *  - Summary KPIs (total, fulfillment rate, avg fulfill hours, lost demand)
 *  - By-branch fulfillment table
 *  - Top 20 most-reserved items
 *  - Conversion by channel
 *  - Lost demand by item
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { reservationsApi, branchesApi } from '../api/client'

const fmt    = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtPct = n => `${fmt(n, 1)}%`

const CHANNEL_LABELS = {
  pickup:        'استلام من الفرع',
  home_delivery: 'توصيل للمنزل',
  insurance:     'تأمين',
  inquiry:       'استفسار',
}

function KpiCard({ label, value, sub, icon, color = 'brand' }) {
  const cls = {
    brand:  'bg-brand-50 border-brand-200 text-brand-700',
    green:  'bg-green-50 border-green-200 text-green-700',
    blue:   'bg-blue-50 border-blue-200 text-blue-700',
    amber:  'bg-amber-50 border-amber-200 text-amber-700',
    red:    'bg-red-50 border-red-200 text-red-700',
    gray:   'bg-gray-50 border-gray-200 text-gray-600',
  }
  return (
    <div className={`rounded-xl border p-4 ${cls[color] || cls.brand}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-gray-500 mb-1 truncate">{label}</p>
          <p className="text-2xl font-black tabular-nums">{value}</p>
          {sub && <p className="text-xs mt-0.5 opacity-75">{sub}</p>}
        </div>
        {icon && <span className="text-2xl flex-shrink-0">{icon}</span>}
      </div>
    </div>
  )
}

function BarRow({ label, value, max, color = 'bg-brand-500', badge }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="w-36 text-xs text-gray-600 truncate shrink-0" title={label}>{label}</div>
      <div className="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <div className="w-12 text-right text-xs font-bold tabular-nums text-gray-700">{fmt(value)}</div>
      {badge !== undefined && (
        <div className="w-14 text-right text-xs font-semibold tabular-nums text-green-700">{fmtPct(badge)}</div>
      )}
    </div>
  )
}

export default function ReservationsAnalyticsPage() {
  const [filters, setFilters] = useState({ date_from: '', date_to: '', branch: '' })
  const upd = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    staleTime: 5 * 60_000,
  })

  const params = {
    date_from: filters.date_from || undefined,
    date_to:   filters.date_to   || undefined,
    branch:    filters.branch    || undefined,
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['reservations-analytics', params],
    queryFn:  () => reservationsApi.analytics(params).then(r => r.data),
    staleTime: 2 * 60_000,
  })

  const s = data?.summary || {}
  const byBranch    = data?.by_branch    || []
  const topItems    = data?.top_items    || []
  const byChannel   = data?.by_channel   || []
  const lostItems   = data?.lost_items   || []

  const maxBranchTotal  = Math.max(...byBranch.map(b => b.total), 1)
  const maxItemCount    = Math.max(...topItems.map(i => i.count), 1)
  const maxChannelTotal = Math.max(...byChannel.map(c => c.total), 1)
  const maxLostCount    = Math.max(...lostItems.map(i => i.count), 1)

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6" dir="rtl">

      {/* Header + filters */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-black text-gray-800">تحليلات الحجوزات</h1>
          <p className="text-xs text-gray-400 mt-0.5">معدلات التحقق، أكثر الأصناف طلباً، الطلب المفقود</p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <input type="date" className="input-field text-xs py-1.5 w-36" value={filters.date_from} onChange={e => upd('date_from', e.target.value)} />
          <input type="date" className="input-field text-xs py-1.5 w-36" value={filters.date_to}   onChange={e => upd('date_to',   e.target.value)} />
          <select className="input-field text-xs py-1.5 w-44" value={filters.branch} onChange={e => upd('branch', e.target.value)}>
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
          <button onClick={() => setFilters({ date_from: '', date_to: '', branch: '' })} className="btn-secondary text-xs py-1.5">مسح</button>
          <button onClick={() => refetch()} className="btn-secondary text-xs py-1.5">🔄 تحديث</button>
        </div>
      </div>

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
          حدث خطأ أثناء تحميل البيانات.
          <button onClick={() => refetch()} className="mr-2 underline">إعادة المحاولة</button>
        </div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-pulse">
          {[1,2,3,4].map(i => <div key={i} className="h-24 bg-gray-100 rounded-xl" />)}
        </div>
      ) : (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard icon="📋" label="إجمالي الحجوزات"     value={fmt(s.total)}            color="brand" />
            <KpiCard icon="✅" label="معدل التسليم"         value={fmtPct(s.fulfillment_rate)} sub={`${fmt(s.fulfilled)} تم تسليمها`} color="green" />
            <KpiCard icon="⏱️" label="متوسط وقت التسليم"   value={s.avg_fulfill_hours != null ? `${s.avg_fulfill_hours} ساعة` : '—'} color="blue" />
            <KpiCard icon="📉" label="طلب مفقود (ملغي/منتهي)" value={fmt(s.lost)}           sub={`من ${fmt(s.total)} إجمالي`} color="red" />
          </div>

          {/* Active pipeline */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard icon="⏳" label="قيد الانتظار"   value={fmt(s.pending)}   color="gray" />
            <KpiCard icon="📦" label="مخزون متاح"     value={fmt(s.available)} color="amber" />
            <KpiCard icon="📞" label="تم التواصل"     value={fmt(s.contacted)} color="blue" />
            <KpiCard icon="🤝" label="مؤكد"           value={fmt(s.confirmed)} color="brand" />
          </div>

          <div className="grid lg:grid-cols-2 gap-6">

            {/* Fulfillment by branch */}
            <div className="card">
              <h2 className="font-bold text-gray-700 mb-4 text-sm">معدل التسليم حسب الفرع</h2>
              {byBranch.length === 0 ? (
                <div className="text-xs text-gray-400 py-4 text-center">لا توجد بيانات</div>
              ) : (
                <div className="space-y-1">
                  <div className="flex items-center gap-3 mb-2 text-[10px] text-gray-400">
                    <div className="w-36" />
                    <div className="flex-1 text-right">الحجوزات</div>
                    <div className="w-12 text-right">العدد</div>
                    <div className="w-14 text-right">النسبة</div>
                  </div>
                  {byBranch.map(b => (
                    <BarRow
                      key={b.branch_name}
                      label={b.branch_name}
                      value={b.total}
                      max={maxBranchTotal}
                      color="bg-brand-400"
                      badge={b.rate}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Top items */}
            <div className="card">
              <h2 className="font-bold text-gray-700 mb-4 text-sm">أكثر الأصناف المحجوزة (أول 20)</h2>
              {topItems.length === 0 ? (
                <div className="text-xs text-gray-400 py-4 text-center">لا توجد بيانات</div>
              ) : (
                <div className="space-y-1 max-h-80 overflow-y-auto">
                  {topItems.map((item, i) => (
                    <div key={item.item_name} className="flex items-center gap-3 py-1">
                      <div className="w-5 text-xs text-gray-400 font-mono text-center flex-shrink-0">{i + 1}</div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-gray-700 break-words">{item.item_name}</div>
                        {item.softech_id && <div className="text-[10px] font-mono text-gray-400">{item.softech_id}</div>}
                      </div>
                      <div className="h-2 w-24 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
                        <div
                          className="h-full bg-blue-400 rounded-full"
                          style={{ width: `${Math.max(3, (item.count / maxItemCount) * 100)}%` }}
                        />
                      </div>
                      <div className="w-8 text-right text-xs font-bold tabular-nums text-gray-700 flex-shrink-0">
                        {fmt(item.count)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Conversion by channel */}
            <div className="card">
              <h2 className="font-bold text-gray-700 mb-4 text-sm">معدل التحويل حسب القناة</h2>
              {byChannel.length === 0 ? (
                <div className="text-xs text-gray-400 py-4 text-center">لا توجد بيانات</div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-gray-100">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-100">
                        <th className="text-right px-3 py-2 text-gray-500 font-semibold">القناة</th>
                        <th className="text-center px-2 py-2 text-gray-500 font-semibold">الإجمالي</th>
                        <th className="text-center px-2 py-2 text-gray-500 font-semibold">مُسلَّم</th>
                        <th className="text-center px-2 py-2 text-gray-500 font-semibold">النسبة</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {byChannel.map(c => (
                        <tr key={c.channel} className="hover:bg-gray-50">
                          <td className="px-3 py-2 font-medium text-gray-700">
                            {c.channel_label || CHANNEL_LABELS[c.channel] || c.channel || '—'}
                          </td>
                          <td className="px-2 py-2 text-center font-mono text-gray-600">{fmt(c.total)}</td>
                          <td className="px-2 py-2 text-center font-mono text-green-700 font-semibold">{fmt(c.fulfilled)}</td>
                          <td className="px-2 py-2 text-center">
                            <span className={`px-1.5 py-0.5 rounded-full font-semibold ${
                              c.rate >= 70 ? 'bg-green-100 text-green-700'
                              : c.rate >= 40 ? 'bg-amber-100 text-amber-700'
                              : 'bg-red-100 text-red-600'
                            }`}>
                              {fmtPct(c.rate)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Lost demand */}
            <div className="card">
              <h2 className="font-bold text-gray-700 mb-4 text-sm">الطلب المفقود (ملغي + منتهي) حسب الصنف</h2>
              {lostItems.length === 0 ? (
                <div className="text-xs text-gray-400 py-4 text-center">لا توجد بيانات</div>
              ) : (
                <div className="space-y-1">
                  {lostItems.map(item => (
                    <BarRow
                      key={item.item_name}
                      label={item.item_name}
                      value={item.count}
                      max={maxLostCount}
                      color="bg-red-400"
                    />
                  ))}
                </div>
              )}
            </div>

          </div>
        </>
      )}
    </div>
  )
}
