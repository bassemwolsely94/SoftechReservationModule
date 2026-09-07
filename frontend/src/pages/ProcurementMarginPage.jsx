/**
 * ProcurementMarginPage.jsx
 *
 * Module 5 + 8: Margin analysis + price control engine.
 * Shows margin distribution, low-margin suppliers/items, price drift alerts.
 */
import { useState, useEffect, useCallback } from 'react'
import { procurementIntelApi } from '../api/client'

const fmt = (n, d = 0) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const pct = (n, d = 1) => n == null ? '—' : `${Number(n).toFixed(d)}%`

const MARGIN_COLOR = m => {
  const v = Number(m)
  if (v < 0)   return 'text-red-700 bg-red-50'
  if (v < 10)  return 'text-orange-700 bg-orange-50'
  if (v < 20)  return 'text-amber-700 bg-amber-50'
  return 'text-emerald-700 bg-emerald-50'
}

const DRIFT_COLOR = d => {
  const v = Number(d)
  if (v > 30) return 'text-red-700 font-bold'
  if (v > 15) return 'text-orange-600 font-semibold'
  return 'text-gray-700'
}

function HistogramBar({ bucket, count, maxCount }) {
  const w = maxCount > 0 ? Math.max(2, (count / maxCount) * 100) : 0
  const colors = {
    '<0%':    'bg-red-500',
    '0-10%':  'bg-orange-400',
    '10-20%': 'bg-amber-400',
    '20-30%': 'bg-yellow-400',
    '30-40%': 'bg-lime-400',
    '>40%':   'bg-emerald-500',
  }
  return (
    <div className="flex items-center gap-3 mb-2 text-sm">
      <span className="w-16 text-right text-xs text-gray-600 shrink-0">{bucket}</span>
      <div className="flex-1 bg-gray-100 rounded-full h-5 relative">
        <div
          className={`${colors[bucket] || 'bg-blue-400'} h-5 rounded-full transition-all`}
          style={{ width: `${w}%` }}
        />
        <span className="absolute right-2 top-0 h-full flex items-center text-xs font-mono font-semibold text-gray-700">
          {fmt(count)}
        </span>
      </div>
    </div>
  )
}

// ── Tab: Margin Analysis ──────────────────────────────────────────────────────

