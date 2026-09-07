/**
 * SupplierCategoriesPage.jsx
 *
 * Admin-managed supplier categories + SOFTECH classification rules.
 *   - Category master (add / edit / activate / fallback / colour)
 *   - (ptcode, ptclassifcode) → category rules, with SOFTECH code dropdowns
 *   - "Reclassify" re-runs Stage 2.5 against the current rules
 *
 * Category codes here drive the labels/colours shown across every procurement
 * tab (history, segments, FOC). Manual per-supplier overrides live on the
 * تصنيف الموردين (segments) tab.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { procurementIntelApi } from '../api/client'

const TONES = {
  blue:   'bg-blue-100 text-blue-800',      green:  'bg-green-100 text-green-800',
  sky:    'bg-sky-100 text-sky-800',        amber:  'bg-amber-100 text-amber-800',
  purple: 'bg-purple-100 text-purple-800',  teal:   'bg-teal-100 text-teal-800',
  pink:   'bg-pink-100 text-pink-800',      slate:  'bg-slate-100 text-slate-700',
  violet: 'bg-violet-100 text-violet-800',  gray:   'bg-gray-100 text-gray-600',
  indigo: 'bg-indigo-100 text-indigo-800',  orange: 'bg-orange-100 text-orange-800',
}
const TONE_KEYS = Object.keys(TONES)

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-5" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

const field = 'input-field w-full text-sm'
const label = 'text-xs text-gray-500 block mb-1'

export default function SupplierCategoriesPage() {
  const qc = useQueryClient()
  const [catModal, setCatModal]   = useState(null)   // category being edited / {} for new
  const [ruleModal, setRuleModal] = useState(null)

  const catsQ  = useQuery({ queryKey: ['proc-categories'], queryFn: () => procurementIntelApi.listCategories().then(r => r.data) })
  const rulesQ = useQuery({ queryKey: ['proc-rules'],      queryFn: () => procurementIntelApi.listRules().then(r => r.data) })
  const codesQ = useQuery({ queryKey: ['proc-person-codes'], queryFn: () => procurementIntelApi.personCodes().then(r => r.data) })

  const cats  = catsQ.data ?? []
  const rules = rulesQ.data ?? []
  const types = codesQ.data?.person_types ?? []
  const classifs = codesQ.data?.classifications ?? []

  const invalidate = () => { qc.invalidateQueries({ queryKey: ['proc-categories'] }); qc.invalidateQueries({ queryKey: ['proc-rules'] }) }

  const saveCat = useMutation({
    mutationFn: (c) => c.id ? procurementIntelApi.updateCategory(c.id, c) : procurementIntelApi.createCategory(c),
    onSuccess: () => { invalidate(); setCatModal(null) },
  })
  const delCat = useMutation({ mutationFn: (id) => procurementIntelApi.deleteCategory(id), onSuccess: invalidate })
  const saveRule = useMutation({
    mutationFn: (r) => r.id ? procurementIntelApi.updateRule(r.id, r) : procurementIntelApi.createRule(r),
    onSuccess: () => { invalidate(); setRuleModal(null) },
  })
  const delRule = useMutation({ mutationFn: (id) => procurementIntelApi.deleteRule(id), onSuccess: invalidate })
  const reclassify = useMutation({ mutationFn: () => procurementIntelApi.reclassify() })

  const catByCode = Object.fromEntries(cats.map(c => [c.code, c]))
  const typeLabel = (pt) => { const t = types.find(x => x.ptcode === pt); return t ? `${pt} — ${t.ptdescr}` : pt }
  const classifLabel = (pt, cl) => {
    if (!cl) return 'كل التصنيفات'
    const c = classifs.find(x => x.ptcode === pt && x.ptclassifcode === cl)
    return c ? `${cl} — ${c.ptclassifdescr}` : cl
  }

  return (
    <div className="p-6 space-y-6" dir="rtl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">فئات وتصنيف الموردين</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            فئات مُدارة + قواعد ربط أكواد SOFTECH (نوع الشخص / التصنيف) بالفئات
          </p>
        </div>
        <button
          onClick={() => reclassify.mutate()}
          disabled={reclassify.isPending}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
          {reclassify.isPending ? '...' : '🔄 إعادة تصنيف الموردين'}
        </button>
      </div>
      {reclassify.isSuccess && (
        <div className="bg-emerald-50 text-emerald-700 text-sm rounded-lg px-4 py-2">
          بدأت إعادة التصنيف في الخلفية — سيتم تحديث الفئات خلال دقيقة.
        </div>
      )}

      {/* Categories */}
      <section className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-gray-800">الفئات ({cats.length})</h2>
          <button onClick={() => setCatModal({ color: 'gray', sort_order: 100, is_active: true })}
            className="text-sm px-3 py-1.5 rounded-lg border border-brand-500 text-brand-700 hover:bg-brand-50">
            + فئة جديدة
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200 text-xs text-gray-600">
              <tr>{['#', 'الاسم', 'الكود', 'موردون', 'قواعد', 'الحالة', ''].map(h =>
                <th key={h} className="px-3 py-2 text-right font-semibold whitespace-nowrap">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {cats.map(c => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-400">{c.sort_order}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${TONES[c.color] ?? TONES.gray}`}>
                      {c.name_ar}
                    </span>
                    {c.is_fallback && <span className="text-xs text-gray-400 mr-2">(افتراضي)</span>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">{c.code}</td>
                  <td className="px-3 py-2 text-gray-700">{c.supplier_count}</td>
                  <td className="px-3 py-2 text-gray-700">{c.rule_count}</td>
                  <td className="px-3 py-2">{c.is_active
                    ? <span className="text-emerald-600 text-xs">نشط</span>
                    : <span className="text-gray-400 text-xs">معطّل</span>}</td>
                  <td className="px-3 py-2 text-left whitespace-nowrap">
                    <button onClick={() => setCatModal(c)} className="text-brand-600 hover:underline text-xs ml-3">تعديل</button>
                    <button onClick={() => { if (confirm(`حذف الفئة "${c.name_ar}"؟`)) delCat.mutate(c.id) }}
                      className="text-red-500 hover:underline text-xs">حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Rules */}
      <section className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-gray-800">قواعد التصنيف ({rules.length})</h2>
          <button onClick={() => setRuleModal({ ptcode: '20', ptclassifcode: '', priority: 10, is_active: true })}
            className="text-sm px-3 py-1.5 rounded-lg border border-brand-500 text-brand-700 hover:bg-brand-50">
            + قاعدة جديدة
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200 text-xs text-gray-600">
              <tr>{['نوع الشخص', 'التصنيف', 'الفئة', 'الأولوية', 'الحالة', ''].map(h =>
                <th key={h} className="px-3 py-2 text-right font-semibold whitespace-nowrap">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rules.map(r => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-700">{typeLabel(r.ptcode)}</td>
                  <td className="px-3 py-2 text-gray-600">{classifLabel(r.ptcode, r.ptclassifcode)}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${TONES[catByCode[r.category_code]?.color] ?? TONES.gray}`}>
                      {r.category_name}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-500">{r.priority}</td>
                  <td className="px-3 py-2">{r.is_active
                    ? <span className="text-emerald-600 text-xs">نشط</span>
                    : <span className="text-gray-400 text-xs">معطّل</span>}</td>
                  <td className="px-3 py-2 text-left whitespace-nowrap">
                    <button onClick={() => setRuleModal(r)} className="text-brand-600 hover:underline text-xs ml-3">تعديل</button>
                    <button onClick={() => { if (confirm('حذف القاعدة؟')) delRule.mutate(r.id) }}
                      className="text-red-500 hover:underline text-xs">حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Category modal */}
      {catModal && (
        <Modal title={catModal.id ? 'تعديل فئة' : 'فئة جديدة'} onClose={() => setCatModal(null)}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><label className={label}>الاسم بالعربية</label>
                <input className={field} value={catModal.name_ar ?? ''} onChange={e => setCatModal({ ...catModal, name_ar: e.target.value })} /></div>
              <div><label className={label}>الاسم بالإنجليزية</label>
                <input className={field} value={catModal.name_en ?? ''} onChange={e => setCatModal({ ...catModal, name_en: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className={label}>الكود (لا يُغيّر بعد الإنشاء)</label>
                <input className={field} value={catModal.code ?? ''} disabled={!!catModal.id}
                  onChange={e => setCatModal({ ...catModal, code: e.target.value.toUpperCase().replace(/\s/g, '_') })} /></div>
              <div><label className={label}>الترتيب</label>
                <input type="number" className={field} value={catModal.sort_order ?? 100}
                  onChange={e => setCatModal({ ...catModal, sort_order: Number(e.target.value) })} /></div>
            </div>
            <div>
              <label className={label}>اللون</label>
              <div className="flex flex-wrap gap-1.5">
                {TONE_KEYS.map(k => (
                  <button key={k} onClick={() => setCatModal({ ...catModal, color: k })}
                    className={`px-2 py-1 rounded text-xs ${TONES[k]} ${catModal.color === k ? 'ring-2 ring-offset-1 ring-brand-500' : ''}`}>
                    {k}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-4 pt-1">
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input type="checkbox" checked={!!catModal.is_active} onChange={e => setCatModal({ ...catModal, is_active: e.target.checked })} /> نشط
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input type="checkbox" checked={!!catModal.is_fallback} onChange={e => setCatModal({ ...catModal, is_fallback: e.target.checked })} /> فئة افتراضية (غير مصنف)
              </label>
            </div>
            {saveCat.isError && <p className="text-xs text-red-500">تعذّر الحفظ — تأكد من الكود.</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setCatModal(null)} className="px-4 py-2 rounded-lg text-sm border border-gray-300 text-gray-600">إلغاء</button>
              <button onClick={() => saveCat.mutate(catModal)} disabled={saveCat.isPending || !catModal.name_ar || !catModal.code}
                className="px-4 py-2 rounded-lg text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">حفظ</button>
            </div>
          </div>
        </Modal>
      )}

      {/* Rule modal */}
      {ruleModal && (
        <Modal title={ruleModal.id ? 'تعديل قاعدة' : 'قاعدة جديدة'} onClose={() => setRuleModal(null)}>
          <div className="space-y-3">
            <div><label className={label}>نوع الشخص (ptcode)</label>
              <select className={field} value={ruleModal.ptcode ?? ''}
                onChange={e => setRuleModal({ ...ruleModal, ptcode: e.target.value, ptclassifcode: '' })}>
                <option value="">— اختر —</option>
                {types.map(t => <option key={t.ptcode} value={t.ptcode}>{t.ptcode} — {t.ptdescr}</option>)}
              </select></div>
            <div><label className={label}>التصنيف (ptclassifcode) — فارغ = كل التصنيفات تحت النوع</label>
              <select className={field} value={ruleModal.ptclassifcode ?? ''}
                onChange={e => setRuleModal({ ...ruleModal, ptclassifcode: e.target.value })}>
                <option value="">كل التصنيفات</option>
                {classifs.filter(c => c.ptcode === ruleModal.ptcode).map(c =>
                  <option key={c.ptclassifcode} value={c.ptclassifcode}>{c.ptclassifcode} — {c.ptclassifdescr}</option>)}
              </select></div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className={label}>الفئة</label>
                <select className={field} value={ruleModal.category ?? ''}
                  onChange={e => setRuleModal({ ...ruleModal, category: Number(e.target.value) })}>
                  <option value="">— اختر —</option>
                  {cats.map(c => <option key={c.id} value={c.id}>{c.name_ar}</option>)}
                </select></div>
              <div><label className={label}>الأولوية (الأقل يفوز)</label>
                <input type="number" className={field} value={ruleModal.priority ?? 10}
                  onChange={e => setRuleModal({ ...ruleModal, priority: Number(e.target.value) })} /></div>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <input type="checkbox" checked={!!ruleModal.is_active} onChange={e => setRuleModal({ ...ruleModal, is_active: e.target.checked })} /> نشط
            </label>
            {saveRule.isError && <p className="text-xs text-red-500">تعذّر الحفظ — قد توجد قاعدة بنفس النوع/التصنيف.</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setRuleModal(null)} className="px-4 py-2 rounded-lg text-sm border border-gray-300 text-gray-600">إلغاء</button>
              <button onClick={() => saveRule.mutate(ruleModal)} disabled={saveRule.isPending || !ruleModal.ptcode || !ruleModal.category}
                className="px-4 py-2 rounded-lg text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">حفظ</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
