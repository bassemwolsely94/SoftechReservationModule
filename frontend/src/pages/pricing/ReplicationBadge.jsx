/** ReplicationBadge — inline per-request branch replication status with a
 *  force-replication action. Lazy-loads on expand. */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

const DOT = {
  replicated:  'bg-emerald-500',
  stale:       'bg-amber-500',
  unreachable: 'bg-red-500',
}
const LABEL = { replicated: 'متزامن', stale: 'متأخر', unreachable: 'متوقف' }

export default function ReplicationBadge({ requestId, isAdmin }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['req-replication', requestId],
    queryFn: () => pricingApprovalsApi.replication(requestId).then(r => r.data),
    enabled: open,
  })

  const force = useMutation({
    mutationFn: (mode) => pricingApprovalsApi.forceReplication(requestId, mode),
    onSuccess: () => refetch(),
  })

  const branches = data?.branches || []
  const okCount = branches.filter(b => b.status === 'replicated').length

  return (
    <div className="inline-block">
      <button onClick={() => setOpen(o => !o)}
        className="text-xs px-2 py-0.5 rounded-full border border-gray-200 bg-gray-50 hover:bg-gray-100 inline-flex items-center gap-1">
        🔁 النسخ للفروع {open ? '▲' : '▼'}
        {data && <span className={data.fully_replicated ? 'text-emerald-600' : 'text-amber-600'}>
          {okCount}/{branches.length}
        </span>}
      </button>

      {open && (
        <div className="mt-1.5 bg-white border border-gray-200 rounded-lg shadow-sm p-2 w-64 text-xs space-y-1">
          {isFetching && <div className="text-gray-400 py-1">جاري الفحص…</div>}
          {data?.source && (
            <div className="pb-1 mb-1 border-b text-gray-500">
              المصدر: <span className="font-medium">{data.source.label}</span>
            </div>
          )}
          {branches.map(b => (
            <div key={b.code} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${DOT[b.status]}`} />
                <span className="font-mono">{b.code}</span>
                <span className="text-gray-400 truncate max-w-[90px]">{b.name}</span>
              </span>
              <span className={b.status === 'replicated' ? 'text-emerald-600' : 'text-amber-600'}>
                {LABEL[b.status]}
              </span>
            </div>
          ))}
          {isAdmin && data && !data.fully_replicated && (
            <div className="pt-1.5 mt-1 border-t flex gap-1.5">
              <button onClick={() => force.mutate('restamp')} disabled={force.isPending}
                className="flex-1 bg-amber-600 text-white rounded px-2 py-1 hover:bg-amber-700 disabled:opacity-60">
                إعادة مزامنة (الدورة)
              </button>
              <button onClick={() => force.mutate('both')} disabled={force.isPending}
                className="flex-1 bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:opacity-60">
                فوري
              </button>
            </div>
          )}
          {force.data && <div className="text-emerald-600 pt-1">تم — أعد الفتح للتأكيد</div>}
        </div>
      )}
    </div>
  )
}
