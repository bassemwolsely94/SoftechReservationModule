/**
 * MobileDeliveryDetailPage.jsx — delivery order detail (route: /m/delivery/:id).
 *
 * Read-focused monitoring view: customer + address (call / map), items, payment,
 * driver, and the status timeline. Lifecycle actions intentionally stay on the
 * desktop dispatch board and the rider app — this surface is for status visibility.
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { deliveryApi } from '../../api/client'
import { deliveryBadgeClass, deliveryStatusLabel } from './deliveryStatus'
import { MobileLoading, MobileError } from '../../components/mobileUi'
import { format } from 'date-fns'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}
function dt(d) {
  try { return toLatin(format(new Date(d), 'yyyy/MM/dd HH:mm')) } catch { return '' }
}
function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <span className="text-xs text-gray-400 shrink-0">{label}</span>
      <span className="text-sm text-gray-800 text-left">{children}</span>
    </div>
  )
}

export default function MobileDeliveryDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const { data: o, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-delivery-detail', id],
    queryFn: () => deliveryApi.get(id).then(r => r.data),
    refetchInterval: 60_000,
  })

  async function openWhatsApp() {
    try {
      const { data } = await deliveryApi.whatsapp(id)
      const url = data?.url || data?.link || data?.whatsapp_url
      if (url) window.open(url, '_blank')
    } catch { /* ignore */ }
  }

  async function shareTracking() {
    try {
      const { data } = await deliveryApi.trackingLink(id)
      if (data?.whatsapp_url) window.open(data.whatsapp_url, '_blank')
      else if (navigator.share && data?.url) navigator.share({ title: 'تتبع الطلب', url: data.url }).catch(() => {})
      else if (data?.url && navigator.clipboard) { navigator.clipboard.writeText(data.url); alert('تم نسخ رابط التتبع') }
    } catch { /* ignore */ }
  }

  if (isLoading) return <MobileLoading />
  if (isError || !o) return <MobileError text="تعذّر تحميل الطلب" onRetry={refetch} />

  const address = o.delivery_address || [o.delivery_area, o.delivery_district, o.delivery_governorate, o.delivery_landmark].filter(Boolean).join(' — ')
  const logs = (o.status_logs || []).slice().reverse()

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/delivery')} className="text-sm text-gray-500">→ الرجوع للوحة</button>

      {/* Header */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h1 className="font-bold text-base text-gray-900">{o.order_number || `#${o.id}`}</h1>
          <div className="flex items-center gap-1.5">
            {o.is_late && <span className="text-[11px] text-red-600 font-medium">متأخر</span>}
            <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${deliveryBadgeClass(o.status)}`}>
              {o.status_label}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {o.customer_phone && (
            <a href={`tel:${o.customer_phone}`} className="flex-1 text-center text-sm bg-brand-50 text-brand-700 border border-brand-200 rounded-xl py-2 font-medium" dir="ltr">📞 اتصال</a>
          )}
          {o.customer_phone && (
            <button onClick={openWhatsApp} className="flex-1 text-center text-sm bg-green-50 text-green-700 border border-green-200 rounded-xl py-2 font-medium">💬 واتساب</button>
          )}
          {o.google_maps_url && (
            <a href={o.google_maps_url} target="_blank" rel="noreferrer" className="flex-1 text-center text-sm bg-blue-50 text-blue-700 border border-blue-200 rounded-xl py-2 font-medium">🗺️ الموقع</a>
          )}
        </div>
        <button onClick={shareTracking} className="mt-2 w-full text-center text-sm bg-brand-50 text-brand-700 border border-brand-200 rounded-xl py-2 font-medium">
          📍 إرسال رابط التتبع للعميل
        </button>
      </div>

      {/* Info */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 divide-y divide-gray-50">
        <Row label="العميل">{o.customer_name || '—'}</Row>
        {o.customer_phone && <Row label="الهاتف"><span dir="ltr">{o.customer_phone}</span></Row>}
        {address && <Row label="العنوان">{address}</Row>}
        <Row label="الفرع">{o.branch_name || '—'}</Row>
        <Row label="السائق">{o.driver_name || 'غير مكلّف'}</Row>
        <Row label="الدفع">{o.payment_label || o.payment_method || '—'}</Row>
        <Row label="الإجمالي">{toLatin(o.total_with_fees ?? o.total_value)} ج.م</Row>
        {o.notes && <Row label="ملاحظات">{o.notes}</Row>}
      </div>

      {/* Items */}
      {Array.isArray(o.items) && o.items.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">الأصناف ({toLatin(o.items.length)})</h2>
          <div className="space-y-1.5">
            {o.items.map(it => (
              <div key={it.id} className="flex items-center justify-between text-sm border-b border-gray-50 last:border-0 pb-1.5 last:pb-0">
                <span className="text-gray-700 break-words flex-1 min-w-0">{it.item_name || '—'}</span>
                <span className="text-gray-500 shrink-0">× {toLatin(it.quantity)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status timeline */}
      {logs.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">📜 سجل الحالة</h2>
          <div className="space-y-2.5">
            {logs.map(l => (
              <div key={l.id} className="flex gap-2.5 text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-brand-400 mt-1.5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-gray-700">
                    {l.from_status ? `${deliveryStatusLabel(l.from_status)} ← ` : ''}
                    <span className="font-semibold">{deliveryStatusLabel(l.to_status)}</span>
                  </div>
                  {l.notes && <div className="text-gray-500 mt-0.5">{l.notes}</div>}
                  <div className="text-gray-400 mt-0.5">
                    {l.recorded_by_name || l.source_label || '—'}{l.recorded_at ? ` · ${dt(l.recorded_at)}` : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
