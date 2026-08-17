/**
 * ProductContentAdminPage.jsx
 *
 * Content management for a product:
 *   - Image / media upload, reorder, approve, delete
 *   - Content (descriptions, FAQ, adherence icons)
 *   - Attributes (strength, pack size, temperature storage, etc.)
 *   - SEO (slug, meta title, description, keywords)
 *
 * Accessible via /products/:id/admin
 * Requires content manager or admin role.
 */
import { useState, useRef, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { productsApi } from '../api/client'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// ── Helpers ───────────────────────────────────────────────────────────────────

function SaveBar({ onSave, saving, dirty }) {
  if (!dirty) return null
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3
                    bg-white border border-gray-200 shadow-xl rounded-2xl px-6 py-3">
      <span className="text-sm text-amber-600 font-medium">⚠ يوجد تغييرات غير محفوظة</span>
      <button
        onClick={onSave}
        disabled={saving}
        className="bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium px-5 py-2
                   rounded-xl disabled:opacity-50 transition-colors"
      >
        {saving ? 'جاري الحفظ...' : 'حفظ التغييرات'}
      </button>
    </div>
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="mb-5">
      <label className="block text-sm font-semibold text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1.5">{hint}</p>}
      {children}
    </div>
  )
}

const inputCls = 'w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-300 bg-white'
const textareaCls = `${inputCls} resize-y min-h-[80px]`

// ── Tab: Media ────────────────────────────────────────────────────────────────

