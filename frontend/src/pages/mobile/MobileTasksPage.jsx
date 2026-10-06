/**
 * MobileTasksPage.jsx — operational tasks queue (route: /m/tasks).
 * Thin list over /tasks/. Status chips + tap to detail. FAB omitted (creation
 * stays on desktop); this is an on-the-go "what do I need to do" surface.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import api, { tasksApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function ago(d) {
  try { return formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true }).replace(/[٠-٩]/g, x => String.fromCharCode(x.charCodeAt(0) - 0x660)) }
  catch { return '' }
}

const FILTERS = [
  { value: 'open',        label: 'مفتوحة' },
  { value: '',            label: 'الكل' },
  { value: 'in_progress', label: 'جارية' },
  { value: 'done',        label: 'منجزة' },
]

export default function MobileTasksPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('open')

  const params = { page_size: 25 }
  if (filter) params.status = filter

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['m-tasks', filter],
      queryFn: ({ pageParam }) =>
        (pageParam ? api.get(pageParam).then(r => r.data) : tasksApi.list(params).then(r => r.data)),
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
            }`}>{f.label}</button>
        ))}
      </div>

      {isLoading ? <MobileLoading />
        : isError ? <MobileError text="تعذّر تحميل المهام" onRetry={refetch} />
        : rows.length === 0 ? <MobileEmpty icon="✅" text="لا توجد مهام" />
        : (
          <div className="space-y-2.5">
            {rows.map(t => (
              <button key={t.id} onClick={() => navigate(`/m/tasks/${t.id}`)}
                className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <span className="font-bold text-sm text-gray-900 leading-snug">{t.title}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-700 shrink-0">
                    {t.status_label || t.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-gray-400 mt-1">
                  <span>{t.priority_label || t.assigned_to_name || ''}</span>
                  <span>{t.due_date ? `يستحق: ${t.due_date}` : (t.created_at ? ago(t.created_at) : '')}</span>
                </div>
              </button>
            ))}
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
