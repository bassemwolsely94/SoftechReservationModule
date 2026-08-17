/**
 * ProductDetailPage.jsx
 *
 * Full product detail: image gallery, content tabs, per-branch availability,
 * related products. Tracks views automatically.
 * NEVER exposes raw quantities — availability shown as available/limited/unavailable only.
 */
import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { productsApi, pickZonesApi } from '../api/client'
import ShelfQrButton from '../components/ShelfQrButton'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// ── Constants ─────────────────────────────────────────────────────────────────

const AVAIL_CONFIG = {
  available:   { label: 'متاح',         cls: 'bg-emerald-100 text-emerald-700 border border-emerald-200', dot: 'bg-emerald-500' },
  limited:     { label: 'كميات محدودة', cls: 'bg-amber-100 text-amber-700 border border-amber-200',     dot: 'bg-amber-400'   },
  unavailable: { label: 'غير متاح',     cls: 'bg-red-100 text-red-600 border border-red-200',           dot: 'bg-red-500'     },
}

const TABS = [
  { key: 'info',          label: 'نظرة عامة' },
  { key: 'instructions',  label: 'التعليمات والتخزين' },
  { key: 'attributes',    label: 'الخصائص' },
  { key: 'availability',  label: 'التوافر بالفروع' },
  { key: 'similar',       label: 'منتجات مشابهة' },
  { key: 'related',       label: 'منتجات مرتبطة' },
  { key: 'demand',        label: 'الطلب المفتوح' },
]

// ── Sub-components ────────────────────────────────────────────────────────────

function AvailBadge({ status, size = 'sm' }) {
  const cfg = AVAIL_CONFIG[status] || AVAIL_CONFIG.unavailable
  const cls = size === 'lg'
    ? `text-sm px-3 py-1 rounded-full font-semibold ${cfg.cls}`
    : `text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`
  return <span className={cls}>{cfg.label}</span>
}

function InfoRow({ label, value }) {
  if (!value) return null
  return (
    <div className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-400 w-32 shrink-0 pt-0.5">{label}</span>
      <span className="text-sm text-gray-700 flex-1">{value}</span>
    </div>
  )
}

function AdherenceIcons({ icons }) {
  if (!icons?.length) return null
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {icons.map((ic, i) => (
        <div key={i} className="flex items-center gap-1.5 bg-brand-50 border border-brand-100 rounded-full px-3 py-1">
          {ic.icon && <span className="text-base">{ic.icon}</span>}
          {ic.label && <span className="text-xs text-brand-700">{ic.label}</span>}
        </div>
      ))}
    </div>
  )
}

// ── Image Gallery ─────────────────────────────────────────────────────────────

