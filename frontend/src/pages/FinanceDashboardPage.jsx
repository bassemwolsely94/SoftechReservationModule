/**
 * FinanceDashboardPage.jsx
 * Route: /finance/dashboard
 *
 * Executive financial dashboard — consolidated KPIs for the selected period.
 * Shows: Revenue, Gross Profit, Net Profit, Purchases, Cash Flow, Inventory.
 * Includes monthly trend (bar chart) + branch breakdown table.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── helpers ──────────────────────────────────────────────────────────────────

const fmt = (n, decimals = 0) => {
  const num = parseFloat(n || 0)
  if (isNaN(num)) return '—'
  return num.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}
const pct = (n, d = 1) => `${fmt(n, d)}%`

const KPI_EMPTY = {
  net_revenue: 0, gross_revenue: 0, returns_value: 0,
  gross_profit: 0, gross_margin_pct: 0,
  net_profit: 0, net_margin_pct: 0,
  total_purchases: 0, net_purchases: 0,
  total_expenses: 0, net_cash_flow: 0,
  inventory_value: 0, is_complete: false,
  period_label: '—',
}

// ── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({ icon, label, value, sub, color = 'green', trend }) {
  const colors = {
    green:  'bg-green-50 border-green-200 text-green-700',
    blue:   'bg-blue-50 border-blue-200 text-blue-700',
    orange: 'bg-orange-50 border-orange-200 text-orange-700',
    purple: 'bg-purple-50 border-purple-200 text-purple-700',
    red:    'bg-red-50 border-red-200 text-red-700',
    gray:   'bg-gray-50 border-gray-200 text-gray-700',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="flex items-start justify-between">
        <span className="text-2xl">{icon}</span>
        {trend != null && (
          <span className={`text-xs font-medium ${trend >= 0 ? 'text-green-600' : 'text-red-500'}`}>
            {trend >= 0 ? '↑' : '↓'} {Math.abs(trend).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-2">
        <div className="text-xs text-gray-500 font-medium">{label}</div>
        <div className="text-xl font-bold mt-0.5">{value}</div>
        {sub && <div className="text-xs opacity-70 mt-0.5">{sub}</div>}
      </div>
    </div>
  )
}

// ── Mini Bar Chart ────────────────────────────────────────────────────────────

function MiniBarChart({ data, valueKey = 'net_revenue', color = '#10b981' }) {
  if (!data?.length) return <div className="text-center text-gray-400 text-sm py-8">لا توجد بيانات</div>

  const max  = Math.max(...data.map(d => parseFloat(d[valueKey] || 0)))
  const MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

  return (
    <div className="flex items-end gap-1 h-28">
      {data.map((d, i) => {
        const val = parseFloat(d[valueKey] || 0)
        const h   = max > 0 ? Math.max(4, (val / max) * 100) : 4
        return (
          <div key={i} className="flex-1 flex flex-col items-center gap-0.5 group">
            <div
              className="w-full rounded-t transition-all group-hover:opacity-80 relative"
              style={{ height: `${h}%`, backgroundColor: color, minHeight: '4px' }}
              title={`${MONTHS_AR[(d.period__month || i + 1) - 1]}: ${fmt(val)}`}
            />
            <span className="text-[9px] text-gray-400">
              {MONTHS_AR[(d.period__month || i + 1) - 1]?.slice(0, 3)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Branch Row ────────────────────────────────────────────────────────────────

function BranchRow({ snap }) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-3 py-2 text-sm font-medium text-gray-800">{snap.branch_name || '—'}</td>
      <td className="px-3 py-2 text-sm text-gray-700 text-left">{fmt(snap.net_revenue)}</td>
      <td className="px-3 py-2 text-sm text-gray-700 text-left">{fmt(snap.gross_profit)}</td>
      <td className="px-3 py-2 text-sm text-center">
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium
          ${parseFloat(snap.gross_margin_pct) >= 20
            ? 'bg-green-100 text-green-700'
            : parseFloat(snap.gross_margin_pct) >= 10
              ? 'bg-yellow-100 text-yellow-700'
              : 'bg-red-100 text-red-700'
          }`}
        >
          {pct(snap.gross_margin_pct)}
        </span>
      </td>
      <td className="px-3 py-2 text-sm text-gray-700 text-left">{fmt(snap.net_profit)}</td>
      <td className="px-3 py-2 text-sm text-center">
        <span className={`inline-block w-2 h-2 rounded-full ${snap.is_complete ? 'bg-green-500' : 'bg-amber-400'}`} />
      </td>
    </tr>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function FinanceDashboardPage() {
  const today = new Date()
  const [year,  setYear]  = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['finance-dashboard', year, month],
    queryFn:  () => financeApi.dashboard({ year, month }).then(r => r.data),
    staleTime: 60_000,
  })

  const kpi = data || KPI_EMPTY
  const trend = data?.monthly_trend || []
  const branches = data?.branch_snapshots || []

  const MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
  const YEARS     = Array.from({ length: 5 }, (_, i) => today.getFullYear() - i)

  return (
    <div className="space-y-6" dir="rtl">
      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={year}
          onChange={e => setYear(Number(e.target.value))}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
        >
          {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <select
          value={month}
          onChange={e => setMonth(Number(e.target.value))}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
        >
          {MONTHS_AR.map((m, i) => (
            <option key={i + 1} value={i + 1}>{m}</option>
          ))}
        </select>
        <RefreshButton loading={isFetching} onClick={() => refetch()} variant="primary">
          تحديث
        </RefreshButton>
        {data?.period_label && (
          <span className="text-sm text-gray-500">الفترة: {data.period_label}</span>
        )}
        {!kpi.is_complete && kpi.net_revenue > 0 && (
          <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full">
            ⚠ بيانات غير مكتملة
          </span>
        )}
      </div>

      {/* ── Loading / Error ───────────────────────────────────────────────── */}
      {isLoading && (
        <div className="text-center py-16 text-gray-400 animate-pulse">جارٍ تحميل البيانات المالية…</div>
      )}
      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
          تعذّر تحميل البيانات. تأكد من تشغيل المزامنة أولاً.
        </div>
      )}

      {!isLoading && !isError && (
        <>
          {/* ── KPI Grid ───────────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            <KpiCard
              icon="📈" color="green" label="صافي الإيرادات"
              value={fmt(kpi.net_revenue)}
              sub={`إجمالي: ${fmt(kpi.gross_revenue)}`}
            />
            <KpiCard
              icon="💰" color="blue" label="إجمالي الربح"
              value={fmt(kpi.gross_profit)}
              sub={`هامش: ${pct(kpi.gross_margin_pct)}`}
            />
            <KpiCard
              icon="✨" color="purple" label="صافي الربح"
              value={fmt(kpi.net_profit)}
              sub={`هامش صافي: ${pct(kpi.net_margin_pct)}`}
            />
            <KpiCard
              icon="🛒" color="orange" label="صافي المشتريات"
              value={fmt(kpi.net_purchases)}
              sub={`إجمالي: ${fmt(kpi.total_purchases)}`}
            />
            <KpiCard
              icon="💸" color="gray" label="إجمالي المصروفات"
              value={fmt(kpi.total_expenses)}
            />
            <KpiCard
              icon="🌊" color={parseFloat(kpi.net_cash_flow) >= 0 ? 'green' : 'red'}
              label="صافي التدفق النقدي"
              value={fmt(kpi.net_cash_flow)}
            />
            <KpiCard
              icon="📦" color="blue" label="قيمة المخزون"
              value={fmt(kpi.inventory_value)}
              sub="تقدير تراكمي"
            />
            <KpiCard
              icon="↩️" color="gray" label="المرتجعات"
              value={fmt(kpi.returns_value)}
            />
          </div>

          {/* ── Monthly trend ──────────────────────────────────────────────── */}
          {trend.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">
                الاتجاه الشهري — صافي الإيرادات ({year})
              </h2>
              <MiniBarChart data={trend} valueKey="net_revenue" color="#10b981" />
            </div>
          )}

          {/* ── Branch breakdown ───────────────────────────────────────────── */}
          {branches.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">
                  تفصيل الفروع — {MONTHS_AR[month - 1]} {year}
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50 text-xs text-gray-500">
                      <th className="px-3 py-2 text-right">الفرع</th>
                      <th className="px-3 py-2 text-left">صافي الإيرادات</th>
                      <th className="px-3 py-2 text-left">إجمالي الربح</th>
                      <th className="px-3 py-2 text-center">هامش الربح</th>
                      <th className="px-3 py-2 text-left">صافي الربح</th>
                      <th className="px-3 py-2 text-center">مكتمل</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {branches.map(snap => (
                      <BranchRow key={snap.id} snap={snap} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── No data banner ─────────────────────────────────────────────── */}
          {kpi.net_revenue === 0 && kpi.gross_revenue === 0 && !isLoading && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
              <div className="text-4xl mb-3">📭</div>
              <div className="text-amber-800 font-semibold">لا توجد بيانات مالية لهذه الفترة</div>
              <div className="text-amber-700 text-sm mt-1">
                قم بتشغيل المزامنة المالية أولاً من صفحة اكتشاف المخطط.
              </div>
            </div>
          )}

          {/* ── Last sync info ─────────────────────────────────────────────── */}
          {data?.last_sync && (
            <div className="text-xs text-gray-400 text-center">
              آخر مزامنة: {data.last_sync.status} —{' '}
              {data.last_sync.started_at
                ? format(new Date(data.last_sync.started_at), 'dd/MM/yyyy HH:mm', { locale: ar })
                : '—'}
            </div>
          )}
        </>
      )}
    </div>
  )
}
