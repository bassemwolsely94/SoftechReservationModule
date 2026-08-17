/**
 * ProcurementHistoryPage.jsx
 *
 * Advanced purchase history with SOFTECH-matched, multi-select filtering:
 *   item attributes (تصنيف عام / العائلة / الشركة المنتجة / المنشأ / الشكل / الاستخدام),
 *   supplier categories (multi), numeric ranges (margin / effective cost / value),
 *   FOC / expiry / direction toggles — plus a totals bar over the full match set.
 */
import { useState, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { procurementIntelApi } from '../api/client'
import { useProcurementFilters } from '../components/ProcurementFilters'

const RETURN_TYPES = [
  { code: 'expiry', label: 'تالف / منتهي' },
  { code: 'normal', label: 'مرتجع عادي' },
]

const ORDERINGS = [
  { value: '-doc_date',       label: 'التاريخ (أحدث أولاً)' },
  { value: 'doc_date',        label: 'التاريخ (أقدم أولاً)' },
  { value: '-net_value',      label: 'القيمة (أعلى)' },
  { value: 'net_value',       label: 'القيمة (أدنى)' },
  { value: '-bonus_qty',      label: 'البونص (أعلى)' },
  { value: '-effective_cost', label: 'التكلفة الفعلية (أعلى)' },
  { value: 'effective_cost',  label: 'التكلفة الفعلية (أدنى)' },
  { value: '-margin_pct',     label: 'الهامش (أعلى)' },
  { value: 'margin_pct',      label: 'الهامش (أدنى)' },
]

// Line-level detail filters only — the period / branch / supplier-category /
// item-attribute dimensions come from the shared hub filter bar.
const EMPTY = {
  q: '', supplier_code: '', item_code: '', buyer_code: '',
  is_return: '', is_foc: '', return_type: '',
  margin_min: '', margin_max: '', eff_cost_min: '', eff_cost_max: '',
  value_min: '', value_max: '',
  ordering: '-doc_date',
}

const fmt  = (n, dp = 2) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
const fmtQ = (n)          => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const fmtK = (n)          => n == null ? '—' : `${(Number(n) / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 })}K`

function Badge({ value, className = '' }) {
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}>{value}</span>
}

const CAT_TONES = {
  OFFICIAL_DISTRIBUTOR: 'bg-blue-100 text-blue-800', MANUFACTURER: 'bg-green-100 text-green-800',
  GENERAL_SUPPLIER: 'bg-sky-100 text-sky-800', DRUG_WAREHOUSE: 'bg-amber-100 text-amber-800',
  INDIVIDUAL_SUPPLIER: 'bg-purple-100 text-purple-800', CLEARING: 'bg-teal-100 text-teal-800',
  SERVICE_VENDOR: 'bg-pink-100 text-pink-800', EXTERNAL_TRANSFER: 'bg-slate-100 text-slate-700',
  CUSTOMER_REPURCHASE: 'bg-violet-100 text-violet-800', INTERNAL_TRANSFER: 'bg-gray-100 text-gray-600',
  SISTER_COMPANY: 'bg-indigo-100 text-indigo-800', FIXED_ASSET_SUPPLIER: 'bg-orange-100 text-orange-800',
}

function StatCard({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400">{sub}</div>}
    </div>
  )
}

