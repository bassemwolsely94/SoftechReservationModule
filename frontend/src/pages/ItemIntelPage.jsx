/**
 * ItemIntelPage.jsx — Unified Item Intelligence Hub
 *
 * All data about one item from every module, in one place.
 * Accessible at /products/:id/intel
 *
 * 7 sections:
 *   1. SOFTECH Base      — read-only synced fields
 *   2. Enrichment        — editable clinical/AI fields → PATCH /api/enrichment/enrichments/{id}/
 *   3. Content & Attrs   — editable display content    → PATCH /api/products/{id}/content/ + /attributes/
 *   4. Clinical / Chronic — ingredient maps + chronic tag → /api/items/{id}/ingredients/
 *   5. Purchasing Intel  — ABC class, demand metrics, lost sales (read-only)
 *   6. Purchase History  — per-supplier avg/min/max prices + vendor codes (read-only)
 *   7. Recommendations   — Frequently Bought Together (read-only)
 */
import { useState, useCallback, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { itemsApi, productsApi, enrichmentApi, chronicApi } from '../api/client'
import { useToast } from '../components/ui.jsx'

// Pull a human-readable message out of an axios error
function errMsg(e, fallback = 'حدث خطأ أثناء الحفظ') {
  const d = e?.response?.data
  if (typeof d === 'string') return d
  if (d?.detail) return d.detail
  if (d && typeof d === 'object') {
    const first = Object.values(d)[0]
    if (Array.isArray(first)) return first[0]
    if (typeof first === 'string') return first
  }
  if (e?.response?.status === 403) return 'ليس لديك صلاحية لتعديل هذا القسم'
  return fallback
}

// ── Shared helpers ────────────────────────────────────────────────────────────

const fmt  = (n, dec = 2) => n != null ? Number(n).toFixed(dec) : '—'
const fmtK = (n) => n != null ? Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'

const inputCls    = 'w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-300 bg-white'
const textareaCls = `${inputCls} resize-y min-h-[80px]`
const labelCls    = 'block text-xs font-semibold text-gray-600 mb-1'

function FieldRow({ label, hint, children }) {
  return (
    <div className="mb-4">
      <label className={labelCls}>{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}
      {children}
    </div>
  )
}

function ReadRow({ label, value, mono }) {
  if (!value && value !== 0) return null
  return (
    <div className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-400 w-44 shrink-0 pt-0.5">{label}</span>
      <span className={`text-sm text-gray-700 flex-1 ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}

function SectionCard({ title, icon, children, actions }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 bg-gray-50">
        <h3 className="font-bold text-gray-800 flex items-center gap-2">
          <span>{icon}</span> {title}
        </h3>
        {actions}
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function SaveBar({ dirty, saving, onSave, onReset }) {
  if (!dirty) return null
  return (
    <div className="fixed bottom-6 inset-x-0 flex justify-center z-50 pointer-events-none">
      <div className="flex items-center gap-3 bg-white border border-gray-200 shadow-2xl rounded-2xl px-6 py-3 pointer-events-auto">
        <span className="text-sm text-amber-600 font-medium">⚠ يوجد تغييرات غير محفوظة</span>
        <button onClick={onReset} className="text-sm text-gray-400 hover:text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50">
          إلغاء
        </button>
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium px-5 py-2 rounded-xl disabled:opacity-50 transition-colors"
        >
          {saving ? 'جاري الحفظ...' : 'حفظ التغييرات'}
        </button>
      </div>
    </div>
  )
}

// ── ABC Badge ─────────────────────────────────────────────────────────────────

function AbcBadge({ cls }) {
  const colors = { A: 'bg-emerald-100 text-emerald-700', B: 'bg-blue-100 text-blue-700', C: 'bg-gray-100 text-gray-600', X: 'bg-red-50 text-red-500' }
  return (
    <span className={`font-bold text-lg px-3 py-1 rounded-full ${colors[cls] || colors.X}`}>
      {cls || 'X'}
    </span>
  )
}

// ── Section: SOFTECH Base ─────────────────────────────────────────────────────

function SoftechSection({ data }) {
  if (!data) return <p className="text-sm text-gray-400">لا تتوفر بيانات.</p>
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
      <div>
        <ReadRow label="كود SOFTECH"      value={data.softech_id} mono />
        <ReadRow label="الاسم (EN)"        value={data.name} />
        <ReadRow label="الاسم العلمي"      value={data.name_scientific} />
        <ReadRow label="الباركود"          value={data.barcode} mono />
        <ReadRow label="الفئة"             value={data.category_name} />
        <ReadRow label="سعر العبوة"        value={data.pack_price ? `${fmt(data.pack_price)} ج.م` : null} />
        <ReadRow label="سعر الوحدة"        value={data.unit_price ? `${fmt(data.unit_price)} ج.م` : null} />
        <ReadRow label="سعر الشراء"        value={data.cost_price ? `${fmt(data.cost_price)} ج.م` : null} />
        <ReadRow label="التصنيف العلاجي"  value={data.effect_name} />
        <ReadRow label="التصنيف 2"         value={data.effect_name2} />
      </div>
      <div>
        <ReadRow label="الشكل الصيدلي"    value={data.shape_name_ar || data.shape_name} />
        <ReadRow label="العائلة"           value={data.family_name_ar || data.family_name} />
        <ReadRow label="المورد"            value={data.supplier_name} />
        <ReadRow label="كود المورد"        value={data.supplier_code} mono />
        <ReadRow label="المنتج"            value={data.producer_name} />
        <ReadRow label="بلد المنشأ"        value={data.origin_name_ar || data.origin_name} />
        <ReadRow label="المواد الفعالة"    value={data.active_ingredients} />
        <ReadRow label="نوع الدواء"        value={data.medicine_type_name_ar || data.medicine_type_name} />
        <ReadRow label="وحدة التعبئة"      value={data.unit_name} />
        <ReadRow label="كمية العبوة"       value={data.pack_qty} />
        <ReadRow label="نوع التأمين"       value={data.insurance_type} />
        <ReadRow label="آخر مزامنة"        value={data.last_synced ? new Date(data.last_synced).toLocaleDateString('en-US') : null} />
      </div>
      {(data.is_fast_moving || data.requires_fridge || data.has_points) && (
        <div className="md:col-span-2 flex gap-2 mt-2 flex-wrap">
          {data.is_fast_moving  && <span className="bg-sky-100 text-sky-700 text-xs px-2 py-1 rounded-full border border-sky-200">سريع التداول FMI</span>}
          {data.requires_fridge && <span className="bg-cyan-100 text-cyan-700 text-xs px-2 py-1 rounded-full border border-cyan-200">❄ يُحفظ في الثلاجة</span>}
          {data.has_points      && <span className="bg-amber-100 text-amber-700 text-xs px-2 py-1 rounded-full border border-amber-200">✦ نظام النقاط</span>}
        </div>
      )}
    </div>
  )
}

// ── Section: Enrichment ───────────────────────────────────────────────────────

const ENRICHMENT_GROUPS = [
  { title: 'الهوية والتصنيف', fields: ['name_ar', 'brand_name', 'manufacturer_ar', 'manufacturer_en', 'country_ar', 'country_en', 'atc_code', 'rx_otc'] },
  { title: 'الشكل والجرعة',  fields: ['dosage_form_ar', 'dosage_form_en', 'strength', 'volume', 'pack_size_label', 'age_range', 'pregnancy_category'] },
  { title: 'الاستخدامات السريرية', fields: ['indication_ar', 'indication_en', 'contraindication_ar', 'warning_ar', 'side_effects_ar', 'side_effects_en', 'drug_interactions_ar'] },
  { title: 'التخزين والاستخدام', fields: ['storage_condition', 'administration_route_ar', 'dosage_ar', 'frequency_ar', 'duration_ar'] },
  { title: 'SEO والكلمات المفتاحية', fields: ['seo_desc_ar', 'seo_desc_en', 'medical_keywords_ar', 'medical_keywords_en'] },
]

const TEXT_FIELDS = new Set(['indication_ar', 'indication_en', 'contraindication_ar', 'warning_ar', 'side_effects_ar', 'side_effects_en', 'drug_interactions_ar', 'storage_condition', 'administration_route_ar', 'dosage_ar', 'frequency_ar', 'duration_ar', 'seo_desc_ar', 'seo_desc_en', 'medical_keywords_ar', 'medical_keywords_en', 'age_range'])

function EnrichmentSection({ data, softech_id }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState(null)
  const [dirty, setDirty] = useState(false)

  const d = data?.enrichment
  const current = form || d || {}

  const set = useCallback((key, val) => {
    setForm(prev => ({ ...(prev || d || {}), [key]: val }))
    setDirty(true)
  }, [d])

  const mutation = useMutation({
    mutationFn: () => enrichmentApi.patch(d.id, Object.fromEntries(
      Object.entries(form || {}).filter(([k]) => k !== 'id' && k !== 'completeness_score' && k !== 'is_published' && k !== 'field_labels')
    )),
    onSuccess: () => {
      setDirty(false); setForm(null)
      qc.invalidateQueries(['item-intel', softech_id])
      toast.success('تم الحفظ', 'تم تحديث بيانات الإثراء')
    },
    onError: (e) => toast.error('تعذّر الحفظ', errMsg(e)),
  })

  if (!d) return <p className="text-sm text-gray-400">لا يوجد سجل إثراء لهذا المنتج.</p>

  return (
    <>
      {/* Score */}
      <div className="flex items-center gap-4 mb-5 p-4 bg-gray-50 rounded-xl">
        <div className="flex-1">
          <p className="text-xs text-gray-500 mb-1">نسبة اكتمال البيانات</p>
          <div className="h-3 bg-gray-200 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${d.completeness_score >= 70 ? 'bg-emerald-500' : d.completeness_score >= 40 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${d.completeness_score || 0}%` }}
            />
          </div>
        </div>
        <span className="text-2xl font-bold text-gray-700">{Math.round(d.completeness_score || 0)}%</span>
        <span className={`text-xs px-2 py-1 rounded-full ${d.is_published ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
          {d.is_published ? '✓ منشور' : 'غير منشور'}
        </span>
      </div>

      {ENRICHMENT_GROUPS.map(group => (
        <div key={group.title} className="mb-6">
          <h4 className="text-sm font-bold text-gray-700 mb-3 pb-1 border-b border-gray-100">{group.title}</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {group.fields.map(field => {
              const label = d.field_labels?.[field] || field
              const val   = current[field] || ''
              const isText = TEXT_FIELDS.has(field)
              return (
                <FieldRow key={field} label={label}>
                  {field === 'rx_otc' ? (
                    <select value={val} onChange={e => set(field, e.target.value)} className={inputCls}>
                      <option value="">— اختر —</option>
                      <option value="rx">يحتاج وصفة (Rx)</option>
                      <option value="otc">بدون وصفة (OTC)</option>
                      <option value="cd">مخدرات (CD)</option>
                    </select>
                  ) : isText ? (
                    <textarea value={val} onChange={e => set(field, e.target.value)} className={`${textareaCls} sm:col-span-2`} rows={2} />
                  ) : (
                    <input type="text" value={val} onChange={e => set(field, e.target.value)} className={inputCls} />
                  )}
                </FieldRow>
              )
            })}
          </div>
        </div>
      ))}

      <SaveBar
        dirty={dirty}
        saving={mutation.isPending}
        onSave={() => mutation.mutate()}
        onReset={() => { setForm(null); setDirty(false) }}
      />
    </>
  )
}

// ── Section: Content & Attributes ─────────────────────────────────────────────

function ContentSection({ data, softech_id }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [cForm, setCForm] = useState(null)
  const [aForm, setAForm] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const c = data?.content || {}
  const a = data?.attributes || {}
  const cc = cForm || c
  const aa = aForm || a

  const setC = (k, v) => { setCForm(p => ({ ...(p || c), [k]: v })); setDirty(true) }
  const setA = (k, v) => { setAForm(p => ({ ...(p || a), [k]: v })); setDirty(true) }

  const handleSave = async () => {
    setSaving(true)
    try {
      if (cForm) await productsApi.patchContent(softech_id, cForm)
      if (aForm) await productsApi.patchAttributes(softech_id, aForm)
      setDirty(false)
      setCForm(null)
      setAForm(null)
      qc.invalidateQueries(['item-intel', softech_id])
      toast.success('تم الحفظ', 'تم تحديث المحتوى والخصائص')
    } catch (e) {
      toast.error('تعذّر الحفظ', errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
        {/* Content fields */}
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3">المحتوى التسويقي</h4>
          <FieldRow label="الاسم العربي (عرض)">
            <input type="text" value={cc.display_name_ar || ''} onChange={e => setC('display_name_ar', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="الاسم الإنجليزي (عرض)">
            <input type="text" value={cc.display_name_en || ''} onChange={e => setC('display_name_en', e.target.value)} className={inputCls} dir="ltr" />
          </FieldRow>
          <FieldRow label="وصف مختصر">
            <textarea value={cc.short_description || ''} onChange={e => setC('short_description', e.target.value)} className={textareaCls} rows={2} />
          </FieldRow>
          <FieldRow label="وصف تفصيلي">
            <textarea value={cc.long_description || ''} onChange={e => setC('long_description', e.target.value)} className={textareaCls} rows={4} />
          </FieldRow>
          <FieldRow label="الفوائد">
            <textarea value={cc.benefits || ''} onChange={e => setC('benefits', e.target.value)} className={textareaCls} rows={3} />
          </FieldRow>
          <FieldRow label="تعليمات الاستخدام">
            <textarea value={cc.instructions || ''} onChange={e => setC('instructions', e.target.value)} className={textareaCls} rows={3} />
          </FieldRow>
          <FieldRow label="طريقة الاستخدام">
            <textarea value={cc.usage || ''} onChange={e => setC('usage', e.target.value)} className={textareaCls} rows={2} />
          </FieldRow>
          <FieldRow label="شروط التخزين">
            <textarea value={cc.storage || ''} onChange={e => setC('storage', e.target.value)} className={textareaCls} rows={2} />
          </FieldRow>
          <FieldRow label="موانع الاستخدام">
            <textarea value={cc.contraindications || ''} onChange={e => setC('contraindications', e.target.value)} className={textareaCls} rows={2} />
          </FieldRow>
          <FieldRow label="الكلمات المفتاحية">
            <input type="text" value={cc.keywords || ''} onChange={e => setC('keywords', e.target.value)} className={inputCls} placeholder="كوميد، باراسيتامول، مسكن..." />
          </FieldRow>
        </div>

        {/* Attributes */}
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3">الخصائص التقنية</h4>
          <FieldRow label="التركيز / القوة">
            <input type="text" value={aa.strength || ''} onChange={e => setA('strength', e.target.value)} className={inputCls} placeholder="500mg، 10mg/5ml" />
          </FieldRow>
          <FieldRow label="التركيز السائل">
            <input type="text" value={aa.concentration || ''} onChange={e => setA('concentration', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="النكهة">
            <input type="text" value={aa.flavor || ''} onChange={e => setA('flavor', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="اللون">
            <input type="text" value={aa.color || ''} onChange={e => setA('color', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="الحجم / الوزن">
            <input type="text" value={aa.size || ''} onChange={e => setA('size', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="مواصفات العبوة">
            <input type="text" value={aa.pack_size_label || ''} onChange={e => setA('pack_size_label', e.target.value)} className={inputCls} placeholder="10 أقراص × 3 شرائط" />
          </FieldRow>
          <FieldRow label="العدد في العبوة">
            <input type="number" value={aa.count_per_pack || ''} onChange={e => setA('count_per_pack', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="درجة حرارة التخزين">
            <select value={aa.temperature_storage || ''} onChange={e => setA('temperature_storage', e.target.value)} className={inputCls}>
              <option value="">— اختر —</option>
              <option value="room">حرارة الغرفة</option>
              <option value="cool">بارد (8–15°م)</option>
              <option value="refrigerated">ثلاجة (2–8°م)</option>
              <option value="frozen">مجمد (&lt;-18°م)</option>
            </select>
          </FieldRow>
          <FieldRow label="مدة الصلاحية (شهر)">
            <input type="number" value={aa.shelf_life_months || ''} onChange={e => setA('shelf_life_months', e.target.value)} className={inputCls} />
          </FieldRow>
          <FieldRow label="وصفة طبية">
            <select value={aa.prescription_required == null ? '' : String(aa.prescription_required)} onChange={e => setA('prescription_required', e.target.value === '' ? null : e.target.value === 'true')} className={inputCls}>
              <option value="">— غير محدد —</option>
              <option value="true">مطلوبة (Rx)</option>
              <option value="false">غير مطلوبة (OTC)</option>
            </select>
          </FieldRow>
          <FieldRow label="تحذيرات خاصة">
            <textarea value={aa.special_warnings || ''} onChange={e => setA('special_warnings', e.target.value)} className={textareaCls} rows={3} />
          </FieldRow>
        </div>
      </div>

      <SaveBar
        dirty={dirty}
        saving={saving}
        onSave={handleSave}
        onReset={() => { setCForm(null); setAForm(null); setDirty(false) }}
      />
    </>
  )
}

// ── Section: Clinical / Chronic ───────────────────────────────────────────────

function ClinicalSection({ data, softech_id }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [searchQ, setSearchQ]   = useState('')
  const [searchRes, setSearchRes] = useState([])
  const [searching, setSearching] = useState(false)

  const ingredients = data?.ingredients || []
  const tag         = data?.chronic_tag || {}

  const searchTimer = useRef(null)
  const handleSearch = val => {
    setSearchQ(val)
    clearTimeout(searchTimer.current)
    if (val.trim().length < 2) { setSearchRes([]); return }
    searchTimer.current = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await chronicApi.listIngredients({ q: val, page_size: 10 })
        setSearchRes(Array.isArray(r.data) ? r.data : r.data?.results || [])
      } catch {
        setSearchRes([])
      } finally { setSearching(false) }
    }, 300)
  }

  const addMut = useMutation({
    mutationFn: (ai) => itemsApi.addIngredient(softech_id, {
      active_ingredient_id: ai.id,
      concentration: '',
      is_primary: ingredients.length === 0,
    }),
    onSuccess: () => {
      qc.invalidateQueries(['item-intel', softech_id]); setSearchQ(''); setSearchRes([])
      toast.success('تمت الإضافة', 'تم ربط المادة الفعّالة بالصنف')
    },
    onError: (e) => toast.error('تعذّرت الإضافة', errMsg(e, 'فشل ربط المادة الفعّالة')),
  })

  const delMut = useMutation({
    mutationFn: (map_id) => itemsApi.deleteIngredient(softech_id, map_id),
    onSuccess: () => {
      qc.invalidateQueries(['item-intel', softech_id])
      toast.success('تم الحذف', 'تم إزالة المادة الفعّالة')
    },
    onError: (e) => toast.error('تعذّر الحذف', errMsg(e)),
  })

  const CHRONIC_COLORS = {
    diabetes: 'bg-blue-100 text-blue-700',
    hypertension: 'bg-red-100 text-red-700',
    cardiovascular: 'bg-rose-100 text-rose-700',
    thyroid: 'bg-purple-100 text-purple-700',
    asthma: 'bg-sky-100 text-sky-700',
    cholesterol: 'bg-amber-100 text-amber-700',
    depression: 'bg-indigo-100 text-indigo-700',
  }

  return (
    <div className="space-y-6">
      {/* Chronic tag */}
      <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
        <span className="text-2xl">🏥</span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-gray-700">تصنيف مزمن</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {tag.exists
              ? `مصنّف كمزمن: ${tag.category_label || '—'}`
              : 'لم يُصنَّف كدواء مزمن بعد'}
          </p>
        </div>
        {tag.exists && (
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${tag.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
            {tag.is_active ? '✓ نشط' : 'معطّل'}
          </span>
        )}
      </div>

      {/* Active ingredient maps */}
      <div>
        <h4 className="text-sm font-bold text-gray-700 mb-3">المواد الفعّالة المرتبطة</h4>

        {ingredients.length === 0 ? (
          <p className="text-sm text-gray-400 mb-3">لا توجد مواد فعّالة مرتبطة بهذا المنتج.</p>
        ) : (
          <div className="space-y-2 mb-4">
            {ingredients.map(ing => (
              <div key={ing.map_id}
                className="flex items-center gap-3 bg-white border border-gray-200 rounded-xl px-4 py-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-gray-800">{ing.name_ar || ing.name}</span>
                    {ing.is_primary && (
                      <span className="text-xs bg-brand-100 text-brand-700 px-1.5 py-0.5 rounded">رئيسية</span>
                    )}
                    {ing.is_chronic && (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${CHRONIC_COLORS[ing.chronic_class] || 'bg-purple-100 text-purple-700'}`}>
                        {ing.chronic_class_display || 'مزمن'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    {ing.atc_code && <span className="text-xs font-mono text-gray-400">{ing.atc_code}</span>}
                    {ing.concentration && <span className="text-xs text-gray-500">{ing.concentration}</span>}
                  </div>
                </div>
                <button
                  onClick={() => delMut.mutate(ing.map_id)}
                  disabled={delMut.isPending}
                  className="text-red-400 hover:text-red-600 text-xs px-2 py-1 rounded hover:bg-red-50 transition-colors"
                >
                  حذف
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Add ingredient search */}
        <div className="relative">
          <input
            type="text"
            value={searchQ}
            onChange={e => handleSearch(e.target.value)}
            placeholder="ابحث عن مادة فعّالة لإضافتها..."
            className={inputCls}
          />
          {searching && <span className="absolute left-3 top-2 text-xs text-gray-400">...</span>}
          {searchRes.length > 0 && (
            <div className="absolute z-20 top-full right-0 left-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg max-h-48 overflow-y-auto">
              {searchRes.map(ai => (
                <button
                  key={ai.id}
                  onClick={() => addMut.mutate(ai)}
                  disabled={addMut.isPending || ingredients.some(i => i.ingredient_id === ai.id)}
                  className="w-full text-right px-4 py-2.5 hover:bg-brand-50 text-sm border-b border-gray-50 last:border-0 disabled:opacity-50 transition-colors"
                >
                  <span className="font-semibold text-gray-800">{ai.name_ar || ai.name}</span>
                  {ai.atc_code && <span className="text-xs font-mono text-gray-400 mr-2">{ai.atc_code}</span>}
                  {ai.is_chronic && (
                    <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded mr-1">مزمن</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Section: Purchasing Intelligence ─────────────────────────────────────────

function PurchasingSection({ data }) {
  const net     = data?.demand_network
  const branches = data?.demand_branches || []

  if (!net) return (
    <div className="text-center py-8 text-gray-400">
      <p className="text-sm">لم يُشغَّل محرك الطلب بعد لهذا المنتج.</p>
    </div>
  )

  const statCard = (label, value, sub, color = 'gray') => {
    const colors = { gray: 'bg-gray-50', blue: 'bg-blue-50', amber: 'bg-amber-50', red: 'bg-red-50', green: 'bg-emerald-50' }
    return (
      <div className={`${colors[color]} rounded-xl p-4`}>
        <p className="text-xs text-gray-500 mb-1">{label}</p>
        <p className="text-xl font-bold text-gray-800">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Network KPIs */}
      <div>
        <h4 className="text-sm font-bold text-gray-700 mb-3">أداء الشبكة (آخر تشغيل: {net.calc_date || '—'})</h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <div className="bg-white border-2 border-brand-200 rounded-xl p-4 flex items-center gap-3">
            <AbcBadge cls={net.abc_class} />
            <div>
              <p className="text-xs text-gray-500">تصنيف ABC</p>
              <p className="text-xs text-gray-400">شبكة كاملة</p>
            </div>
          </div>
          {statCard('متوسط مبيعات شهري (وحدة)', fmt(net.total_monthly_avg, 1), `${net.branches_with_sales} فرع نشط`, 'blue')}
          {statCard('القيمة الشهرية', `${fmtK(net.total_monthly_value)} ج`, `إيراد سنوي: ${fmtK(net.total_net_sales_revenue)} ج`, 'green')}
          {statCard('الفجوة الإجمالية', fmt(net.total_gap, 1), `${net.branches_with_gap} فرع محتاج`, net.total_gap > 0 ? 'amber' : 'gray')}
          {statCard('مبيعات 30 يوم', fmt(net.total_qty_30d, 0), `90 يوم: ${fmt(net.total_qty_90d, 0)}`)}
          {statCard('مبيعات 365 يوم', fmtK(net.total_qty_365d))}
          {statCard('إيراد ضائع (30 يوم)', `${fmtK(net.total_lost_revenue_30d)} ج`, `كمية ضائعة: ${fmt(net.total_lost_qty_30d, 0)}`, net.total_lost_revenue_30d > 0 ? 'red' : 'gray')}
          {statCard('معدل توفر الشبكة', `${Math.round(net.network_availability_rate_30d)}%`, '30 يوم', net.network_availability_rate_30d >= 90 ? 'green' : net.network_availability_rate_30d >= 70 ? 'amber' : 'red')}
        </div>
      </div>

      {/* Per-branch breakdown */}
      {branches.length > 0 && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3">تفصيل الفروع</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead className="bg-gray-50">
                <tr>
                  {['الفرع', 'ABC', 'رصيد', 'أمان', 'متوسط شهري', 'فجوة', 'تغطية', 'توفر', 'إيراد ضائع', 'حالة'].map(h => (
                    <th key={h} className="text-right px-3 py-2 text-xs text-gray-500 font-medium border-b border-gray-100 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {branches.map(b => (
                  <tr key={b.branch_id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-3 py-2 text-xs font-medium text-gray-700 whitespace-nowrap">{b.branch_name}</td>
                    <td className="px-3 py-2 text-center">
                      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${b.abc_class === 'A' ? 'bg-emerald-100 text-emerald-700' : b.abc_class === 'B' ? 'bg-blue-100 text-blue-700' : b.abc_class === 'X' ? 'bg-red-50 text-red-500' : 'bg-gray-100 text-gray-600'}`}>{b.abc_class}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-center">{fmt(b.current_stock, 0)}</td>
                    <td className="px-3 py-2 text-xs text-center text-amber-700">{fmt(b.safety_stock, 0)}</td>
                    <td className="px-3 py-2 text-xs text-center">{fmt(b.monthly_avg, 1)}</td>
                    <td className={`px-3 py-2 text-xs text-center font-medium ${b.gap > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{fmt(b.gap, 1)}</td>
                    <td className="px-3 py-2 text-xs text-center">{b.coverage_months != null ? `${fmt(b.coverage_months, 1)} شهر` : '—'}</td>
                    <td className={`px-3 py-2 text-xs text-center ${b.availability_rate_30d >= 90 ? 'text-emerald-600' : b.availability_rate_30d >= 70 ? 'text-amber-600' : 'text-red-600'}`}>{Math.round(b.availability_rate_30d)}%</td>
                    <td className="px-3 py-2 text-xs text-center text-red-600">{b.lost_revenue_30d > 0 ? `${fmtK(b.lost_revenue_30d)} ج` : '—'}</td>
                    <td className="px-3 py-2 text-xs text-center">
                      <span className={`px-2 py-0.5 rounded-full text-xs ${b.stock_status === 'جيد' || b.stock_status === 'مقبول' ? 'bg-emerald-50 text-emerald-700' : b.stock_status === 'منخفض' ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-600'}`}>
                        {b.stock_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Section: Purchase History ─────────────────────────────────────────────────

function PurchaseHistorySection({ data }) {
  const hist = data?.purchase_history
  if (!hist || !hist.suppliers?.length) return (
    <div className="text-center py-8 text-gray-400">
      <p className="text-sm">لا توجد فواتير شراء مؤكدة لهذا المنتج.</p>
    </div>
  )

  const { overall, suppliers } = hist
  return (
    <div className="space-y-6">
      {/* Overall stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-emerald-50 rounded-xl p-4 text-center">
          <p className="text-xs text-gray-500 mb-1">متوسط سعر الشراء</p>
          <p className="text-xl font-bold text-emerald-700">{fmt(overall.avg_price)} ج.م</p>
        </div>
        <div className="bg-blue-50 rounded-xl p-4 text-center">
          <p className="text-xs text-gray-500 mb-1">أدنى سعر شراء</p>
          <p className="text-xl font-bold text-blue-700">{fmt(overall.min_price)} ج.م</p>
        </div>
        <div className="bg-amber-50 rounded-xl p-4 text-center">
          <p className="text-xs text-gray-500 mb-1">أعلى سعر شراء</p>
          <p className="text-xl font-bold text-amber-700">{fmt(overall.max_price)} ج.م</p>
        </div>
      </div>
      <p className="text-xs text-gray-400 -mt-2">من {overall.invoice_count?.toLocaleString()} سطر فاتورة مؤكدة</p>

      {/* Per-supplier breakdown */}
      <div>
        <h4 className="text-sm font-bold text-gray-700 mb-3">تفصيل حسب المورد</h4>
        <div className="space-y-3">
          {suppliers.map((s, i) => (
            <div key={i} className="bg-white border border-gray-100 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <h5 className="text-sm font-bold text-gray-800">{s.name}</h5>
                <span className="text-xs text-gray-400">{s.invoice_count} فاتورة</span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center mb-2">
                <div>
                  <p className="text-xs text-gray-400">متوسط</p>
                  <p className="text-sm font-bold text-gray-700">{fmt(s.avg_price)} ج</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">أدنى</p>
                  <p className="text-sm font-bold text-blue-600">{fmt(s.min_price)} ج</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">أعلى</p>
                  <p className="text-sm font-bold text-amber-600">{fmt(s.max_price)} ج</p>
                </div>
              </div>
              {s.vendor_item_codes?.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-gray-400">كود المورد:</span>
                  {s.vendor_item_codes.map(code => (
                    <span key={code} className="text-xs font-mono bg-gray-100 text-gray-700 px-2 py-0.5 rounded">{code}</span>
                  ))}
                </div>
              )}
              {s.last_invoice_date && (
                <p className="text-xs text-gray-400 mt-1">آخر فاتورة: {s.last_invoice_date}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Section: Recommendations (FBT) ───────────────────────────────────────────

function RecommendationsSection({ data }) {
  const navigate = useNavigate()
  const fbt = data?.fbt || []

  if (!fbt.length) return (
    <div className="text-center py-8 text-gray-400">
      <p className="text-sm">لا توجد بيانات "يُشترى معاً" لهذا المنتج.</p>
      <p className="text-xs mt-1">شغّل محرك التوصيات من صفحة التوصيات لتوليد البيانات.</p>
    </div>
  )

  return (
    <div>
      <div className="space-y-2">
        {fbt.map((pair, i) => (
          <button
            key={i}
            onClick={() => navigate(`/products/${pair.partner_softech_id}`)}
            className="w-full flex items-center gap-4 bg-white hover:bg-brand-50 border border-gray-100 hover:border-brand-200 rounded-xl px-4 py-3 text-right transition-colors"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-gray-800 truncate">{pair.partner_name}</p>
              <p className="text-xs font-mono text-gray-400">{pair.partner_softech_id}</p>
            </div>
            <div className="flex items-center gap-4 text-xs text-gray-500 shrink-0">
              <div className="text-center">
                <p className="font-bold text-brand-600 text-base">{Math.round(pair.confidence * 100)}%</p>
                <p>ثقة</p>
              </div>
              <div className="text-center">
                <p className="font-bold text-gray-700">{pair.lift?.toFixed(1)}×</p>
                <p>رفع</p>
              </div>
              <div className="text-center">
                <p className="font-bold text-gray-700">{pair.co_occurrences?.toLocaleString()}</p>
                <p>تكرار</p>
              </div>
            </div>
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-400 text-center mt-4">
        الثقة = احتمال شراء هذا المنتج عند شراء المنتج الرئيسي | الرفع = قوة الارتباط
      </p>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const SECTIONS = [
  { key: 'softech',    label: 'بيانات SOFTECH',   icon: '🔗' },
  { key: 'enrichment', label: 'الإثراء والبيانات', icon: '🧬' },
  { key: 'content',    label: 'المحتوى والخصائص', icon: '📝' },
  { key: 'clinical',   label: 'المواد الفعّالة',  icon: '💊' },
  { key: 'purchasing', label: 'مؤشرات الطلب',    icon: '📊' },
  { key: 'purchase_history', label: 'تاريخ الشراء', icon: '🧾' },
  { key: 'fbt',        label: 'يُشترى معاً',     icon: '🔀' },
]

export default function ItemIntelPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [activeSection, setActiveSection] = useState('softech')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['item-intel', id],
    queryFn:  () => itemsApi.fullIntel(id).then(r => r.data),
    staleTime: 60_000,
  })

  if (isLoading) return (
    <div className="min-h-screen flex items-center justify-center font-cairo" dir="rtl">
      <div className="text-brand-500 animate-pulse text-lg">جاري تحميل بيانات المنتج...</div>
    </div>
  )

  if (isError || !data) return (
    <div className="min-h-screen flex flex-col items-center justify-center font-cairo gap-4" dir="rtl">
      <div className="text-5xl">❌</div>
      <p className="text-gray-500">المنتج غير موجود</p>
      <button onClick={() => navigate('/products')} className="text-brand-600 hover:underline text-sm">
        العودة للكتالوج
      </button>
    </div>
  )

  const item = data.softech || {}
  const itemName = data.content?.display_name_ar || item.name || id

  return (
    <div className="min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* Breadcrumb */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto flex items-center gap-2 text-sm text-gray-400">
          <button onClick={() => navigate('/products')} className="hover:text-brand-600">الكتالوج</button>
          <span>›</span>
          <button onClick={() => navigate(`/products/${id}`)} className="hover:text-brand-600 truncate max-w-xs">{itemName}</button>
          <span>›</span>
          <span className="text-gray-700 font-medium">ملف الصنف الشامل</span>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex gap-6">

          {/* Sidebar nav */}
          <aside className="w-52 shrink-0 space-y-1 sticky top-20 self-start">
            <div className="bg-white rounded-2xl border border-gray-100 p-3 space-y-1">
              {SECTIONS.map(s => (
                <button
                  key={s.key}
                  onClick={() => setActiveSection(s.key)}
                  className={`w-full flex items-center gap-2.5 text-right text-sm px-3 py-2.5 rounded-xl transition-all
                    ${activeSection === s.key
                      ? 'bg-brand-600 text-white font-medium shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100'}`}
                >
                  <span className="text-base">{s.icon}</span>
                  <span className="flex-1 truncate">{s.label}</span>
                </button>
              ))}
            </div>

            {/* Quick meta */}
            <div className="bg-white rounded-2xl border border-gray-100 p-4 space-y-2">
              <p className="text-xs font-semibold text-gray-500 mb-2">معلومات سريعة</p>
              <div className="flex items-center gap-2">
                <AbcBadge cls={data.demand_network?.abc_class} />
                <span className="text-xs text-gray-500">ABC</span>
              </div>
              {data.enrichment?.completeness_score != null && (
                <div>
                  <p className="text-xs text-gray-400">اكتمال البيانات</p>
                  <div className="h-2 bg-gray-100 rounded-full mt-1">
                    <div
                      className={`h-full rounded-full ${data.enrichment.completeness_score >= 70 ? 'bg-emerald-400' : data.enrichment.completeness_score >= 40 ? 'bg-amber-400' : 'bg-red-400'}`}
                      style={{ width: `${data.enrichment.completeness_score}%` }}
                    />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 text-left">{Math.round(data.enrichment.completeness_score)}%</p>
                </div>
              )}
            </div>

            {/* Links */}
            <div className="bg-white rounded-2xl border border-gray-100 p-3 space-y-1">
              <Link to={`/products/${id}`} className="flex items-center gap-2 text-xs text-gray-500 hover:text-brand-600 px-3 py-2 rounded-lg hover:bg-gray-50">
                🔍 صفحة المنتج
              </Link>
              <Link to={`/products/${id}/admin`} className="flex items-center gap-2 text-xs text-gray-500 hover:text-brand-600 px-3 py-2 rounded-lg hover:bg-gray-50">
                🖼 إدارة الصور
              </Link>
            </div>
          </aside>

          {/* Content area */}
          <div className="flex-1 min-w-0 space-y-6">
            {activeSection === 'softech' && (
              <SectionCard title="بيانات SOFTECH (للقراءة فقط)" icon="🔗"
                actions={<span className="text-xs text-gray-400">مصدر: SOFTECH ERP — لا يمكن التعديل</span>}>
                <SoftechSection data={item} />
              </SectionCard>
            )}

            {activeSection === 'enrichment' && (
              <SectionCard title="الإثراء والبيانات السريرية" icon="🧬"
                actions={<span className="text-xs text-emerald-600">✎ قابل للتعديل</span>}>
                <EnrichmentSection data={data} softech_id={id} />
              </SectionCard>
            )}

            {activeSection === 'content' && (
              <SectionCard title="المحتوى التسويقي والخصائص التقنية" icon="📝"
                actions={<span className="text-xs text-emerald-600">✎ قابل للتعديل</span>}>
                <ContentSection data={data} softech_id={id} />
              </SectionCard>
            )}

            {activeSection === 'clinical' && (
              <SectionCard title="المواد الفعّالة والتصنيف المزمن" icon="💊"
                actions={<span className="text-xs text-emerald-600">✎ قابل للتعديل</span>}>
                <ClinicalSection data={data} softech_id={id} />
              </SectionCard>
            )}

            {activeSection === 'purchasing' && (
              <SectionCard title="مؤشرات الطلب وتصنيف ABC" icon="📊"
                actions={<span className="text-xs text-gray-400">للقراءة فقط — محرك الطلب</span>}>
                <PurchasingSection data={data} />
              </SectionCard>
            )}

            {activeSection === 'purchase_history' && (
              <SectionCard title="تاريخ الشراء من الموردين" icon="🧾"
                actions={<span className="text-xs text-gray-400">للقراءة فقط — فواتير الموردين</span>}>
                <PurchaseHistorySection data={data} />
              </SectionCard>
            )}

            {activeSection === 'fbt' && (
              <SectionCard title="المنتجات التي تُشترى معاً" icon="🔀"
                actions={<span className="text-xs text-gray-400">للقراءة فقط — محرك التوصيات</span>}>
                <RecommendationsSection data={data} />
              </SectionCard>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
