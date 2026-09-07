/**
 * CustomerLocationsPanel.jsx
 * Reusable panel showing all locations for a customer.
 * Used in CustomerDetailPage and inline in reservation/demand create forms.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { customersApi } from '../api/client'

const LABEL_OPTIONS = [
  { value: 'home',     label: '🏠 المنزل' },
  { value: 'work',     label: '💼 العمل' },
  { value: 'relative', label: '👨‍👩‍👧 قريب' },
  { value: 'other',    label: '📍 أخرى' },
]

const LABEL_ICONS = { home: '🏠', work: '💼', relative: '👨‍👩‍👧', other: '📍' }

// ── WhatsApp share buttons ────────────────────────────────────────────────────

function WhatsAppButtons({ loc }) {
  const [copied, setCopied] = useState(false)

  function copyText() {
    navigator.clipboard.writeText(loc.whatsapp_message || loc.address_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex items-center gap-1.5 mt-2 flex-wrap">
      {loc.maps_url && (
        <a href={loc.maps_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2.5 py-1 rounded-lg hover:bg-blue-100 transition-colors">
          🗺️ الخريطة
        </a>
      )}
      {loc.whatsapp_url && (
        <a href={loc.whatsapp_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs bg-green-50 text-green-700 border border-green-200 px-2.5 py-1 rounded-lg hover:bg-green-100 transition-colors">
          💬 واتساب + العنوان
        </a>
      )}
      {loc.whatsapp_url_bare && (
        <a href={loc.whatsapp_url_bare} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 border border-gray-200 px-2.5 py-1 rounded-lg hover:bg-gray-100 transition-colors">
          📞 واتساب فقط
        </a>
      )}
      <button onClick={copyText}
        className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 border border-gray-200 px-2.5 py-1 rounded-lg hover:bg-gray-100 transition-colors">
        {copied ? '✓ تم النسخ' : '📋 نسخ العنوان'}
      </button>
    </div>
  )
}

// ── Location Form ─────────────────────────────────────────────────────────────

function LocationForm({ initial = {}, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    label:           initial.label        || 'home',
    label_custom:    initial.label_custom  || '',
    address_text:    initial.address_text  || '',
    area:            initial.area          || '',
    city:            initial.city          || 'القاهرة',
    floor:           initial.floor         || '',
    apartment:       initial.apartment     || '',
    landmark:        initial.landmark      || '',
    google_maps_link: initial.google_maps_link || '',
    delivery_phone:  initial.delivery_phone || '',
    delivery_notes:  initial.delivery_notes || '',
    is_default:      initial.is_default    || false,
    notes:           initial.notes         || '',
  })

  const f = (field) => (e) => setForm(p => ({ ...p, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3" dir="rtl">
      <div className="text-xs font-bold text-gray-600 mb-2">
        {initial.id ? 'تعديل العنوان' : 'إضافة عنوان جديد'}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label text-xs">نوع العنوان</label>
          <select className="input-field" value={form.label} onChange={f('label')}>
            {LABEL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label text-xs">تسمية مخصصة (اختياري)</label>
          <input className="input-field" placeholder="مثال: بيت الوالدين"
            value={form.label_custom} onChange={f('label_custom')} />
        </div>
      </div>

      <div>
        <label className="label text-xs">العنوان التفصيلي *</label>
        <textarea rows={2} className="input-field resize-none"
          placeholder="الشارع والبناية..."
          value={form.address_text} onChange={f('address_text')} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label text-xs">المنطقة</label>
          <input className="input-field" placeholder="مصر الجديدة"
            value={form.area} onChange={f('area')} />
        </div>
        <div>
          <label className="label text-xs">الدور</label>
          <input className="input-field" placeholder="3"
            value={form.floor} onChange={f('floor')} />
        </div>
        <div>
          <label className="label text-xs">رقم الشقة</label>
          <input className="input-field" placeholder="12"
            value={form.apartment} onChange={f('apartment')} />
        </div>
      </div>

      <div>
        <label className="label text-xs">علامة مميزة</label>
        <input className="input-field" placeholder="أمام مسجد النور، بجانب بنك مصر..."
          value={form.landmark} onChange={f('landmark')} />
      </div>

      <div>
        <label className="label text-xs">رابط خرائط جوجل (اختياري)</label>
        <input className="input-field font-mono text-sm" dir="ltr"
          placeholder="https://maps.google.com/..."
          value={form.google_maps_link} onChange={f('google_maps_link')} />
        <p className="text-xs text-gray-400 mt-0.5">
          افتح الموقع في خرائط جوجل → Share → انسخ الرابط هنا
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label text-xs">هاتف التوصيل (إذا مختلف)</label>
          <input className="input-field" dir="ltr"
            placeholder="010xxxxxxxx"
            value={form.delivery_phone} onChange={f('delivery_phone')} />
        </div>
        <div>
          <label className="label text-xs">تعليمات للمندوب</label>
          <input className="input-field"
            placeholder="اتصل قبل الوصول بـ 30 دقيقة"
            value={form.delivery_notes} onChange={f('delivery_notes')} />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
        <input type="checkbox" checked={form.is_default} onChange={f('is_default')} />
        تعيين كعنوان افتراضي
      </label>

      <div className="flex gap-2 pt-1">
        <button onClick={() => onSave(form)} disabled={saving || !form.address_text.trim()}
          className="btn-primary text-sm disabled:opacity-50">
          {saving ? 'جارٍ...' : '💾 حفظ'}
        </button>
        <button onClick={onCancel} className="btn-secondary text-sm">إلغاء</button>
      </div>
    </div>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function CustomerLocationsPanel({ customerId, readonly = false }) {
  const qc = useQueryClient()
  const [adding, setAdding]   = useState(false)
  const [editing, setEditing] = useState(null)  // loc id being edited
  const [saving, setSaving]   = useState(false)

  const { data: locations = [], isLoading } = useQuery({
    queryKey: ['customer-locations', customerId],
    queryFn: () => customersApi.locations(customerId).then(r => r.data),
    enabled: !!customerId,
  })

  const invalidate = () => qc.invalidateQueries(['customer-locations', customerId])

  async function handleAdd(form) {
    setSaving(true)
    try {
      await customersApi.addLocation(customerId, form)
      invalidate(); setAdding(false)
    } catch { } finally { setSaving(false) }
  }

  async function handleUpdate(locId, form) {
    setSaving(true)
    try {
      await customersApi.updateLocation(customerId, locId, form)
      invalidate(); setEditing(null)
    } catch { } finally { setSaving(false) }
  }

  async function handleDelete(locId) {
    if (!window.confirm('حذف هذا العنوان؟')) return
    await customersApi.deleteLocation(customerId, locId)
    invalidate()
  }

  async function handleSetDefault(locId) {
    await customersApi.setDefaultLocation(customerId, locId)
    invalidate()
  }

  if (isLoading) return (
    <div className="space-y-2 animate-pulse">
      {[1,2].map(i => <div key={i} className="h-20 bg-gray-100 rounded-xl" />)}
    </div>
  )

  return (
    <div className="space-y-3" dir="rtl">
      {locations.length === 0 && !adding && (
        <div className="text-center py-8 border-2 border-dashed border-gray-200 rounded-xl">
          <div className="text-3xl mb-2">📍</div>
          <div className="text-sm text-gray-400">لا توجد عناوين مسجلة</div>
        </div>
      )}

      {locations.map(loc => (
        <div key={loc.id}>
          {editing === loc.id ? (
            <LocationForm
              initial={loc}
              onSave={(form) => handleUpdate(loc.id, form)}
              onCancel={() => setEditing(null)}
              saving={saving}
            />
          ) : (
            <div className={`border rounded-xl p-4 ${
              loc.is_default ? 'border-brand-300 bg-brand-50' : 'border-gray-200 bg-white'
            }`}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="font-bold text-gray-800 text-sm">
                      {LABEL_ICONS[loc.label] || '📍'} {loc.label_display}
                    </span>
                    {loc.is_default && (
                      <span className="badge bg-brand-100 text-brand-700 text-xs">
                        افتراضي ✓
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-gray-700 leading-relaxed">
                    {loc.address_text}
                  </div>
                  {(loc.area || loc.floor || loc.apartment) && (
                    <div className="text-xs text-gray-500 mt-0.5">
                      {[loc.area, loc.floor && `دور ${loc.floor}`, loc.apartment && `شقة ${loc.apartment}`]
                        .filter(Boolean).join(' · ')}
                    </div>
                  )}
                  {loc.landmark && (
                    <div className="text-xs text-blue-600 mt-0.5">🗺️ {loc.landmark}</div>
                  )}
                  {loc.delivery_phone && (
                    <div className="text-xs text-gray-500 mt-0.5 font-mono" dir="ltr">
                      📞 {loc.delivery_phone}
                    </div>
                  )}
                  {loc.delivery_notes && (
                    <div className="text-xs text-orange-600 mt-0.5">⚠️ {loc.delivery_notes}</div>
                  )}
                  <WhatsAppButtons loc={loc} />
                </div>

                {!readonly && (
                  <div className="flex flex-col gap-1 shrink-0">
                    <button onClick={() => setEditing(loc.id)}
                      className="text-xs text-gray-400 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100">
                      تعديل
                    </button>
                    {!loc.is_default && (
                      <button onClick={() => handleSetDefault(loc.id)}
                        className="text-xs text-brand-600 hover:text-brand-800 px-2 py-1 rounded hover:bg-brand-50">
                        افتراضي
                      </button>
                    )}
                    <button onClick={() => handleDelete(loc.id)}
                      className="text-xs text-red-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50">
                      حذف
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ))}

      {adding ? (
        <LocationForm
          onSave={handleAdd}
          onCancel={() => setAdding(false)}
          saving={saving}
        />
      ) : !readonly && (
        <button onClick={() => setAdding(true)}
          className="btn-secondary text-sm w-full">
          + إضافة عنوان جديد
        </button>
      )}
    </div>
  )
}
