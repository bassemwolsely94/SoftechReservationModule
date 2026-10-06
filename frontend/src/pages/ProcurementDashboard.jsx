/**
 * ProcurementDashboard.jsx
 *
 * Module 1 + 15: Purchasing Overview KPIs, monthly trend, alerts summary,
 * top suppliers, engine status.
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { procurementIntelApi } from '../api/client'
import { useProcurementFilters } from '../components/ProcurementFilters'
import RefreshButton from '../components/RefreshButton'

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n, dec = 0) =>
  n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })

const pct = (n, dec = 1) => (n == null ? '—' : `${Number(n).toFixed(dec)}%`)

const SEVERITY_STYLE = {
  critical: 'bg-red-100 text-red-700 border border-red-300',
  warning:  'bg-amber-100 text-amber-700 border border-amber-300',
  info:     'bg-blue-100 text-blue-700 border border-blue-300',
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, trend, color = 'brand' }) {
  const colors = {
    brand:  'from-brand-600 to-brand-700',
    green:  'from-emerald-500 to-emerald-600',
    amber:  'from-amber-500 to-amber-600',
    red:    'from-red-500 to-red-600',
    purple: 'from-purple-500 to-purple-600',
    sky:    'from-sky-500 to-sky-600',
  }
  return (
    <div className={`bg-gradient-to-br ${colors[color]} rounded-xl p-4 text-white shadow`}>
      <p className="text-xs opacity-80 mb-1">{label}</p>
      <p className="text-2xl font-bold font-mono">{value}</p>
      {sub   && <p className="text-xs opacity-75 mt-1">{sub}</p>}
      {trend != null && (
        <p className={`text-xs mt-1 font-semibold ${trend >= 0 ? 'text-emerald-200' : 'text-red-200'}`}>
          {trend >= 0 ? '▲' : '▼'} {Math.abs(trend).toFixed(1)}% مقارنة بالشهر السابق
        </p>
      )}
    </div>
  )
}

function MiniBar({ label, value, max }) {
  const pctVal = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-gray-600 mb-0.5">
        <span>{label}</span>
        <span className="font-mono">{fmt(value)}</span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full">
        <div className="h-2 bg-brand-500 rounded-full" style={{ width: `${pctVal}%` }} />
      </div>
    </div>
  )
}

function TrendChart({ data }) {
  if (!data || data.length === 0) return null
  const maxVal = Math.max(...data.map(d => d.net_value), 1)
  return (
    <div className="flex items-end gap-1 h-28">
      {data.map((d, i) => {
        const h = Math.max(4, (d.net_value / maxVal) * 100)
        return (
          <div key={i} className="flex-1 flex flex-col items-center group relative">
            <div
              className="w-full bg-brand-500 rounded-t hover:bg-brand-400 transition-colors cursor-default"
              style={{ height: `${h}%` }}
            />
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10 pointer-events-none">
              {d.month}<br />{fmt(d.net_value)} ج.م
            </div>
            {i % 3 === 0 && (
              <span className="text-[9px] text-gray-400 mt-0.5 truncate w-full text-center">
                {d.month?.slice(5)}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

function AlertRow({ alert, onResolve }) {
  const [resolving, setResolving] = useState(false)
  const handleResolve = async () => {
    setResolving(true)
    try { await onResolve(alert.id) } finally { setResolving(false) }
  }
  return (
    <div className={`flex items-start gap-3 px-3 py-2 rounded-lg text-sm ${SEVERITY_STYLE[alert.severity]}`}>
      <span className="mt-0.5 shrink-0">
        {alert.severity === 'critical' ? '🔴' : alert.severity === 'warning' ? '🟡' : 'ℹ️'}
      </span>
      <div className="flex-1 min-w-0">
        <p className="font-semibold truncate">{alert.title}</p>
        <p className="text-xs opacity-75 truncate">{alert.message}</p>
      </div>
      {!alert.is_resolved && (
        <button
          onClick={handleResolve}
          disabled={resolving}
          className="shrink-0 text-xs underline opacity-60 hover:opacity-100"
        >
          {resolving ? '...' : 'حل'}
        </button>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProcurementDashboard() {
  const navigate = useNavigate()
  const { params } = useProcurementFilters()
  const [data, setData]         = useState(null)
  const [trend, setTrend]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [triggering, setTriggering] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [dashRes, overviewRes] = await Promise.all([
        procurementIntelApi.dashboard(),
        procurementIntelApi.overview(params),
      ])
      setData(dashRes.data)
      setTrend(overviewRes.data.monthly_trend || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'فشل تحميل البيانات')
    } finally {
      setLoading(false)
    }
  }, [params])

  useEffect(() => { load() }, [load])

  const handleTrigger = async () => {
    if (!confirm('تشغيل محرك المشتريات الآن؟')) return
    setTriggering(true)
    try {
      await procurementIntelApi.triggerEngine({ days: 365 })
      setTimeout(load, 3000)
    } catch (e) {
      alert(e.response?.data?.detail || 'فشل التشغيل')
    } finally {
      setTriggering(false)
    }
  }

  const handleResolveAlert = async (id) => {
    await procurementIntelApi.resolveAlert(id, {
      resolved_by: 'dashboard_user',
      resolution_notes: 'تم الحل من لوحة التحكم',
    })
    load()
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-brand-600 font-semibold text-lg animate-pulse">
      جارٍ تحميل بيانات المشتريات…
    </div>
  )

  if (error) return (
    <div className="p-8 text-center">
      <p className="text-red-600 mb-4">{error}</p>
      <button onClick={load} className="btn-primary">إعادة المحاولة</button>
    </div>
  )

  const snap = data?.snapshot
  const run  = data?.latest_run
  const alertCounts = data?.alert_counts || {}

  return (
    <div className="p-6 space-y-6 font-cairo" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ذكاء المشتريات</h1>
          <p className="text-sm text-gray-500">
            {snap ? `آخر تحديث: ${snap.snapshot_date}` : 'لا توجد لقطة بعد'}
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton loading={loading} onClick={load}>
            🔄 تحديث
          </RefreshButton>
          <button
            onClick={handleTrigger}
            disabled={triggering || data?.engine_running}
            className="px-4 py-2 text-sm bg-brand-600 hover:bg-brand-700 text-white rounded-lg disabled:opacity-50 transition-colors"
          >
            {data?.engine_running ? '⏳ المحرك يعمل…' : triggering ? '⏳ جارٍ التشغيل…' : '▶ تشغيل المحرك'}
          </button>
        </div>
      </div>

      {/* Engine status */}
      {run && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-2 text-xs text-gray-600 flex flex-wrap gap-4">
          <span>آخر تشغيل: <strong>{new Date(run.started_at).toLocaleString('en-GB')}</strong></span>
          <span className={`font-semibold ${run.status === 'success' ? 'text-emerald-600' : 'text-red-600'}`}>
            {run.status === 'success' ? '✅ ناجح' : '❌ فشل'}
          </span>
          <span>سطور: {fmt(run.lines_upserted)}</span>
          <span>موردون: {fmt(run.suppliers_updated)}</span>
          <span>خرائط: {fmt(run.mappings_updated)}</span>
          <span>تنبيهات: {fmt(run.alerts_generated)}</span>
          {run.duration_seconds && <span>المدة: {run.duration_seconds}ث</span>}
        </div>
      )}

      {/* KPI cards — 30d */}
      {snap && (
        <div>
          <h2 className="text-sm font-semibold text-gray-500 mb-3">آخر 30 يوم</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <KpiCard label="صافي المشتريات" value={`${fmt(snap.net_purchase_value_30d)} ج.م`} trend={Number(snap.purchase_growth_pct_mom)} color="brand" />
            <KpiCard label="الكميات" value={fmt(snap.net_purchase_qty_30d)} sub="صافي وحدة" color="sky" />
            <KpiCard label="الأصناف" value={fmt(snap.distinct_items_30d)} sub="صنف مختلف" color="purple" />
            <KpiCard label="الموردون" value={fmt(snap.distinct_suppliers_30d)} sub="مورد نشط" color="green" />
            <KpiCard label="الفواتير" value={fmt(snap.invoice_count_30d)} sub="فاتورة" color="amber" />
            <KpiCard label="متوسط الهامش" value={pct(snap.avg_margin_pct_30d)} sub="هامش مشتريات" color={Number(snap.avg_margin_pct_30d) >= 20 ? 'green' : 'red'} />
          </div>
        </div>
      )}

      {/* KPI cards — 365d */}
      {snap && (
        <div>
          <h2 className="text-sm font-semibold text-gray-500 mb-3">آخر 365 يوم</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            <KpiCard label="إجمالي المشتريات" value={`${fmt(snap.net_purchase_value_365d)} ج.م`} color="brand" />
            <KpiCard label="الأصناف" value={fmt(snap.distinct_items_365d)} color="purple" />
            <KpiCard label="الموردون" value={fmt(snap.distinct_suppliers_365d)} color="sky" />
            <KpiCard label="تركز أعلى 3 موردين" value={pct(snap.top3_supplier_pct_365d)} sub="من الإجمالي" color={Number(snap.top3_supplier_pct_365d) > 60 ? 'red' : 'green'} />
            <KpiCard label="المرتجعات 30ي" value={pct(snap.return_pct_30d)} sub={`${fmt(snap.return_value_30d)} ج.م`} color={Number(snap.return_pct_30d) > 10 ? 'red' : 'green'} />
          </div>
        </div>
      )}

      {/* Trend chart + Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Monthly Trend */}
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <h3 className="font-semibold text-gray-700 mb-3">اتجاه المشتريات الشهري</h3>
          <TrendChart data={trend} />
        </div>

        {/* Alerts Summary */}
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-700">التنبيهات المفتوحة</h3>
            <button
              onClick={() => navigate('/procurement/optimization')}
              className="text-xs text-brand-600 hover:underline"
            >
              عرض الكل ←
            </button>
          </div>
          <div className="flex gap-2 text-xs">
            {alertCounts.critical > 0 && (
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">
                🔴 {alertCounts.critical} حرجة
              </span>
            )}
            {alertCounts.warning > 0 && (
              <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                🟡 {alertCounts.warning} تحذير
              </span>
            )}
            {alertCounts.info > 0 && (
              <span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-semibold">
                ℹ️ {alertCounts.info}
              </span>
            )}
            {alertCounts.total === 0 && (
              <span className="text-gray-400">لا توجد تنبيهات</span>
            )}
          </div>
          <div className="space-y-2 overflow-y-auto flex-1 max-h-52">
            {(data?.recent_alerts || []).map(a => (
              <AlertRow key={a.id} alert={a} onResolve={handleResolveAlert} />
            ))}
            {(data?.recent_alerts || []).length === 0 && (
              <p className="text-sm text-gray-400 text-center py-4">✅ لا توجد تنبيهات مفتوحة</p>
            )}
          </div>
        </div>
      </div>

      {/* Top Suppliers */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-700">أفضل الموردين (حسب الدرجة)</h3>
          <button
            onClick={() => navigate('/procurement/suppliers')}
            className="text-xs text-brand-600 hover:underline"
          >
            عرض جميع الموردين ←
          </button>
        </div>
        {snap && (
          <div className="mb-3">
            <MiniBar label={`أعلى 3 موردين (${pct(snap.top3_supplier_pct_365d)} من الإجمالي)`} value={Number(snap.top3_supplier_pct_365d)} max={100} />
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="text-right pb-2 font-medium">المورد</th>
                <th className="text-right pb-2 font-medium">الدرجة</th>
                <th className="text-right pb-2 font-medium">الشراء 30ي</th>
                <th className="text-right pb-2 font-medium">هامش%</th>
                <th className="text-right pb-2 font-medium">مرتجع%</th>
                <th className="text-right pb-2 font-medium">أصناف</th>
              </tr>
            </thead>
            <tbody>
              {(data?.top_suppliers || []).map(s => (
                <tr
                  key={s.supplier_code}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/procurement/suppliers/${s.supplier_code}`)}
                >
                  <td className="py-2">
                    <p className="font-medium text-gray-800">{s.supplier_name}</p>
                    <p className="text-xs text-gray-400">{s.supplier_code}</p>
                  </td>
                  <td className="py-2">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-bold ${
                      s.total_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                      s.total_score >= 60 ? 'bg-blue-100 text-blue-700' :
                      s.total_score >= 40 ? 'bg-amber-100 text-amber-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {Number(s.total_score).toFixed(0)} — {s.score_label}
                    </span>
                  </td>
                  <td className="py-2 font-mono text-gray-700">{fmt(s.value_30d)}</td>
                  <td className={`py-2 font-mono ${Number(s.avg_margin_pct) < 10 ? 'text-red-600' : 'text-emerald-600'}`}>
                    {pct(s.avg_margin_pct)}
                  </td>
                  <td className={`py-2 font-mono ${Number(s.return_pct) > 15 ? 'text-red-600' : 'text-gray-700'}`}>
                    {pct(s.return_pct)}
                  </td>
                  <td className="py-2 text-gray-600">{s.distinct_items}</td>
                </tr>
              ))}
              {(data?.top_suppliers || []).length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-gray-400">
                    لا توجد بيانات — شغّل المحرك أولاً
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Quick nav */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { to: '/procurement/suppliers',   icon: '🏭', label: 'أداء الموردين' },
          { to: '/procurement/margins',     icon: '📊', label: 'تحليل الهوامش' },
          { to: '/procurement/mappings',    icon: '🔗', label: 'خريطة المورد-صنف' },
          { to: '/procurement/optimization', icon: '🎯', label: 'التحسين والتنبيهات' },
        ].map(item => (
          <button
            key={item.to}
            onClick={() => navigate(item.to)}
            className="bg-white border border-gray-200 rounded-xl p-4 text-center hover:border-brand-400 hover:shadow-sm transition-all"
          >
            <div className="text-2xl mb-1">{item.icon}</div>
            <div className="text-sm font-semibold text-gray-700">{item.label}</div>
          </button>
        ))}
      </div>

    </div>
  )
}
