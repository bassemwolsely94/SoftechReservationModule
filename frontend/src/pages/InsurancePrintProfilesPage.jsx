/**
 * InsurancePrintProfilesPage — manage claim print/export profiles.
 * Customize header/footer sections, fonts, fills, borders, day-block spacing.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

const PLACEHOLDERS = ['{client}', '{subclient}', '{claim_number}', '{month}',
  '{period_from}', '{period_to}', '{call_center}', '{page}', '{pages}', '{rx_count}', '{net}']

const BLANK = {
  name: 'ملف طباعة جديد', is_default: false, subclient: null,
  header_left: '', header_center: '{client} - {subclient}\nشهر {month}', header_right: '',
  footer_left: '', footer_center: 'صفحة {page} من {pages}', footer_right: '',
  font_name: 'Arial',
  header_font_size: 10, header_fill: '1F4E79', header_font_color: 'FFFFFF',
  subtotal_font_size: 10, subtotal_fill: 'D6E4F0',
  total_font_size: 11, total_fill: 'E2EFDA',
  border_style: 'thin', day_block_blank_rows: 4, repeat_header_each_page: true,
}

export default function InsurancePrintProfilesPage() {
  const navigate = useNavigate()
  const [profiles, setProfiles] = useState([])
  const [subclients, setSubclients] = useState([])
  const [editing, setEditing] = useState(null)   // profile object or null
  const [saving, setSaving] = useState(false)

  const load = () => insuranceApi.exportProfiles().then(r => setProfiles(r.data.results || r.data))
  useEffect(() => {
    load()
    insuranceApi.subclients().then(r => setSubclients(r.data.results || r.data)).catch(() => {})
  }, [])

  const [wmFile, setWmFile] = useState(null)

  const save = async () => {
    setSaving(true)
    try {
      let payload, isMultipart = false
      if (wmFile) {
        // multipart — include the watermark image
        const fd = new FormData()
        Object.entries({ ...editing, subclient: editing.subclient || '' }).forEach(([k, v]) => {
          if (k === 'watermark_image' || k === 'subclient_name' || k === 'id') return
          if (v === null || v === undefined) return
          fd.append(k, typeof v === 'boolean' ? (v ? 'true' : 'false') : v)
        })
        fd.append('watermark_image', wmFile)
        payload = fd; isMultipart = true
      } else {
        payload = { ...editing, subclient: editing.subclient || null }
        delete payload.watermark_image; delete payload.subclient_name
      }
      const cfg = isMultipart ? { headers: { 'Content-Type': 'multipart/form-data' } } : undefined
      if (editing.id) await insuranceApi.updateExportProfile(editing.id, payload, cfg)
      else await insuranceApi.createExportProfile(payload, cfg)
      setEditing(null); setWmFile(null); load()
    } catch (e) {
      alert(e.response?.data ? JSON.stringify(e.response.data) : 'تعذّر الحفظ')
    } finally { setSaving(false) }
  }

  const del = async (id) => {
    if (!window.confirm('حذف ملف الطباعة؟')) return
    await insuranceApi.deleteExportProfile(id); load()
  }

  const set = (k, v) => setEditing(p => ({ ...p, [k]: v }))
  const inp = 'w-full border border-gray-300 rounded px-2 py-1.5 text-sm'
  const lbl = 'text-xs text-gray-600 mb-1 block'

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <button onClick={() => navigate('/insurance')} className="text-blue-600 text-sm hover:underline">← مطالبات التأمين</button>
          <h1 className="text-xl font-bold text-gray-900 mt-1">تخصيص طباعة المطالبات</h1>
        </div>
        <button onClick={() => setEditing({ ...BLANK })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">+ ملف جديد</button>
      </div>

      <div className="p-6 max-w-5xl mx-auto">
        {!editing ? (
          <div className="space-y-2">
            {profiles.length === 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400 text-sm">
                لا توجد ملفات طباعة مخصّصة — تُستخدم الإعدادات الافتراضية. أنشئ ملفاً لتخصيص الترويسة والخطوط والألوان.
              </div>
            )}
            {profiles.map(p => (
              <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-3 flex items-center justify-between">
                <div>
                  <span className="font-semibold text-gray-800">{p.name}</span>
                  {p.is_default && <span className="text-xs bg-green-100 text-green-700 px-1.5 rounded mr-2">عام افتراضي</span>}
                  {p.subclient_name && <span className="text-xs bg-blue-100 text-blue-700 px-1.5 rounded mr-2">{p.subclient_name}</span>}
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setEditing(p)} className="px-3 py-1 bg-gray-100 text-gray-700 text-xs rounded hover:bg-gray-200">تعديل</button>
                  <button onClick={() => del(p.id)} className="px-3 py-1 bg-red-50 text-red-600 text-xs rounded hover:bg-red-100">حذف</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
            {/* Scope */}
            <div className="grid grid-cols-3 gap-3">
              <div><label className={lbl}>اسم الملف</label>
                <input className={inp} value={editing.name} onChange={e => set('name', e.target.value)} /></div>
              <div><label className={lbl}>خاص بالفئة (اختياري)</label>
                <select className={inp} value={editing.subclient || ''} onChange={e => set('subclient', e.target.value || null)}>
                  <option value="">— عام —</option>
                  {subclients.map(s => <option key={s.id} value={s.id}>{s.client_name} — {s.name}</option>)}
                </select></div>
              <div className="flex items-end gap-2">
                <label className="text-sm text-gray-600 flex items-center gap-1">
                  <input type="checkbox" checked={editing.is_default} onChange={e => set('is_default', e.target.checked)} />
                  الافتراضي العام
                </label>
              </div>
            </div>

            {/* Placeholder hint */}
            <div className="bg-blue-50 border border-blue-200 rounded p-2 text-xs text-blue-700">
              المتغيرات المتاحة: {PLACEHOLDERS.join(' · ')} — استخدم سطراً جديداً للفصل بين الأسطر.
            </div>

            {/* Header sections */}
            <div>
              <p className="text-sm font-semibold text-gray-700 mb-2">الترويسة (Header)</p>
              <div className="grid grid-cols-3 gap-3">
                {[['يمين', 'header_right'], ['وسط', 'header_center'], ['يسار', 'header_left']].map(([t, k]) => (
                  <div key={k}><label className={lbl}>{t}</label>
                    <textarea rows={4} className={inp} value={editing[k]} onChange={e => set(k, e.target.value)} /></div>
                ))}
              </div>
            </div>

            {/* Footer sections */}
            <div>
              <p className="text-sm font-semibold text-gray-700 mb-2">التذييل (Footer)</p>
              <div className="grid grid-cols-3 gap-3">
                {[['يمين', 'footer_right'], ['وسط', 'footer_center'], ['يسار', 'footer_left']].map(([t, k]) => (
                  <div key={k}><label className={lbl}>{t}</label>
                    <textarea rows={2} className={inp} value={editing[k]} onChange={e => set(k, e.target.value)} /></div>
                ))}
              </div>
            </div>

            {/* Typography */}
            <div>
              <p className="text-sm font-semibold text-gray-700 mb-2">الخطوط والألوان</p>
              <div className="grid grid-cols-4 gap-3">
                <div><label className={lbl}>الخط</label>
                  <input className={inp} value={editing.font_name} onChange={e => set('font_name', e.target.value)} /></div>
                {[
                  ['حجم خط العناوين', 'header_font_size'], ['حجم خط المجاميع', 'subtotal_font_size'],
                  ['حجم خط الإجمالى', 'total_font_size'],
                ].map(([t, k]) => (
                  <div key={k}><label className={lbl}>{t}</label>
                    <input type="number" className={inp} value={editing[k]} onChange={e => set(k, +e.target.value)} /></div>
                ))}
              </div>
              <div className="grid grid-cols-4 gap-3 mt-3">
                {[
                  ['لون تعبئة العناوين', 'header_fill'], ['لون خط العناوين', 'header_font_color'],
                  ['لون المجاميع اليومية', 'subtotal_fill'], ['لون الإجمالى', 'total_fill'],
                ].map(([t, k]) => (
                  <div key={k}><label className={lbl}>{t}</label>
                    <div className="flex items-center gap-1">
                      <input type="color" value={'#' + editing[k]} onChange={e => set(k, e.target.value.slice(1).toUpperCase())}
                        className="w-9 h-8 border border-gray-300 rounded" />
                      <input className={inp} value={editing[k]} onChange={e => set(k, e.target.value.replace('#', '').toUpperCase())} />
                    </div></div>
                ))}
              </div>
            </div>

            {/* Layout */}
            <div className="grid grid-cols-3 gap-3">
              <div><label className={lbl}>سُمك الإطار</label>
                <select className={inp} value={editing.border_style} onChange={e => set('border_style', e.target.value)}>
                  <option value="none">بدون</option><option value="thin">رفيع</option>
                  <option value="medium">متوسط</option><option value="thick">سميك</option>
                </select></div>
              <div><label className={lbl}>أسطر فارغة بين الأيام</label>
                <input type="number" min="0" max="20" className={inp}
                  value={editing.day_block_blank_rows} onChange={e => set('day_block_blank_rows', +e.target.value)} /></div>
              <div className="flex items-end">
                <label className="text-sm text-gray-600 flex items-center gap-1">
                  <input type="checkbox" checked={editing.repeat_header_each_page}
                    onChange={e => set('repeat_header_each_page', e.target.checked)} />
                  تكرار العناوين بكل صفحة
                </label>
              </div>
            </div>

            {/* Watermark */}
            <div>
              <p className="text-sm font-semibold text-gray-700 mb-2">العلامة المائية (شعار باهت)</p>
              <div className="grid grid-cols-3 gap-3">
                <div><label className={lbl}>صورة PNG (يفضّل فاتحة/شفافة)</label>
                  <input type="file" accept="image/png,image/*" className="text-sm"
                    onChange={e => setWmFile(e.target.files?.[0] || null)} />
                  {editing.watermark_image && !wmFile && (
                    <p className="text-[11px] text-green-600 mt-1">صورة محفوظة ✓</p>
                  )}
                </div>
                <div><label className={lbl}>العرض (سم)</label>
                  <input type="number" step="0.5" className={inp}
                    value={editing.watermark_width_cm || 8} onChange={e => set('watermark_width_cm', e.target.value)} /></div>
                <div><label className={lbl}>موضع الإرساء</label>
                  <input className={inp} value={editing.watermark_anchor || 'C15'}
                    onChange={e => set('watermark_anchor', e.target.value)} /></div>
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                تظهر الصورة فوق البيانات كعلامة مائية — استخدم صورة فاتحة لتبدو خلف الجدول.
              </p>
            </div>

            <div className="flex gap-2 pt-2 border-t border-gray-100">
              <button onClick={save} disabled={saving}
                className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
                {saving ? 'جارٍ الحفظ…' : 'حفظ'}
              </button>
              <button onClick={() => setEditing(null)}
                className="px-5 py-2 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">إلغاء</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
