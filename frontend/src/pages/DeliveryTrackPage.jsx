/**
 * DeliveryTrackPage.jsx — PUBLIC customer-facing live delivery tracking
 * (route: /track/:token — no login).
 *
 * Opens from a tokenized link (WhatsApp/SMS). Polls the public endpoint and
 * shows order status, driver, a "view on map" link (live driver location while
 * out for delivery), and milestone times. No customer PII beyond the order.
 */
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

const STEPS = [
  { key: 'created',          label: 'تم الاستلام' },
  { key: 'preparing',        label: 'جاري التحضير' },
  { key: 'ready',            label: 'جاهز' },
  { key: 'out_for_delivery', label: 'في الطريق إليك' },
  { key: 'delivered',        label: 'تم التسليم' },
]
const STEP_INDEX = { created: 0, pending_review: 0, preparing: 1, ready: 2, assigned: 3, driver_accepted: 3, out_for_delivery: 3, delivered: 4, closed: 4 }
const BAD = { failed: 'تعذّر التسليم', cancelled: 'أُلغي الطلب', returned: 'أُعيد الطلب', customer_unavailable: 'تعذّر الوصول إليك', partial_delivery: 'تسليم جزئي' }

function fmt(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' }) } catch { return '' }
}

export default function DeliveryTrackPage() {
  const { token } = useParams()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['public-track', token],
    queryFn: () => fetch(`/api/delivery/track/${token}/`).then(r => { if (!r.ok) throw new Error(); return r.json() }),
    refetchInterval: 30_000,
    retry: false,
  })

  const Shell = ({ children }) => (
    <div className="min-h-screen bg-gray-50 font-cairo flex flex-col" dir="rtl">
      <header className="bg-brand-600 text-white px-4 py-3 flex items-center gap-2">
        <div className="w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center"><span className="font-black">ر</span></div>
        <div className="font-bold text-sm">صيدليات الرزيقي — تتبع الطلب</div>
      </header>
      <main className="flex-1 p-4">{children}</main>
    </div>
  )

  if (isLoading) return <Shell><div className="text-center text-sm text-gray-400 py-12">جارٍ التحميل...</div></Shell>
  if (isError || !data) return <Shell><div className="text-center py-12"><div className="text-3xl mb-2">⚠️</div><div className="text-sm text-gray-500">الرابط غير صالح أو منتهي الصلاحية</div></div></Shell>

  const bad = BAD[data.status]
  const idx = STEP_INDEX[data.status] ?? 0

  return (
    <Shell>
      <div className="max-w-md mx-auto space-y-4">
        <div className="bg-white rounded-2xl border border-gray-200 p-5 text-center">
          <div className="text-xs text-gray-400">رقم الطلب</div>
          <div className="font-bold text-lg text-gray-900">{data.order_number}</div>
          <div className={`mt-2 inline-block text-sm px-3 py-1 rounded-full font-medium ${bad ? 'bg-red-100 text-red-700' : 'bg-brand-100 text-brand-700'}`}>
            {data.status_label}
          </div>
        </div>

        {!bad && (
          <div className="bg-white rounded-2xl border border-gray-200 p-5">
            <div className="space-y-3">
              {STEPS.map((s, i) => {
                const done = i <= idx
                return (
                  <div key={s.key} className="flex items-center gap-3">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${done ? 'bg-brand-600 text-white' : 'bg-gray-200 text-gray-400'}`}>
                      {done ? '✓' : i + 1}
                    </span>
                    <span className={`text-sm ${i === idx ? 'font-bold text-gray-900' : done ? 'text-gray-600' : 'text-gray-400'}`}>{s.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {(data.driver_name || data.location) && (
          <div className="bg-white rounded-2xl border border-gray-200 p-5">
            {data.driver_name && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">المندوب</span>
                <span className="text-sm font-medium text-gray-800">{data.driver_name}{data.driver_vehicle ? ` · ${data.driver_vehicle}` : ''}</span>
              </div>
            )}
            {data.maps_url && (
              <a href={data.maps_url} target="_blank" rel="noreferrer"
                className="mt-3 block text-center text-sm bg-blue-50 text-blue-700 border border-blue-200 rounded-xl py-2.5 font-medium">
                🗺️ موقع المندوب على الخريطة
              </a>
            )}
          </div>
        )}

        <div className="bg-white rounded-2xl border border-gray-200 p-5 text-sm space-y-1.5 text-gray-600">
          {data.ordered_at && <div className="flex justify-between"><span className="text-gray-400">وقت الطلب</span><span>{fmt(data.ordered_at)}</span></div>}
          {data.dispatched_at && <div className="flex justify-between"><span className="text-gray-400">وقت الخروج</span><span>{fmt(data.dispatched_at)}</span></div>}
          {data.delivered_at && <div className="flex justify-between"><span className="text-gray-400">وقت التسليم</span><span>{fmt(data.delivered_at)}</span></div>}
        </div>

        <p className="text-center text-[11px] text-gray-400">يُحدَّث تلقائياً كل ٣٠ ثانية</p>
      </div>
    </Shell>
  )
}
