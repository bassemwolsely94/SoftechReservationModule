/**
 * SupplierPerformancePage.jsx
 *
 * Module 2 + 6: Supplier performance rankings, scoring breakdown,
 * purchase history per supplier, return analysis.
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { procurementIntelApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'

const fmt  = (n, d = 0) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const pct  = (n, d = 1) => n == null ? '—' : `${Number(n).toFixed(d)}%`

const SCORE_COLOR = s => {
  const v = Number(s)
  if (v >= 80) return 'text-emerald-600 bg-emerald-50'
  if (v >= 60) return 'text-blue-600 bg-blue-50'
  if (v >= 40) return 'text-amber-600 bg-amber-50'
  return 'text-red-600 bg-red-50'
}

// ── Score Bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ label, value, total = 100, color = '#3b82f6' }) {
  const w = Math.min(100, Math.max(0, (Number(value) / total) * 100))
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-gray-600 mb-0.5">
        <span>{label}</span>
        <span className="font-mono font-semibold">{Number(value).toFixed(1)}</span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full">
        <div className="h-2 rounded-full transition-all" style={{ width: `${w}%`, backgroundColor: color }} />
      </div>
    </div>
  )
}

// ── Monthly Bar Chart ─────────────────────────────────────────────────────────

function HistoryChart({ data }) {
  if (!data?.length) return <p className="text-sm text-gray-400 text-center py-6">لا توجد بيانات</p>
  const maxVal = Math.max(...data.map(d => Math.abs(d.purchase_value)), 1)
  return (
    <div className="flex items-end gap-1 h-32 mt-2">
      {data.map((d, i) => {
        const h = Math.max(4, (Math.abs(d.purchase_value) / maxVal) * 100)
        return (
          <div key={i} className="flex-1 flex flex-col items-center group relative">
            <div className="w-full bg-brand-500 rounded-t hover:bg-brand-400 transition-colors" style={{ height: `${h}%` }} />
            <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10 pointer-events-none">
              {d.month}: {fmt(d.net_value)} ج.م
            </div>
            {i % 2 === 0 && <span className="text-[9px] text-gray-400 mt-0.5">{d.month?.slice(5)}</span>}
          </div>
        )
      })}
    </div>
  )
}

// ── Supplier Detail Panel ─────────────────────────────────────────────────────

function SupplierDetail({ supplierCode, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      procurementIntelApi.getSupplier(supplierCode),
      procurementIntelApi.supplierHistory(supplierCode),
    ]).then(([sp, hist]) => {
      setData({ supplier: sp.data, history: hist.data.history || [] })
    }).finally(() => setLoading(false))
  }, [supplierCode])

  if (loading) return <div className="p-8 text-center text-brand-600 animate-pulse">جارٍ التحميل…</div>
  if (!data) return null

  const { supplier: s, history } = data

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="text-sm text-brand-600 hover:underline flex items-center gap-1">
        ← العودة للقائمة
      </button>

      {/* Header */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900">{s.supplier_name}</h2>
            <p className="text-sm text-gray-500">{s.supplier_code} · {s.classif_code || 'غير مصنف'}</p>
            <p className="text-xs text-gray-400 mt-1">
              أول شراء: {s.first_purchase_date || '—'} · آخر شراء: {s.last_purchase_date || '—'}
            </p>
          </div>
          <span className={`text-2xl font-bold px-4 py-2 rounded-xl ${SCORE_COLOR(s.total_score)}`}>
            {Number(s.total_score).toFixed(0)}<span className="text-sm font-normal">/100</span>
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'صافي المشتريات (365ي)',  val: `${fmt(s.net_purchase_value)} ج.م` },
            { label: 'الفواتير',               val: fmt(s.invoice_count) },
            { label: 'الأصناف',                val: fmt(s.distinct_items) },
            { label: 'الفروع المُزودة',         val: fmt(s.branches_supplied) },
            { label: 'شراء 30ي',               val: `${fmt(s.value_30d)} ج.م` },
            { label: 'شراء 90ي',               val: `${fmt(s.value_90d)} ج.م` },
            { label: 'متوسط الهامش',            val: pct(s.avg_margin_pct) },
            { label: 'معدل المرتجعات',          val: pct(s.return_pct) },
          ].map((item, i) => (
            <div key={i} className="bg-gray-50 rounded-lg px-3 py-2">
              <p className="text-xs text-gray-500">{item.label}</p>
              <p className="font-mono font-semibold text-gray-800 text-sm">{item.val}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Scoring Breakdown */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <h3 className="font-semibold text-gray-700 mb-3">تفصيل الدرجة</h3>
        <ScoreBar label="هامش الربح (×0.30)" value={s.score_margin} color="#10b981" />
        <ScoreBar label="التوافر / التكرار (×0.25)" value={s.score_availability} color="#3b82f6" />
        <ScoreBar label="معدل المرتجعات (×0.25)" value={s.score_returns} color="#f59e0b" />
        <ScoreBar label="استقرار الأسعار (×0.20)" value={s.score_price_stability} color="#8b5cf6" />
        <div className="mt-3 pt-3 border-t border-gray-200">
          <ScoreBar label="الدرجة الإجمالية" value={s.total_score} color="#ef4444" />
        </div>
      </div>

      {/* Purchase History Chart */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <h3 className="font-semibold text-gray-700 mb-1">المشتريات الشهرية</h3>
        <HistoryChart data={history} />
      </div>

      {/* History Table */}
      {history.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm overflow-x-auto">
          <h3 className="font-semibold text-gray-700 mb-3">تفصيل الأشهر</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="text-right pb-2 font-medium">الشهر</th>
                <th className="text-right pb-2 font-medium">مشتريات</th>
                <th className="text-right pb-2 font-medium">مرتجعات</th>
                <th className="text-right pb-2 font-medium">صافي</th>
                <th className="text-right pb-2 font-medium">فواتير</th>
                <th className="text-right pb-2 font-medium">أصناف</th>
              </tr>
            </thead>
            <tbody>
              {history.map((row, i) => (
                <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-1.5 font-mono text-gray-700">{row.month}</td>
                  <td className="py-1.5 font-mono text-emerald-700">{fmt(row.purchase_value, 0)}</td>
                  <td className="py-1.5 font-mono text-red-600">{fmt(row.return_value, 0)}</td>
                  <td className={`py-1.5 font-mono font-semibold ${row.net_value >= 0 ? 'text-gray-800' : 'text-red-600'}`}>
                    {fmt(row.net_value, 0)}
                  </td>
                  <td className="py-1.5 text-gray-600">{row.invoice_count}</td>
                  <td className="py-1.5 text-gray-600">{row.item_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Supplier List ─────────────────────────────────────────────────────────────

export default function SupplierPerformancePage() {
  const { supplierCode } = useParams()
  const navigate = useNavigate()

  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading]     = useState(true)
  const [search, setSearch]       = useState('')
  const [ordering, setOrdering]   = useState('-total_score')
  const [page, setPage]           = useState(0)

  const PAGE_SIZE = 20

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await procurementIntelApi.listSuppliers({ q: search, ordering })
      setSuppliers(res.data.results || res.data || [])
      setPage(0)
    } finally {
      setLoading(false)
    }
  }, [search, ordering])

  useEffect(() => { load() }, [load])

  if (supplierCode) {
    return (
      <div className="p-6 font-cairo" dir="rtl">
        <SupplierDetail supplierCode={supplierCode} onBack={() => navigate('/procurement/suppliers')} />
      </div>
    )
  }

  const paged = suppliers.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(suppliers.length / PAGE_SIZE)

  const cols = [
    { key: '-total_score',         label: 'الدرجة ↓' },
    { key: '-net_purchase_value',  label: 'الأعلى شراءً ↓' },
    { key: '-avg_margin_pct',      label: 'أعلى هامش ↓' },
    { key: 'return_pct',           label: 'أقل مرتجعات ↑' },
    { key: '-value_30d',           label: 'شراء 30ي ↓' },
  ]

  return (
    <div className="p-6 space-y-4 font-cairo" dir="rtl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">أداء الموردين</h1>
        <span className="text-sm text-gray-500">{suppliers.length} مورد</span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <input
          type="text"
          placeholder="بحث باسم أو كود المورد…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64"
        />
        <select
          value={ordering}
          onChange={e => setOrdering(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          {cols.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <RefreshButton loading={loading} onClick={load}>
          🔄 تحديث
        </RefreshButton>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr className="border-b border-gray-200 text-xs text-gray-500">
              <th className="text-right px-4 py-3 font-medium">المورد</th>
              <th className="text-right px-3 py-3 font-medium">الدرجة</th>
              <th className="text-right px-3 py-3 font-medium">شراء 30ي</th>
              <th className="text-right px-3 py-3 font-medium">شراء 365ي</th>
              <th className="text-right px-3 py-3 font-medium">هامش%</th>
              <th className="text-right px-3 py-3 font-medium">مرتجع%</th>
              <th className="text-right px-3 py-3 font-medium">فواتير</th>
              <th className="text-right px-3 py-3 font-medium">أصناف</th>
              <th className="text-right px-3 py-3 font-medium">آخر شراء</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</td></tr>
            ) : paged.length === 0 ? (
              <tr><td colSpan={9} className="py-8 text-center text-gray-400">لا توجد نتائج</td></tr>
            ) : paged.map(s => (
              <tr
                key={s.supplier_code}
                className="border-b border-gray-100 hover:bg-brand-50 cursor-pointer"
                onClick={() => navigate(`/procurement/suppliers/${s.supplier_code}`)}
              >
                <td className="px-4 py-2.5">
                  <p className="font-semibold text-gray-800">{s.supplier_name}</p>
                  <p className="text-xs text-gray-400">{s.supplier_code} · {s.classif_code}</p>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-bold ${SCORE_COLOR(s.total_score)}`}>
                    {Number(s.total_score).toFixed(0)}
                  </span>
                </td>
                <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(s.value_30d)}</td>
                <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(s.net_purchase_value)}</td>
                <td className={`px-3 py-2.5 font-mono ${Number(s.avg_margin_pct) < 10 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {pct(s.avg_margin_pct)}
                </td>
                <td className={`px-3 py-2.5 font-mono ${Number(s.return_pct) > 15 ? 'text-red-600' : 'text-gray-700'}`}>
                  {pct(s.return_pct)}
                </td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(s.invoice_count)}</td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(s.distinct_items)}</td>
                <td className="px-3 py-2.5 text-xs text-gray-500">{s.last_purchase_date || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 text-sm">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="px-3 py-1.5 border rounded-lg disabled:opacity-40">
            ‹ السابق
          </button>
          <span className="px-3 py-1.5 text-gray-600">{page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
            className="px-3 py-1.5 border rounded-lg disabled:opacity-40">
            التالي ›
          </button>
        </div>
      )}
    </div>
  )
}
