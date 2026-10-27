import { useState, useEffect } from 'react'
import { invoicesApi } from '../../api/client'

/**
 * Per-distributor column-template calibrator (#9).
 *
 * A power user defines a vendor's invoice column layout (ocr_profile.column_bands)
 * without touching code: each band is a field + its horizontal span as a fraction
 * of page width (RTL → item name is on the right / high x). The sample scan shows
 * the bands as coloured strips so the ranges can be tuned by eye. The free OCR
 * engine then maps that distributor's columns deterministically.
 */

const FIELDS = [
  ['item_name', 'اسم الصنف'], ['manufacturer', 'المورد/المصنع'], ['quantity', 'الكمية'],
  ['public_price', 'سعر الجمهور'], ['pharmacist_price', 'سعر الصيدلي'], ['discount_pct', 'الخصم %'],
  ['vat_pct', 'الضريبة'], ['expiry_date', 'الصلاحية'], ['batch_number', 'التشغيلة'],
  ['vendor_item_code', 'كود الصنف'], ['line_total', 'الإجمالي'], ['ignore', 'تجاهل'],
]
const COLORS = ['#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6', '#ec4899',
                '#14b8a6', '#f97316', '#6366f1', '#84cc16', '#06b6d4', '#9ca3af']

export default function VendorTemplateEditor({ vendorId, sampleImageUrl, onClose, onSaved }) {
  const [vendor, setVendor] = useState(null)
  const [bands, setBands] = useState([])
  const [multiline, setMultiline] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    invoicesApi.getVendor(vendorId).then(r => {
      setVendor(r.data)
      const prof = r.data.ocr_profile || {}
      setBands(Array.isArray(prof.column_bands) ? prof.column_bands : [])
      setMultiline(!!prof.multiline)
    }).catch(() => setErr('تعذّر تحميل المورد'))
  }, [vendorId])

  const update = (i, k, v) => setBands(bs => bs.map((b, j) => j === i ? { ...b, [k]: v } : b))
  const addBand = () => setBands(bs => [...bs, { field: 'item_name', x0: 0.7, x1: 0.95 }])
  const remove = (i) => setBands(bs => bs.filter((_, j) => j !== i))

  const save = async () => {
    setSaving(true); setErr('')
    try {
      const clean = bands
        .filter(b => b.field)
        .map(b => ({ field: b.field, x0: Number(b.x0), x1: Number(b.x1) }))
      const ocr_profile = { ...(vendor.ocr_profile || {}), column_bands: clean, multiline }
      await invoicesApi.updateVendor(vendorId, { ocr_profile })
      onSaved?.()
      onClose?.()
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الحفظ')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <div className="font-bold text-gray-900">قالب أعمدة المورد — {vendor?.name || '…'}</div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <div className="flex-1 overflow-auto p-5 grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* sample with band overlay */}
          <div>
            <div className="text-xs text-gray-500 mb-2">عيّنة الفاتورة (الأعمدة ملوّنة حسب الحقل):</div>
            <div className="relative border border-gray-200 rounded-lg overflow-hidden">
              {sampleImageUrl
                ? <img src={sampleImageUrl} alt="sample" className="w-full block" />
                : <div className="h-64 flex items-center justify-center text-gray-400 text-sm">لا توجد عيّنة</div>}
              {bands.map((b, i) => (
                <div key={i} className="absolute top-0 bottom-0 opacity-25"
                  style={{ left: `${Number(b.x0) * 100}%`, width: `${(Number(b.x1) - Number(b.x0)) * 100}%`,
                           background: COLORS[i % COLORS.length] }} />
              ))}
            </div>
            <label className="flex items-center gap-2 mt-3 text-sm text-gray-600">
              <input type="checkbox" checked={multiline} onChange={e => setMultiline(e.target.checked)} className="accent-brand-600" />
              كل صنف على سطرين (مثل رامكو)
            </label>
          </div>

          {/* band table */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-gray-500">الأعمدة (x من 0 يسار إلى 1 يمين):</div>
              <button onClick={addBand} className="text-xs px-2 py-1 bg-gray-100 rounded-lg hover:bg-gray-200">+ عمود</button>
            </div>
            <div className="space-y-1.5 max-h-[50vh] overflow-auto">
              {bands.map((b, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                  <select value={b.field} onChange={e => update(i, 'field', e.target.value)}
                    className="flex-1 border border-gray-200 rounded-lg px-2 py-1 text-xs">
                    {FIELDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                  <input type="number" step="0.01" min="0" max="1" value={b.x0}
                    onChange={e => update(i, 'x0', e.target.value)}
                    className="w-16 border border-gray-200 rounded-lg px-1 py-1 text-xs text-center" />
                  <input type="number" step="0.01" min="0" max="1" value={b.x1}
                    onChange={e => update(i, 'x1', e.target.value)}
                    className="w-16 border border-gray-200 rounded-lg px-1 py-1 text-xs text-center" />
                  <button onClick={() => remove(i)} className="text-red-400 hover:text-red-600 text-sm px-1">✕</button>
                </div>
              ))}
              {bands.length === 0 && <div className="text-xs text-gray-400 py-4 text-center">لا توجد أعمدة — أضف عموداً للبدء</div>}
            </div>
          </div>
        </div>

        {err && <div className="mx-5 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{err}</div>}
        <div className="px-5 py-4 border-t border-gray-100 flex gap-2">
          <button onClick={save} disabled={saving}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? 'جارٍ الحفظ…' : 'حفظ القالب'}
          </button>
          <button onClick={onClose} className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">إلغاء</button>
        </div>
      </div>
    </div>
  )
}