export default function ProcurementHistoryPage() {
  const { params: globalParams } = useProcurementFilters()
  const [filters, setFilters] = useState(EMPTY)
  const [applied, setApplied] = useState(EMPTY)

  const set = useCallback((name, value) => setFilters(f => ({ ...f, [name]: value })), [])
  const onInput = useCallback(e => set(e.target.name, e.target.value), [set])

  const handleSearch = useCallback(() => setApplied({ ...filters }), [filters])
  const handleReset  = useCallback(() => { setFilters(EMPTY); setApplied(EMPTY) }, [])

  // Merge shared hub filters (period/branch/category/item) with local detail
  // filters (codes/ranges/toggles/ordering); local wins on key collisions.
  const params = useMemo(() => {
    const out = { ...globalParams }
    for (const [k, v] of Object.entries(applied)) {
      if (v !== '' && v != null) out[k] = v
    }
    return out
  }, [applied, globalParams])

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement-history', params],
    queryFn:  () => procurementIntelApi.history(params).then(r => r.data),
    keepPreviousData: true,
  })
  const summaryQ = useQuery({
    queryKey: ['procurement-history-summary', params],
    queryFn:  () => procurementIntelApi.historySummary(params).then(r => r.data),
    keepPreviousData: true,
  })

  const rows = Array.isArray(data) ? data : (data?.results ?? [])
  const s = summaryQ.data

  const activeCount = useMemo(() =>
    Object.entries(applied).filter(([k, v]) =>
      k !== 'ordering' && (Array.isArray(v) ? v.length : v !== '')).length,
  [applied])

  return (
    <div className="p-6 space-y-4" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">سجل المشتريات المتقدم</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            فلترة SOFTECH كاملة · الفئة · العائلة · الشركة المنتجة · البونص · التكلفة الفعلية
          </p>
        </div>
      </div>

      {/* Summary bar (totals over the full match set) */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
        <StatCard label="سطور مطابقة" value={s ? fmt(s.line_count, 0) : '…'} sub={s ? `${fmt(s.invoices, 0)} فاتورة` : ''} />
        <StatCard label="صافي المشتريات" value={s ? `${fmtK(s.paid_value)}` : '…'} sub="ج.م" />
        <StatCard label="بونص (وحدات)" value={s ? fmt(s.bonus_units, 0) : '…'} sub={s ? `${fmt(s.foc_lines, 0)} سطر FOC` : ''} tone="text-emerald-600" />
        <StatCard label="الضريبة" value={s ? `${fmtK(s.vat_total)}` : '…'} sub="ج.م" tone="text-amber-700" />
        <StatCard label="مرتجعات" value={s ? `${fmtK(s.return_value)}` : '…'} sub="ج.م" tone="text-red-600" />
        <StatCard label="متوسط الهامش" value={s ? `${fmt(s.avg_margin, 1)}%` : '…'} sub={s ? `${fmt(s.suppliers, 0)} مورد` : ''} />
      </div>

      {/* Filter panel */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3 shadow-sm">

        {/* Row 1 — line-level lookups + ordering (dimensions live in the top bar) */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">بحث عام</label>
            <input name="q" value={filters.q} onChange={onInput} placeholder="اسم/كود صنف، فاتورة..."
              className="input-field w-full text-sm" onKeyDown={e => e.key === 'Enter' && handleSearch()} />
          </div>
          <div><label className="text-xs text-gray-500 block mb-1">كود المورد</label>
            <input name="supplier_code" value={filters.supplier_code} onChange={onInput} placeholder="مثال: 565" className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">كود الصنف</label>
            <input name="item_code" value={filters.item_code} onChange={onInput} placeholder="مثال: 91338" className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">كود المشتري</label>
            <input name="buyer_code" value={filters.buyer_code} onChange={onInput} placeholder="اختياري" className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">الترتيب</label>
            <select name="ordering" value={filters.ordering} onChange={onInput} className="input-field w-full text-sm">
              {ORDERINGS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select></div>
        </div>

        {/* Row 4 — numeric ranges */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <div><label className="text-xs text-gray-500 block mb-1">هامش من %</label>
            <input type="number" name="margin_min" value={filters.margin_min} onChange={onInput} className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">هامش إلى %</label>
            <input type="number" name="margin_max" value={filters.margin_max} onChange={onInput} className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">تكلفة فعلية من</label>
            <input type="number" name="eff_cost_min" value={filters.eff_cost_min} onChange={onInput} className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">تكلفة فعلية إلى</label>
            <input type="number" name="eff_cost_max" value={filters.eff_cost_max} onChange={onInput} className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">قيمة من</label>
            <input type="number" name="value_min" value={filters.value_min} onChange={onInput} className="input-field w-full text-sm" /></div>
          <div><label className="text-xs text-gray-500 block mb-1">قيمة إلى</label>
            <input type="number" name="value_max" value={filters.value_max} onChange={onInput} className="input-field w-full text-sm" /></div>
        </div>

        {/* Row 5 — toggle filters + actions */}
        <div className="flex flex-wrap gap-2 items-center pt-1">
          {[
            { label: 'كل الحركات', value: '' },
            { label: 'مشتريات فقط', value: 'false' },
            { label: 'مرتجعات فقط', value: 'true' },
          ].map(opt => (
            <button key={opt.value} onClick={() => set('is_return', opt.value)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                filters.is_return === opt.value ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'}`}>
              {opt.label}
            </button>
          ))}
          <span className="text-gray-300 mx-1">|</span>
          <button onClick={() => set('is_foc', filters.is_foc === 'true' ? '' : 'true')}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              filters.is_foc === 'true' ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-gray-600 border-gray-300 hover:border-emerald-400'}`}>
            🎁 بونص فقط
          </button>
          {RETURN_TYPES.map(rt => (
            <button key={rt.code}
              onClick={() => set('return_type', filters.return_type === rt.code ? '' : rt.code)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                filters.return_type === rt.code ? 'bg-red-500 text-white border-red-500' : 'bg-white text-gray-600 border-gray-300 hover:border-red-400'}`}>
              {rt.code === 'expiry' ? '⚠️' : '↩️'} {rt.label}
            </button>
          ))}
          <div className="flex-1" />
          <span className="text-xs text-gray-400">{activeCount > 0 ? `${activeCount} فلتر نشط` : ''}</span>
          <button onClick={handleReset} className="px-3 py-1 rounded-lg text-xs text-gray-500 border border-gray-300 hover:bg-gray-50">إعادة ضبط</button>
          <button onClick={handleSearch} className="px-4 py-1.5 rounded-lg text-sm font-medium bg-brand-600 text-white hover:bg-brand-700">بحث</button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-gray-400">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-600 ml-3" />جاري التحميل...
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center py-20 text-red-500">⚠️ خطأ في تحميل البيانات</div>
        ) : rows.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-gray-400">لا توجد نتائج مطابقة للفلاتر المحددة</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {['التاريخ', 'رقم الفاتورة', 'الفرع', 'المورد', 'فئة المورد', 'كود الصنف', 'الصنف',
                    'اتجاه', 'كمية', 'بونص', 'سعر الوحدة', 'التكلفة الفعلية', 'القيمة الصافية',
                    'الهامش%', 'ضريبة', 'FOC', 'نوع المرتجع'].map(h => (
                    <th key={h} className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map(row => (
                  <tr key={row.id} className={`hover:bg-gray-50 transition-colors ${row.is_return ? 'bg-red-50/40' : row.is_foc ? 'bg-emerald-50/40' : ''}`}>
                    <td className="px-3 py-2 text-gray-700 whitespace-nowrap">{row.doc_date}</td>
                    <td className="px-3 py-2 text-gray-500 font-mono text-xs">{row.doc_number}</td>
                    <td className="px-3 py-2 text-gray-600">{row.branch_name || row.branch_code}</td>
                    <td className="px-3 py-2 font-medium text-gray-800">{row.supplier_code}</td>
                    <td className="px-3 py-2">
                      <Badge value={row.supplier_category_display || '—'} className={CAT_TONES[row.supplier_category] ?? 'bg-gray-100 text-gray-500'} />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-600">{row.item_code}</td>
                    <td className="px-3 py-2 text-gray-700 max-w-[16rem] truncate" title={row.item_name}>{row.item_name || '—'}</td>
                    <td className="px-3 py-2">
                      <Badge value={row.is_return ? 'مرتجع' : 'شراء'} className={row.is_return ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'} />
                    </td>
                    <td className="px-3 py-2 text-gray-700 text-left dir-ltr">{fmtQ(row.net_qty)}</td>
                    <td className="px-3 py-2 text-left dir-ltr">
                      {row.bonus_qty > 0 ? <span className="font-medium text-emerald-600">+{fmtQ(row.bonus_qty)}</span> : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-700 text-left dir-ltr">{fmt(row.unit_price, 4)}</td>
                    <td className="px-3 py-2 text-left dir-ltr">
                      {row.effective_cost > 0
                        ? <span className={`font-medium ${row.effective_cost < row.unit_price ? 'text-emerald-600' : row.effective_cost > row.unit_price ? 'text-red-600' : 'text-gray-700'}`}>{fmt(row.effective_cost, 4)}</span>
                        : '—'}
                    </td>
                    <td className="px-3 py-2 font-semibold text-gray-800 text-left dir-ltr">{fmt(row.net_value)}</td>
                    <td className="px-3 py-2 text-left dir-ltr">
                      <span className={`font-medium ${row.margin_pct < 0 ? 'text-red-600' : row.margin_pct < 10 ? 'text-yellow-600' : 'text-green-600'}`}>{fmt(row.margin_pct, 1)}%</span>
                    </td>
                    <td className="px-3 py-2 text-left dir-ltr text-amber-700">{row.vat_value > 0 ? fmt(row.vat_value, 2) : '—'}</td>
                    <td className="px-3 py-2">{row.is_foc && <Badge value="FOC 🎁" className="bg-emerald-100 text-emerald-700" />}</td>
                    <td className="px-3 py-2">
                      {row.is_return && row.return_type && (
                        <Badge value={row.return_type === 'expiry' ? '⚠️ تالف' : '↩️ عادي'} className={row.return_type === 'expiry' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {rows.length >= 1000 && (
        <p className="text-xs text-gray-400 text-center">
          يتم عرض أول 1,000 سطر — الإجماليات أعلاه محسوبة على كامل النتائج المطابقة ({s ? fmt(s.line_count, 0) : ''} سطر)
        </p>
      )}
    </div>
  )
}
