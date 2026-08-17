/**
 * TransfersAnalyticsPage.jsx
 * Route: /analytics/transfers
 *
 * C1 — Analytics panel: KPIs, avg cycle time, top items, branch flow, rejection rate
 * C3 — Discrepancy report: received vs approved quantity mismatches
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { transfersApi } from '../api/client'
import { useNavigate } from 'react-router-dom'

const fmt    = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtPct = n => `${Number(n || 0).toFixed(1)}%`
const fmtH   = h => h != null ? `${Number(h).toFixed(1)} س` : '—'

const fmtDate = iso => {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) }
  catch { return iso }
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

function BarRow({ label, value, max, badge, color = 'bg-brand-500' }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="w-28 text-xs text-gray-600 truncate flex-shrink-0 text-right">{label}</div>
      <div className="flex-1 bg-gray-100 rounded-full h-2">
        <div className={`${color} rounded-full h-2 transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <div className="w-10 text-xs text-gray-700 font-bold tabular-nums text-left">{value}</div>
      {badge && <div className="text-xs text-gray-400">{badge}</div>}
    </div>
  )
}

// ── C1 — Analytics Panel ──────────────────────────────────────────────────────

function AnalyticsPanel({ days }) {
  const { data, isLoading } = useQuery({
    queryKey: ['transfers-analytics', days],
    queryFn: () => transfersApi.analytics({ days }).then(r => r.data),
    staleTime: 120_000,
  })

  if (isLoading) return (
    <div className="animate-pulse space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[1,2,3,4].map(i => <div key={i} className="h-24 bg-gray-100 rounded-xl" />)}
      </div>
      <div className="h-48 bg-gray-100 rounded-xl" />
    </div>
  )
  if (!data) return null

  const { kpis, top_items = [], branch_flow = [], rejection_by_branch = [] } = data
  const maxItems = top_items[0]?.request_count || 1
  const maxFlow  = branch_flow[0]?.count || 1
  const maxRej   = rejection_by_branch[0]?.total || 1

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard label="إجمالي الطلبات"     value={fmt(kpis.total)}           icon="🔀" color="brand" />
        <KpiCard label="نسبة الإكمال"        value={fmtPct(kpis.completion_rate)} icon="✅" color="green"
                 sub={`${fmt(kpis.completed)} طلب مكتمل`} />
        <KpiCard label="نسبة الرفض"          value={fmtPct(kpis.rejection_rate)} icon="❌" color="red"
                 sub={`${fmt(kpis.rejected)} مرفوض`} />
        <KpiCard label="متوسط دورة الطلب"   value={fmtH(kpis.avg_cycle_hours)}  icon="⏱️" color="blue"
                 sub={`متوسط الاستجابة: ${fmtH(kpis.avg_response_hours)}`} />
      </div>

      <div className="grid sm:grid-cols-2 gap-6">
        {/* Top transferred items */}
        <div className="card">
          <div className="text-sm font-bold text-gray-700 mb-4">أكثر الأصناف تحويلاً</div>
          {top_items.length === 0
            ? <div className="text-xs text-gray-400 text-center py-6">لا توجد بيانات</div>
            : top_items.slice(0, 15).map((item, i) => (
              <BarRow
                key={i}
                label={item['item__name'] || '—'}
                value={item.request_count}
                max={maxItems}
                badge={`${Number(item.total_qty || 0).toFixed(0)} وحدة`}
              />
            ))
          }
        </div>

        {/* Branch flow */}
        <div className="card">
          <div className="text-sm font-bold text-gray-700 mb-4">أكثر مسارات التحويل نشاطاً</div>
          {branch_flow.length === 0
            ? <div className="text-xs text-gray-400 text-center py-6">لا توجد بيانات</div>
            : branch_flow.map((flow, i) => (
              <BarRow
                key={i}
                label={`${flow['requesting_branch__name_ar'] || '—'} → ${flow['supplying_branch__name_ar'] || '—'}`}
                value={flow.count}
                max={maxFlow}
                color="bg-blue-500"
              />
            ))
          }
        </div>
      </div>

      {/* Rejection by supplying branch */}
      {rejection_by_branch.length > 0 && (
        <div className="card">
          <div className="text-sm font-bold text-gray-700 mb-4">معدل الرفض حسب الفرع المصدر</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-right py-2 text-xs font-semibold text-gray-400">الفرع المصدر</th>
                  <th className="text-right py-2 text-xs font-semibold text-gray-400">إجمالي</th>
                  <th className="text-right py-2 text-xs font-semibold text-gray-400">مرفوض</th>
                  <th className="text-right py-2 text-xs font-semibold text-gray-400">نسبة الرفض</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rejection_by_branch.map((row, i) => {
                  const pct = row.total > 0 ? (row.rejected / row.total * 100) : 0
                  return (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="py-2 font-medium text-gray-800">{row['supplying_branch__name_ar'] || '—'}</td>
                      <td className="py-2 tabular-nums text-gray-600">{row.total}</td>
                      <td className="py-2 tabular-nums text-red-600 font-semibold">{row.rejected}</td>
                      <td className="py-2">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                          pct > 30 ? 'bg-red-100 text-red-700'
                          : pct > 10 ? 'bg-amber-100 text-amber-700'
                          : 'bg-green-100 text-green-700'
                        }`}>
                          {fmtPct(pct)}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── C3 — Discrepancy Report ───────────────────────────────────────────────────

function DiscrepancyReport() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['transfers-discrepancy'],
    queryFn: () => transfersApi.discrepancyReport().then(r => r.data),
    staleTime: 300_000,
  })

  if (isLoading) return (
    <div className="animate-pulse h-48 bg-gray-100 rounded-xl" />
  )

  const discrepancies = data?.discrepancies || []

  if (discrepancies.length === 0) return (
    <div className="card text-center py-12">
      <div className="text-3xl mb-2">✅</div>
      <div className="text-sm font-semibold text-gray-600">لا توجد تباينات</div>
      <div className="text-xs text-gray-400 mt-1">جميع الكميات المستلمة تطابق الكميات المعتمدة</div>
    </div>
  )

  return (
    <div className="card p-0 overflow-hidden">
      <div className="px-4 py-3 bg-red-50 border-b border-red-100 flex items-center gap-2">
        <span className="text-sm font-bold text-red-800">تقرير التباينات</span>
        <span className="text-xs bg-red-600 text-white px-2 py-0.5 rounded-full font-bold">{discrepancies.length}</span>
        <div className="text-xs text-red-600 mr-auto">كمية مستلمة تختلف عن المعتمدة</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">رقم الطلب</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">الصنف</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">المصدر</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">معتمد</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">مستلم</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">الفرق</th>
              <th className="text-right px-4 py-2 text-xs font-semibold text-gray-400">التاريخ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {discrepancies.map((d, i) => (
              <tr key={i}
                className="hover:bg-red-50 cursor-pointer transition-colors"
                onClick={() => navigate(`/transfers/${d.request_id}`)}>
                <td className="px-4 py-2 font-mono font-bold text-brand-700 text-xs">{d.request_number}</td>
                <td className="px-4 py-2">
                  <div className="font-medium text-gray-800 text-xs break-words max-w-40">{d.item_name}</div>
                  <div className="text-[10px] text-gray-400 font-mono">{d.item_code}</div>
                </td>
                <td className="px-4 py-2 text-xs text-gray-600">{d.supplying_branch}</td>
                <td className="px-4 py-2 font-bold tabular-nums text-blue-700">{d.approved_quantity}</td>
                <td className="px-4 py-2 font-bold tabular-nums text-green-700">{d.received_quantity}</td>
                <td className="px-4 py-2">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    d.short ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
                  }`}>
                    {d.short ? '-' : '+'}{Math.abs(d.discrepancy)} ({d.discrepancy_pct}%)
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-gray-400">{fmtDate(d.completed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'analytics',    label: 'التحليلات',      icon: '📊' },
  { key: 'discrepancy',  label: 'تقرير التباينات', icon: '⚠️' },
]

export default function TransfersAnalyticsPage() {
  const [activeTab, setActiveTab] = useState('analytics')
  const [days, setDays] = useState(30)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-black text-gray-900">تحليلات طلبات التحويل</h1>
            <p className="text-xs text-gray-400">أداء وسير عمل التحويلات بين الفروع</p>
          </div>
          <div className="flex-1" />

          {activeTab === 'analytics' && (
            <select
              value={days}
              onChange={e => setDays(Number(e.target.value))}
              className="input-field text-xs w-36"
            >
              <option value={7}>آخر 7 أيام</option>
              <option value={30}>آخر 30 يوم</option>
              <option value={90}>آخر 90 يوم</option>
              <option value={365}>آخر سنة</option>
            </select>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mt-3">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                activeTab === t.key
                  ? 'bg-brand-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              <span>{t.icon}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-6 py-6">
        {activeTab === 'analytics' && <AnalyticsPanel days={days} />}
        {activeTab === 'discrepancy' && <DiscrepancyReport />}
      </div>
    </div>
  )
}
