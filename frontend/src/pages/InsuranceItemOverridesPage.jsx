/**
 * InsuranceItemOverridesPage — تصويبات تصنيف الأصناف
 *
 * Correct items wrongly defined in the master as مستورد/محلى (which get the wrong
 * discount and are deducted in full by the insurer).  Corrections are GLOBAL by
 * item code and are applied to open draft claims per-claim (audited & revertible).
 */
import { useState, useEffect, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

const CATS = [
  { value: 'local',    label: 'محلى',   cls: 'bg-green-100 text-green-700' },
  { value: 'imported', label: 'مستورد', cls: 'bg-amber-100 text-amber-700' },
  { value: 'tarsia',   label: 'ترسية',  cls: 'bg-purple-100 text-purple-700' },
]
const catInfo = (v) => CATS.find(c => c.value === v) || { label: v, cls: 'bg-gray-100 text-gray-600' }

const inp = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500'
const lbl = 'block text-xs font-medium text-gray-600 mb-1'

function Btn({ children, onClick, variant = 'primary', disabled, className = '' }) {
  const v = {
    primary:   'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    danger:    'bg-red-50 text-red-600 border border-red-200 hover:bg-red-100',
  }
  return (
    <button onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1 rounded font-medium transition-colors disabled:opacity-50 px-2.5 py-1 text-xs ${v[variant]} ${className}`}>
      {children}
    </button>
  )
}

function CatBadge({ value }) {
  const c = catInfo(value)
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${c.cls}`}>{c.label}</span>
}

const MODES = [
  { value: 'force',  label: 'فرض تصنيف موحّد',   hint: 'الصنف مُعرّف خطأً — نفس التصنيف في كل المطالبات' },
  { value: 'review', label: 'مراجعة يدوية (منشأ مزدوج)', hint: 'الصنف له منشأان — يُقرَّر تصنيفه لكل مطالبة في تبويب فحص الفروقات' },
]
const BLANK = { item_code: '', item_name: '', mode: 'force', forced_category: 'local', reason: '', is_active: true }

export default function InsuranceItemOverridesPage() {
  const navigate = useNavigate()
  const [rows, setRows]       = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')
  const [form, setForm]       = useState(BLANK)
  const [editId, setEditId]   = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving]   = useState(false)
  const [lookup, setLookup]   = useState(null)   // catalog-lookup result for the form's item_code
  const [msg, setMsg]         = useState(null)   // {type, text}
  const [affected, setAffected] = useState({})   // {overrideId: [claims]}

  const load = () => {
    setLoading(true)
    insuranceApi.itemOverrides(search ? { search } : {})
      .then(r => setRows(r.data.results || r.data))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])   // eslint-disable-line

  const flash = (type, text) => { setMsg({ type, text }); setTimeout(() => setMsg(null), 4000) }

  const openAdd  = () => { setEditId(null); setForm(BLANK); setLookup(null); setShowForm(true) }
  const openEdit = (o) => {
    setEditId(o.id)
    setForm({ item_code: o.item_code, item_name: o.item_name || '', mode: o.mode || 'force',
      forced_category: o.forced_category, reason: o.reason || '', is_active: o.is_active })
    setLookup(null); setShowForm(true)
  }

  const doLookup = async () => {
    const code = (form.item_code || '').trim()
    if (!code) return
    try {
      const { data } = await insuranceApi.itemOverrideLookup(code)
      setLookup(data)
      if (data.found && !form.item_name) setForm(f => ({ ...f, item_name: data.item_name }))
    } catch { setLookup({ found: false, item_code: code }) }
  }

  const save = async () => {
    if (!(form.item_code || '').trim()) { flash('error', 'أدخل كود الصنف'); return }
    setSaving(true)
    try {
      if (editId) await insuranceApi.updateItemOverride(editId, form)
      else        await insuranceApi.createItemOverride(form)
      setShowForm(false); flash('success', 'تم الحفظ'); load()
    } catch (e) {
      const d = e?.response?.data
      flash('error', d?.item_code?.[0] || d?.detail || 'تعذّر الحفظ — تأكد أن الكود غير مكرر')
    } finally { setSaving(false) }
  }

  const toggleActive = async (o) => {
    await insuranceApi.updateItemOverride(o.id, { is_active: !o.is_active })
    load()
  }
  const remove = async (o) => {
    if (!window.confirm(`حذف تصويب الصنف ${o.item_code}؟`)) return
    await insuranceApi.deleteItemOverride(o.id); load()
  }
  const toggleAffected = async (o) => {
    if (affected[o.id]) { setAffected(a => ({ ...a, [o.id]: undefined })); return }
    const { data } = await insuranceApi.itemOverrideAffected(o.id)
    setAffected(a => ({ ...a, [o.id]: data }))
  }

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <button onClick={() => navigate('/insurance')} className="text-blue-600 text-sm hover:underline">
          ← مطالبات التأمين
        </button>
        <div className="flex items-center justify-between mt-1">
          <div>
            <h1 className="text-xl font-bold text-gray-800">تصويبات تصنيف الأصناف</h1>
            <p className="text-sm text-gray-500">
              تصحيح الأصناف المُعرّفة خطأً كمستورد/محلى — تُطبَّق على المطالبات المسودة قبل الإصدار
            </p>
          </div>
          <Btn onClick={openAdd}>+ تصويب صنف</Btn>
        </div>
      </div>

      {msg && (
        <div className={`mx-6 mt-3 rounded px-3 py-2 text-sm ${
          msg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200'
                                 : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {msg.text}
        </div>
      )}

      <div className="px-6 py-5">
        <div className="mb-3 flex gap-2">
          <input className={inp + ' max-w-xs'} placeholder="بحث بالكود أو الاسم…"
            value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && load()} />
          <Btn variant="secondary" onClick={load}>بحث</Btn>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200 text-gray-500">
              <tr>
                {['كود الصنف', 'اسم الصنف', 'النوع', 'التصنيف', 'الحالة', 'السبب', ''].map((h, i) => (
                  <th key={i} className="text-right px-3 py-2 text-xs font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">جارٍ التحميل…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">
                  لا توجد تصويبات — أضف تصويباً لتصحيح صنف مُعرّف خطأً أو تحديد صنف مزدوج المنشأ.
                </td></tr>
              ) : rows.map(o => (
                <Fragment key={o.id}>
                  <tr className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono">{o.item_code}</td>
                    <td className="px-3 py-2">{o.item_name || <span className="text-gray-400">—</span>}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                        o.mode === 'review' ? 'bg-indigo-100 text-indigo-700' : 'bg-blue-100 text-blue-700'}`}>
                        {o.mode === 'review' ? 'مراجعة يدوية' : 'فرض موحّد'}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {o.mode === 'review'
                        ? <span className="text-xs text-gray-500">مقترح: <CatBadge value={o.forced_category} /></span>
                        : <CatBadge value={o.forced_category} />}
                    </td>
                    <td className="px-3 py-2">
                      <button onClick={() => toggleActive(o)}
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          o.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                        {o.is_active ? 'مُفعَّل' : 'موقوف'}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{o.reason}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1 justify-end">
                        <Btn variant="secondary" onClick={() => toggleAffected(o)}>المطالبات المتأثرة</Btn>
                        <Btn variant="secondary" onClick={() => openEdit(o)}>تعديل</Btn>
                        <Btn variant="danger" onClick={() => remove(o)}>حذف</Btn>
                      </div>
                    </td>
                  </tr>
                  {affected[o.id] && (
                    <tr className="bg-blue-50/40">
                      <td colSpan={7} className="px-4 py-2">
                        {affected[o.id].length === 0 ? (
                          <span className="text-xs text-gray-500">لا توجد مطالبات مفتوحة تحتوي هذا الصنف.</span>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            <span className="text-xs text-gray-500">مطالبات تحتوي هذا الصنف ({affected[o.id].length}):</span>
                            {affected[o.id].map(c => (
                              <button key={c.claim_id}
                                onClick={() => navigate(`/insurance/claims/${c.claim_id}`)}
                                className="text-xs text-blue-600 hover:underline">
                                {c.claim_number} <span className="text-gray-400">({c.lines} بند)</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add / edit modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-xl w-full max-w-md p-5 shadow-xl" dir="rtl" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-gray-800 mb-4">
              {editId ? 'تعديل التصويب' : 'تصويب صنف جديد'}
            </h3>
            <div className="space-y-3">
              <div>
                <label className={lbl}>كود الصنف (itemcode)</label>
                <div className="flex gap-2">
                  <input className={inp} value={form.item_code} disabled={!!editId}
                    onChange={e => setForm(f => ({ ...f, item_code: e.target.value }))}
                    onBlur={doLookup} placeholder="مثال: 128331" />
                  <Btn variant="secondary" onClick={doLookup} disabled={!!editId}>بحث بالكتالوج</Btn>
                </div>
                {lookup && (
                  <p className="mt-1 text-xs">
                    {lookup.found
                      ? <>الكتالوج: <b>{lookup.item_name}</b> — التصنيف الحالى <CatBadge value={lookup.current_category} /></>
                      : <span className="text-amber-600">الكود غير موجود في الكتالوج (يمكن حفظ التصويب بأي حال).</span>}
                  </p>
                )}
              </div>
              <div>
                <label className={lbl}>اسم الصنف (اختياري)</label>
                <input className={inp} value={form.item_name}
                  onChange={e => setForm(f => ({ ...f, item_name: e.target.value }))} />
              </div>
              <div>
                <label className={lbl}>النوع</label>
                <div className="space-y-1.5">
                  {MODES.map(m => (
                    <label key={m.value}
                      className={`flex items-start gap-2 rounded border p-2 cursor-pointer ${
                        form.mode === m.value ? 'border-blue-500 bg-blue-50/50' : 'border-gray-200'}`}>
                      <input type="radio" name="mode" checked={form.mode === m.value}
                        onChange={() => setForm(f => ({ ...f, mode: m.value }))} className="mt-0.5" />
                      <span>
                        <span className="block text-sm font-medium text-gray-800">{m.label}</span>
                        <span className="block text-xs text-gray-500">{m.hint}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className={lbl}>{form.mode === 'review' ? 'التصنيف المقترح (يُقرَّر لكل مطالبة)' : 'التصنيف الصحيح'}</label>
                <div className="flex gap-2">
                  {CATS.map(c => (
                    <button key={c.value} onClick={() => setForm(f => ({ ...f, forced_category: c.value }))}
                      className={`flex-1 rounded border px-3 py-2 text-sm font-medium ${
                        form.forced_category === c.value ? 'border-blue-500 ' + c.cls : 'border-gray-200 text-gray-500'}`}>
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className={lbl}>سبب التصويب (اختياري)</label>
                <input className={inp} value={form.reason}
                  onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                  placeholder="مثال: مُعرّف خطأً كمستورد" />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.is_active}
                  onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} />
                مُفعَّل
              </label>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <Btn variant="secondary" onClick={() => setShowForm(false)}>إلغاء</Btn>
              <Btn onClick={save} disabled={saving}>{saving ? 'جارٍ الحفظ…' : 'حفظ'}</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