function ImageGallery({ media }) {
  const images = (media || []).filter(m => m.media_type === 'image')
  const [selected, setSelected] = useState(0)

  if (!images.length) {
    return (
      <div className="h-72 bg-gray-50 rounded-xl flex items-center justify-center border border-gray-100">
        <span className="text-7xl opacity-15">💊</span>
      </div>
    )
  }

  const current = images[selected]

  return (
    <div>
      {/* Main image */}
      <div className="h-72 bg-gray-50 rounded-xl overflow-hidden border border-gray-100 flex items-center justify-center">
        <img
          src={current.url}
          alt={current.alt_text || ''}
          className="max-h-full max-w-full object-contain"
        />
      </div>

      {/* Thumbnails */}
      {images.length > 1 && (
        <div className="flex gap-2 mt-3 overflow-x-auto pb-1">
          {images.map((img, i) => (
            <button
              key={img.id}
              onClick={() => setSelected(i)}
              className={`w-14 h-14 rounded-lg overflow-hidden border-2 shrink-0 transition-all
                ${i === selected ? 'border-brand-500' : 'border-gray-100 hover:border-gray-300'}`}
            >
              <img
                src={img.thumb_url || img.url}
                alt=""
                className="w-full h-full object-contain"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tab: Overview ─────────────────────────────────────────────────────────────

function OverviewTab({ product }) {
  const content    = product.content || {}
  const attributes = product.attributes || {}

  return (
    <div className="space-y-6">
      {/* Short description */}
      {content.short_description && (
        <p className="text-sm text-gray-700 leading-relaxed">{content.short_description}</p>
      )}

      {/* Long description */}
      {content.long_description && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-2">وصف تفصيلي</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">
            {content.long_description}
          </p>
        </div>
      )}

      {/* Benefits */}
      {content.benefits && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-2">الفوائد والاستخدامات</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{content.benefits}</p>
        </div>
      )}

      {/* Key attributes summary */}
      <div className="bg-gray-50 rounded-xl p-4 space-y-1">
        <h4 className="text-sm font-bold text-gray-700 mb-2">معلومات سريعة</h4>
        <InfoRow label="الاسم العلمي"     value={product.name_scientific} />
        <InfoRow label="المادة الفعالة"   value={product.active_ingredients} />
        <InfoRow label="التصنيف العلاجي"  value={product.effect_name_ar} />
        <InfoRow label="الشركة المنتجة"   value={product.producer_name || product.supplier_name} />
        <InfoRow label="التركيز"          value={attributes.strength || attributes.concentration} />
        <InfoRow label="الشكل الصيدلي"   value={product.shape_name_ar} />
        <InfoRow label="مواصفات العبوة"   value={attributes.pack_size_label} />
        {attributes.count_per_pack && (
          <InfoRow label="العدد في العبوة" value={`${attributes.count_per_pack} قطعة`} />
        )}
      </div>

      {/* Adherence icons */}
      {content.adherence_icons?.length > 0 && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-1">الالتزام بالعلاج</h4>
          <AdherenceIcons icons={content.adherence_icons} />
        </div>
      )}

      {/* FAQ */}
      {content.faq?.length > 0 && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3">الأسئلة الشائعة</h4>
          <div className="space-y-3">
            {content.faq.map((item, i) => (
              <details key={i} className="bg-gray-50 rounded-lg">
                <summary className="px-4 py-3 text-sm font-medium text-gray-700 cursor-pointer hover:text-brand-600 list-none flex items-center justify-between">
                  <span>{item.question}</span>
                  <span className="text-gray-400 text-xs">▾</span>
                </summary>
                <p className="px-4 pb-3 text-sm text-gray-600 leading-relaxed">{item.answer}</p>
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab: Instructions ─────────────────────────────────────────────────────────

function InstructionsTab({ product }) {
  const content    = product.content || {}
  const attributes = product.attributes || {}

  const STORAGE_LABELS = {
    room:         'حفظ بدرجة حرارة الغرفة (أقل من 25°م)',
    cool:         'حفظ في مكان بارد (8-15°م)',
    refrigerated: 'حفظ في الثلاجة (2-8°م) ❄',
    frozen:       'حفظ مجمداً (أقل من −18°م) 🧊',
  }

  return (
    <div className="space-y-6">
      {content.instructions && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-2">تعليمات الاستخدام</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap bg-brand-50 rounded-xl p-4">
            {content.instructions}
          </p>
        </div>
      )}

      {content.usage && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-2">طريقة الاستخدام</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{content.usage}</p>
        </div>
      )}

      {content.storage && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-2">شروط التخزين</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{content.storage}</p>
        </div>
      )}

      {attributes.temperature_storage && (
        <div className="flex items-center gap-3 bg-sky-50 border border-sky-100 rounded-xl p-4">
          <span className="text-2xl">🌡️</span>
          <div>
            <p className="text-xs text-sky-500 font-medium">درجة حرارة التخزين</p>
            <p className="text-sm text-sky-700 font-semibold">
              {STORAGE_LABELS[attributes.temperature_storage] || attributes.temperature_storage}
            </p>
          </div>
        </div>
      )}

      {attributes.shelf_life_months && (
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-100 rounded-xl p-4">
          <span className="text-2xl">📅</span>
          <div>
            <p className="text-xs text-amber-500 font-medium">مدة الصلاحية</p>
            <p className="text-sm text-amber-700 font-semibold">{attributes.shelf_life_months} شهر</p>
          </div>
        </div>
      )}

      {content.contraindications && (
        <div>
          <h4 className="text-sm font-bold text-red-600 mb-2">⚠️ موانع الاستخدام</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap bg-red-50 rounded-xl p-4 border border-red-100">
            {content.contraindications}
          </p>
        </div>
      )}

      {attributes.special_warnings && (
        <div>
          <h4 className="text-sm font-bold text-orange-600 mb-2">⚠️ تحذيرات خاصة</h4>
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap bg-orange-50 rounded-xl p-4 border border-orange-100">
            {attributes.special_warnings}
          </p>
        </div>
      )}

      {!content.instructions && !content.usage && !content.storage && !attributes.temperature_storage && (
        <p className="text-sm text-gray-400 text-center py-8">لا تتوفر تعليمات لهذا المنتج حتى الآن.</p>
      )}
    </div>
  )
}

// ── Tab: Attributes ───────────────────────────────────────────────────────────

function AttributesTab({ product }) {
  const a = product.attributes || {}

  return (
    <div className="bg-gray-50 rounded-xl p-4 space-y-1">
      <InfoRow label="الاسم العلمي"       value={product.name_scientific} />
      <InfoRow label="المادة الفعالة"     value={product.active_ingredients} />
      <InfoRow label="التصنيف العائلي"    value={product.family_name_ar} />
      <InfoRow label="التصنيف العلاجي"    value={product.effect_name_ar} />
      <InfoRow label="المورد"             value={product.supplier_name} />
      <InfoRow label="الشركة المنتجة"     value={product.producer_name} />
      <InfoRow label="البلد"              value={product.origin_name_ar} />
      <InfoRow label="التركيز / القوة"    value={a.strength} />
      <InfoRow label="تركيز السوائل"      value={a.concentration} />
      <InfoRow label="النكهة"             value={a.flavor} />
      <InfoRow label="اللون"              value={a.color} />
      <InfoRow label="الحجم / الوزن"      value={a.size} />
      <InfoRow label="مواصفات العبوة"     value={a.pack_size_label} />
      {a.count_per_pack && <InfoRow label="العدد في العبوة" value={`${a.count_per_pack}`} />}
      <InfoRow label="الباركود"           value={product.barcode} />
      <InfoRow label="كود SOFTECH"        value={product.softech_id} />
      {a.prescription_required != null && (
        <InfoRow
          label="وصفة طبية"
          value={a.prescription_required ? 'مطلوبة ✓' : 'غير مطلوبة'}
        />
      )}
    </div>
  )
}

// ── Tab: Availability (per branch) ────────────────────────────────────────────

function AvailabilityTab({ productId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['product-availability', productId],
    queryFn: () => productsApi.getAvailability(productId).then(r => r.data),
    staleTime: 30_000,
  })

  if (isLoading) return <div className="text-center py-8 text-sm text-gray-400 animate-pulse">جاري التحميل...</div>

  const branches = data?.branches || []
  const overall  = data?.overall || 'unavailable'

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <span className="text-sm text-gray-500">التوافر العام:</span>
        <AvailBadge status={overall} size="lg" />
      </div>

      {branches.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">لا توجد بيانات مخزون.</p>
      ) : (
        <div className="space-y-2">
          {branches.map(b => {
            const cfg = AVAIL_CONFIG[b.status] || AVAIL_CONFIG.unavailable
            return (
              <div
                key={b.branch_id}
                className="flex items-center justify-between bg-gray-50 rounded-xl px-4 py-3 border border-gray-100"
              >
                <div className="flex items-center gap-2">
                  <div className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
                  <span className="text-sm font-medium text-gray-700">
                    {b.branch_name_ar || b.branch_name}
                  </span>
                </div>
                <AvailBadge status={b.status} />
              </div>
            )
          })}
        </div>
      )}

      <p className="mt-4 text-xs text-gray-400 text-center">
        * التوافر يُحدَّث تلقائياً من نظام الـ ERP
      </p>
    </div>
  )
}

// ── Tab: Related Products ─────────────────────────────────────────────────────

function RelatedTab({ product }) {
  const navigate   = useNavigate()
  const relations  = product.relations || []
  const grouped    = {}

  const RELATION_LABELS = {
    recommended:       'موصى به',
    frequently_bought: 'يُشترى معاً',
    substitute:        'بديل',
    refill:            'إعادة طلب',
    companion:         'مكمل',
    starter_pack:      'حزمة البداية',
  }

  relations.forEach(r => {
    const key = r.relation_type
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(r)
  })

  if (!relations.length) {
    return <p className="text-sm text-gray-400 text-center py-8">لا توجد منتجات مرتبطة حتى الآن.</p>
  }

  return (
    <div className="space-y-6">
      {Object.entries(grouped).map(([type, items]) => (
        <div key={type}>
          <h4 className="text-sm font-bold text-gray-700 mb-3">
            {RELATION_LABELS[type] || type}
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {items.map(rel => {
              const p = rel.to_item
              return (
                <button
                  key={rel.id}
                  onClick={() => navigate(`/products/${p.softech_id}`)}
                  className="flex items-center gap-3 bg-gray-50 hover:bg-brand-50 border border-gray-100
                             hover:border-brand-200 rounded-xl p-3 text-right transition-colors"
                >
                  <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center shrink-0 border border-gray-100">
                    {p.primary_image_url ? (
                      <img src={p.primary_image_url} alt="" className="w-full h-full object-contain rounded-lg" />
                    ) : (
                      <span className="text-xl opacity-30">💊</span>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-gray-700 break-words">{p.display_name_ar || p.name}</p>
                    <p className="text-xs text-gray-400 font-mono">{p.softech_id}</p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Tab: Similar Items ────────────────────────────────────────────────────────

function SimilarTab({ productId }) {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['product-similar', productId],
    queryFn: () => productsApi.getSimilar(productId, { limit: 12 }).then(r => r.data),
    staleTime: 5 * 60_000,
  })

  if (isLoading) return <div className="text-center py-8 text-sm text-gray-400 animate-pulse">جاري التحميل...</div>

  const items = data?.results || []
  const groupLabel = data?.grouped_by || ''

  if (!items.length) {
    return <p className="text-sm text-gray-400 text-center py-8">لا توجد منتجات مشابهة في نفس التصنيف.</p>
  }

  return (
    <div>
      {groupLabel && (
        <p className="text-xs text-brand-600 bg-brand-50 rounded-lg px-3 py-1.5 mb-4 inline-block">
          التصنيف: {groupLabel}
        </p>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {items.map(p => {
          const avail = p.overall_availability || 'unavailable'
          const avCfg = AVAIL_CONFIG[avail] || AVAIL_CONFIG.unavailable
          return (
            <button
              key={p.softech_id}
              onClick={() => navigate(`/products/${p.softech_id}`)}
              className="flex flex-col bg-gray-50 hover:bg-brand-50 border border-gray-100
                         hover:border-brand-200 rounded-xl p-3 text-right transition-colors"
            >
              <div className="flex items-start justify-between mb-2">
                <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center shrink-0 border border-gray-100">
                  {p.primary_image_url ? (
                    <img src={p.primary_image_url} alt="" className="w-full h-full object-contain rounded-lg" />
                  ) : (
                    <span className="text-xl opacity-30">💊</span>
                  )}
                </div>
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${avCfg.cls}`}>{avCfg.label}</span>
              </div>
              <p className="text-xs font-semibold text-gray-700 break-words mb-1 flex-1">
                {p.display_name_ar || p.name}
              </p>
              <div className="flex items-center justify-between mt-1">
                <span className="text-xs font-bold text-gray-700">
                  {p.pack_price ? `${Number(p.pack_price).toFixed(2)} ج` : '—'}
                </span>
                {p.margin_pct != null && (
                  <span className="text-xs text-gray-400">{p.margin_pct}%</span>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Tab: Demand Crosslink ─────────────────────────────────────────────────────

function DemandTab({ productId }) {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['product-demand', productId],
    queryFn: () => productsApi.getDemand(productId).then(r => r.data),
    staleTime: 60_000,
  })

  if (isLoading) return <div className="text-center py-8 text-sm text-gray-400 animate-pulse">جاري التحميل...</div>

  const demands   = data?.demands   || []
  const shortages = data?.shortages || []

  if (!demands.length && !shortages.length) {
    return (
      <div className="text-center py-8 text-gray-400">
        <div className="text-3xl mb-2">✅</div>
        <p className="text-sm">لا يوجد طلب مفتوح أو نقص مسجل لهذا المنتج.</p>
      </div>
    )
  }

  const STATUS_LABELS = {
    new: 'جديد', assigned: 'مُعيَّن', contacted: 'تم التواصل',
    ordered: 'مطلوب', received: 'وصل',
  }

  return (
    <div className="space-y-6">
      {/* Open demands */}
      {demands.length > 0 && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
            <span className="w-2 h-2 bg-amber-400 rounded-full" />
            طلبات مفتوحة ({demands.length})
          </h4>
          <div className="space-y-2">
            {demands.map((d, i) => (
              <button
                key={i}
                onClick={() => navigate(`/demand?q=${d.demand_number}`)}
                className="w-full flex items-center justify-between text-right bg-amber-50 hover:bg-amber-100
                           border border-amber-200 rounded-xl px-4 py-2.5 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-amber-700">{d.demand_number}</span>
                  {d.branch && <span className="text-xs text-gray-600">{d.branch}</span>}
                  {d.customer_name && <span className="text-xs text-gray-500">{d.customer_name}</span>}
                </div>
                <div className="flex items-center gap-2">
                  {d.quantity > 1 && <span className="text-xs text-gray-500">× {d.quantity}</span>}
                  <span className="text-xs bg-white border border-amber-200 text-amber-700 px-2 py-0.5 rounded-full">
                    {STATUS_LABELS[d.status] || d.status}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Open shortages */}
      {shortages.length > 0 && (
        <div>
          <h4 className="text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
            <span className="w-2 h-2 bg-red-400 rounded-full" />
            نواقص مسجلة ({shortages.length})
          </h4>
          <div className="space-y-2">
            {shortages.map((s, i) => (
              <div
                key={i}
                className="flex items-center justify-between bg-red-50 border border-red-200 rounded-xl px-4 py-2.5"
              >
                <span className="text-xs text-red-700">{s.branch}</span>
                <span className="text-xs text-gray-600">كمية مطلوبة: {s.quantity_needed}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Share Button ──────────────────────────────────────────────────────────────

function ShareButton({ productId }) {
  const [copied, setCopied] = useState(false)
  const { data, refetch } = useQuery({
    queryKey: ['product-share', productId],
    queryFn: () => productsApi.getShareCard(productId).then(r => r.data),
    enabled: false,
  })

  const handleShare = async () => {
    const res = await refetch()
    const card = res.data
    if (!card) return
    const text = card.whatsapp_text || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // fallback: open WhatsApp
      const url = `https://wa.me/?text=${encodeURIComponent(text)}`
      window.open(url, '_blank')
    }
  }

  return (
    <button
      onClick={handleShare}
      className="flex items-center gap-2 text-sm px-4 py-2 border border-gray-200 rounded-xl
                 hover:bg-green-50 hover:border-green-300 hover:text-green-700 transition-colors"
    >
      <span>{copied ? '✓' : '📤'}</span>
      <span>{copied ? 'تم النسخ' : 'مشاركة واتساب'}</span>
    </button>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProductDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState('info')

  // Fetch detail
  const { data: product, isLoading, isError } = useQuery({
    queryKey: ['product-detail', id],
    queryFn: () => productsApi.getDetail(id).then(r => r.data),
  })

  // Pick zone (ورقة التجميع) — computed by the replenishment classifier
  const { data: pickZoneMap } = useQuery({
    queryKey: ['catalog-pick-zones', id],
    queryFn: () => pickZonesApi.classifyItems([id]).then(r => r.data),
    enabled: !!id,
    staleTime: 300_000,
  })
  const pickZone = pickZoneMap?.[id]

  // Track view (fire once on mount)
  const trackMutation = useMutation({
    mutationFn: () => productsApi.trackInteraction(id, 'views'),
  })
  useEffect(() => {
    if (id) trackMutation.mutate()
  }, [id])  // eslint-disable-line

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center font-cairo" dir="rtl">
        <div className="text-brand-500 animate-pulse text-lg">جاري التحميل...</div>
      </div>
    )
  }

  if (isError || !product) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center font-cairo gap-4" dir="rtl">
        <div className="text-5xl">❌</div>
        <p className="text-gray-500">المنتج غير موجود</p>
        <button onClick={() => navigate('/products')} className="text-brand-600 hover:underline text-sm">
          العودة للكتالوج
        </button>
      </div>
    )
  }

  const overall = product.overall_availability || 'unavailable'

  return (
    <div className="min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* Breadcrumb */}
      <div className="bg-white border-b border-gray-100 px-6 py-3">
        <div className="max-w-5xl mx-auto flex items-center gap-2 text-sm text-gray-400">
          <button onClick={() => navigate('/products')} className="hover:text-brand-600 transition-colors">
            الكتالوج
          </button>
          <span>›</span>
          <span className="text-gray-600 break-words max-w-xs">
            {product.display_name_ar || product.name}
          </span>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-8">

          {/* LEFT — Gallery + quick info */}
          <div className="md:col-span-2 space-y-4">
            <ImageGallery media={product.all_media} />

            {/* Quick info card */}
            <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <AvailBadge status={overall} size="lg" />
                {product.prescription_required === true && (
                  <span className="text-xs bg-orange-50 text-orange-600 border border-orange-200 px-2 py-1 rounded-full">
                    يحتاج وصفة طبية Rx
                  </span>
                )}
              </div>

              <div>
                <h1 className="text-xl font-bold text-gray-800 leading-snug">
                  {product.display_name_ar || product.name}
                </h1>
                {product.display_name_en && (
                  <p className="text-sm text-gray-400 mt-0.5" dir="ltr">{product.display_name_en}</p>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                {product.effect_name_ar && (
                  <span className="text-sm text-brand-600 bg-brand-50 rounded-lg px-3 py-1.5">
                    {product.effect_name_ar}
                  </span>
                )}
                {product.is_chronic && (
                  <span className="text-sm text-purple-700 bg-purple-50 border border-purple-200 rounded-lg px-3 py-1.5">
                    دواء مزمن
                  </span>
                )}
                {product.is_fast_moving && (
                  <span className="text-sm text-sky-700 bg-sky-50 border border-sky-200 rounded-lg px-3 py-1.5">
                    سريع التداول FMI
                  </span>
                )}
              </div>

              <div className="flex gap-3 text-xs text-gray-400 items-center">
                <span className="font-mono">{product.softech_id}</span>
                {product.barcode && <span className="font-mono">|  {product.barcode}</span>}
                <span className="flex-1" />
                <ShelfQrButton productId={product.id || id} productName={product.display_name_ar || product.name} />
              </div>

              {/* Pricing */}
              {product.pack_price && (
                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-50">
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <p className="text-xs text-gray-400">سعر العبوة</p>
                    <p className="text-sm font-bold text-gray-800">{Number(product.pack_price).toFixed(2)} ج</p>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <p className="text-xs text-gray-400">سعر الوحدة</p>
                    <p className="text-sm font-bold text-gray-800">
                      {product.unit_price ? `${Number(product.unit_price).toFixed(2)} ج` : '—'}
                    </p>
                  </div>
                  {product.margin_pct != null && (
                    <div className={`col-span-2 rounded-lg p-2 text-center ${
                      product.margin_pct >= 30
                        ? 'bg-emerald-50 text-emerald-700'
                        : product.margin_pct >= 15
                          ? 'bg-amber-50 text-amber-700'
                          : 'bg-red-50 text-red-600'
                    }`}>
                      <p className="text-xs opacity-70">هامش الربح</p>
                      <p className="text-sm font-bold">{product.margin_pct}%</p>
                    </div>
                  )}
                </div>
              )}

              {product.temperature_storage === 'refrigerated' && (
                <div className="flex items-center gap-2 text-sky-600 text-sm bg-sky-50 rounded-lg px-3 py-2">
                  <span>❄</span>
                  <span>يحفظ في الثلاجة (2–8°م)</span>
                </div>
              )}

              {pickZone?.zone_name && (
                <div className="flex items-center gap-2 text-teal-700 text-sm bg-teal-50 rounded-lg px-3 py-2"
                  title={pickZone.reason || ''}>
                  <span>📍</span>
                  <span>منطقة التجميع: <b>{pickZone.zone_name}</b></span>
                  {pickZone.tag && (
                    <span className="text-xs bg-white/70 rounded px-1.5 py-0.5">🏷️ {pickZone.tag}</span>
                  )}
                  <span className="text-[10px] text-teal-500">({pickZone.reason})</span>
                </div>
              )}

              {/* Analytics row */}
              {product.experience && (
                <div className="flex gap-4 text-xs text-gray-400 pt-1 border-t border-gray-50">
                  <span>👁 {product.experience.views || 0}</span>
                  <span>📤 {product.experience.shares || 0}</span>
                  <span>📋 {product.experience.reservations || 0} حجز</span>
                </div>
              )}
            </div>

            {/* Share button */}
            <ShareButton productId={id} />

            {/* Admin links */}
            <div className="flex gap-2">
              <Link
                to={`/products/${id}/intel`}
                className="flex-1 flex items-center justify-center gap-2 text-xs text-brand-600 hover:text-brand-700
                           border border-brand-200 bg-brand-50 hover:bg-brand-100 rounded-xl py-2 transition-colors font-medium"
              >
                🔬 ملف الصنف الشامل
              </Link>
              <Link
                to={`/products/${id}/admin`}
                className="flex items-center justify-center gap-2 text-xs text-gray-400 hover:text-brand-500
                           border border-dashed border-gray-200 rounded-xl py-2 px-3 transition-colors"
              >
                🖼 الصور
              </Link>
            </div>
          </div>

          {/* RIGHT — Tabs */}
          <div className="md:col-span-3">
            {/* Tab bar */}
            <div className="flex gap-1 bg-gray-100 rounded-xl p-1 mb-6 overflow-x-auto">
              {TABS.map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex-1 text-xs font-medium px-3 py-2 rounded-lg transition-all whitespace-nowrap
                    ${activeTab === tab.key
                      ? 'bg-white text-brand-700 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="bg-white rounded-xl border border-gray-100 p-5 min-h-[300px]">
              {activeTab === 'info'         && <OverviewTab product={product} />}
              {activeTab === 'instructions' && <InstructionsTab product={product} />}
              {activeTab === 'attributes'   && <AttributesTab product={product} />}
              {activeTab === 'availability' && <AvailabilityTab productId={id} />}
              {activeTab === 'similar'      && <SimilarTab productId={id} />}
              {activeTab === 'related'      && <RelatedTab product={product} />}
              {activeTab === 'demand'       && <DemandTab productId={id} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
