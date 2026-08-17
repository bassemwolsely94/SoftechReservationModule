/**
 * DriverDeliveryApp.jsx — /delivery/my  (mobile-first driver screen)
 * The driver's route for today, in sequence, with accept → out → deliver (+POD).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { deliveryApi } from '../api/client'

const STATUS = {
  assigned:        { label: 'مكلّف', next: 'accept', nextLabel: 'قبول الطلب', color: 'bg-blue-50' },
  driver_accepted: { label: 'مقبول', next: 'dispatch', nextLabel: 'انطلقت 🚚', color: 'bg-indigo-50' },
  out_for_delivery:{ label: 'في الطريق', next: 'deliver', nextLabel: 'تم التسليم ✅', color: 'bg-amber-50' },
  delivered:       { label: 'تم التسليم', next: null, color: 'bg-emerald-50' },
}
const fmt = n => (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

function getGeo() {
  return new Promise((res, rej) => {
    if (!navigator.geolocation) return rej(new Error('no-geo'))
    navigator.geolocation.getCurrentPosition(
      p => res({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => rej(new Error('denied')),
      { timeout: 7000, enableHighAccuracy: true },
    )
  })
}

export default function DriverDeliveryApp() {
  const qc = useQueryClient()
  const [podFor, setPodFor] = useState(null)

  const { data: route, isLoading } = useQuery({
    queryKey: ['my-route'],
    queryFn: () => deliveryApi.myRoute().then(r => r.data),
    refetchInterval: 30_000,
  })
  const { data: looseOrders = [] } = useQuery({
    queryKey: ['my-orders'],
    queryFn: () => deliveryApi.myOrders().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
    refetchInterval: 30_000,
  })

  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function doAction(s) {
    setErr('')
    const action = STATUS[s.status]?.next
    if (!action || action === 'deliver') return
    setBusyId(s.id)
    try {
      let body = {}
      if (action === 'dispatch') {            // pickup → must be at the branch
        let g
        try { g = await getGeo() }
        catch { setErr('فعّل خدمة تحديد الموقع لتأكيد الاستلام من الفرع'); setBusyId(null); return }
        body = { driver_lat: g.lat, driver_lng: g.lng }
      }
      await deliveryApi[action](s.id, body)
      qc.invalidateQueries({ queryKey: ['my-route'] }); qc.invalidateQueries({ queryKey: ['my-orders'] })
    } catch (e) {
      setErr(e?.response?.data?.detail || 'تعذّر تنفيذ العملية')
    } finally {
      setBusyId(null)
    }
  }

  const stops = route?.orders?.length ? route.orders
    : looseOrders.map(o => ({ id: o.id, order_number: o.order_number, seq: null, customer_name: o.customer_name,
        customer_phone: o.customer_phone, address: o.delivery_address, total: o.total_with_fees,
        payment: o.payment_method, status: o.status, google_maps: o.google_maps_url }))

  return (
    <div className="p-4 max-w-md mx-auto" dir="rtl">
      <div className="mb-3">
        <h1 className="text-xl font-bold text-gray-900">🚚 مهامي اليوم</h1>
        {route && <p className="text-xs text-gray-500">المسار ROUTE-{route.id} · {route.delivered_count}/{route.stop_count} تم · متوقّع نقدي {fmt(route.expected_cash)} ج.م</p>}
      </div>

      {err && (
        <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex items-start gap-2">
          <span>📍</span><span className="flex-1">{err}</span>
          <button onClick={() => setErr('')} className="text-red-400">✕</button>
        </div>
      )}

      {isLoading ? <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
        : stops.length === 0 ? <div className="text-center py-16 text-gray-400">لا توجد مهام حالياً</div>
        : (
        <div className="space-y-2.5">
          {stops.map((s, i) => {
            const cfg = STATUS[s.status] || { label: s.status_label || s.status, next: null, color: 'bg-gray-50' }
            return (
              <div key={s.id} className={`rounded-2xl border border-gray-100 p-3 ${cfg.color}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <span className="w-6 h-6 rounded-full bg-white border border-gray-200 text-xs font-bold flex items-center justify-center shrink-0">{s.seq || i + 1}</span>
                    <div className="min-w-0">
                      <div className="font-bold text-gray-900 text-sm">{s.customer_name}</div>
                      <div className="text-xs text-gray-500 truncate">{s.address || '—'}</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">{fmt(s.total)} ج.م · {s.payment === 'cash' ? 'كاش 💵' : s.payment}</div>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold text-gray-500 shrink-0">{cfg.label}</span>
                </div>
                <div className="flex gap-1.5 mt-2.5">
                  {s.customer_phone && <a href={`tel:${s.customer_phone}`} className="flex-1 text-center text-xs bg-white border border-gray-200 rounded-lg py-1.5">📞 اتصال</a>}
                  {s.google_maps && <a href={s.google_maps} target="_blank" rel="noreferrer" className="flex-1 text-center text-xs bg-white border border-gray-200 rounded-lg py-1.5">🗺️ خريطة</a>}
                  {cfg.next === 'deliver'
                    ? <button onClick={() => setPodFor(s)} className="flex-[2] text-xs bg-emerald-600 text-white rounded-lg py-1.5 font-medium">تم التسليم ✅</button>
                    : cfg.next && <button onClick={() => doAction(s)} disabled={busyId === s.id} className="flex-[2] text-xs bg-brand-600 text-white rounded-lg py-1.5 font-medium disabled:opacity-50">{busyId === s.id ? '…' : cfg.nextLabel}</button>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {podFor && <PodModal stop={podFor} onClose={() => setPodFor(null)} onDone={() => { setPodFor(null); qc.invalidateQueries({ queryKey: ['my-route'] }); qc.invalidateQueries({ queryKey: ['my-orders'] }) }} />}
    </div>
  )
}

function PodModal({ stop, onClose, onDone }) {
  const [recipient, setRecipient] = useState('')
  const [cash, setCash] = useState(stop.payment === 'cash' ? String(Math.round(stop.total || 0)) : '')
  const [note, setNote] = useState('')
  const [photo, setPhoto] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit() {
    setBusy(true); setErr('')
    let lat, lng
    try { const g = await getGeo(); lat = g.lat; lng = g.lng } catch { /* may be required by geofence */ }
    const fd = new FormData()
    if (recipient) fd.append('pod_recipient_name', recipient)
    if (note) fd.append('pod_note', note)
    if (cash !== '') fd.append('collected_amount', cash)
    if (lat) { fd.append('pod_lat', lat); fd.append('pod_lng', lng) }
    if (photo) fd.append('pod_photo', photo)
    try { await deliveryApi.completeWithPod(stop.id, fd); onDone() }
    catch (e) { setErr(e?.response?.data?.detail || 'تعذّر تأكيد التسليم') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-[10000] flex items-end sm:items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm p-5">
        <h3 className="font-black text-gray-900 mb-3">إثبات التسليم — {stop.customer_name}</h3>
        <label className="block text-xs font-semibold text-gray-600 mb-1">اسم المستلِم</label>
        <input className="input-field mb-2" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder="من استلم الطلب؟" />
        <label className="block text-xs font-semibold text-gray-600 mb-1">المبلغ المحصَّل</label>
        <input className="input-field mb-2" type="number" value={cash} onChange={e => setCash(e.target.value)} dir="ltr" />
        <label className="block text-xs font-semibold text-gray-600 mb-1">صورة (اختياري)</label>
        <input className="mb-2 text-xs" type="file" accept="image/*" capture="environment" onChange={e => setPhoto(e.target.files?.[0] || null)} />
        <label className="block text-xs font-semibold text-gray-600 mb-1">ملاحظة</label>
        <input className="input-field mb-3" value={note} onChange={e => setNote(e.target.value)} placeholder="مثال: سُلّم للبواب" />
        {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mb-2">📍 {err}</div>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
          <button onClick={submit} disabled={busy} className="btn-primary text-sm px-4 disabled:opacity-50">{busy ? 'جارٍ…' : 'تأكيد التسليم'}</button>
        </div>
        <p className="text-[10px] text-gray-400 mt-2 text-center">سيُسجَّل موقعك الحالي تلقائياً كإثبات.</p>
      </div>
    </div>
  )
}
