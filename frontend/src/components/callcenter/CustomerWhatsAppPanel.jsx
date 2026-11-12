import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { omniApi } from '../../api/client'

const fmt = (dt) => dt ? new Date(dt).toLocaleString('ar-EG', {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
}) : ''

/**
 * The caller's recent WhatsApp / social messages from the omni inbox, beside the
 * call-center profile. Display only — replying stays in the inbox.
 */
export default function CustomerWhatsAppPanel({ customerId }) {
  const { data: convo } = useQuery({
    queryKey: ['cc-omni-convo', customerId],
    queryFn: () => omniApi.conversations({ customer: customerId })
      .then(r => (r.data.results || r.data)[0] || null),
    enabled: !!customerId,
    staleTime: 30_000,
  })
  const { data: events = [], isLoading } = useQuery({
    queryKey: ['cc-omni-timeline', convo?.id],
    queryFn: () => omniApi.timeline(convo.id, { types: 'message_in,message_out', latest: 8 })
      .then(r => (r.data.results || r.data).slice().reverse()),
    enabled: !!convo?.id,
    refetchInterval: 30_000,
  })

  if (!customerId || convo === undefined) return null
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide">💬 آخر الرسائل</div>
        {convo && (
          <Link to={`/omni/inbox?conversation=${convo.id}`} className="text-xs text-brand-600 hover:underline">
            فتح المحادثة ←
          </Link>
        )}
      </div>
      {!convo ? (
        <div className="text-xs text-gray-400">لا توجد رسائل لهذا العميل</div>
      ) : isLoading ? (
        <div className="text-xs text-gray-400">جارٍ التحميل…</div>
      ) : events.length === 0 ? (
        <div className="text-xs text-gray-400">لا توجد رسائل حديثة</div>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-auto">
          {events.map(e => {
            const inbound = e.event_type === 'message_in'
            return (
              <div key={e.id} className={`flex ${inbound ? 'justify-start' : 'justify-end'}`}>
                <div className={`max-w-[85%] rounded-xl px-2.5 py-1.5 text-xs ${inbound
                  ? 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-100'
                  : 'bg-green-50 dark:bg-green-900/30 text-green-900 dark:text-green-100'}`}>
                  <div className="whitespace-pre-wrap break-words" dir="auto">{e.summary}</div>
                  <div className="text-[10px] text-gray-400 mt-0.5">
                    {fmt(e.occurred_at)}{!inbound && e.actor_name ? ` · ${e.actor_name}` : ''}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
