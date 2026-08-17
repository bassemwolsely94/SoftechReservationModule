/**
 * ProductCatalogPage.jsx
 *
 * Catalog features:
 *   - Full-text search across 37,500+ items (no cap when query applied)
 *   - Filters: availability, effect, shape, insurance type, fridge, chronic, FMI, Rx
 *   - View tabs: Catalog | Fast Moving | Bundles | Low Stock | Recent
 *   - Grid / list view toggle
 *   - Margin % display (pack_price - cost_price)
 *   - Chronic medication badge
 *   - Barcode scanner (device camera → navigate to item)
 *   - Item comparison (up to 3 items → floating compare panel)
 *   - Price list export to Excel
 *   - Ordering: popular | newest synced | price asc/desc | A–Z
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { productsApi, itemsApi, pickZonesApi } from '../api/client'
import { useQuery, useQueryClient } from '@tanstack/react-query'

// ── Helpers ───────────────────────────────────────────────────────────────────

const AVAIL_CONFIG = {
  available:   { label: 'متاح',          cls: 'bg-emerald-100 text-emerald-700 border border-emerald-200' },
  limited:     { label: 'كميات محدودة',  cls: 'bg-amber-100 text-amber-700 border border-amber-200' },
  unavailable: { label: 'غير متاح',      cls: 'bg-red-100 text-red-600 border border-red-200' },
}

const INSURANCE_LABELS = {
  '0': 'غير خاضع للتأمين',
  '1': 'طلبية',
  '2': 'TPA',
  '3': 'تكافل',
  '4': 'أخرى',
}

const ORDERING_OPTIONS = [
  { value: 'popular',    label: 'الأكثر شهرة' },
  { value: 'newest',     label: 'آخر مزامنة' },
  { value: 'price_asc',  label: 'السعر: الأقل أولاً' },
  { value: 'price_desc', label: 'السعر: الأعلى أولاً' },
  { value: 'name_asc',   label: 'أبجدي' },
]

const VIEW_TABS = [
  { key: 'catalog',     label: 'الكتالوج' },
  { key: 'fmi',         label: 'سريع التداول' },
  { key: 'low_stock',   label: 'مخزون منخفض' },
  { key: 'bundles',     label: 'الباقات' },
  { key: 'recent',      label: 'آخر تحديث' },
]

function AvailBadge({ status }) {
  const cfg = AVAIL_CONFIG[status] || AVAIL_CONFIG.unavailable
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

function MarginBadge({ pct }) {
  if (pct == null) return null
  const cls = pct >= 30
    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
    : pct >= 15
      ? 'bg-amber-50 text-amber-700 border border-amber-200'
      : 'bg-red-50 text-red-600 border border-red-200'
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${cls}`} title="هامش الربح">
      {pct}%
    </span>
  )
}

function useDebounce(value, delay = 350) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

// ── ProductCard ────────────────────────────────────────────────────────────────

function ProductCard({ product, onClick, onCompareToggle, isCompared, pickZone }) {
  const media = product.primary_image_url
  const avail = product.overall_availability || 'unavailable'

  return (
    <div className="relative bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden
                    hover:shadow-md hover:border-brand-200 transition-all duration-150 group">
      {/* Compare checkbox */}
      <button
        onClick={e => { e.stopPropagation(); onCompareToggle(product) }}
        title="إضافة للمقارنة"
        className={`absolute top-2 left-2 z-10 w-6 h-6 rounded-full border-2 flex items-center justify-center transition-all
          ${isCompared
            ? 'bg-brand-600 border-brand-600 text-white'
            : 'bg-white border-gray-300 text-transparent hover:border-brand-400'}`}
      >
        {isCompared && <span className="text-xs">✓</span>}
      </button>

      <div onClick={() => onClick(product)} className="cursor-pointer">
        {/* Image */}
        <div className="relative h-40 bg-gray-50 flex items-center justify-center overflow-hidden">
          {media ? (
            <img
              src={media}
              alt={product.display_name_ar || product.name}
              className="h-full w-full object-contain group-hover:scale-105 transition-transform duration-200"
              loading="lazy"
              onError={e => { e.target.style.display = 'none' }}
            />
          ) : (
            <div className="text-5xl opacity-20">💊</div>
          )}
          <div className="absolute top-2 right-2">
            <AvailBadge status={avail} />
          </div>
          {product.prescription_required === true && (
            <div className="absolute bottom-2 left-2 bg-orange-100 text-orange-600 text-xs px-1.5 py-0.5 rounded border border-orange-200">
              Rx
            </div>
          )}
          {product.is_chronic && (
            <div className="absolute bottom-2 right-2 bg-purple-100 text-purple-700 text-xs px-1.5 py-0.5 rounded border border-purple-200">
              مزمن
            </div>
          )}
          {product.is_fast_moving && (
            <div className="absolute top-2 left-8 bg-sky-100 text-sky-700 text-xs px-1.5 py-0.5 rounded border border-sky-200">
              FMI
            </div>
          )}
        </div>

        {/* Body */}
        <div className="p-3">
          <p className="text-sm font-semibold text-gray-800 break-words leading-snug min-h-[2.5rem]">
            {product.display_name_ar || product.name || '—'}
          </p>
          {product.display_name_en && (
            <p className="text-xs text-gray-400 mt-0.5 break-words" dir="ltr">{product.display_name_en}</p>
          )}

          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-gray-400 font-mono">{product.softech_id}</span>
            <span className="flex items-center gap-1">
              {pickZone?.zone_name && (
                <span className="text-[10px] bg-teal-50 text-teal-700 rounded px-1.5 py-0.5"
                  title={'منطقة التجميع — ' + (pickZone.reason || '')}>
                  📍 {pickZone.zone_name}
                </span>
              )}
              {product.requires_fridge && <span className="text-xs text-sky-500">❄</span>}
            </span>
          </div>

          {product.effect_name_ar && (
            <p className="mt-1.5 text-xs text-brand-600 bg-brand-50 rounded px-2 py-0.5 truncate">
              {product.effect_name_ar}
            </p>
          )}

          {/* Pricing row */}
          <div className="mt-2 flex items-center justify-between gap-1">
            <span className="text-sm font-bold text-gray-700">
              {product.pack_price ? `${Number(product.pack_price).toFixed(2)} ج` : '—'}
            </span>
            <MarginBadge pct={product.margin_pct} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── ProductRow (list view) ─────────────────────────────────────────────────────

