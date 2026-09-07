/**
 * ProcurementOptimizationPage.jsx
 *
 * Module 9 + 3 + 4: Procurement optimization — best suppliers,
 * price saving opportunities, avoid list, supplier-item mapping table,
 * open alerts management.
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { procurementIntelApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'

const fmt  = (n, d = 0) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const pct  = (n, d = 1) => n == null ? '—' : `${Number(n).toFixed(d)}%`

const ALERT_STYLE = {
  critical: { bg: 'bg-red-50  border-red-300',  text: 'text-red-700',   icon: '🔴' },
  warning:  { bg: 'bg-amber-50 border-amber-300', text: 'text-amber-700', icon: '🟡' },
  info:     { bg: 'bg-blue-50  border-blue-300',  text: 'text-blue-700',  icon: 'ℹ️' },
}

// ── Tab: Optimization ─────────────────────────────────────────────────────────

function OptimizationTab({ days }) {
  const navigate = useNavigate()
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    procurementIntelApi.optimization({ days }).then(r => setData(r.data)).finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</div>
  if (!data) return null

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Top suppliers to use */}
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="font-semibold text-emerald-700 mb-3">✅ الموردون الموصى بهم</h3>
          <div className="space-y-2">
            {(data.top_suppliers || []).map(s => (
              <div
                key={s.supplier_code}
                className="flex items-center justify-between px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200 cursor-pointer hover:bg-emerald-100 transition-colors"
                onClick={() => navigate(`/procurement/suppliers/${s.supplier_code}`)}
              >
                <div>
                  <p className="font-medium text-gray-800 text-sm">{s.supplier_name}</p>
                  <p className="text-xs text-gray-500">{s.supplier_code}</p>
                </div>
                <div className="text-right">
                  <p className="font-bold text-emerald-700">{Number(s.total_score).toFixed(0)}</p>
                  <p className="text-xs text-gray-500">هامش {pct(s.avg_margin_pct)}</p>
                </div>
              </div>
            ))}
            {(data.top_suppliers || []).length === 0 && (
              <p className="text-sm text-gray-400 text-center py-4">لا توجد بيانات</p>
            )}
          </div>
        </div>

        {/* Suppliers to avoid */}
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="font-semibold text-red-700 mb-3">⚠️ الموردون المحذورون</h3>
          <div className="space-y-2">
            {(data.avoid_suppliers || []).map(s => (
              <div
                key={s.supplier_code}
                className="flex items-center justify-between px-3 py-2 rounded-lg bg-red-50 border border-red-200 cursor-pointer hover:bg-red-100 transition-colors"
                onClick={() => navigate(`/procurement/suppliers/${s.supplier_code}`)}
              >
                <div>
                  <p className="font-medium text-gray-800 text-sm">{s.supplier_name}</p>
                  <p className="text-xs text-gray-500">{s.supplier_code}</p>
                </div>
                <div className="text-right">
                  <p className="font-bold text-red-700">{Number(s.total_score).toFixed(0)}</p>
                  <p className="text-xs text-gray-500">مرتجع {pct(s.return_pct)}</p>
                </div>
              </div>
            ))}
            {(data.avoid_suppliers || []).length === 0 && (
              <p className="text-sm text-gray-400 text-center py-4">لا توجد موردين محذورين</p>
            )}
          </div>
        </div>
      </div>

      {/* Price Saving Opportunities */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 overflow-x-auto">
        <h3 className="font-semibold text-blue-700 mb-3">💡 فرص توفير السعر (أصناف بعدة موردين)</h3>
        {(data.price_saving_items || []).length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">لا توجد فرص مكتشفة</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="text-right pb-2 font-medium">الصنف</th>
                <th className="text-right pb-2 font-medium">عدد الموردين</th>
                <th className="text-right pb-2 font-medium">أقل سعر</th>
                <th className="text-right pb-2 font-medium">أعلى سعر</th>
                <th className="text-right pb-2 font-medium">فرصة التوفير</th>
              </tr>
            </thead>
            <tbody>
              {(data.price_saving_items || []).map(item => (
                <tr key={item.item_code} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2">
                    <p className="font-medium text-gray-800">{item.item_name || item.item_code}</p>
                    <p className="text-xs text-gray-400">{item.item_code}</p>
                  </td>
                  <td className="py-2 text-center text-gray-700">{item.supplier_count}</td>
                  <td className="py-2 font-mono text-emerald-600 font-semibold">{fmt(item.min_price, 4)}</td>
                  <td className="py-2 font-mono text-red-600">{fmt(item.max_price, 4)}</td>
                  <td className="py-2">
                    <span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full text-xs font-bold">
                      {pct(item.saving_pct, 1)} وفورات
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Tab: Supplier-Item Mapping ────────────────────────────────────────────────

function MappingTab() {
  const [data, setData]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [primaryOnly, setPrimaryOnly]       = useState(false)
  const [minConf, setMinConf]               = useState('')
  const [page, setPage]         = useState(0)

  const PAGE_SIZE = 25

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await procurementIntelApi.listMappings({
        q:              search,
        supplier_code:  supplierFilter,
        primary_only:   primaryOnly ? '1' : '',
        min_confidence: minConf,
        ordering:       '-purchase_count',
      })
      setData(res.data.results || res.data || [])
      setPage(0)
    } finally {
      setLoading(false)
    }
  }, [search, supplierFilter, primaryOnly, minConf])

  useEffect(() => { load() }, [load])

  const paged = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(data.length / PAGE_SIZE)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <input
          type="text" placeholder="بحث بالصنف أو المورد…"
          value={search} onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-56"
        />
        <input
          type="text" placeholder="كود المورد…"
          value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-32"
        />
        <input
          type="number" placeholder="حد الثقة…" min={0} max={100}
          value={minConf} onChange={e => setMinConf(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-28"
        />
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input type="checkbox" checked={primaryOnly} onChange={e => setPrimaryOnly(e.target.checked)} className="rounded" />
          مورد رئيسي فقط
        </label>
        <button onClick={load} className="px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg">
          🔍 بحث
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-x-auto">
        <div className="px-4 py-2 border-b border-gray-200 text-xs text-gray-500">
          {data.length} خريطة مورد-صنف
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr className="border-b border-gray-200 text-xs text-gray-500">
              <th className="text-right px-4 py-3 font-medium">الصنف</th>
              <th className="text-right px-3 py-3 font-medium">المورد</th>
              <th className="text-right px-3 py-3 font-medium">درجة الثقة</th>
              <th className="text-right px-3 py-3 font-medium">رئيسي</th>
              <th className="text-right px-3 py-3 font-medium">مشتريات</th>
              <th className="text-right px-3 py-3 font-medium">متوسط السعر</th>
              <th className="text-right px-3 py-3 font-medium">تذبذب%</th>
              <th className="text-right px-3 py-3 font-medium">آخر شراء</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</td></tr>
            ) : paged.length === 0 ? (
              <tr><td colSpan={8} className="py-8 text-center text-gray-400">لا توجد نتائج</td></tr>
            ) : paged.map(m => (
              <tr key={`${m.supplier_code}-${m.item_code}`} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="px-4 py-2.5">
                  <p className="font-medium text-gray-800 break-words max-w-xs">{m.item_name || m.item_code}</p>
                  <p className="text-xs text-gray-400">{m.item_code}</p>
                </td>
                <td className="px-3 py-2.5">
                  <p className="text-gray-700">{m.supplier_name || m.supplier_code}</p>
                  <p className="text-xs text-gray-400">{m.supplier_code}</p>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <div className="w-16 h-1.5 bg-gray-200 rounded-full">
                      <div
                        className="h-1.5 rounded-full bg-brand-500"
                        style={{ width: `${Math.min(100, Number(m.confidence_score))}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono font-semibold text-gray-700">
                      {Number(m.confidence_score).toFixed(0)}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-center">
                  {m.is_primary ? <span className="text-emerald-600 font-bold">✓</span> : <span className="text-gray-300">—</span>}
                </td>
                <td className="px-3 py-2.5 font-mono text-gray-700">{m.purchase_count}</td>
                <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(m.avg_price, 4)}</td>
                <td className="px-3 py-2.5">
                  <span className={`font-mono text-xs ${Number(m.price_drift_pct) > 15 ? 'text-red-600 font-semibold' : 'text-gray-600'}`}>
                    {m.price_drift_pct > 0 ? '+' : ''}{pct(m.price_drift_pct, 1)}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-500">{m.last_purchase_date || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center gap-2 text-sm">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="px-3 py-1.5 border rounded-lg disabled:opacity-40">‹ السابق</button>
          <span className="px-3 py-1.5 text-gray-600">{page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
            className="px-3 py-1.5 border rounded-lg disabled:opacity-40">التالي ›</button>
        </div>
      )}
    </div>
  )
}

// ── Tab: Alerts ───────────────────────────────────────────────────────────────

function AlertsTab() {
  const [alerts, setAlerts]     = useState([])
  const [loading, setLoading]   = useState(true)
  const [severity, setSeverity] = useState('')
  const [resolved, setResolved] = useState('false')
  const [resolving, setResolving] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await procurementIntelApi.listAlerts({ severity, is_resolved: resolved })
      setAlerts(res.data.results || res.data || [])
    } finally {
      setLoading(false)
    }
  }, [severity, resolved])

  useEffect(() => { load() }, [load])

  const handleResolve = async (id) => {
    setResolving(id)
    try {
      await procurementIntelApi.resolveAlert(id, {
        resolved_by: 'user',
        resolution_notes: 'تم الحل يدوياً',
      })
      load()
    } finally {
      setResolving(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <select value={severity} onChange={e => setSeverity(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
          <option value="">جميع المستويات</option>
          <option value="critical">حرجة</option>
          <option value="warning">تحذير</option>
          <option value="info">معلومة</option>
        </select>
        <select value={resolved} onChange={e => setResolved(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
          <option value="false">مفتوحة فقط</option>
          <option value="true">محلولة</option>
          <option value="">الكل</option>
        </select>
        <RefreshButton loading={loading} onClick={load}>
          🔄 تحديث
        </RefreshButton>
        <span className="text-sm text-gray-500 mr-auto">{alerts.length} تنبيه</span>
      </div>

      {loading ? (
        <div className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</div>
      ) : alerts.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <p className="text-3xl mb-2">✅</p>
          <p>لا توجد تنبيهات</p>
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map(a => {
            const style = ALERT_STYLE[a.severity] || ALERT_STYLE.info
            return (
              <div key={a.id} className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg}`}>
                <span className="shrink-0 text-lg mt-0.5">{style.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className={`font-semibold text-sm ${style.text}`}>{a.title}</p>
                    <span className="text-xs text-gray-500 bg-white/60 px-2 py-0.5 rounded-full">
                      {a.alert_type_display}
                    </span>
                    {a.entity_code && (
                      <span className="text-xs text-gray-500 bg-white/60 px-2 py-0.5 rounded-full font-mono">
                        {a.entity_type}: {a.entity_code}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">{a.message}</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {new Date(a.detected_at).toLocaleString('en-GB')}
                    {a.metric_value != null && ` · القيمة: ${Number(a.metric_value).toFixed(2)}`}
                    {a.threshold != null && ` (الحد: ${Number(a.threshold).toFixed(2)})`}
                  </p>
                  {a.is_resolved && (
                    <p className="text-xs text-emerald-600 mt-1">
                      ✓ حُل بواسطة {a.resolved_by} — {a.resolution_notes}
                    </p>
                  )}
                </div>
                {!a.is_resolved && (
                  <button
                    onClick={() => handleResolve(a.id)}
                    disabled={resolving === a.id}
                    className="shrink-0 px-3 py-1 text-xs bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                  >
                    {resolving === a.id ? '…' : 'حل ✓'}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProcurementOptimizationPage() {
  const [activeTab, setActiveTab] = useState('optimization')
  const [days, setDays]           = useState(90)

  const TABS = [
    { key: 'optimization', label: '🎯 التحسين' },
    { key: 'mapping',      label: '🔗 خريطة المورد-صنف' },
    { key: 'alerts',       label: '🚨 التنبيهات' },
  ]

  return (
    <div className="p-6 space-y-4 font-cairo" dir="rtl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">تحسين المشتريات والتنبيهات</h1>
        {activeTab === 'optimization' && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-600">الفترة:</span>
            {[30, 90, 365].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-3 py-1 rounded-lg ${days === d ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}>
                {d}ي
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex border-b border-gray-200 gap-1">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              activeTab === t.key
                ? 'bg-white border border-b-white border-gray-200 text-brand-700 -mb-px'
                : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'optimization' && <OptimizationTab days={days} />}
      {activeTab === 'mapping'      && <MappingTab />}
      {activeTab === 'alerts'       && <AlertsTab />}
    </div>
  )
}
