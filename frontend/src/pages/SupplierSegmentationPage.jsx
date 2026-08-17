/**
 * SupplierSegmentationPage.jsx
 *
 * Supplier segmentation overview driven by the DB-managed categories and the
 * shared hub filters (period / branch / category / item attributes). Category
 * labels + colours come from the admin-managed master, not hard-coded.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { procurementIntelApi } from '../api/client'
import { useProcurementFilters } from '../components/ProcurementFilters'
import useAuthStore from '../store/authStore'

const TONES = {
  blue:   { badge: 'bg-blue-100 text-blue-800',   bar: 'bg-blue-500' },
  green:  { badge: 'bg-green-100 text-green-800',  bar: 'bg-green-500' },
  sky:    { badge: 'bg-sky-100 text-sky-800',      bar: 'bg-sky-500' },
  amber:  { badge: 'bg-amber-100 text-amber-800',  bar: 'bg-amber-500' },
  purple: { badge: 'bg-purple-100 text-purple-800',bar: 'bg-purple-500' },
  teal:   { badge: 'bg-teal-100 text-teal-800',    bar: 'bg-teal-500' },
  pink:   { badge: 'bg-pink-100 text-pink-800',    bar: 'bg-pink-500' },
  slate:  { badge: 'bg-slate-100 text-slate-700',  bar: 'bg-slate-500' },
  violet: { badge: 'bg-violet-100 text-violet-800',bar: 'bg-violet-500' },
  gray:   { badge: 'bg-gray-100 text-gray-600',    bar: 'bg-gray-400' },
  indigo: { badge: 'bg-indigo-100 text-indigo-800',bar: 'bg-indigo-500' },
  orange: { badge: 'bg-orange-100 text-orange-800',bar: 'bg-orange-500' },
}
const tone = c => TONES[c] ?? TONES.gray
const fmt = (n, dp = 0) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })

function CategoryCard({ cat, meta }) {
  const t = tone(meta.color)
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="font-semibold text-gray-800">{cat.category_display || meta.name}</div>
        <div className="text-left">
          <div className="text-lg font-bold text-gray-900">{fmt(cat.share_of_total, 1)}%</div>
          <div className="text-xs text-gray-500">من الإجمالي</div>
        </div>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-2">
        <div className={`h-2 rounded-full ${t.bar}`} style={{ width: `${Math.min(100, cat.share_of_total)}%` }} />
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div><div className="text-xs text-gray-500">إجمالي القيمة</div><div className="font-semibold text-gray-800">{fmt(cat.total_value / 1000, 1)}K ج.م</div></div>
        <div><div className="text-xs text-gray-500">عدد الموردين</div><div className="font-semibold text-gray-800">{fmt(cat.supplier_count)}</div></div>
        <div><div className="text-xs text-gray-500">معدل المرتجعات</div><div className={`font-semibold ${cat.return_pct > 20 ? 'text-red-600' : 'text-gray-800'}`}>{fmt(cat.return_pct, 1)}%</div></div>
        <div><div className="text-xs text-gray-500">معدل FOC</div><div className={`font-semibold ${cat.foc_rate_pct > 2 ? 'text-emerald-600' : 'text-gray-800'}`}>{fmt(cat.foc_rate_pct, 1)}%</div></div>
      </div>
    </div>
  )
}

function OverrideModal({ seg, catList, onClose, onSave }) {
  const [category, setCategory] = useState(seg.supplier_category)
  const [notes, setNotes] = useState(seg.notes || '')
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" dir="rtl" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-gray-900">تعديل تصنيف المورد</h3>
        <p className="text-sm text-gray-600">المورد: <strong>{seg.supplier_name || seg.supplier_code}</strong></p>
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">الفئة الجديدة</label>
          <select value={category} onChange={e => setCategory(e.target.value)} className="input-field w-full">
            {catList.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">ملاحظات</label>
          <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} placeholder="سبب التعديل اليدوي..." className="input-field w-full resize-none" />
        </div>
        <p className="text-xs text-amber-600 bg-amber-50 rounded-lg p-3">⚠️ سيتم تعطيل التصنيف التلقائي لهذا المورد ويبقى ثابتًا عند إعادة التشغيل.</p>
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">إلغاء</button>
          <button onClick={() => onSave({ supplier_category: category, notes })} className="px-4 py-2 text-sm font-medium bg-brand-600 text-white rounded-lg hover:bg-brand-700">حفظ التعديل</button>
        </div>
      </div>
    </div>
  )
}

export default function SupplierSegmentationPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const qc = useQueryClient()
  const { params, options } = useProcurementFilters()

  const [activeCategory, setActiveCategory] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [editingSeg, setEditingSeg] = useState(null)

  const catList = options.supplier_categories ?? []
  const catMap  = Object.fromEntries(catList.map(c => [c.code, c]))
  const meta    = (code) => catMap[code] ?? { code, name: code, color: 'gray' }

  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: ['segments-summary', params],
    queryFn:  () => procurementIntelApi.segmentsSummary(params).then(r => r.data),
    keepPreviousData: true,
  })

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['segments-list', activeCategory, searchQ],
    queryFn:  () => procurementIntelApi.listSegments({
      category: activeCategory || undefined,
      q:        searchQ || undefined,
    }).then(r => r.data),
    keepPreviousData: true,
  })

  const overrideMutation = useMutation({
    mutationFn: ({ id, data }) => procurementIntelApi.updateSegment(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['segments-list'] })
      qc.invalidateQueries({ queryKey: ['segments-summary'] })
      setEditingSeg(null)
    },
  })

  const categories = summaryData?.categories ?? []
  const segments   = Array.isArray(listData) ? listData : (listData?.results ?? [])
  const totalValue = summaryData?.total_value ?? 0

  return (
    <div className="p-6 space-y-6" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">تصنيف الموردين الذكي</h1>
        <p className="text-sm text-gray-500 mt-0.5">تصنيف مبني على أكواد SOFTECH — حسب الفلاتر أعلاه · اضغط بطاقة للتصفية</p>
      </div>

      {/* Summary cards */}
      {summaryLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {[...Array(8)].map((_, i) => <div key={i} className="h-36 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {categories.map(cat => (
            <div key={cat.category} onClick={() => setActiveCategory(a => a === cat.category ? '' : cat.category)}
              className={`cursor-pointer transition-all rounded-xl ${activeCategory === cat.category ? 'ring-2 ring-brand-500' : ''}`}>
              <CategoryCard cat={cat} meta={meta(cat.category)} />
            </div>
          ))}
        </div>
      )}

      {/* Distribution bar */}
      {totalValue > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <div className="text-sm font-medium text-gray-700 mb-2">توزيع قيمة المشتريات</div>
          <div className="flex gap-0.5 h-6 rounded-full overflow-hidden">
            {categories.map(cat => (
              <div key={cat.category} className={`${tone(meta(cat.category).color).bar} transition-all`}
                style={{ width: `${cat.share_of_total}%` }} title={`${cat.category_display}: ${cat.share_of_total}%`} />
            ))}
          </div>
          <div className="flex flex-wrap gap-3 mt-2">
            {categories.map(cat => (
              <div key={cat.category} className="flex items-center gap-1 text-xs text-gray-600">
                <div className={`w-2.5 h-2.5 rounded-full ${tone(meta(cat.category).color).bar}`} />
                {cat.category_display} ({fmt(cat.share_of_total, 1)}%)
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Supplier list */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">
            قائمة الموردين
            {activeCategory && <span className="text-sm text-brand-600 mr-2">— {meta(activeCategory).name}</span>}
          </h2>
          <div className="flex items-center gap-2">
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="بحث بالاسم أو الكود..." className="input-field text-sm w-48" />
            {activeCategory && <button onClick={() => setActiveCategory('')} className="text-xs text-gray-400 hover:text-gray-600 underline">إلغاء الفلتر</button>}
          </div>
        </div>

        {listLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-brand-600 ml-2" />جاري التحميل...
          </div>
        ) : segments.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-gray-400">لا توجد موردون مطابقون</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  {['كود المورد', 'اسم المورد', 'الفئة', 'ptcode', 'classif', 'قيمة الشراء', 'الفواتير',
                    'معدل FOC', 'معدل الإرجاع', 'النوع', isAdmin && 'إجراء'].filter(Boolean).map(h => (
                    <th key={h} className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {segments.map(seg => {
                  const m = meta(seg.supplier_category)
                  return (
                    <tr key={seg.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-3 py-2.5 font-mono text-xs text-gray-600">{seg.supplier_code}</td>
                      <td className="px-3 py-2.5 font-medium text-gray-800 max-w-[200px] truncate">{seg.supplier_name || '—'}</td>
                      <td className="px-3 py-2.5">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${tone(m.color).badge}`}>
                          {seg.supplier_category_display || m.name}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs text-gray-500">{seg.ptcode || '—'}</td>
                      <td className="px-3 py-2.5 font-mono text-xs text-gray-500">{seg.ptclassifcode || '—'}</td>
                      <td className="px-3 py-2.5 text-left dir-ltr font-medium text-gray-800">{fmt(seg.purchase_value_365d / 1000, 1)}K</td>
                      <td className="px-3 py-2.5 text-left dir-ltr text-gray-600">{fmt(seg.invoice_count_365d)}</td>
                      <td className="px-3 py-2.5 text-left dir-ltr"><span className={seg.foc_rate_pct > 2 ? 'text-emerald-600 font-medium' : 'text-gray-500'}>{fmt(seg.foc_rate_pct, 1)}%</span></td>
                      <td className="px-3 py-2.5 text-left dir-ltr"><span className={seg.return_pct > 20 ? 'text-red-600 font-medium' : 'text-gray-500'}>{fmt(seg.return_pct, 1)}%</span></td>
                      <td className="px-3 py-2.5">
                        {seg.manual_override
                          ? <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-amber-100 text-amber-700">✋ يدوي</span>
                          : <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500">🤖 آلي</span>}
                      </td>
                      {isAdmin && (
                        <td className="px-3 py-2.5">
                          <button onClick={() => setEditingSeg(seg)} className="text-xs text-brand-600 hover:text-brand-800 underline">تعديل</button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editingSeg && (
        <OverrideModal seg={editingSeg} catList={catList}
          onClose={() => setEditingSeg(null)}
          onSave={data => overrideMutation.mutate({ id: editingSeg.id, data })} />
      )}
    </div>
  )
}
