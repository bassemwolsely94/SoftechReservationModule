/**
 * MobileShortagePage.jsx — phone shortage-lists queue (route: /m/shortage).
 *
 * Floor-capture surface: branch staff open a shortage list and log missing items
 * from the aisle. Thin list over the existing shortage API. Status chips + FAB.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { shortageApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const STATUS_CLASS = {
  open:      'bg-orange-100 text-orange-700',
  submitted: 'bg-blue-100 text-blue-700',
  resolved:  'bg-green-100 text-green-700',
}
const FILTERS = [
  { value: 'open',      label: 'مفتوحة' },
  { value: '',          label: 'الكل' },
  { value: 'submitted', label: 'مُرسَلة' },
  { value: 'resolved',  label: 'محلولة' },
]

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function ListCard({ l, onOpen }) {
  return (
    <button onClick={onOpen}
      className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-bold text-sm text-gray-900 line-clamp-1">{l.title || `نواقص ${l.branch_name || ''}`}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${STATUS_CLASS[l.status] || 'bg-gray-100 text-gray-700'}`}>
          {l.status_label}
        </span>
      </div>
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{toLatin(l.item_count)} صنف · {toLatin(l.confirmed_count)} مؤكد</span>
        <span>{l.created_at ? toLatin(formatDistanceToNow(new Date(l.created_at), { locale: ar, addSuffix: true })) : ''}</span>
      </div>
    </button>
  )
}

export default function MobileShortagePage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('open')

  const params = { page_size: 25 }
  if (filter) params.status = filter

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['m-shortage', filter],
      queryFn: ({ pageParam }) =>
        (pageParam ? api.get(pageParam).then(r => r.data)
                   : shortageApi.list(params).then(r => r.data)),
      initialPageParam: null,
      getNextPageParam: (last) => last.next || undefined,
    })

  const rows = (data?.pages || []).flatMap(p => p.results || (Array.isArray(p) ? p : []))

  return (
    <div className="p-3 space-y-3">
      <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1">
        {FILTERS.map(f => (
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
        <MobileError text="تعذّر تحميل القوائم" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="🚨" text="لا توجد قوائم نواقص" />
      ) : (
        <div className="space-y-2.5">
          {rows.map(l => <ListCard key={l.id} l={l} onOpen={() => navigate(`/m/shortage/${l.id}`)} />)}
          {hasNextPage && (
            <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
              className="w-full py-3 text-sm text-brand-600 font-medium disabled:opacity-50">
              {isFetchingNextPage ? 'جارٍ التحميل...' : 'تحميل المزيد'}
            </button>
          )}
        </div>
      )}

      <button onClick={() => navigate('/m/shortage/new')}
        className="fixed bottom-20 left-4 z-20 w-14 h-14 rounded-full bg-brand-600 text-white shadow-lg shadow-brand-900/30 flex items-center justify-center text-2xl active:bg-brand-700"
        title="قائمة نواقص جديدة">
        +
      </button>
    </div>
  )
}
