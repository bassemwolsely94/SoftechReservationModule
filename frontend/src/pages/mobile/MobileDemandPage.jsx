/**
 * MobileDemandPage.jsx — lost-sales / unmet-demand queue (route: /m/demand).
 *
 * Branch-scoped queue over the demand API. Status chips + SLA-breach flags + FAB
 * to capture new demand from the counter.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { demandApi } from '../../api/client'
import { demandBadgeClass, DEMAND_FILTERS } from './demandStatus'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function DemandCard({ d, onOpen }) {
  const items = (d.item_names || []).join('، ')
  return (
    <button onClick={onOpen}
      className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-bold text-sm text-gray-900">{d.demand_number}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {d.sla_breached && <span className="text-[11px] text-red-600 font-medium">SLA</span>}
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${demandBadgeClass(d.status)}`}>
            {d.status_label}
          </span>
        </div>
      </div>
      <div className="text-sm text-gray-700 truncate">{d.customer_name || d.phone}</div>
      {items && <div className="text-xs text-gray-500 truncate mt-0.5">{items}</div>}
      <div className="flex items-center justify-between text-xs text-gray-400 mt-1.5">
        <span>{toLatin(d.total_items)} صنف{d.priority && d.priority !== 'normal' ? ` · ${d.priority_label}` : ''}</span>
        <span>{d.created_at ? toLatin(formatDistanceToNow(new Date(d.created_at), { locale: ar, addSuffix: true })) : ''}</span>
      </div>
    </button>
  )
}

export default function MobileDemandPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('new')

  const params = { page_size: 25, ordering: '-created_at' }
  if (filter) params.status = filter

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['m-demand', filter],
      queryFn: ({ pageParam }) =>
        (pageParam ? api.get(pageParam).then(r => r.data)
                   : demandApi.list(params).then(r => r.data)),
      initialPageParam: null,
      getNextPageParam: (last) => last.next || undefined,
    })

  const rows = (data?.pages || []).flatMap(p => p.results || (Array.isArray(p) ? p : []))

  return (
    <div className="p-3 space-y-3">
      <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1">
        {DEMAND_FILTERS.map(f => (
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
        <MobileError text="تعذّر تحميل الطلبات" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="🔍" text="لا يوجد طلب ضائع" />
      ) : (
        <div className="space-y-2.5">
          {rows.map(d => <DemandCard key={d.id} d={d} onOpen={() => navigate(`/m/demand/${d.id}`)} />)}
          {hasNextPage && (
            <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
              className="w-full py-3 text-sm text-brand-600 font-medium disabled:opacity-50">
              {isFetchingNextPage ? 'جارٍ التحميل...' : 'تحميل المزيد'}
            </button>
          )}
        </div>
      )}

      <button onClick={() => navigate('/m/demand/new')}
        className="fixed bottom-20 left-4 z-20 w-14 h-14 rounded-full bg-brand-600 text-white shadow-lg shadow-brand-900/30 flex items-center justify-center text-2xl active:bg-brand-700"
        title="تسجيل طلب ضائع">
        +
      </button>
    </div>
  )
}
