/**
 * PortalHomePage.jsx — customer's active orders: reservations + delivery orders.
 * Each delivery exposes a 1-tap "تتبع" link to the existing public /track/:token page.
 */
import { useQuery } from '@tanstack/react-query'
import { portalApi } from '../../portal/portalApi'

function fmt(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleDateString('ar-EG', { dateStyle: 'medium' }) } catch { return '' }
}

function Card({ children }) {
  return <div className="bg-white rounded-2xl border border-gray-200 p-4">{children}</div>
}

export default function PortalHomePage() {
  const { data, isLoading } = useQuery({
    queryKey: ['portal-orders'],
    queryFn: () => portalApi.orders().then(r => r.data),
  })

  if (isLoading) return <div className="text-center text-sm text-gray-400 py-12">جارٍ التحميل...</div>

  const reservations = data?.reservations || []
  const deliveries   = data?.deliveries || []
  const empty = reservations.length === 0 && deliveries.length === 0

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="font-bold text-gray-900 text-lg">طلباتي</h1>

      {empty && (
        <Card>
          <div className="text-center py-8 text-gray-400">
            <div className="text-3xl mb-2">🗂️</div>
            <div className="text-sm">لا توجد طلبات حالياً</div>
          </div>
        </Card>
      )}

      {deliveries.map(d => (
        <Card key={`d${d.id}`}>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-gray-400">طلب توصيل</div>
              <div className="font-bold text-gray-900">{d.order_number}</div>
            </div>
            <span className="text-xs px-2.5 py-1 rounded-full bg-brand-100 text-brand-700 font-medium">{d.status_label}</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-gray-400">{d.branch} · {fmt(d.created_at)}</span>
            {!d.is_terminal && (
              <a href={`/track/${d.track_token}`} className="text-sm text-brand-600 font-bold">تتبع الطلب ←</a>
            )}
          </div>
        </Card>
      ))}

      {reservations.map(r => (
        <Card key={`r${r.id}`}>
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <div className="text-xs text-gray-400">حجز</div>
              <div className="font-bold text-gray-900 truncate">{r.item} × {r.quantity}</div>
            </div>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${r.is_active ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}`}>
              {r.status_label}
            </span>
          </div>
          <div className="mt-2 text-xs text-gray-400">{r.branch} · {fmt(r.created_at)}</div>
        </Card>
      ))}
    </div>
  )
}