function MarginTab({ days, setDays }) {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await procurementIntelApi.margins({ days })
      setData(res.data)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</div>
  if (!data) return null

  const maxBucket = Math.max(...(data.histogram || []).map(h => h.count), 1)

  return (
    <div className="space-y-5">
      {/* Overall KPIs */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500">متوسط الهامش</p>
          <p className={`text-xl font-bold mt-1 ${Number(data.overall?.avg_margin) < 15 ? 'text-red-600' : 'text-emerald-600'}`}>
            {pct(data.overall?.avg_margin, 2)}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500">صافي قيمة المشتريات</p>
          <p className="text-xl font-bold text-gray-800 mt-1">{fmt(data.overall?.net_value)} <span className="text-sm font-normal text-gray-500">ج.م</span></p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500">عدد السطور</p>
          <p className="text-xl font-bold text-gray-800 mt-1">{fmt(data.overall?.line_count)}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Histogram */}
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="font-semibold text-gray-700 mb-4">توزيع الهامش</h3>
          {(data.histogram || []).map(h => (
            <HistogramBar key={h.range} bucket={h.range} count={h.count} maxCount={maxBucket} />
          ))}
        </div>

        {/* Low margin items */}
        <div className="bg-white border border-gray-200 rounded-xl p-5 overflow-y-auto max-h-80">
          <h3 className="font-semibold text-gray-700 mb-3">أدنى هوامش (أصناف)</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500">
                <th className="text-right pb-2">كود</th>
                <th className="text-right pb-2">هامش%</th>
                <th className="text-right pb-2">قيمة</th>
              </tr>
            </thead>
            <tbody>
              {(data.by_item || []).map(r => (
                <tr key={r.item_code} className="border-b border-gray-100">
                  <td className="py-1 font-mono text-gray-700">{r.item_code}</td>
                  <td className="py-1">
                    <span className={`px-1.5 py-0.5 rounded text-xs ${MARGIN_COLOR(r.avg_margin)}`}>
                      {pct(r.avg_margin, 2)}
                    </span>
                  </td>
                  <td className="py-1 font-mono text-gray-600">{fmt(r.net_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* By Supplier */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 overflow-x-auto">
        <h3 className="font-semibold text-gray-700 mb-3">الهوامش حسب المورد</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-xs text-gray-500">
              <th className="text-right pb-2 font-medium">كود المورد</th>
              <th className="text-right pb-2 font-medium">متوسط الهامش</th>
              <th className="text-right pb-2 font-medium">صافي القيمة</th>
              <th className="text-right pb-2 font-medium">الأصناف</th>
            </tr>
          </thead>
          <tbody>
            {(data.by_supplier || []).map(r => (
              <tr key={r.supplier_code} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 font-mono text-gray-700">{r.supplier_code}</td>
                <td className="py-2">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${MARGIN_COLOR(r.avg_margin)}`}>
                    {pct(r.avg_margin, 2)}
                  </span>
                </td>
                <td className="py-2 font-mono text-gray-700">{fmt(r.net_value)}</td>
                <td className="py-2 text-gray-600">{r.item_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Tab: Price Control ────────────────────────────────────────────────────────

function PriceControlTab() {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [minDrift, setMinDrift] = useState(10)
  const [minPurchases, setMinPurchases] = useState(3)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await procurementIntelApi.priceControl({ min_drift: minDrift, min_purchases: minPurchases })
      setData(res.data)
    } finally {
      setLoading(false)
    }
  }, [minDrift, minPurchases])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center">
        <label className="text-sm text-gray-600 flex items-center gap-2">
          حد التذبذب المئوي:
          <input
            type="number" min={0} max={100} value={minDrift}
            onChange={e => setMinDrift(Number(e.target.value))}
            className="w-16 border border-gray-300 rounded px-2 py-1 text-sm text-center"
          />
          %
        </label>
        <label className="text-sm text-gray-600 flex items-center gap-2">
          أدنى عدد مشتريات:
          <input
            type="number" min={1} max={50} value={minPurchases}
            onChange={e => setMinPurchases(Number(e.target.value))}
            className="w-16 border border-gray-300 rounded px-2 py-1 text-sm text-center"
          />
        </label>
        <button onClick={load} className="px-3 py-1.5 text-sm bg-brand-600 text-white rounded-lg">
          تطبيق
        </button>
      </div>

      {loading ? (
        <div className="py-12 text-center text-brand-600 animate-pulse">جارٍ التحميل…</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-x-auto">
          <div className="px-4 py-3 border-b border-gray-200">
            <span className="text-sm text-gray-600">
              {(data?.items || []).length} صنف بتذبذب سعر ≥ {minDrift}%
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="text-right px-4 py-3 font-medium">الصنف</th>
                <th className="text-right px-3 py-3 font-medium">المورد</th>
                <th className="text-right px-3 py-3 font-medium">سعر أدنى</th>
                <th className="text-right px-3 py-3 font-medium">سعر أعلى</th>
                <th className="text-right px-3 py-3 font-medium">متوسط</th>
                <th className="text-right px-3 py-3 font-medium">آخر سعر</th>
                <th className="text-right px-3 py-3 font-medium">تذبذب%</th>
                <th className="text-right px-3 py-3 font-medium">عدد الشراء</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).length === 0 ? (
                <tr><td colSpan={8} className="py-8 text-center text-gray-400">لا توجد نتائج</td></tr>
              ) : (data?.items || []).map(item => (
                <tr key={`${item.supplier_code}-${item.item_code}`} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <p className="font-medium text-gray-800 break-words max-w-xs">{item.item_name || item.item_code}</p>
                    <p className="text-xs text-gray-400">{item.item_code}</p>
                  </td>
                  <td className="px-3 py-2.5">
                    <p className="text-gray-700">{item.supplier_name || item.supplier_code}</p>
                    <p className="text-xs text-gray-400">{item.supplier_code}</p>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(item.min_price, 4)}</td>
                  <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(item.max_price, 4)}</td>
                  <td className="px-3 py-2.5 font-mono text-gray-700">{fmt(item.avg_price, 4)}</td>
                  <td className="px-3 py-2.5 font-mono font-semibold text-gray-800">{fmt(item.last_price, 4)}</td>
                  <td className="px-3 py-2.5">
                    <span className={`font-mono text-sm ${DRIFT_COLOR(item.price_drift_pct)}`}>
                      {item.price_drift_pct > 0 ? '+' : ''}{pct(item.price_drift_pct, 1)}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{item.purchase_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProcurementMarginPage() {
  const [activeTab, setActiveTab] = useState('margin')
  const [days, setDays]           = useState(90)

  const TABS = [
    { key: 'margin',  label: 'تحليل الهوامش' },
    { key: 'price',   label: 'مراقبة الأسعار' },
  ]

  return (
    <div className="p-6 space-y-4 font-cairo" dir="rtl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">الهوامش ومراقبة الأسعار</h1>
        {activeTab === 'margin' && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-600">الفترة:</span>
            {[30, 90, 180, 365].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1 rounded-lg ${days === d ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
              >
                {d}ي
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 gap-1">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              activeTab === t.key
                ? 'bg-white border border-b-white border-gray-200 text-brand-700 -mb-px'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'margin' && <MarginTab days={days} setDays={setDays} />}
      {activeTab === 'price'  && <PriceControlTab />}
    </div>
  )
}