function MediaTab({ product, productId }) {
  const queryClient  = useQueryClient()
  const fileInputRef = useRef()
  const [uploading, setUploading]   = useState(false)
  const [uploadError, setUploadError] = useState('')

  const media = product.all_media || []

  const uploadMutation = useMutation({
    mutationFn: (formData) => productsApi.uploadMedia(productId, formData),
    onSuccess: () => {
      queryClient.invalidateQueries(['product-detail', productId])
      setUploadError('')
    },
    onError: (err) => {
      setUploadError(err.response?.data?.detail || 'فشل رفع الملف')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ mediaId, data }) => productsApi.updateMedia(productId, mediaId, data),
    onSuccess: () => queryClient.invalidateQueries(['product-detail', productId]),
  })

  const deleteMutation = useMutation({
    mutationFn: (mediaId) => productsApi.deleteMedia(productId, mediaId),
    onSuccess: () => queryClient.invalidateQueries(['product-detail', productId]),
  })

  const handleFileChange = useCallback(async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setUploading(true)
    for (const file of files) {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('media_type', 'image')
      fd.append('alt_text', '')
      await uploadMutation.mutateAsync(fd)
    }
    setUploading(false)
    e.target.value = ''
  }, [uploadMutation])

  const MEDIA_TYPE_LABELS = {
    image:  '🖼 صورة',
    video:  '🎬 فيديو',
    pdf:    '📄 PDF',
    manual: '📋 نشرة',
  }

  return (
    <div>
      {/* Upload zone */}
      <div
        onClick={() => fileInputRef.current?.click()}
        className="border-2 border-dashed border-brand-200 hover:border-brand-400 rounded-xl p-8
                   text-center cursor-pointer transition-colors bg-brand-50 hover:bg-brand-100 mb-6"
      >
        {uploading ? (
          <div className="text-brand-500 animate-pulse">جاري الرفع...</div>
        ) : (
          <>
            <div className="text-4xl mb-2">📁</div>
            <p className="text-sm text-brand-600 font-medium">انقر لاختيار صور أو اسحبها هنا</p>
            <p className="text-xs text-gray-400 mt-1">JPG، PNG، WebP — حجم أقصى 10MB</p>
          </>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        onChange={handleFileChange}
        className="hidden"
      />
      {uploadError && (
        <p className="text-sm text-red-500 bg-red-50 rounded-lg px-3 py-2 mb-4">{uploadError}</p>
      )}

      {/* Media grid */}
      {media.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">لا توجد وسائط بعد. ارفع صورة للبدء.</p>
      ) : (
        <div className="space-y-3">
          {media.map(m => (
            <div
              key={m.id}
              className="flex items-center gap-4 bg-white border border-gray-100 rounded-xl p-3"
            >
              {/* Thumbnail */}
              <div className="w-16 h-16 bg-gray-50 rounded-lg overflow-hidden flex items-center justify-center shrink-0 border border-gray-100">
                {m.media_type === 'image' ? (
                  <img
                    src={m.thumb_url || m.url}
                    alt=""
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <span className="text-2xl">{MEDIA_TYPE_LABELS[m.media_type]?.split(' ')[0]}</span>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                    {MEDIA_TYPE_LABELS[m.media_type] || m.media_type}
                  </span>
                  {m.is_primary && (
                    <span className="text-xs bg-brand-100 text-brand-700 px-2 py-0.5 rounded">رئيسية</span>
                  )}
                  {m.approved ? (
                    <span className="text-xs bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded">✓ معتمدة</span>
                  ) : (
                    <span className="text-xs bg-amber-50 text-amber-600 px-2 py-0.5 rounded">في انتظار الاعتماد</span>
                  )}
                </div>
                <input
                  type="text"
                  defaultValue={m.alt_text || ''}
                  placeholder="النص البديل..."
                  onBlur={e => {
                    if (e.target.value !== m.alt_text) {
                      updateMutation.mutate({ mediaId: m.id, data: { alt_text: e.target.value } })
                    }
                  }}
                  className="w-full text-xs border border-gray-100 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-200"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 shrink-0">
                {!m.is_primary && (
                  <button
                    onClick={() => updateMutation.mutate({ mediaId: m.id, data: { is_primary: true } })}
                    className="text-xs text-gray-400 hover:text-brand-500 border border-gray-200 rounded-lg px-2 py-1 transition-colors"
                    title="جعلها رئيسية"
                  >
                    ★
                  </button>
                )}
                <button
                  onClick={() => updateMutation.mutate({ mediaId: m.id, data: { approved: !m.approved } })}
                  className={`text-xs border rounded-lg px-2 py-1 transition-colors
                    ${m.approved
                      ? 'border-amber-200 text-amber-500 hover:bg-amber-50'
                      : 'border-emerald-200 text-emerald-500 hover:bg-emerald-50'}`}
                >
                  {m.approved ? 'إلغاء الاعتماد' : 'اعتماد'}
                </button>
                <button
                  onClick={() => {
                    if (window.confirm('حذف هذه الصورة نهائياً؟')) {
                      deleteMutation.mutate(m.id)
                    }
                  }}
                  className="text-xs text-gray-300 hover:text-red-500 border border-gray-100 hover:border-red-200 rounded-lg px-2 py-1 transition-colors"
                >
                  🗑
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tab: Content ──────────────────────────────────────────────────────────────

function ContentTab({ productId, initialContent }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialContent || {})
  const [dirty, setDirty] = useState(false)
  const [faqText, setFaqText] = useState(() => JSON.stringify(initialContent?.faq || [], null, 2))
  const [faqError, setFaqError] = useState('')

  const mutation = useMutation({
    mutationFn: (data) => productsApi.patchContent(productId, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['product-detail', productId])
      setDirty(false)
    },
  })

  const set = (field, val) => {
    setForm(f => ({ ...f, [field]: val }))
    setDirty(true)
  }

  const handleSave = () => {
    // Validate FAQ JSON
    let faq = form.faq || []
    try {
      faq = JSON.parse(faqText)
      setFaqError('')
    } catch {
      setFaqError('تنسيق JSON غير صحيح في الأسئلة الشائعة')
      return
    }
    mutation.mutate({ ...form, faq })
  }

  return (
    <>
      <div className="space-y-1">
        <FieldRow label="الاسم التجاري (عربي)">
          <input value={form.display_name_ar || ''} onChange={e => set('display_name_ar', e.target.value)} className={inputCls} />
        </FieldRow>
        <FieldRow label="الاسم التجاري (إنجليزي)">
          <input value={form.display_name_en || ''} onChange={e => set('display_name_en', e.target.value)} className={inputCls} dir="ltr" />
        </FieldRow>
        <FieldRow label="وصف مختصر" hint="يظهر في بطاقة المنتج وواتساب">
          <textarea value={form.short_description || ''} onChange={e => set('short_description', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
        <FieldRow label="وصف تفصيلي">
          <textarea value={form.long_description || ''} onChange={e => set('long_description', e.target.value)} className={textareaCls} rows={5} />
        </FieldRow>
        <FieldRow label="تعليمات الاستخدام">
          <textarea value={form.instructions || ''} onChange={e => set('instructions', e.target.value)} className={textareaCls} rows={4} />
        </FieldRow>
        <FieldRow label="طريقة الاستخدام">
          <textarea value={form.usage || ''} onChange={e => set('usage', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
        <FieldRow label="شروط التخزين">
          <textarea value={form.storage || ''} onChange={e => set('storage', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
        <FieldRow label="موانع الاستخدام">
          <textarea value={form.contraindications || ''} onChange={e => set('contraindications', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
        <FieldRow label="الفوائد والاستخدامات">
          <textarea value={form.benefits || ''} onChange={e => set('benefits', e.target.value)} className={textareaCls} rows={4} />
        </FieldRow>
        <FieldRow label="النص التسويقي">
          <textarea value={form.marketing_text || ''} onChange={e => set('marketing_text', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
        <FieldRow label="الكلمات المفتاحية" hint="مفصولة بفواصل">
          <input value={form.keywords || ''} onChange={e => set('keywords', e.target.value)} className={inputCls} />
        </FieldRow>
        <FieldRow label="الأسئلة الشائعة (FAQ)" hint='تنسيق JSON: [{"question":"...","answer":"..."}]'>
          <textarea
            value={faqText}
            onChange={e => { setFaqText(e.target.value); setDirty(true) }}
            className={`${textareaCls} font-mono text-xs`}
            rows={6}
            dir="ltr"
          />
          {faqError && <p className="text-xs text-red-500 mt-1">{faqError}</p>}
        </FieldRow>
        <FieldRow label="معاينة واتساب" hint="نص جاهز للمشاركة — يُنسخ مباشرة">
          <textarea value={form.whatsapp_preview || ''} onChange={e => set('whatsapp_preview', e.target.value)} className={textareaCls} rows={4} />
        </FieldRow>
      </div>

      <SaveBar onSave={handleSave} saving={mutation.isLoading} dirty={dirty} />
      {mutation.isError && (
        <p className="text-sm text-red-500 mt-2">
          {mutation.error?.response?.data?.detail || 'فشل الحفظ'}
        </p>
      )}
    </>
  )
}

// ── Tab: Attributes ───────────────────────────────────────────────────────────

function AttributesTab({ productId, initialAttributes }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialAttributes || {})
  const [dirty, setDirty] = useState(false)

  const mutation = useMutation({
    mutationFn: (data) => productsApi.patchAttributes(productId, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['product-detail', productId])
      setDirty(false)
    },
  })

  const set = (field, val) => {
    setForm(f => ({ ...f, [field]: val }))
    setDirty(true)
  }

  const TEMP_OPTIONS = [
    ['', 'اختر...'],
    ['room',         'حفظ بدرجة حرارة الغرفة (أقل من 25°م)'],
    ['cool',         'حفظ في مكان بارد (8-15°م)'],
    ['refrigerated', 'حفظ في الثلاجة (2-8°م)'],
    ['frozen',       'حفظ مجمداً (أقل من −18°م)'],
  ]

  return (
    <>
      <div className="space-y-1">
        <FieldRow label="التركيز / القوة">
          <input value={form.strength || ''} onChange={e => set('strength', e.target.value)} className={inputCls} placeholder="مثال: 500 mg" />
        </FieldRow>
        <FieldRow label="تركيز السوائل">
          <input value={form.concentration || ''} onChange={e => set('concentration', e.target.value)} className={inputCls} placeholder="مثال: 250 mg/5 ml" />
        </FieldRow>
        <FieldRow label="النكهة">
          <input value={form.flavor || ''} onChange={e => set('flavor', e.target.value)} className={inputCls} />
        </FieldRow>
        <FieldRow label="اللون">
          <input value={form.color || ''} onChange={e => set('color', e.target.value)} className={inputCls} />
        </FieldRow>
        <FieldRow label="الحجم / الوزن">
          <input value={form.size || ''} onChange={e => set('size', e.target.value)} className={inputCls} />
        </FieldRow>
        <FieldRow label="مواصفات العبوة">
          <input value={form.pack_size_label || ''} onChange={e => set('pack_size_label', e.target.value)} className={inputCls} placeholder="مثال: علبة 30 قرص" />
        </FieldRow>
        <FieldRow label="العدد في العبوة">
          <input type="number" value={form.count_per_pack || ''} onChange={e => set('count_per_pack', e.target.value || null)} className={inputCls} />
        </FieldRow>
        <FieldRow label="درجة حرارة التخزين">
          <select value={form.temperature_storage || ''} onChange={e => set('temperature_storage', e.target.value)} className={inputCls}>
            {TEMP_OPTIONS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
          </select>
        </FieldRow>
        <FieldRow label="مدة الصلاحية (شهور)">
          <input type="number" value={form.shelf_life_months || ''} onChange={e => set('shelf_life_months', e.target.value || null)} className={inputCls} />
        </FieldRow>
        <FieldRow label="يحتاج وصفة طبية">
          <select
            value={form.prescription_required == null ? '' : String(form.prescription_required)}
            onChange={e => set('prescription_required', e.target.value === '' ? null : e.target.value === 'true')}
            className={inputCls}
          >
            <option value="">غير محدد</option>
            <option value="true">نعم (وصفة مطلوبة)</option>
            <option value="false">لا (OTC)</option>
          </select>
        </FieldRow>
        <FieldRow label="تحذيرات خاصة">
          <textarea value={form.special_warnings || ''} onChange={e => set('special_warnings', e.target.value)} className={textareaCls} rows={3} />
        </FieldRow>
      </div>

      <SaveBar onSave={() => mutation.mutate(form)} saving={mutation.isLoading} dirty={dirty} />
    </>
  )
}

// ── Tab: SEO ──────────────────────────────────────────────────────────────────

function SeoTab({ productId, initialSeo }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialSeo || {})
  const [dirty, setDirty] = useState(false)

  const mutation = useMutation({
    mutationFn: (data) => productsApi.patchSeo(productId, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['product-detail', productId])
      setDirty(false)
    },
  })

  const set = (field, val) => {
    setForm(f => ({ ...f, [field]: val }))
    setDirty(true)
  }

  const slugLen = (form.slug || '').length
  const titleArLen = (form.title_ar || '').length
  const descArLen  = (form.description_ar || '').length

  return (
    <>
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-5 text-sm text-amber-700">
        ⚠️ تغيير الـ Slug يؤثر على روابط المنتج. تأكد من إعداد إعادة التوجيه إذا لزم.
      </div>

      <div className="space-y-1">
        <FieldRow label="Slug (رابط المنتج)" hint="حروف إنجليزية وأرقام وشرطة فقط">
          <div className="relative">
            <input
              value={form.slug || ''}
              onChange={e => set('slug', e.target.value)}
              className={inputCls}
              dir="ltr"
              placeholder="product-name-12345"
            />
            <span className={`absolute left-3 top-1/2 -translate-y-1/2 text-xs ${slugLen > 200 ? 'text-red-500' : 'text-gray-400'}`}>
              {slugLen}/250
            </span>
          </div>
        </FieldRow>

        <FieldRow label="عنوان الصفحة (عربي)" hint="مثالي: 50–60 حرف">
          <div className="relative">
            <input
              value={form.title_ar || ''}
              onChange={e => set('title_ar', e.target.value)}
              className={inputCls}
            />
            <span className={`absolute left-3 top-1/2 -translate-y-1/2 text-xs ${titleArLen > 200 ? 'text-red-500' : 'text-gray-400'}`}>
              {titleArLen}/200
            </span>
          </div>
        </FieldRow>

        <FieldRow label="عنوان الصفحة (إنجليزي)">
          <input value={form.title_en || ''} onChange={e => set('title_en', e.target.value)} className={inputCls} dir="ltr" />
        </FieldRow>

        <FieldRow label="وصف الصفحة (عربي)" hint="مثالي: 120–160 حرف">
          <div className="relative">
            <textarea
              value={form.description_ar || ''}
              onChange={e => set('description_ar', e.target.value)}
              className={textareaCls}
              rows={3}
              maxLength={320}
            />
            <span className={`absolute left-3 bottom-3 text-xs ${descArLen > 280 ? 'text-amber-500' : 'text-gray-400'}`}>
              {descArLen}/320
            </span>
          </div>
        </FieldRow>

        <FieldRow label="وصف الصفحة (إنجليزي)">
          <textarea value={form.description_en || ''} onChange={e => set('description_en', e.target.value)} className={textareaCls} rows={3} dir="ltr" maxLength={320} />
        </FieldRow>

        <FieldRow label="الكلمات المفتاحية" hint="مفصولة بفواصل، للـ SEO فقط">
          <input value={form.keywords || ''} onChange={e => set('keywords', e.target.value)} className={inputCls} />
        </FieldRow>

        <FieldRow label="الرابط الأصلي (Canonical URL)">
          <input value={form.canonical || ''} onChange={e => set('canonical', e.target.value)} className={inputCls} dir="ltr" type="url" placeholder="https://..." />
        </FieldRow>
      </div>

      {/* Preview */}
      {(form.title_ar || form.description_ar) && (
        <div className="mt-6 border border-gray-100 rounded-xl p-4 bg-gray-50">
          <p className="text-xs text-gray-400 mb-2">معاينة نتيجة البحث (Google)</p>
          <p className="text-blue-600 text-sm font-medium truncate">
            {form.title_ar || 'عنوان الصفحة'}
          </p>
          <p className="text-green-600 text-xs mt-0.5 font-mono">
            https://elrezeiky.com/products/{form.slug || 'slug'}
          </p>
          <p className="text-gray-600 text-xs mt-1 line-clamp-2">
            {form.description_ar || 'وصف الصفحة...'}
          </p>
        </div>
      )}

      <SaveBar onSave={() => mutation.mutate(form)} saving={mutation.isLoading} dirty={dirty} />
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const ADMIN_TABS = [
  { key: 'media',      label: '🖼 الصور والوسائط' },
  { key: 'content',    label: '📝 المحتوى والوصف' },
  { key: 'attributes', label: '⚗️ الخصائص الدوائية' },
  { key: 'seo',        label: '🔍 SEO والروابط' },
]

export default function ProductContentAdminPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('media')

  const { data: product, isLoading, isError } = useQuery({
    queryKey: ['product-detail', id],
    queryFn: () => productsApi.getDetail(id).then(r => r.data),
  })

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center font-cairo" dir="rtl">
        <div className="text-brand-500 animate-pulse">جاري التحميل...</div>
      </div>
    )
  }

  if (isError || !product) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center font-cairo gap-4" dir="rtl">
        <p className="text-gray-500">المنتج غير موجود</p>
        <button onClick={() => navigate('/products')} className="text-brand-600 hover:underline text-sm">العودة</button>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-100 px-6 py-4 sticky top-0 z-10 shadow-sm">
        <div className="max-w-4xl mx-auto flex items-center gap-4">
          <button
            onClick={() => navigate(`/products/${id}`)}
            className="text-gray-400 hover:text-brand-600 text-xl leading-none"
          >
            ←
          </button>
          <div className="flex-1">
            <h1 className="text-lg font-bold text-gray-800">
              إدارة المحتوى — {product.display_name_ar || product.name}
            </h1>
            <p className="text-xs text-gray-400 font-mono">{product.softech_id}</p>
          </div>
          <Link
            to={`/products/${id}`}
            className="text-xs text-brand-600 border border-brand-200 rounded-lg px-3 py-1.5 hover:bg-brand-50"
          >
            عرض صفحة المنتج ↗
          </Link>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-6">
        {/* Tab bar */}
        <div className="flex gap-2 mb-6 overflow-x-auto">
          {ADMIN_TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`whitespace-nowrap text-sm font-medium px-4 py-2 rounded-xl border transition-all
                ${activeTab === tab.key
                  ? 'bg-brand-600 text-white border-brand-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50 hover:border-gray-300'}`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="bg-white rounded-2xl border border-gray-100 p-6">
          {activeTab === 'media'      && <MediaTab product={product} productId={id} />}
          {activeTab === 'content'    && <ContentTab productId={id} initialContent={product.content} />}
          {activeTab === 'attributes' && <AttributesTab productId={id} initialAttributes={product.attributes} />}
          {activeTab === 'seo'        && <SeoTab productId={id} initialSeo={product.seo} />}
        </div>
      </div>
    </div>
  )
}