function ProductRow({ product, onClick, onCompareToggle, isCompared, pickZone }) {
  const avail = product.overall_availability || 'unavailable'
  return (
    <div className="flex items-center gap-4 bg-white rounded-lg border border-gray-100 px-4 py-3
                    hover:bg-brand-50 hover:border-brand-200 transition-colors duration-100">
      {/* Compare */}
      <button
        onClick={() => onCompareToggle(product)}
        className={`w-5 h-5 shrink-0 rounded border-2 flex items-center justify-center transition-all
          ${isCompared ? 'bg-brand-600 border-brand-600 text-white' : 'border-gray-300 hover:border-brand-400'}`}
      >
        {isCompared && <span className="text-xs">✓</span>}
      </button>

      {/* Thumbnail */}
      <div
        onClick={() => onClick(product)}
        className="w-12 h-12 bg-gray-50 rounded-lg flex items-center justify-center overflow-hidden shrink-0 cursor-pointer"
      >
        {product.primary_image_url ? (
          <img src={product.primary_image_url} alt="" className="w-full h-full object-contain" loading="lazy" />
        ) : (
          <span className="text-2xl opacity-20">💊</span>
        )}
      </div>

      {/* Name + code */}
      <div className="flex-1 min-w-[140px] cursor-pointer" onClick={() => onClick(product)}>
        <p className="text-sm font-semibold text-gray-800 break-words">
          {product.display_name_ar || product.name}
          {product.is_chronic && <span className="mr-1.5 text-xs text-purple-600 bg-purple-50 rounded px-1">مزمن</span>}
          {product.is_fast_moving && <span className="mr-1 text-xs text-sky-600 bg-sky-50 rounded px-1">FMI</span>}
        </p>
        <p className="text-xs text-gray-400 font-mono" dir="ltr">{product.softech_id}</p>
      </div>

      {/* Effect */}
      <div className="hidden md:block w-36 text-xs text-gray-500 truncate text-center">
        {product.effect_name_ar || '—'}
      </div>

      {/* Pick zone (ورقة التجميع) */}
      <div className="hidden lg:block w-24 text-center">
        {pickZone?.zone_name ? (
          <span className="text-[10px] bg-teal-50 text-teal-700 rounded px-1.5 py-0.5"
            title={'منطقة التجميع — ' + (pickZone.reason || '')}>
            📍 {pickZone.zone_name}
          </span>
        ) : <span className="text-xs text-gray-300">—</span>}
      </div>

      {/* Price */}
      <div className="hidden sm:block w-24 text-sm font-bold text-gray-700 text-center">
        {product.pack_price ? `${Number(product.pack_price).toFixed(2)} ج` : '—'}
      </div>

      {/* Margin */}
      <div className="hidden lg:flex w-16 justify-center">
        <MarginBadge pct={product.margin_pct} />
      </div>

      {/* Availability */}
      <div className="w-28 text-center">
        <AvailBadge status={avail} />
      </div>

      {/* Indicators */}
      <div className="flex items-center gap-1 text-xs shrink-0">
        {product.prescription_required === true && <span className="text-orange-500">Rx</span>}
        {product.requires_fridge && <span className="text-sky-400">❄</span>}
        {product.insurance_type && product.insurance_type !== '0' && (
          <span className="text-green-600" title={INSURANCE_LABELS[product.insurance_type]}>🏥</span>
        )}
      </div>
    </div>
  )
}

