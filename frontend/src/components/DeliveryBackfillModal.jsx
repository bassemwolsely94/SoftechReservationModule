/**
 * DeliveryBackfillModal.jsx
 * Branch-user manual backfill when the rider didn't log pickup / delivery.
 * Lets staff confirm pickup/delivery and optionally pin an approximate drop
 * location on the map (not mandatory). Bypasses geofencing; flags as manual.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { deliveryApi } from '../api/client'
import MapPicker from './MapPicker'

export default function DeliveryBackfillModal({ order, onClose, onDone }) {
  const delivered = order.status === 'delivered'
  const [confirmPickup, setConfirmPickup]     = useState(false)
  const [confirmDelivery, setConfirmDelivery] = useState(!delivered)
  const [recipient, setRecipient] = useState(order.pod_recipient_name || '')
  const [cash, setCash]   = useState(order.collected_amount ?? '')
  const [note, setNote]   = useState('')
  const [showMap, setShowMap] = useState(false)
  const [pin, setPin]     = useState(
    order.delivery_lat != null ? { lat: Number(order.delivery_lat), lng: Number(order.delivery_lng) } : null)

  const save = useMutation({
    mutationFn: () => deliveryApi.backfill(order.id, {
      confirm_pickup: confirmPickup,
      confirm_delivery: confirmDelivery,
      pod_recipient_name: recipient,
      pod_note: note,
      collected_amount: cash === '' ? undefined : cash,
      delivery_lat: pin?.lat, delivery_lng: pin?.lng,
    }),
    onSuccess: onDone,
  })

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-5 max-h-[92vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <h3 className="font-black text-gray-900">إدخال يدوي للتوصيل</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        <p className="text-[11px] text-amber-600 mb-3">⚠️ يُستخدم فقط عندما لا يسجّل السائق الاستلام/التسليم. الموقع تقديري.</p>
        <div className="text-xs text-gray-500 mb-3">{order.order_number} · {order.customer_name}</div>

        <div className="space-y-2.5">
          {order.status !== 'out_for_delivery' && !delivered && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={confirmPickup} onChange={e => setConfirmPickup(e.target.checked)} className="accent-brand-600" />
              تأكيد الاستلام من الفرع (خروج للتوصيل)
            </label>
          )}
          {!delivered && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={confirmDelivery} onChange={e => setConfirmDelivery(e.target.checked)} className="accent-brand-600" />
              تأكيد التسليم للعميل
            </label>
          )}

          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">اسم المستلِم</label>
            <input className="input-field" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder="من استلم؟" />
          </div>
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">المبلغ المحصَّل</label>
            <input className="input-field" type="number" dir="ltr" value={cash} onChange={e => setCash(e.target.value)} />
          </div>
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">ملاحظة</label>
            <input className="input-field" value={note} onChange={e => setNote(e.target.value)} />
          </div>

          {/* Optional approximate location from the map */}
          <div className="border-t border-gray-100 pt-2">
            {!showMap ? (
              <button onClick={() => setShowMap(true)} className="text-sm text-brand-600 hover:underline">
                📍 تحديد موقع التسليم التقريبي على الخريطة (اختياري)
              </button>
            ) : (
              <>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] text-gray-500">اضغط على الخريطة لتحديد الموقع التقريبي</span>
                  <button onClick={() => { setShowMap(false); setPin(order.delivery_lat != null ? { lat: +order.delivery_lat, lng: +order.delivery_lng } : null) }}
                    className="text-[11px] text-gray-400 hover:text-red-500">إزالة</button>
                </div>
                <MapPicker lat={pin?.lat} lng={pin?.lng} onPick={(lat, lng) => setPin({ lat, lng })} />
                {pin && <div className="text-[11px] text-emerald-600 font-mono mt-1" dir="ltr">📌 {pin.lat}, {pin.lng}</div>}
              </>
            )}
          </div>
        </div>

        {save.isError && <div className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2 mt-3">{save.error?.response?.data?.detail || 'تعذّر الحفظ'}</div>}
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
          <button onClick={() => save.mutate()} disabled={save.isPending || (!confirmPickup && !confirmDelivery && !pin)}
            className="btn-primary text-sm px-4 disabled:opacity-50">{save.isPending ? 'جارٍ…' : 'حفظ'}</button>
        </div>
      </div>
    </div>
  )
}
