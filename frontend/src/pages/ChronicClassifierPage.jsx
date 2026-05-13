/**
 * ChronicClassifierPage.jsx
 *
 * Three tabs:
 *  1. Item Classifier  — browse catalog items, classify each as chronic by
 *                        linking to an ActiveIngredient
 *  2. Ingredients      — manage the ActiveIngredient master table + tags + protocols
 *  3. Task Generator   — generate follow-up tasks based on purchase history
 *
 * NOTE: stktransm.phcode = customer personcode (e.g. 04HD1006). It is NOT a
 *       drug code. Classification is done per-item by the pharmacy team.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { chronicApi } from '../api/client'

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const CHRONIC_CLASSES = [
  { value: 'diabetes',          label: 'السكري' },
  { value: 'hypertension',      label: 'ضغط الدم' },
  { value: 'cardiovascular',    label: 'أمراض القلب والأوعية' },
  { value: 'thyroid',           label: 'الغدة الدرقية' },
  { value: 'asthma',            label: 'الربو' },
  { value: 'anticoagulant',     label: 'مضادات التخثر' },
  { value: 'epilepsy',          label: 'الصرع' },
  { value: 'parkinson',         label: 'باركنسون' },
  { value: 'depression',        label: 'الاكتئاب' },
  { value: 'immunosuppressant', label: 'مثبطات المناعة' },
  { value: 'osteoporosis',      label: 'هشاشة العظام' },
  { value: 'renal',             label: 'أمراض الكلى' },
  { value: 'oncology',          label: 'الأورام' },
  { value: 'cholesterol',       label: 'الكوليسترول' },
  { value: 'gerd',              label: 'ارتجاع المريء' },
  { value: 'anemia',            label: 'فقر الدم' },
  { value: 'other_chronic',     label: 'مزمن - أخرى' },
]

const CHRONIC_CLASS_COLORS = {
  diabetes:          'bg-blue-100 text-blue-800',
  hypertension:      'bg-red-100 text-red-800',
  cardiovascular:    'bg-pink-100 text-pink-800',
  thyroid:           'bg-purple-100 text-purple-800',
  asthma:            'bg-sky-100 text-sky-800',
  anticoagulant:     'bg-orange-100 text-orange-800',
  epilepsy:          'bg-yellow-100 text-yellow-800',
  parkinson:         'bg-lime-100 text-lime-800',
  depression:        'bg-indigo-100 text-indigo-800',
  immunosuppressant: 'bg-violet-100 text-violet-800',
  osteoporosis:      'bg-amber-100 text-amber-800',
  renal:             'bg-teal-100 text-teal-800',
  oncology:          'bg-rose-100 text-rose-800',
  cholesterol:       'bg-green-100 text-green-800',
  gerd:              'bg-cyan-100 text-cyan-800',
  anemia:            'bg-red-50 text-red-700',
  other_chronic:     'bg-gray-100 text-gray-700',
}

// ─────────────────────────────────────────────────────────────────────────────
// Small helpers
// ─────────────────────────────────────────────────────────────────────────────

function ChronicBadge({ cls, label }) {
  if (!cls) return null
  const colors = CHRONIC_CLASS_COLORS[cls] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colors}`}>
      {label || cls}
    </span>
  )
}

function TagBadge({ tag }) {
  if (!tag) return null
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ background: tag.color + '22', color: tag.color, border: `1px solid ${tag.color}44` }}
    >
      {tag.name_ar || tag.name}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 1 — Item Classifier
// ─────────────────────────────────────────────────────────────────────────────

function ItemClassifier() {
  const qc = useQueryClient()
  const [page, setPage]           = useState(1)
  const [search, setSearch]       = useState('')
  const [statusFilter, setStatus] = useState('all')
  const [selected, setSelected]   = useState(null)
  const [panel, setPanel]         = useState(false)

  // Classify form state
  const [mode, setMode]                 = useState('existing') // 'existing' | 'new'
  const [existingIngId, setExistingId]  = useState('')
  const [newName, setNewName]           = useState('')
  const [newNameAr, setNewNameAr]       = useState('')
  const [newAtc, setNewAtc]             = useState('')
  const [isChronic, setIsChronic]       = useState(true)
  const [chronicClass, setChronicClass] = useState('')
  const [concentration, setConc]        = useState('')
  const [selectedTagIds, setTagIds]     = useState([])

  const params = {
    page,
    page_size: 30,
    ...(search && { q: search }),
    ...(statusFilter !== 'all' && { status: statusFilter }),
  }

  const { data: summary } = useQuery({
    queryKey: ['chronicItemSummary'],
    queryFn:  () => chronicApi.getItemSummary().then(r => r.data),
    staleTime: 60_000,
  })

  const { data, isFetching } = useQuery({
    queryKey: ['chronicItems', params],
    queryFn:  () => chronicApi.listItems(params).then(r => r.data),
    keepPreviousData: true,
  })

  const { data: ingredients } = useQuery({
    queryKey: ['chronicIngredients', 'all'],
    queryFn:  () => chronicApi.listIngredients({ page_size: 200 }).then(r => r.data.results || r.data),
  })

  const { data: tags } = useQuery({
    queryKey: ['chronicTags'],
    queryFn:  () => chronicApi.listTags({ active_only: true, page_size: 200 }).then(r => r.data.results || r.data),
  })

  const classifyMut = useMutation({
    mutationFn: (payload) => chronicApi.classifyItem(selected.id, payload),
    onSuccess: (res) => {
      qc.invalidateQueries(['chronicItems'])
      qc.invalidateQueries(['chronicItemSummary'])
      // update selected with fresh data
      setSelected(res.data)
      setPanel(false)
      resetForm()
    },
  })

  const unclassifyMut = useMutation({
    mutationFn: ({ itemId, ingredientId }) =>
      chronicApi.unclassifyItem(itemId, ingredientId ? { ingredient_id: ingredientId } : {}),
    onSuccess: () => {
      qc.invalidateQueries(['chronicItems'])
      qc.invalidateQueries(['chronicItemSummary'])
      setSelected(null)
      setPanel(false)
    },
  })

  const resetForm = () => {
    setMode('existing')
    setExistingId('')
    setNewName('')
    setNewNameAr('')
    setNewAtc('')
    setIsChronic(true)
    setChronicClass('')
    setConc('')
    setTagIds([])
  }

  const openPanel = (item) => {
    setSelected(item)
    resetForm()
    if (item.ingredient) {
      setMode('existing')
      setExistingId(String(item.ingredient.ingredient_id))
      setIsChronic(item.ingredient.is_chronic)
      setChronicClass(item.ingredient.chronic_class || '')
      setConc(item.ingredient.concentration || '')
    }
    setPanel(true)
  }

  const handleClassify = () => {
    const payload = {
      is_chronic:    isChronic,
      chronic_class: chronicClass,
      concentration,
      tag_ids:       selectedTagIds,
    }
    if (mode === 'existing') {
      payload.active_ingredient_id = parseInt(existingIngId, 10)
    } else {
      payload.ingredient_name     = newName.trim()
      payload.ingredient_name_ar  = newNameAr.trim()
      payload.ingredient_atc_code = newAtc.trim()
    }
    classifyMut.mutate(payload)
  }

  const toggleTag = (id) =>
    setTagIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const items    = data?.results || []
  const count    = data?.count   || 0
  const totalPgs = Math.ceil(count / 30)

  return (
    <div className="flex gap-4 h-full overflow-hidden">

      {/* ── Left: table ─────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col gap-3 overflow-hidden">

        {/* Summary cards */}
        {summary && (
          <div className="grid grid-cols-4 gap-3 flex-shrink-0">
            {[
              { label: 'إجمالي الأصناف', value: summary.total_items,  color: 'blue'   },
              { label: 'مصنَّف',         value: summary.classified,   color: 'green'  },
              { label: 'غير مصنَّف',    value: summary.unclassified, color: 'orange' },
              { label: 'مزمن',           value: summary.chronic,      color: 'red',
                sub: (summary.classification_pct || 0) + '% مصنَّف' },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-2xl font-bold text-gray-800">{(c.value || 0).toLocaleString()}</div>
                <div className="text-xs text-gray-500 mt-1">{c.label}</div>
                {c.sub && <div className="text-xs text-gray-400 mt-0.5">{c.sub}</div>}
              </div>
            ))}
          </div>
        )}

        {/* Filters */}
        <div className="bg-white rounded-xl border border-gray-200 p-3 flex gap-3 items-center flex-shrink-0">
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            placeholder="بحث باسم الصنف أو كود SOFTECH أو الباركود..."
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
          <select
            value={statusFilter}
            onChange={e => { setStatus(e.target.value); setPage(1) }}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          >
            <option value="all">جميع الأصناف</option>
            <option value="unclassified">غير مصنَّف</option>
            <option value="classified">مصنَّف</option>
            <option value="chronic">مزمن</option>
            <option value="non_chronic">مصنَّف / غير مزمن</option>
          </select>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-auto flex-1">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
              <tr>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">اسم الصنف</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600 w-24">كود</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">المادة الفعّالة</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600 w-36">التصنيف</th>
                <th className="w-28 px-3 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isFetching && !items.length ? (
                <tr><td colSpan={5} className="text-center py-10 text-gray-400">جارٍ التحميل...</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={5} className="text-center py-10 text-gray-400">لا توجد أصناف مطابقة</td></tr>
              ) : items.map(item => (
                <tr
                  key={item.id}
                  className={`hover:bg-gray-50 transition-colors cursor-pointer ${
                    selected?.id === item.id && panel ? 'bg-brand-50 border-r-2 border-brand-500' : ''
                  }`}
                  onClick={() => openPanel(item)}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900">{item.name}</div>
                    {item.name_scientific && (
                      <div className="text-xs text-gray-400 italic">{item.name_scientific}</div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500 font-mono">{item.softech_id}</td>
                  <td className="px-3 py-3">
                    {item.ingredient ? (
                      <div>
                        <div className="text-xs font-medium text-gray-800">
                          {item.ingredient.name_ar || item.ingredient.name}
                        </div>
                        {item.ingredient.concentration && (
                          <div className="text-xs text-gray-400">{item.ingredient.concentration}</div>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {item.is_chronic ? (
                      <ChronicBadge
                        cls={item.ingredient?.chronic_class}
                        label={CHRONIC_CLASSES.find(c => c.value === item.ingredient?.chronic_class)?.label || 'مزمن'}
                      />
                    ) : item.is_classified ? (
                      <span className="text-xs text-gray-400">مصنَّف / غير مزمن</span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">
                        غير مصنَّف
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-left" onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => openPanel(item)}
                      className="text-xs text-brand-600 hover:text-brand-800 font-medium ml-2"
                    >
                      {item.is_classified ? 'تعديل' : 'تصنيف'}
                    </button>
                    {item.is_classified && (
                      <button
                        onClick={() => {
                          if (window.confirm('إزالة تصنيف هذا الصنف؟'))
                            unclassifyMut.mutate({ itemId: item.id })
                        }}
                        className="text-xs text-red-400 hover:text-red-600"
                      >
                        حذف
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPgs > 1 && (
          <div className="flex items-center justify-between flex-shrink-0">
            <span className="text-sm text-gray-500">{count.toLocaleString()} صنف</span>
            <div className="flex gap-2">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >السابق</button>
              <span className="px-3 py-1.5 text-sm text-gray-600">{page} / {totalPgs}</span>
              <button
                disabled={page === totalPgs}
                onClick={() => setPage(p => p + 1)}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >التالي</button>
            </div>
          </div>
        )}
      </div>

      {/* ── Right: classify panel ──────────────────────────────────────── */}
      {panel && selected && (
        <div className="w-80 flex-shrink-0 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          {/* Panel header */}
          <div className="px-4 py-3 border-b border-gray-100 flex items-start justify-between">
            <div className="min-w-0">
              <div className="font-semibold text-gray-900 text-sm truncate">{selected.name}</div>
              <div className="text-xs text-gray-400 mt-0.5 font-mono">{selected.softech_id}</div>
            </div>
            <button
              onClick={() => { setPanel(false); setSelected(null) }}
              className="text-gray-400 hover:text-gray-600 text-xl leading-none ml-2 flex-shrink-0"
            >×</button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">

            {/* Current maps */}
            {selected.all_maps?.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-gray-500 mb-2">مرتبط حالياً بـ</div>
                <div className="space-y-1.5">
                  {selected.all_maps.map(m => (
                    <div key={m.map_id} className="flex items-start justify-between bg-gray-50 rounded-lg px-3 py-2 gap-2">
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-gray-800 truncate">{m.name_ar || m.name}</div>
                        {m.concentration && <div className="text-xs text-gray-400">{m.concentration}</div>}
                        {m.is_chronic && (
                          <ChronicBadge
                            cls={m.chronic_class}
                            label={CHRONIC_CLASSES.find(c => c.value === m.chronic_class)?.label}
                          />
                        )}
                      </div>
                      <button
                        onClick={() => unclassifyMut.mutate({ itemId: selected.id, ingredientId: m.ingredient_id })}
                        className="text-red-400 hover:text-red-600 text-xs flex-shrink-0"
                      >حذف</button>
                    </div>
                  ))}
                </div>
                <hr className="my-3 border-gray-100" />
                <div className="text-xs text-gray-500 mb-2 font-semibold">إضافة مادة فعّالة أخرى</div>
              </div>
            )}

            {/* Mode toggle */}
            <div className="flex gap-2">
              <button
                onClick={() => setMode('existing')}
                className={`flex-1 py-1.5 text-xs rounded-lg border transition-colors ${
                  mode === 'existing'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
                }`}
              >مادة موجودة</button>
              <button
                onClick={() => setMode('new')}
                className={`flex-1 py-1.5 text-xs rounded-lg border transition-colors ${
                  mode === 'new'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
                }`}
              >إنشاء جديد</button>
            </div>

            {/* Existing ingredient selector */}
            {mode === 'existing' && (
              <div>
                <label className="text-xs font-semibold text-gray-600 block mb-1">المادة الفعّالة</label>
                <select
                  value={existingIngId}
                  onChange={e => {
                    setExistingId(e.target.value)
                    const ing = (ingredients || []).find(i => i.id === parseInt(e.target.value))
                    if (ing) {
                      setIsChronic(ing.is_chronic)
                      setChronicClass(ing.chronic_class || '')
                    }
                  }}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                >
                  <option value="">اختر مادة فعّالة...</option>
                  {(ingredients || []).map(i => (
                    <option key={i.id} value={i.id}>
                      {i.name_ar || i.name}{i.is_chronic ? ' 🏥' : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* New ingredient form */}
            {mode === 'new' && (
              <div className="space-y-2">
                <div>
                  <label className="text-xs font-semibold text-gray-600 block mb-1">الاسم (إنجليزي) *</label>
                  <input
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                    placeholder="Metformin"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 block mb-1">الاسم (عربي)</label>
                  <input
                    value={newNameAr}
                    onChange={e => setNewNameAr(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                    placeholder="ميتفورمين"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 block mb-1">كود ATC</label>
                  <input
                    value={newAtc}
                    onChange={e => setNewAtc(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-400"
                    placeholder="A10BA02"
                  />
                </div>
              </div>
            )}

            {/* Shared fields */}
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">التركيز (اختياري)</label>
              <input
                value={concentration}
                onChange={e => setConc(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                placeholder="500mg / 10mg/5ml"
              />
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="is_chronic_chk"
                checked={isChronic}
                onChange={e => setIsChronic(e.target.checked)}
                className="w-4 h-4 accent-brand-600"
              />
              <label htmlFor="is_chronic_chk" className="text-sm text-gray-700">دواء مزمن</label>
            </div>

            {isChronic && (
              <div>
                <label className="text-xs font-semibold text-gray-600 block mb-1">تصنيف المرض المزمن</label>
                <select
                  value={chronicClass}
                  onChange={e => setChronicClass(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                >
                  <option value="">اختر تصنيفاً...</option>
                  {CHRONIC_CLASSES.map(c => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Tags */}
            {tags?.length > 0 && (
              <div>
                <label className="text-xs font-semibold text-gray-600 block mb-2">وسوم الوصفة</label>
                <div className="flex flex-wrap gap-1.5">
                  {tags.map(tag => {
                    const active = selectedTagIds.includes(tag.id)
                    return (
                      <button
                        key={tag.id}
                        onClick={() => toggleTag(tag.id)}
                        className={`text-xs px-2 py-1 rounded border transition-all ${
                          active ? 'shadow-sm' : 'opacity-50 hover:opacity-80'
                        }`}
                        style={{
                          background:  active ? tag.color + '22' : '#f9fafb',
                          color:       tag.color,
                          borderColor: tag.color + (active ? '99' : '44'),
                        }}
                      >
                        {tag.name_ar || tag.name}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Panel footer */}
          <div className="px-4 py-3 border-t border-gray-100 space-y-2">
            {classifyMut.isError && (
              <div className="text-xs text-red-500 bg-red-50 rounded px-2 py-1">
                {classifyMut.error?.response?.data?.non_field_errors?.[0] ||
                 classifyMut.error?.response?.data?.detail ||
                 JSON.stringify(classifyMut.error?.response?.data) ||
                 'حدث خطأ'}
              </div>
            )}
            <button
              onClick={handleClassify}
              disabled={
                classifyMut.isLoading ||
                (mode === 'existing' && !existingIngId) ||
                (mode === 'new' && !newName.trim())
              }
              className="w-full bg-brand-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-40 transition-colors"
            >
              {classifyMut.isLoading ? 'جارٍ الحفظ...' : 'حفظ التصنيف'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 2 — Ingredients Manager
// ─────────────────────────────────────────────────────────────────────────────

function IngredientsManager() {
  const qc = useQueryClient()
  const [selected, setSelected]         = useState(null)
  const [search, setSearch]             = useState('')
  const [showForm, setShowForm]         = useState(false)
  const [showProtForm, setShowProtForm] = useState(false)

  const [form, setForm] = useState({
    name: '', name_ar: '', name_scientific: '',
    atc_code: '', is_chronic: false, chronic_class: '', notes: '',
  })

  const [prot, setProt] = useState({
    name: '', frequency_type: 'days_after_purchase', days: 30,
    trigger_condition: 'any_purchase', customer_type_filter: 'all',
    task_type: 'call', priority: 'normal', message_template: '',
  })

  const { data: ingList } = useQuery({
    queryKey: ['chronicIngredients', { q: search }],
    queryFn: () => chronicApi.listIngredients({ q: search, page_size: 100 }).then(r => r.data.results || r.data),
  })

  const { data: ingDetail } = useQuery({
    queryKey: ['chronicIngredient', selected?.id],
    queryFn: () => chronicApi.getIngredient(selected.id).then(r => r.data),
    enabled:  !!selected?.id,
  })

  const { data: tags } = useQuery({
    queryKey: ['chronicTags'],
    queryFn: () => chronicApi.listTags({ active_only: true, page_size: 200 }).then(r => r.data.results || r.data),
  })

  const createIngMut = useMutation({
    mutationFn: (data) => chronicApi.createIngredient(data),
    onSuccess: (res) => {
      qc.invalidateQueries(['chronicIngredients'])
      setSelected(res.data)
      setShowForm(false)
    },
  })

  const addTagMut = useMutation({
    mutationFn: ({ id, tagId }) => chronicApi.addTag(id, tagId),
    onSuccess: () => qc.invalidateQueries(['chronicIngredient', selected?.id]),
  })

  const removeTagMut = useMutation({
    mutationFn: ({ id, tagId }) => chronicApi.removeTag(id, tagId),
    onSuccess: () => qc.invalidateQueries(['chronicIngredient', selected?.id]),
  })

  const addProtMut = useMutation({
    mutationFn: (data) => chronicApi.addProtocol(selected.id, data),
    onSuccess: () => {
      qc.invalidateQueries(['chronicIngredient', selected?.id])
      setShowProtForm(false)
      setProt({
        name: '', frequency_type: 'days_after_purchase', days: 30,
        trigger_condition: 'any_purchase', customer_type_filter: 'all',
        task_type: 'call', priority: 'normal', message_template: '',
      })
    },
  })

  const linkedTagIds = new Set((ingDetail?.ingredient_tags || []).map(t => t.tag))

  return (
    <div className="flex gap-4 h-full overflow-hidden">

      {/* ── Left list ───────────────────────────────────────────────────── */}
      <div className="w-64 flex-shrink-0 flex flex-col gap-2 overflow-hidden">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="بحث في المواد الفعّالة..."
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-brand-400 flex-shrink-0"
        />
        <button
          onClick={() => {
            setShowForm(true)
            setForm({ name:'', name_ar:'', name_scientific:'', atc_code:'', is_chronic:false, chronic_class:'', notes:'' })
          }}
          className="w-full bg-brand-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-brand-700 flex-shrink-0"
        >
          + مادة فعّالة جديدة
        </button>
        <div className="flex-1 overflow-y-auto space-y-1 min-h-0">
          {(ingList || []).map(ing => (
            <button
              key={ing.id}
              onClick={() => setSelected(ing)}
              className={`w-full text-right px-3 py-2.5 rounded-lg text-sm transition-colors ${
                selected?.id === ing.id
                  ? 'bg-brand-600 text-white'
                  : 'bg-white hover:bg-gray-50 text-gray-700 border border-gray-200'
              }`}
            >
              <div className="font-medium truncate">{ing.name_ar || ing.name}</div>
              <div className={`text-xs mt-0.5 flex gap-1.5 items-center ${
                selected?.id === ing.id ? 'text-brand-200' : 'text-gray-400'
              }`}>
                <span>{ing.item_count} صنف</span>
                {ing.is_chronic && <span>• 🏥 مزمن</span>}
              </div>
            </button>
          ))}
          {!ingList?.length && (
            <div className="text-sm text-gray-400 text-center py-4">لا توجد مواد فعّالة بعد</div>
          )}
        </div>
      </div>

      {/* ── Right detail ────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 bg-white rounded-xl border border-gray-200 overflow-y-auto p-5">
        {!selected ? (
          <div className="h-full flex items-center justify-center text-gray-300 text-sm">
            اختر مادة فعّالة من القائمة أو أنشئ مادة جديدة
          </div>
        ) : !ingDetail ? (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            جارٍ التحميل...
          </div>
        ) : (
          <div className="space-y-6">

            {/* Header */}
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900">{ingDetail.name_ar || ingDetail.name}</h2>
                {ingDetail.name_ar && (
                  <div className="text-sm text-gray-400 italic mt-0.5">{ingDetail.name}</div>
                )}
                {ingDetail.name_scientific && (
                  <div className="text-xs text-gray-400 mt-0.5">{ingDetail.name_scientific}</div>
                )}
                {ingDetail.atc_code && (
                  <div className="text-xs font-mono text-gray-400 mt-1">ATC: {ingDetail.atc_code}</div>
                )}
              </div>
              {ingDetail.is_chronic && (
                <ChronicBadge
                  cls={ingDetail.chronic_class}
                  label={CHRONIC_CLASSES.find(c => c.value === ingDetail.chronic_class)?.label || 'مزمن'}
                />
              )}
            </div>

            {/* Tags section */}
            <div>
              <div className="text-sm font-semibold text-gray-700 mb-2">الوسوم</div>
              <div className="flex flex-wrap gap-2">
                {(ingDetail.ingredient_tags || []).map(it => (
                  <div key={it.id} className="flex items-center gap-1">
                    <TagBadge tag={it.tag_detail} />
                    <button
                      onClick={() => removeTagMut.mutate({ id: ingDetail.id, tagId: it.tag })}
                      className="text-gray-300 hover:text-red-400 text-xs leading-none"
                      title="حذف الوسم"
                    >×</button>
                  </div>
                ))}
                {(tags || []).filter(t => !linkedTagIds.has(t.id)).map(tag => (
                  <button
                    key={tag.id}
                    onClick={() => addTagMut.mutate({ id: ingDetail.id, tagId: tag.id })}
                    className="text-xs px-2 py-0.5 rounded border border-dashed border-gray-300 text-gray-400 hover:border-brand-400 hover:text-brand-600 transition-colors"
                  >
                    + {tag.name_ar || tag.name}
                  </button>
                ))}
                {!tags?.length && (
                  <span className="text-xs text-gray-400">لا توجد وسوم — أنشئ وسوماً من صفحة الإعدادات</span>
                )}
              </div>
            </div>

            {/* Linked items */}
            <div>
              <div className="text-sm font-semibold text-gray-700 mb-2">
                الأصناف المرتبطة ({ingDetail.item_maps?.length || 0})
              </div>
              {ingDetail.item_maps?.length > 0 ? (
                <div className="grid grid-cols-2 gap-2">
                  {ingDetail.item_maps.map(m => (
                    <div key={m.id} className="bg-gray-50 rounded-lg px-3 py-2 text-xs">
                      <div className="font-medium text-gray-800 truncate">{m.item_name}</div>
                      <div className="text-gray-400 font-mono">{m.item_softech_id}</div>
                      {m.concentration && <div className="text-gray-500 mt-0.5">{m.concentration}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-400 bg-gray-50 rounded-lg px-4 py-3">
                  لا توجد أصناف مرتبطة بعد — انتقل إلى تبويب <strong>مصنّف الأصناف</strong> لربط الأصناف بهذه المادة
                </div>
              )}
            </div>

            {/* Follow-up protocols */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-semibold text-gray-700">
                  بروتوكولات المتابعة ({ingDetail.followup_protocols?.length || 0})
                </div>
                <button
                  onClick={() => setShowProtForm(p => !p)}
                  className="text-xs text-brand-600 hover:text-brand-800 font-medium"
                >
                  {showProtForm ? 'إلغاء' : '+ بروتوكول جديد'}
                </button>
              </div>

              {showProtForm && (
                <div className="bg-gray-50 rounded-xl p-4 mb-4 space-y-3 text-sm border border-gray-200">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2">
                      <label className="text-xs text-gray-500 block mb-1">اسم البروتوكول *</label>
                      <input
                        value={prot.name}
                        onChange={e => setProt(p => ({ ...p, name: e.target.value }))}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                        placeholder="مثال: تذكير إعادة صرف شهري"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">نوع التكرار</label>
                      <select
                        value={prot.frequency_type}
                        onChange={e => setProt(p => ({ ...p, frequency_type: e.target.value }))}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      >
                        <option value="days_after_purchase">بعد الشراء بـ X يوم</option>
                        <option value="before_runout">قبل نفاد العبوة بـ X يوم</option>
                        <option value="on_runout">عند يوم النفاد</option>
                        <option value="days_after_last_task">بعد آخر متابعة بـ X يوم</option>
                        <option value="fixed_monthly">شهري — نفس اليوم</option>
                      </select>
                    </div>
                    {['days_after_purchase','before_runout','days_after_last_task'].includes(prot.frequency_type) && (
                      <div>
                        <label className="text-xs text-gray-500 block mb-1">عدد الأيام</label>
                        <input
                          type="number" min={1}
                          value={prot.days}
                          onChange={e => setProt(p => ({ ...p, days: parseInt(e.target.value) || 30 }))}
                          className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                        />
                      </div>
                    )}
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">نوع العميل</label>
                      <select
                        value={prot.customer_type_filter}
                        onChange={e => setProt(p => ({ ...p, customer_type_filter: e.target.value }))}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      >
                        <option value="all">جميع العملاء</option>
                        <option value="home_delivery">توصيل منزلي</option>
                        <option value="walkin">كاش / مشي</option>
                        <option value="b2b">شركات / تأمين</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">وسيلة التواصل</label>
                      <select
                        value={prot.task_type}
                        onChange={e => setProt(p => ({ ...p, task_type: e.target.value }))}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      >
                        <option value="call">📞 اتصال هاتفي</option>
                        <option value="whatsapp">💬 واتساب</option>
                        <option value="sms">📱 رسالة نصية</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">الأولوية</label>
                      <select
                        value={prot.priority}
                        onChange={e => setProt(p => ({ ...p, priority: e.target.value }))}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      >
                        <option value="low">منخفض</option>
                        <option value="normal">عادي</option>
                        <option value="high">مرتفع</option>
                        <option value="urgent">عاجل</option>
                      </select>
                    </div>
                    <div className="col-span-2">
                      <label className="text-xs text-gray-500 block mb-1">قالب الرسالة (اختياري)</label>
                      <textarea
                        value={prot.message_template}
                        onChange={e => setProt(p => ({ ...p, message_template: e.target.value }))}
                        rows={2}
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm resize-none"
                        placeholder="مرحبًا {customer_name}، حان موعد إعادة صرف {item_name}..."
                      />
                    </div>
                  </div>
                  {addProtMut.isError && (
                    <div className="text-xs text-red-500 bg-red-50 rounded px-2 py-1">
                      {JSON.stringify(addProtMut.error?.response?.data)}
                    </div>
                  )}
                  <button
                    onClick={() => addProtMut.mutate(prot)}
                    disabled={!prot.name.trim() || addProtMut.isLoading}
                    className="w-full bg-brand-600 text-white rounded py-1.5 text-sm hover:bg-brand-700 disabled:opacity-40"
                  >
                    {addProtMut.isLoading ? 'جارٍ الحفظ...' : 'حفظ البروتوكول'}
                  </button>
                </div>
              )}

              <div className="space-y-2">
                {(ingDetail.followup_protocols || []).map(p => (
                  <div key={p.id} className="bg-gray-50 rounded-lg px-4 py-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-800">{p.name}</div>
                      <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${
                      p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {p.is_active ? 'نشط' : 'معطل'}
                    </span>
                  </div>
                ))}
                {!ingDetail.followup_protocols?.length && (
                  <div className="text-sm text-gray-400 py-2 text-center">
                    لا توجد بروتوكولات — أضف واحداً باستخدام الزر أعلاه
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* New ingredient modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="font-bold text-gray-900 text-lg">مادة فعّالة جديدة</h3>
            {[
              { key: 'name',            label: 'الاسم (إنجليزي) *', ph: 'Metformin' },
              { key: 'name_ar',         label: 'الاسم (عربي)',      ph: 'ميتفورمين' },
              { key: 'name_scientific', label: 'الاسم العلمي',      ph: 'Metformin HCl' },
              { key: 'atc_code',        label: 'كود ATC',           ph: 'A10BA02' },
            ].map(f => (
              <div key={f.key}>
                <label className="text-xs font-semibold text-gray-600 block mb-1">{f.label}</label>
                <input
                  value={form[f.key]}
                  onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                  placeholder={f.ph}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                />
              </div>
            ))}
            <div className="flex items-center gap-2">
              <input
                type="checkbox" id="modal_is_chronic"
                checked={form.is_chronic}
                onChange={e => setForm(p => ({ ...p, is_chronic: e.target.checked }))}
                className="w-4 h-4 accent-brand-600"
              />
              <label htmlFor="modal_is_chronic" className="text-sm text-gray-700">دواء مزمن</label>
            </div>
            {form.is_chronic && (
              <select
                value={form.chronic_class}
                onChange={e => setForm(p => ({ ...p, chronic_class: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">اختر تصنيف المرض المزمن...</option>
                {CHRONIC_CLASSES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            )}
            {createIngMut.isError && (
              <div className="text-xs text-red-500 bg-red-50 rounded px-2 py-1">
                {JSON.stringify(createIngMut.error?.response?.data)}
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => createIngMut.mutate(form)}
                disabled={!form.name.trim() || createIngMut.isLoading}
                className="flex-1 bg-brand-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-40"
              >
                {createIngMut.isLoading ? 'جارٍ الحفظ...' : 'حفظ'}
              </button>
              <button
                onClick={() => setShowForm(false)}
                className="flex-1 border border-gray-300 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                إلغاء
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 3 — Task Generator
// ─────────────────────────────────────────────────────────────────────────────

function TaskGenerator() {
  const [form, setForm] = useState({
    period_start:   new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10),
    period_end:     new Date().toISOString().slice(0, 10),
    customer_types: ['all'],
    branch_ids:     [],
    ingredient_ids: [],
  })
  const [result, setResult] = useState(null)

  const { data: ingredients } = useQuery({
    queryKey: ['chronicIngredients', 'chronic_only'],
    queryFn: () => chronicApi.listIngredients({ chronic_only: true, page_size: 200 })
      .then(r => r.data.results || r.data),
  })

  const previewMut = useMutation({
    mutationFn: (data) => chronicApi.previewTasks(data),
    onSuccess:  r => setResult({ ...r.data, dry_run: true }),
  })

  const generateMut = useMutation({
    mutationFn: (data) => chronicApi.generateTasks(data),
    onSuccess:  r => setResult({ ...r.data, dry_run: false }),
  })

  const toggleCustType = (t) => {
    if (t === 'all') {
      setForm(f => ({ ...f, customer_types: ['all'] }))
      return
    }
    setForm(f => {
      const filtered = f.customer_types.filter(x => x !== 'all')
      return {
        ...f,
        customer_types: filtered.includes(t)
          ? filtered.filter(x => x !== t)
          : [...filtered, t],
      }
    })
  }

  const toggleIngredient = (id) => {
    const sid = String(id)
    setForm(f => ({
      ...f,
      ingredient_ids: f.ingredient_ids.includes(sid)
        ? f.ingredient_ids.filter(x => x !== sid)
        : [...f.ingredient_ids, sid],
    }))
  }

  const payload = {
    ...form,
    ingredient_ids: form.ingredient_ids.map(Number),
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-5">
        <div>
          <h3 className="font-semibold text-gray-800">توليد مهام المتابعة</h3>
          <p className="text-xs text-gray-500 mt-1">
            يولّد مهام متابعة لعملاء اشتروا أدوية مزمنة خلال الفترة المحددة بناءً على بروتوكولات كل مادة فعّالة.
          </p>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-4">
          {[
            ['period_start', 'من تاريخ (تاريخ الشراء)'],
            ['period_end',   'إلى تاريخ (تاريخ الشراء)'],
          ].map(([k, l]) => (
            <div key={k}>
              <label className="text-xs font-semibold text-gray-600 block mb-1">{l}</label>
              <input
                type="date"
                value={form[k]}
                onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
            </div>
          ))}
        </div>

        {/* Customer type */}
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-2">نوع العميل</label>
          <div className="flex flex-wrap gap-3">
            {[
              { v: 'all',           l: 'الكل' },
              { v: 'home_delivery', l: 'توصيل منزلي' },
              { v: 'walkin',        l: 'كاش / مشي' },
              { v: 'b2b',           l: 'شركات / تأمين' },
            ].map(({ v, l }) => (
              <label key={v} className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.customer_types.includes(v)}
                  onChange={() => toggleCustType(v)}
                  className="accent-brand-600 w-4 h-4"
                />
                {l}
              </label>
            ))}
          </div>
        </div>

        {/* Ingredient filter */}
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-2">
            تصفية بمادة فعّالة
            <span className="font-normal text-gray-400 mr-1">(اتركها فارغة للتطبيق على كل الأدوية المزمنة)</span>
          </label>
          {ingredients?.length ? (
            <div className="grid grid-cols-3 gap-2 max-h-48 overflow-y-auto border border-gray-200 rounded-lg p-3 bg-gray-50">
              {ingredients.map(ing => (
                <label key={ing.id} className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={form.ingredient_ids.includes(String(ing.id))}
                    onChange={() => toggleIngredient(ing.id)}
                    className="accent-brand-600"
                  />
                  <span className="truncate">{ing.name_ar || ing.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <div className="text-sm text-gray-400 bg-gray-50 rounded-lg px-4 py-3">
              لا توجد مواد فعّالة مزمنة بعد — أضف مواد من تبويب المواد الفعّالة
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={() => { setResult(null); previewMut.mutate(payload) }}
            disabled={previewMut.isLoading}
            className="flex-1 border border-brand-600 text-brand-600 rounded-lg py-2.5 text-sm font-medium hover:bg-brand-50 disabled:opacity-40 transition-colors"
          >
            {previewMut.isLoading ? 'جارٍ المعاينة...' : '👁 معاينة (بدون حفظ)'}
          </button>
          <button
            onClick={() => {
              if (window.confirm('سيتم إنشاء مهام المتابعة فعلياً في قاعدة البيانات. هل أنت متأكد؟'))
                generateMut.mutate(payload)
            }}
            disabled={generateMut.isLoading}
            className="flex-1 bg-brand-600 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-brand-700 disabled:opacity-40 transition-colors"
          >
            {generateMut.isLoading ? 'جارٍ الإنشاء...' : '⚡ إنشاء المهام'}
          </button>
        </div>
      </div>

      {/* Result card */}
      {result && (
        <div className={`bg-white rounded-xl border p-5 space-y-4 ${
          result.dry_run ? 'border-yellow-300 bg-yellow-50' : 'border-green-300 bg-green-50'
        }`}>
          <div className="font-semibold text-gray-800">
            {result.dry_run ? '👁 معاينة — لم يُحفظ شيء' : '✅ تم إنشاء المهام بنجاح'}
          </div>

          <div className="grid grid-cols-3 gap-3">
            {[
              { label: result.dry_run ? 'سيتم إنشاء' : 'تم إنشاء', value: result.created,              color: 'green'  },
              { label: 'تخطي — موجود مسبقاً',                       value: result.skipped_dedup,        color: 'gray'   },
              { label: 'تخطي — لا عميل',                            value: result.skipped_no_customer,  color: 'orange' },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-lg p-3 text-center border border-gray-200">
                <div className="text-2xl font-bold text-gray-800">{c.value ?? 0}</div>
                <div className="text-xs text-gray-500 mt-1">{c.label}</div>
              </div>
            ))}
          </div>

          {result.breakdown && Object.keys(result.breakdown).length > 0 && (
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-2">توزيع حسب المادة الفعّالة</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {Object.entries(result.breakdown)
                  .sort((a, b) => b[1] - a[1])
                  .map(([ing, cnt]) => (
                    <div key={ing} className="flex items-center justify-between bg-white rounded px-3 py-1.5 text-xs border border-gray-100">
                      <span className="text-gray-700">{ing}</span>
                      <span className="font-bold text-gray-900">{cnt}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page shell
// ─────────────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'classifier',  label: '🔬 مصنّف الأصناف' },
  { id: 'ingredients', label: '💊 المواد الفعّالة' },
  { id: 'tasks',       label: '⚡ توليد المهام' },
]

export default function ChronicClassifierPage() {
  const [tab, setTab] = useState('classifier')

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-hidden" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-xl font-bold text-gray-900">مصنّف الأدوية المزمنة</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            صنّف أصناف المخزون كأدوية مزمنة وأنشئ بروتوكولات متابعة تلقائية للعملاء
          </p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t.id
                ? 'bg-white text-brand-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'classifier'  && <ItemClassifier />}
        {tab === 'ingredients' && <IngredientsManager />}
        {tab === 'tasks'       && (
          <div className="h-full overflow-y-auto">
            <TaskGenerator />
          </div>
        )}
      </div>
    </div>
  )
}