// ── FilterPanel ───────────────────────────────────────────────────────────────

function FilterPanel({ filters, onChange, options }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-4 sticky top-20">
      <h3 className="text-sm font-bold text-gray-700">تصفية النتائج</h3>

      {/* Availability */}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-1.5">التوافر</p>
        <div className="space-y-1">
          {[['', 'الكل'], ['available', 'متاح'], ['limited', 'محدود'], ['unavailable', 'غير متاح']].map(([val, lbl]) => (
            <label key={val} className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="radio" name="avail" value={val}
                checked={filters.availability === val}
                onChange={() => onChange({ ...filters, availability: val })}
                className="accent-brand-600"
              />
              {lbl}
            </label>
          ))}
        </div>
      </div>

      {/* Effect */}
      {options?.effects?.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-1.5">التصنيف العلاجي</p>
          <select
            value={filters.effect_code || ''}
            onChange={e => onChange({ ...filters, effect_code: e.target.value })}
            className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">الكل</option>
            {options.effects.map(e => (
              <option key={e.code} value={e.code}>{e.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Shape */}
      {options?.shapes?.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-1.5">الشكل الصيدلي</p>
          <select
            value={filters.shape_code || ''}
            onChange={e => onChange({ ...filters, shape_code: e.target.value })}
            className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">الكل</option>
            {options.shapes.map(s => (
              <option key={s.code} value={s.code}>{s.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Insurance type */}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-1.5">التأمين الصحي</p>
        <select
          value={filters.insurance_type || ''}
          onChange={e => onChange({ ...filters, insurance_type: e.target.value })}
          className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
        >
          <option value="">الكل</option>
          {Object.entries(INSURANCE_LABELS).map(([code, label]) => (
            <option key={code} value={code}>{label}</option>
          ))}
        </select>
      </div>

      {/* Special flags */}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-1.5">خيارات إضافية</p>
        <div className="space-y-1.5">
          {[
            ['requires_fridge',   'يحفظ في الثلاجة ❄'],
            ['prescription_required', 'يحتاج وصفة Rx'],
            ['is_chronic',        'دواء مزمن 🏥'],
            ['is_fast_moving',    'سريع التداول FMI'],
            ['has_image',         'لديه صورة 🖼'],
          ].map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={!!filters[key]}
                onChange={e => onChange({ ...filters, [key]: e.target.checked || undefined })}
                className="accent-brand-600"
              />
              {label}
            </label>
          ))}
        </div>
      </div>

      {/* Reset */}
      <button
        onClick={() => onChange({ availability: '' })}
        className="w-full text-xs text-gray-400 hover:text-red-500 border border-dashed border-gray-200
                   rounded-lg py-1.5 transition-colors"
      >
        ↺ مسح الفلاتر
      </button>
    </div>
  )
}

// ── Barcode Scanner Modal ─────────────────────────────────────────────────────

function BarcodeScannerModal({ onClose, onFound }) {
  const videoRef   = useRef(null)
  const streamRef  = useRef(null)
  const [manual, setManual] = useState('')
  const [error, setError]   = useState('')

  useEffect(() => {
    let interval
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: 'environment' } })
      .then(stream => {
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        // Attempt barcode detection API (Chrome 83+)
        if ('BarcodeDetector' in window) {
          const detector = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'code_39'] })
          interval = setInterval(async () => {
            if (!videoRef.current) return
            try {
              const codes = await detector.detect(videoRef.current)
              if (codes.length > 0) {
                clearInterval(interval)
                onFound(codes[0].rawValue)
              }
            } catch { /* ignore */ }
          }, 500)
        }
      })
      .catch(() => setError('لا يمكن الوصول للكاميرا. استخدم البحث اليدوي.'))

    return () => {
      clearInterval(interval)
      streamRef.current?.getTracks().forEach(t => t.stop())
    }
  }, [onFound])

  const handleManual = () => {
    if (manual.trim()) onFound(manual.trim())
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-800">مسح الباركود</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {error ? (
          <p className="text-sm text-red-500 bg-red-50 rounded-lg p-3">{error}</p>
        ) : (
          <div className="relative h-52 bg-black rounded-xl overflow-hidden flex items-center justify-center">
            <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-cover" />
            <div className="absolute inset-0 border-2 border-brand-400 rounded-xl pointer-events-none" />
            <p className="absolute bottom-2 text-white text-xs bg-black/50 px-2 py-0.5 rounded">
              وجّه الكاميرا نحو الباركود
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            value={manual}
            onChange={e => setManual(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleManual()}
            placeholder="أدخل الباركود يدوياً"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-300"
          />
          <button
            onClick={handleManual}
            className="bg-brand-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-brand-700"
          >بحث</button>
        </div>
      </div>
    </div>
  )
}

