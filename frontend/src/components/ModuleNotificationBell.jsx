/**
 * ModuleNotificationBell.jsx
 *
 * A module-scoped notification bell. Unlike the global NotificationBell, this
 * shows ONLY one category's feed (e.g. 'demand' or 'followups') — the
 * notifications that were intentionally kept out of the global bell to reduce
 * noise. Mount it in a module's header; it is "active only inside the module".
 *
 * Props:
 *   category  — 'demand' | 'followups' | 'monitoring' | 'settings'
 *   label     — short Arabic label for the header / empty state (optional)
 *   icon      — emoji shown on the button (default 🔔)
 */
import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '../api/client'
import useNotificationStore from '../store/notificationStore'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatin = s => s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

function timeAgo(d) {
  if (!d) return ''
  try { return toLatin(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' }
}

export default function ModuleNotificationBell({ category, label = 'إشعارات الوحدة', icon = '🔔' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const qc = useQueryClient()
  const moduleCounts = useNotificationStore(s => s.moduleCounts)
  const refreshCounts = useNotificationStore(s => s.refresh)
  const count = moduleCounts[category] || 0

  // Close on outside click
  useEffect(() => {
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const { data: items = [], refetch } = useQuery({
    queryKey: ['module-notifications', category],
    queryFn: () => notificationsApi.list({ category, limit: 50 }).then(r => Array.isArray(r.data) ? r.data : []),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  })

  const after = () => { refetch(); refreshCounts() }
  const markOne = useMutation({ mutationFn: id => notificationsApi.markRead(id), onSuccess: after })
  const markAll = useMutation({ mutationFn: () => notificationsApi.markAllRead({ category }), onSuccess: after })

  function openPanel() {
    setOpen(o => !o)
    if (!open) { refetch(); refreshCounts() }
  }

  return (
    <div className="relative" ref={ref}>
      <button onClick={openPanel}
        className="btn-secondary text-sm relative"
        title={label}>
        {icon}
        {count > 0 && (
          <span className="absolute -top-2 -left-2 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 mt-2 w-80 max-h-[70vh] bg-white rounded-2xl shadow-2xl border border-gray-100 z-50 flex flex-col" dir="rtl">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <span className="text-sm font-bold text-gray-700">{label}</span>
            {count > 0 && (
              <button onClick={() => markAll.mutate()} disabled={markAll.isPending}
                className="text-xs text-brand-600 hover:underline disabled:opacity-50">
                تعليم الكل كمقروء
              </button>
            )}
          </div>
          <div className="overflow-y-auto flex-1">
            {items.length === 0 ? (
              <div className="text-center py-10 text-gray-400 text-sm">لا توجد إشعارات</div>
            ) : items.map(n => (
              <div key={n.id}
                onClick={() => { if (!n.is_read) markOne.mutate(n.id) }}
                className={`px-4 py-3 border-b border-gray-50 last:border-0 cursor-pointer transition-colors ${
                  n.is_read ? 'bg-white hover:bg-gray-50' : 'bg-brand-50/50 hover:bg-brand-50'
                }`}>
                <div className="flex items-start gap-2">
                  <span className="text-base leading-none mt-0.5">{n.type_icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm ${n.is_read ? 'text-gray-700' : 'font-semibold text-gray-900'}`}>
                      {n.title}
                    </div>
                    {n.body && <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</div>}
                    <div className="text-[11px] text-gray-400 mt-1">{timeAgo(n.created_at)}</div>
                  </div>
                  {!n.is_read && <span className="w-2 h-2 rounded-full bg-red-500 mt-1.5 shrink-0" />}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
