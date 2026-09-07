/**
 * MobileStockCountPage.jsx — stock-count sessions monitor (route: /m/stock-count).
 *
 * Read/monitor surface: list sessions, open one to see status + variance.
 * (Live aisle count-entry would need a per-item count endpoint — not built here;
 * counting today flows through the exported/uploaded sheet on desktop.)
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { stockCountApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'

function ago(d) {
  try { return new Date(d).toLocaleDateString('en-GB') } catch { return '' }
}

export default function MobileStockCountPage() {
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-stockcount'],
    queryFn: () => stockCountApi.list({ page_size: 30 }).then(r => r.data),
  })
  const rows = Array.isArray(data) ? data : (data?.results || [])

  return (
    <div className="p-3 space-y-3">
      <h1 className="text-base font-bold text-gray-900">جلسات الجرد</h1>
      {isLoading ? <MobileLoading />
        : isError ? <MobileError text="تعذّر تحميل الجلسات" onRetry={refetch} />
        : rows.length === 0 ? <MobileEmpty icon="📦" text="لا توجد جلسات جرد" />
        : (
          <div className="space-y-2.5">
            {rows.map(s => (
              <button key={s.id} onClick={() => navigate(`/m/stock-count/${s.id}`)}
                className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <span className="font-bold text-sm text-gray-900">{s.name || s.title || `جرد #${s.id}`}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-700 shrink-0">
                    {s.status_label || s.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-gray-400 mt-1">
                  <span>{s.branch_name || s.branch_name_ar || ''}</span>
                  <span>{s.created_at ? ago(s.created_at) : ''}</span>
                </div>
              </button>
            ))}
          </div>
        )}
    </div>
  )
}