// ── Comparison Panel ──────────────────────────────────────────────────────────

function ComparePanel({ items, onRemove, onClear, onNavigate }) {
  const [expanded, setExpanded] = useState(false)

  if (!items.length) return null

  const FIELDS = [
    { key: 'pack_price',     label: 'سعر العبوة',    fmt: v => v ? `${Number(v).toFixed(2)} ج` : '—' },
    { key: 'unit_price',     label: 'سعر الوحدة',    fmt: v => v ? `${Number(v).toFixed(2)} ج` : '—' },
    { key: 'margin_pct',     label: 'هامش الربح',    fmt: v => v != null ? `${v}%` : '—' },
    { key: 'effect_name_ar', label: 'التصنيف العلاجي', fmt: v => v || '—' },
    { key: 'shape_name_ar',  label: 'الشكل الصيدلي', fmt: v => v || '—' },
    { key: 'supplier_name',  label: 'المورد',         fmt: v => v || '—' },
    { key: 'overall_availability', label: 'التوافر', fmt: v => AVAIL_CONFIG[v]?.label || '—' },
    { key: 'requires_fridge', label: 'ثلاجة',        fmt: v => v ? '❄ نعم' : 'لا' },
    { key: 'is_fast_moving',  label: 'FMI',           fmt: v => v ? '✓' : '—' },
    { key: 'is_chronic',      label: 'مزمن',          fmt: v => v ? '✓' : '—' },
  ]

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 bg-white border-t-2 border-brand-400 shadow-2xl" dir="rtl">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-brand-600 text-white">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold">المقارنة ({items.length}/3)</span>
          <div className="flex gap-2">
            {items.map(p => (
              <div key={p.softech_id} className="flex items-center gap-1 bg-white/20 rounded-full px-2 py-0.5 text-xs">
                <span className="break-words max-w-[10rem]">{p.display_name_ar || p.name}</span>
                <button onClick={() => onRemove(p.softech_id)} className="hover:text-red-300">✕</button>
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setExpanded(v => !v)} className="text-xs underline hover:no-underline">
            {expanded ? 'إخفاء التفاصيل' : 'عرض التفاصيل'}
          </button>
          <button onClick={onClear} className="text-xs text-red-200 hover:text-white">مسح الكل</button>
        </div>
      </div>

      {/* Comparison table */}
      {expanded && (
        <div className="overflow-x-auto max-h-72 overflow-y-auto">
          <table className="w-full text-sm border-collapse">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-4 py-2 text-right text-xs text-gray-500 font-medium w-32">الخاصية</th>
                {items.map(p => (
                  <th key={p.softech_id} className="px-4 py-2 text-center">
                    <button
                      onClick={() => onNavigate(p.softech_id)}
                      className="text-xs font-bold text-brand-600 hover:underline break-words"
                    >
                      {p.display_name_ar || p.name}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FIELDS.map(({ key, label, fmt }) => (
                <tr key={key} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2 text-xs text-gray-500 font-medium">{label}</td>
                  {items.map(p => (
                    <td key={p.softech_id} className="px-4 py-2 text-center text-sm text-gray-700">
                      {fmt(p[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Bundle Tab Content ────────────────────────────────────────────────────────

function BundleTab({ onNavigate }) {
  const { data, isLoading } = useQuery({
    queryKey: ['product-bundles'],
    queryFn: () => itemsApi.listBundles({ active: true }).then(r => r.data),
    staleTime: 2 * 60_000,
  })

  const bundles = Array.isArray(data) ? data : (data?.results || [])

  if (isLoading) return <div className="py-10 text-center text-sm text-gray-400 animate-pulse">جاري التحميل...</div>
  if (!bundles.length) return (
    <div className="py-20 text-center text-gray-400">
      <div className="text-5xl mb-3">📦</div>
      <p className="text-sm">لا توجد باقات نشطة حتى الآن.</p>
    </div>
  )

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {bundles.map(bundle => (
        <div key={bundle.id} className="bg-white rounded-xl border border-gray-100 p-4 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h3 className="font-bold text-gray-800 text-sm">{bundle.name_ar || bundle.name}</h3>
              {bundle.description && (
                <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{bundle.description}</p>
              )}
            </div>
            {bundle.discount_type !== 'none' && (
              <span className="bg-red-50 text-red-600 text-xs px-2 py-0.5 rounded-full border border-red-200 shrink-0 mr-2">
                {bundle.discount_type === 'pct' ? `${bundle.discount_value}%` : `${bundle.discount_value} ج`} خصم
              </span>
            )}
          </div>

          <div className="space-y-1.5">
            {(bundle.items || []).map(bi => (
              <button
                key={bi.id}
                onClick={() => onNavigate(bi.item_code)}
                className="w-full flex items-center justify-between text-right text-xs bg-gray-50 hover:bg-brand-50
                           hover:text-brand-600 rounded-lg px-3 py-1.5 transition-colors"
              >
                <span className="min-w-0 break-words">{bi.item_name}</span>
                <span className="font-mono text-gray-400 shrink-0 mr-2">× {bi.quantity}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProductCatalogPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [query,       setQuery]       = useState(searchParams.get('q') || '')
  const [viewMode,    setViewMode]    = useState('grid')    // grid | list
  const [viewTab,     setViewTab]     = useState('catalog') // catalog | fmi | low_stock | bundles | recent
  const [page,        setPage]        = useState(1)
  const [ordering,    setOrdering]    = useState('popular')
  const [showFilters, setShowFilters] = useState(false)
  const [compareList, setCompareList] = useState([])        // up to 3 items
  const [showScanner, setShowScanner] = useState(false)
  const [exporting,   setExporting]   = useState(false)

  const [filters, setFilters] = useState({
    availability:          searchParams.get('availability') || '',
    effect_code:           searchParams.get('effect_code') || '',
    shape_code:            searchParams.get('shape_code') || '',
    insurance_type:        '',
    requires_fridge:       false,
    prescription_required: false,
    is_chronic:            false,
    is_fast_moving:        false,
    has_image:             false,
  })

  const debouncedQuery = useDebounce(query)
  const inputRef = useRef(null)

  // Sync URL params
  useEffect(() => {
    const p = {}
    if (debouncedQuery)         p.q            = debouncedQuery
    if (filters.availability)   p.availability = filters.availability
    if (filters.effect_code)    p.effect_code  = filters.effect_code
    if (filters.shape_code)     p.shape_code   = filters.shape_code
    setSearchParams(p, { replace: true })
    setPage(1)
  }, [debouncedQuery, filters])  // eslint-disable-line

  // Tab-specific overrides
  const tabFilters = viewTab === 'fmi'
    ? { is_fast_moving: true }
    : viewTab === 'low_stock'
      ? { availability: 'limited' }
      : viewTab === 'recent'
        ? {}   // uses ordering=newest below
        : {}

  const tabOrdering = viewTab === 'recent' ? 'newest' : ordering

  const activeFilterCount = Object.entries(filters).filter(([k, v]) =>
    k !== 'availability' && !!v
  ).length + (filters.availability ? 1 : 0)

  const apiParams = {
    page,
    page_size: viewMode === 'grid' ? 24 : 40,
    ordering: tabOrdering,
    // "Recent" tab browses the whole catalog ordered by newest — no search needed.
    ...(viewTab === 'recent' && { browse: 1 }),
    ...(debouncedQuery && { q: debouncedQuery }),
    ...Object.fromEntries(
      Object.entries({ ...filters, ...tabFilters }).filter(([, v]) => v !== '' && v !== false && v !== undefined)
    ),
  }

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['product-catalog', apiParams],
    queryFn: () => productsApi.list(apiParams).then(r => r.data),
    keepPreviousData: true,
    enabled: viewTab !== 'bundles',
  })

  const { data: filterOptions } = useQuery({
    queryKey: ['product-filter-options'],
    queryFn: () => productsApi.filterOptions().then(r => r.data),
    staleTime: 10 * 60_000,
  })

  const products      = data?.results || []

  // Pick-zone classification for the visible page (ورقة التجميع column)
  const productCodes = products.map(p => p.softech_id).filter(Boolean)
  const { data: pickZoneMap = {} } = useQuery({
    queryKey: ['catalog-pick-zones', productCodes.join(',')],
    queryFn: () => pickZonesApi.classifyItems(productCodes).then(r => r.data),
    enabled: productCodes.length > 0,
    staleTime: 300_000,
  })
  const totalCount    = data?.count || 0
  const requiresSearch = data?.requires_search === true
  const totalPages    = Math.ceil(totalCount / (viewMode === 'grid' ? 24 : 40))

  const handleProductClick = useCallback(product => {
    navigate(`/products/${product.softech_id}`)
  }, [navigate])

  // ── Compare ────────────────────────────────────────────────────────────────
  const handleCompareToggle = useCallback(product => {
    setCompareList(prev => {
      const exists = prev.find(p => p.softech_id === product.softech_id)
      if (exists) return prev.filter(p => p.softech_id !== product.softech_id)
      if (prev.length >= 3) return prev
      return [...prev, product]
    })
  }, [])

  // ── Barcode scanner result ─────────────────────────────────────────────────
  const handleBarcodeFound = useCallback(async barcode => {
    setShowScanner(false)
    try {
      const res = await productsApi.getByBarcode(barcode)
      if (res.data?.softech_id) {
        navigate(`/products/${res.data.softech_id}`)
      }
    } catch {
      setQuery(barcode)
    }
  }, [navigate])

  // ── Export ─────────────────────────────────────────────────────────────────
  const handleExport = async () => {
    setExporting(true)
    try {
      const exportParams = {
        ...(debouncedQuery && { q: debouncedQuery }),
        ...Object.fromEntries(
          Object.entries({ ...filters, ...tabFilters }).filter(([, v]) => v !== '' && v !== false && v !== undefined)
        ),
      }
      const res = await productsApi.export(exportParams)
      const url = URL.createObjectURL(new Blob([res.data]))
      const a   = document.createElement('a')
      a.href    = url
      a.download = 'catalog_export.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('فشل التصدير. حاول مجدداً.')
    } finally {
      setExporting(false)
    }
  }

  // ── Tab change: reset page ─────────────────────────────────────────────────
  const handleTabChange = tab => {
    setViewTab(tab)
    setPage(1)
  }

  return (
    <div className="min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-100 px-6 py-4 sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto space-y-3">

          {/* Title + search + actions */}
          <div className="flex items-center gap-4">
            <div className="shrink-0">
              <h1 className="text-xl font-bold text-gray-800">كتالوج المنتجات</h1>
              <p className="text-xs text-gray-400">
                {isLoading
                  ? 'جاري التحميل...'
                  : requiresSearch && viewTab === 'catalog'
                    ? 'ابحث للاستعراض'
                    : `${totalCount.toLocaleString('en-US')} منتج`}
              </p>
            </div>

            {/* Search */}
            <div className="flex-1 relative max-w-2xl">
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="ابحث بالاسم، الكود، الباركود، المادة الفعالة..."
                className="w-full border border-gray-200 rounded-xl pr-9 pl-4 py-2.5 text-sm
                           focus:outline-none focus:ring-2 focus:ring-brand-300"
              />
              {query && (
                <button
                  onClick={() => setQuery('')}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"
                >×</button>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 shrink-0">
              {/* Barcode scanner */}
              <button
                onClick={() => setShowScanner(true)}
                className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-gray-200
                           bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                title="مسح باركود"
              >
                📷
              </button>

              {/* Export */}
              <button
                onClick={handleExport}
                disabled={exporting}
                className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-gray-200
                           bg-white text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
                title="تصدير Excel"
              >
                {exporting ? '⏳' : '⬇'} Excel
              </button>

              {/* Ordering */}
              <select
                value={ordering}
                onChange={e => { setOrdering(e.target.value); setPage(1) }}
                className="text-sm border border-gray-200 rounded-lg px-2 py-2 bg-white text-gray-600"
              >
                {ORDERING_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>

              {/* Filter toggle */}
              <button
                onClick={() => setShowFilters(v => !v)}
                className={`flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border transition-colors
                  ${showFilters
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}`}
              >
                ⚙ فلتر
                {activeFilterCount > 0 && (
                  <span className="bg-amber-400 text-white text-xs w-4 h-4 rounded-full flex items-center justify-center">
                    {activeFilterCount}
                  </span>
                )}
              </button>

              {/* View mode */}
              <div className="flex border border-gray-200 rounded-lg overflow-hidden">
                {[['grid', '⊞'], ['list', '≡']].map(([mode, icon]) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-2 text-sm transition-colors
                      ${viewMode === mode ? 'bg-brand-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* View tabs */}
          <div className="flex gap-1">
            {VIEW_TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => handleTabChange(tab.key)}
                className={`text-xs font-medium px-4 py-1.5 rounded-lg transition-all
                  ${viewTab === tab.key
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'}`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex gap-6">

          {/* Filter sidebar */}
          {showFilters && viewTab !== 'bundles' && (
            <aside className="w-60 shrink-0">
              <FilterPanel
                filters={filters}
                onChange={f => { setFilters(f); setPage(1) }}
                options={filterOptions}
              />
            </aside>
          )}

          {/* Main content */}
          <div className="flex-1 min-w-0">

            {/* Bundles tab */}
            {viewTab === 'bundles' && (
              <BundleTab onNavigate={code => navigate(`/products/${code}`)} />
            )}

            {/* Loading */}
            {viewTab !== 'bundles' && (isLoading || isFetching) && (
              <div className="text-center py-10 text-brand-500 animate-pulse text-sm">جاري التحميل...</div>
            )}

            {/* Empty states */}
            {viewTab !== 'bundles' && !isLoading && (requiresSearch || products.length === 0) && (
              <div className="text-center py-24 text-gray-400">
                {requiresSearch ? (
                  <>
                    <div className="text-6xl mb-4 opacity-60">🔍</div>
                    <p className="text-base font-medium text-gray-600">ابحث في الكتالوج</p>
                    <p className="text-sm mt-1 text-gray-400">
                      اكتب اسم المنتج أو الكود أو الباركود أو المادة الفعالة للبحث في جميع الأصناف
                    </p>
                    <button
                      onClick={() => setShowScanner(true)}
                      className="mt-4 text-brand-600 text-sm border border-brand-200 rounded-xl px-4 py-2 hover:bg-brand-50"
                    >
                      📷 أو امسح الباركود
                    </button>
                  </>
                ) : (
                  <>
                    <div className="text-5xl mb-3">📭</div>
                    <p className="text-sm">لا توجد نتائج مطابقة</p>
                    {(query || activeFilterCount > 0) && (
                      <button
                        onClick={() => { setQuery(''); setFilters({ availability: '' }); setPage(1) }}
                        className="mt-3 text-brand-500 text-xs hover:underline"
                      >
                        مسح البحث والفلاتر
                      </button>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Grid view */}
            {viewTab !== 'bundles' && !isLoading && products.length > 0 && viewMode === 'grid' && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {products.map(p => (
                  <ProductCard
                    key={p.id}
                    product={p}
                    pickZone={pickZoneMap[p.softech_id]}
                    onClick={handleProductClick}
                    onCompareToggle={handleCompareToggle}
                    isCompared={compareList.some(c => c.softech_id === p.softech_id)}
                  />
                ))}
              </div>
            )}

            {/* List view */}
            {viewTab !== 'bundles' && !isLoading && products.length > 0 && viewMode === 'list' && (
              <div className="space-y-2">
                <div className="flex items-center gap-4 px-4 py-2 text-xs text-gray-400 font-medium">
                  <div className="w-5" />
                  <div className="w-12" />
                  <div className="flex-1">اسم المنتج</div>
                  <div className="hidden md:block w-36 text-center">التصنيف العلاجي</div>
                  <div className="hidden lg:block w-24 text-center">منطقة التجميع</div>
                  <div className="hidden sm:block w-24 text-center">السعر</div>
                  <div className="hidden lg:block w-16 text-center">الهامش</div>
                  <div className="w-28 text-center">التوافر</div>
                  <div className="w-16" />
                </div>
                {products.map(p => (
                  <ProductRow
                    key={p.id}
                    product={p}
                    pickZone={pickZoneMap[p.softech_id]}
                    onClick={handleProductClick}
                    onCompareToggle={handleCompareToggle}
                    isCompared={compareList.some(c => c.softech_id === p.softech_id)}
                  />
                ))}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && viewTab !== 'bundles' && (
              <div className="flex items-center justify-center gap-2 mt-8">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  ‹ السابق
                </button>
                <span className="text-sm text-gray-500">صفحة {page} من {totalPages}</span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  التالي ›
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Barcode scanner modal */}
      {showScanner && (
        <BarcodeScannerModal
          onClose={() => setShowScanner(false)}
          onFound={handleBarcodeFound}
        />
      )}

      {/* Comparison panel */}
      <ComparePanel
        items={compareList}
        onRemove={id => setCompareList(prev => prev.filter(p => p.softech_id !== id))}
        onClear={() => setCompareList([])}
        onNavigate={id => navigate(`/products/${id}`)}
      />

      {/* Bottom padding when compare panel is open */}
      {compareList.length > 0 && <div className="h-16" />}
    </div>
  )
}
