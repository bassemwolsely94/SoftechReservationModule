/**
 * PortalRefillsPage.jsx — chronic refills due soon + 1-tap re-order.
 * Re-order posts to the customer-scoped endpoint; the backend creates a
 * Reservation for THIS customer (order_source='online').
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { portalApi } from '../../portal/portalApi'

function fmt(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleDateString('ar-EG', { dateStyle: 'medium' }) } catch { return '' }
}

export default function PortalRefillsPage() {
  const qc = useQueryClient()
  const [done, setDone] = useState({})

  const { data, isLoading } = useQuery({
    queryKey: ['portal-refills'],
    queryFn: () => portalApi.refills().then(r => r.data),
  })

  const reorder = useMutation({
    mutationFn: (refill) =>
      portalApi.reorder(refill.item_id ? { item: refill.item_id } : { manual_item_name: refill.item }),
    onSuccess: (_res, refill) => {
      setDone(d => ({ ...d, [refill.id]: true }))
      qc.invalidateQueries({ queryKey: ['portal-orders'] })
    },
  })

  if (isLoading) return <div className="text-center text-sm text-gray-400 py-12">جارٍ التحميل...</div>

  const refills = data?.refills || []

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="font-bold text-gray-900 text-lg">إعادة الطلب</h1>
      <p className="text-sm text-gray-500">أدويتك المزمنة التي اقترب موعد إعادة صرفها.</p>

      {refills.length === 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 text-center py-8 text-gray-400">
          <div className="text-3xl mb-2">✅</div>
          <div className="text-sm">لا توجد أدوية مستحقة حالياً</div>
        </div>
      )}

      {refills.map(r => (
        <div key={r.id} className="bg-white rounded-2xl border border-gray-200 p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="font-bold text-gray-900 truncate">{r.item || 'دواء'}</div>
              <div className={`text-xs ${r.is_overdue ? 'text-red-500' : 'text-gray-400'}`}>
                {r.is_overdue ? 'متأخر — ' : 'يستحق '}{fmt(r.due_date)}
              </div>
            </div>
            <button
              disabled={done[r.id] || reorder.isPending}
              onClick={() => reorder.mutate(r)}
              className="shrink-0 bg-brand-600 text-white text-sm rounded-xl px-4 py-2 font-bold disabled:opacity-60"
            >
              {done[r.id] ? 'تم الطلب ✓' : 'إعادة الطلب'}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
