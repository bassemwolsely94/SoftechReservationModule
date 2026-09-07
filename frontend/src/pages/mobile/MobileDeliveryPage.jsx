/**
 * MobileDeliveryPage.jsx — live delivery order-status board (route: /m/delivery).
 *
 * Dispatcher/manager monitoring surface over the existing delivery API — a
 * read-focused status board (lifecycle actions stay on the desktop dispatch
 * board + the rider app). Status filter chips, late flags, cursor load-more.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { deliveryApi } from '../../api/client'
import { deliveryBadgeClass, DELIVERY_FILTERS } from './deliveryStatus'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function OrderCard({ o, onOpen }) {
  return (
    <button onClick={onOpen}
      className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-bold text-sm text-gray-900">{o.order_number || `#${o.id}`}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {o.is_late && <span className="text-[11px] text-red-600 font-medium">متأخر</span>}
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${deliveryBadgeClass(o.status)}`}>
            {o.status_label}
          </span>
        </div>
      </div>
      <div className="text-sm text-gray-700 truncate">{o.customer_name || 'عميل'}</div>
      <div className="flex items-center justify-between text-xs text-gray-500 mt-1.5">
        <span className="truncate">{o.delivery_area || o.branch_name || '—'}{o.driver_name ? ` · 🛵 ${o.driver_name}` : ''}</span>
        <span className="shrink-0">{o.ordered_at ? toLatin(formatDistanceToNow(new Date(o.ordered_at), { locale: ar, addSuffix: true })) : ''}</span>
      </div>
    </button>
  )
}

export default function MobileDeliveryPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('active')

  const chip = DELIVERY_FILTERS.find(f => f.value === filter) || DELIVERY_FILTERS[0]
  const params = { page_size: 25, ordering: '-ordered_at', ...chip.param }

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['m-delivery', filter],
      queryFn: ({ pageParam }) =>
        (pageParam ? api.get(pageParam).then(r => r.data)
                   : deliveryApi.list(params).then(r => r.data)),
      initialPageParam: null,
      getNextPageParam: (last) => last.next || undefined,
      refetchInterval: 60_000,   // live board — keep statuses fresh
    })

  const rows = (data?.pages || []).flatMap(p => p.results || (Array.isArray(p) ? p : []))

  return (
    <div className="p-3 space-y-3">
      <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1">
        {DELIVERY_FILTERS.map(f => (
          <button key={f.value || 'all'} onClick={() => setFilter(f.value)}
            className={`shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f.value ? 'bg-brand-600 text-white' : 'bg-white border border-gray-200 text-gray-600 active:bg-gray-50'
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <MobileLoading />
      ) : isError ? (
        <MobileError text="تعذّر تحميل طلبات التوصيل" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="🚚" text="لا توجد طلبات توصيل" />
      ) : (
        <div className="space-y-2.5">
          {rows.map(o => <OrderCard key={o.id} o={o} onOpen={() => navigate(`/m/delivery/${o.id}`)} />)}
          {hasNextPage && (
            <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
              className="w-full py-3 text-sm text-brand-600 font-medium disabled:opacity-50">
              {isFetchingNextPage ? 'جارٍ التحميل...' : 'تحميل المزيد'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
