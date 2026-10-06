/**
 * MobileTransfersPage.jsx — phone transfer-requests queue (route: /m/transfers).
 *
 * Thin card list over the existing transfers API (branch-scoped server-side:
 * branch staff see requests where they are requesting OR supplying). Status
 * filter chips + cursor "load more" + a floating new-request button.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { transfersApi } from '../../api/client'
import { transferBadgeClass, TRANSFER_FILTERS } from './transferStatus'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function TransferCard({ t, onOpen }) {
  return (
    <button
      onClick={onOpen}
      className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50 transition-colors"
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-bold text-sm text-gray-900">{t.request_number}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${transferBadgeClass(t.status_color)}`}>
          {t.status_label}
        </span>
      </div>
      <div className="text-sm text-gray-700 mb-2">
        {t.requesting_branch_name} <span className="text-gray-400">←</span> {t.supplying_branch_name || '—'}
      </div>
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{toLatin(t.total_items)} صنف</span>
        <span>{t.created_at ? toLatin(formatDistanceToNow(new Date(t.created_at), { locale: ar, addSuffix: true })) : ''}</span>
      </div>
    </button>
  )
}

export default function MobileTransfersPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('pending')

  const params = { page_size: 25, ordering: '-created_at' }
  if (filter) params.status = filter

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['m-transfers', filter],
      queryFn: ({ pageParam }) =>
        (pageParam ? api.get(pageParam).then(r => r.data)
                   : transfersApi.list(params).then(r => r.data)),
      initialPageParam: null,
      getNextPageParam: (last) => last.next || undefined,
    })

  const rows = (data?.pages || []).flatMap(p => p.results || [])

  return (
    <div className="p-3 space-y-3">
      <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1">
        {TRANSFER_FILTERS.map(f => (
          <button
            key={f.value || 'all'}
            onClick={() => setFilter(f.value)}
            className={`shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f.value ? 'bg-brand-600 text-white' : 'bg-white border border-gray-200 text-gray-600 active:bg-gray-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <MobileLoading />
      ) : isError ? (
        <MobileError text="تعذّر تحميل الطلبات" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="🔀" text="لا توجد طلبات تحويل" />
      ) : (
        <div className="space-y-2.5">
          {rows.map(t => (
            <TransferCard key={t.id} t={t} onOpen={() => navigate(`/m/transfers/${t.id}`)} />
          ))}
          {hasNextPage && (
            <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
              className="w-full py-3 text-sm text-brand-600 font-medium disabled:opacity-50">
              {isFetchingNextPage ? 'جارٍ التحميل...' : 'تحميل المزيد'}
            </button>
          )}
        </div>
      )}

      <button
        onClick={() => navigate('/m/transfers/new')}
        className="fixed bottom-20 left-4 z-20 w-14 h-14 rounded-full bg-brand-600 text-white shadow-lg shadow-brand-900/30 flex items-center justify-center text-2xl active:bg-brand-700"
        title="طلب تحويل جديد"
      >
        +
      </button>
    </div>
  )
}
