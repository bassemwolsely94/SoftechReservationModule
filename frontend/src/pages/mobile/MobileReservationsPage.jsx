/**
 * MobileReservationsPage.jsx — phone reservation queue.
 *
 * Standalone mobile surface (route: /m/reservations). Thin card list over the
 * existing reservations API — branch-scoped server-side for branch roles.
 * Status filter chips + infinite "load more" following the cursor `next` link.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { reservationsApi } from '../../api/client'
import { StatusBadge, PriorityBadge } from '../../components/StatusBadge'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// Active-work statuses front-and-centre; terminal states behind their own chips.
const FILTERS = [
  { value: 'open',      label: 'النشطة' },   // pseudo: pending+available+contacted+confirmed
  { value: '',          label: 'الكل' },
  { value: 'pending',   label: 'قيد الانتظار' },
  { value: 'available', label: 'المخزون متاح' },
  { value: 'contacted', label: 'تم التواصل' },
  { value: 'confirmed', label: 'مؤكد' },
  { value: 'fulfilled', label: 'تم التسليم' },
  { value: 'cancelled', label: 'ملغي' },
]

const OPEN_STATUSES = ['pending', 'available', 'contacted', 'confirmed']

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function ReservationCard({ r, onOpen }) {
  const itemName = r.lines_count > 1
    ? `${r.item_name} +${r.lines_count - 1}`
    : r.item_name

  return (
    <button
      onClick={onOpen}
      className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50 transition-colors"
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-bold text-sm text-gray-900 leading-snug break-words">{itemName}</span>
        <span className="text-[11px] text-gray-400 shrink-0 mt-0.5">#{r.id}</span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        <StatusBadge status={r.status} />
        {r.priority && r.priority !== 'normal' && <PriorityBadge priority={r.priority} />}
        <span className="text-[11px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
          الكمية: {toLatin(r.quantity_requested)}
        </span>
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="truncate">{r.customer_name || 'عميل'}</span>
        <span className="shrink-0">
          {r.created_at
            ? toLatin(formatDistanceToNow(new Date(r.created_at), { locale: ar, addSuffix: true }))
            : ''}
        </span>
      </div>
    </button>
  )
}

export default function MobileReservationsPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('open')

  const params = { page_size: 25, ordering: '-created_at' }
  if (filter && filter !== 'open') params.status = filter
  if (filter === 'open') params.status__in = OPEN_STATUSES.join(',')

  const {
    data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['m-reservations', filter],
    queryFn: ({ pageParam }) =>
      (pageParam
        ? api.get(pageParam).then(r => r.data)
        : reservationsApi.list(params).then(r => r.data)),
    initialPageParam: null,
    getNextPageParam: (lastPage) => lastPage.next || undefined,
  })

  const pages = data?.pages || []
  const rows = pages.flatMap(p => p.results || [])

  return (
    <div className="p-3 space-y-3">

      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1">
        {FILTERS.map(f => (
          <button
            key={f.value || 'all'}
            onClick={() => setFilter(f.value)}
            className={`shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f.value
                ? 'bg-brand-600 text-white'
                : 'bg-white border border-gray-200 text-gray-600 active:bg-gray-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* List */}
      {isLoading ? (
        <MobileLoading />
      ) : isError ? (
        <MobileError text="تعذّر تحميل الحجوزات" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="📋" text="لا توجد حجوزات" />
      ) : (
        <div className="space-y-2.5">
          {rows.map(r => (
            <ReservationCard key={r.id} r={r} onOpen={() => navigate(`/m/reservations/${r.id}`)} />
          ))}

          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="w-full py-3 text-sm text-brand-600 font-medium disabled:opacity-50"
            >
              {isFetchingNextPage ? 'جارٍ التحميل...' : 'تحميل المزيد'}
            </button>
          )}
        </div>
      )}

      {/* Floating new-reservation button */}
      <button
        onClick={() => navigate('/m/reservations/new')}
        className="fixed bottom-20 left-4 z-20 w-14 h-14 rounded-full bg-brand-600 text-white shadow-lg shadow-brand-900/30 flex items-center justify-center text-2xl active:bg-brand-700"
        title="حجز جديد"
      >
        +
      </button>
    </div>
  )
}
