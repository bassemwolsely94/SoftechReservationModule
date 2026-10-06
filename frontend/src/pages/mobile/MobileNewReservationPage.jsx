/**
 * MobileNewReservationPage.jsx — phone reservation creation (route: /m/reservations/new).
 *
 * A lean, single-column version of the desktop NewReservationPage. Reuses the
 * same shared widgets (CustomerSearchWidget, ItemSearchWidget) and posts to the
 * same /reservations/ endpoint, including the 409 duplicate → force flow.
 * Branch defaults to the user's branch; admin/call_center may pick another.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi } from '../../api/client'
import { queuedPost } from '../../api/offlineQueue'
import useAuthStore from '../../store/authStore'
import CustomerSearchWidget from '../../components/CustomerSearchWidget'
import ItemSearchWidget from '../../components/ItemSearchWidget'

const CHANNELS = [
  { value: 'cash_sales',     icon: '💵', label: 'بيع نقدي' },
  { value: 'home_delivery',  icon: '🚚', label: 'توصيل' },
  { value: 'contract_sales', icon: '📋', label: 'كنتراكت' },
]

const PRIORITIES = [
  { value: 'normal',  label: 'عادي' },
  { value: 'urgent',  label: 'عاجل' },
  { value: 'chronic', label: 'مزمن' },
]

export default function MobileNewReservationPage() {
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()
  const canPickBranch = user?.role === 'admin' || user?.role === 'call_center'

  const [form, setForm] = useState({
    customer:           '',
    item:               '',
    manual_item_name:   '',
    branch:             user?.branch_id ? String(user.branch_id) : '',
    priority:           'normal',
    quantity_requested: 1,
    contact_phone:      '',
    contact_name:       '',
    channel:            'cash_sales',
    notes:              '',
  })
  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const [selectedCustomer, setSelectedCustomer] = useState(null)
  const [selectedItem, setSelectedItem]         = useState(null)
  const [manualMode, setManualMode]             = useState(false)
  const [submitting, setSubmitting]             = useState(false)
  const [error, setError]                       = useState('')
  const [duplicateData, setDuplicateData]       = useState(null)

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
    enabled: canPickBranch,
  })

  function handleCustomerSelect(c) {
    setSelectedCustomer(c)
    if (!c) { upd('customer', ''); return }
    setForm(f => ({
      ...f,
      customer:      c.id || '',
      contact_name:  c.name || f.contact_name,
      contact_phone: c.phone || f.contact_phone,
    }))
  }

  function handleItemSelect(item) {
    setSelectedItem(item)
    setForm(f => ({ ...f, item: item.id, manual_item_name: '' }))
  }
  function handleItemClear() {
    setSelectedItem(null)
    setForm(f => ({ ...f, item: '', manual_item_name: '' }))
  }

  async function submit(force = false) {
    if (!form.item && !form.manual_item_name.trim()) {
      setError('حدّد صنفاً من البحث أو اكتب اسمه يدوياً'); return
    }
    if (!form.branch || !form.contact_phone.trim() || !form.contact_name.trim()) {
      setError('يرجى تعبئة: الفرع، اسم التواصل، ورقم الهاتف'); return
    }
    setSubmitting(true); setError('')
    try {
      const payload = {}
      Object.entries(form).forEach(([k, v]) => { if (v !== '' && v !== null) payload[k] = v })
      const url = force ? '/reservations/?force=true' : '/reservations/'
      // queuedPost falls back to the offline queue on no/dropped signal. Duplicate
      // detection (409) only runs online; it re-throws and is handled below.
      const res = await queuedPost(url, payload, { label: 'إنشاء حجز' })
      qc.invalidateQueries({ queryKey: ['m-reservations'] })
      if (res.queued) {
        // No server id yet — it'll be created on reconnect. Surface via the list.
        navigate('/m/reservations', { replace: true })
        return
      }
      navigate(`/m/reservations/${res.data.id}`, { replace: true })
    } catch (e) {
      if (e.response?.status === 409 && e.response?.data?.duplicate) {
        setDuplicateData(e.response.data)
        setSubmitting(false)
        return
      }
      const d = e.response?.data
      let msg = 'حدث خطأ، حاول مجدداً'
      if (typeof d === 'string') msg = d
      else if (d?.detail) msg = d.detail
      else if (d) {
        const parts = Object.entries(d).map(([f, m]) => `${f}: ${Array.isArray(m) ? m.join(' ') : m}`)
        if (parts.length) msg = parts.join(' | ')
      }
      setError(msg)
      setSubmitting(false)
    }
  }

  return (
    <div className="p-3 space-y-3">

      {/* Duplicate modal */}
      {duplicateData && (
        <div className="fixed inset-0 bg-black/40 flex items-end sm:items-center justify-center z-50">
          <div className="bg-white rounded-t-2xl sm:rounded-2xl shadow-2xl w-full sm:max-w-sm p-5 pb-safe-bottom" dir="rtl">
            <div className="text-2xl text-center mb-1">⚠️</div>
            <h3 className="font-bold text-gray-800 text-base mb-1.5 text-center">حجز مكرر محتمل</h3>
            <p className="text-sm text-gray-600 mb-3 text-center">{duplicateData.detail}</p>
            <div className="mb-4 space-y-1.5">
              {duplicateData.duplicates?.map(d => (
                <button
                  key={d.id}
                  onClick={() => navigate(`/m/reservations/${d.id}`)}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-amber-50 border border-amber-200 text-sm text-amber-800"
                >
                  <span>حجز #{d.id}</span>
                  <span className="text-xs font-semibold">{d.status_label}</span>
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setDuplicateData(null)} className="btn-secondary flex-1 text-sm">إلغاء</button>
              <button onClick={() => { setDuplicateData(null); submit(true) }} className="btn-primary flex-1 text-sm">
                إنشاء على أي حال
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Customer */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">
          👤 العميل <span className="text-xs text-gray-400 font-normal">(اختياري)</span>
        </h2>
        <CustomerSearchWidget selected={selectedCustomer} onSelect={handleCustomerSelect} allowManual={false} />
      </div>

      {/* Item */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">💊 الصنف *</h2>
        {manualMode ? (
          <div className="space-y-2">
            <input
              className="input-field w-full"
              placeholder="اكتب اسم الصنف يدوياً..."
              value={form.manual_item_name}
              onChange={e => upd('manual_item_name', e.target.value)}
              autoFocus
            />
            <button
              type="button"
              onClick={() => { setManualMode(false); upd('manual_item_name', '') }}
              className="text-xs text-brand-600 font-medium"
            >🔍 البحث في الكتالوج بدلاً من ذلك</button>
          </div>
        ) : (
          <>
            <ItemSearchWidget
              selected={selectedItem}
              onSelect={handleItemSelect}
              onClear={handleItemClear}
            />
            {!selectedItem && (
              <button
                type="button"
                onClick={() => setManualMode(true)}
                className="text-[11px] text-gray-400 mt-1.5"
              >✏️ الصنف غير موجود؟ اكتب الاسم يدوياً</button>
            )}
          </>
        )}

        {(selectedItem || form.manual_item_name.trim()) && (
          <div className="mt-3 flex items-center gap-3">
            <label className="text-sm font-medium text-gray-700 shrink-0">الكمية:</label>
            <input
              type="number" min="1" inputMode="numeric"
              className="input-field w-24 text-sm"
              value={form.quantity_requested}
              onChange={e => upd('quantity_requested', e.target.value)}
            />
          </div>
        )}
      </div>

      {/* Details */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-4">
        <h2 className="font-semibold text-gray-700 text-sm">📋 التفاصيل</h2>

        {/* Branch */}
        {canPickBranch ? (
          <div>
            <label className="label">الفرع *</label>
            <select className="input-field w-full" value={form.branch} onChange={e => upd('branch', e.target.value)}>
              <option value="">اختر الفرع...</option>
              {branches.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <label className="label">الفرع</label>
            <div className="input-field bg-gray-50 text-gray-600">{user?.branch_name || 'فرعك الحالي'}</div>
          </div>
        )}

        {/* Channel */}
        <div>
          <label className="label">قناة الطلب</label>
          <div className="grid grid-cols-3 gap-2">
            {CHANNELS.map(c => (
              <button
                key={c.value}
                type="button"
                onClick={() => upd('channel', c.value)}
                className={`flex flex-col items-center gap-0.5 py-2.5 rounded-xl border-2 text-xs font-semibold transition-all ${
                  form.channel === c.value
                    ? 'border-brand-500 bg-brand-50 text-brand-700'
                    : 'border-gray-200 bg-white text-gray-600'
                }`}
              >
                <span className="text-xl leading-none">{c.icon}</span>
                <span>{c.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Contact */}
        <div>
          <label className="label">اسم التواصل *</label>
          <input className="input-field w-full" value={form.contact_name} onChange={e => upd('contact_name', e.target.value)} />
        </div>
        <div>
          <label className="label">هاتف التواصل *</label>
          <input className="input-field w-full" dir="ltr" inputMode="tel" type="tel"
            value={form.contact_phone} onChange={e => upd('contact_phone', e.target.value)} />
        </div>

        {/* Priority */}
        <div>
          <label className="label">الأولوية</label>
          <div className="grid grid-cols-3 gap-2">
            {PRIORITIES.map(p => (
              <button
                key={p.value}
                type="button"
                onClick={() => upd('priority', p.value)}
                className={`py-2 rounded-xl border-2 text-xs font-semibold transition-all ${
                  form.priority === p.value
                    ? 'border-brand-500 bg-brand-50 text-brand-700'
                    : 'border-gray-200 bg-white text-gray-600'
                }`}
              >{p.label}</button>
            ))}
          </div>
        </div>

        {/* Notes */}
        <div>
          <label className="label">ملاحظات</label>
          <textarea rows={2} className="input-field w-full resize-none" value={form.notes}
            onChange={e => upd('notes', e.target.value)} placeholder="أي تفاصيل إضافية..." />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-4 py-3">{error}</div>
      )}

      {/* Actions */}
      <div className="flex gap-2.5">
        <button onClick={() => navigate('/m/reservations')} className="btn-secondary px-5">إلغاء</button>
        <button
          onClick={() => submit(false)}
          disabled={submitting}
          className="btn-primary flex-1 py-3 text-base disabled:opacity-50"
        >
          {submitting ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              جارٍ الحفظ...
            </span>
          ) : '✅ إنشاء الحجز'}
        </button>
      </div>
    </div>
  )
}
