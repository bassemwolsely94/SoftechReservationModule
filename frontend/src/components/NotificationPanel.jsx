/**
 * NotificationPanel.jsx
 *
 * A complete notification system component for ElRezeiky platform.
 *
 * Usage in Layout.jsx:
 *   import NotificationPanel from './NotificationPanel'
 *   <NotificationPanel collapsed={collapsed} />
 *
 * The bell icon lives in the sidebar. Clicking it opens a slide-in panel
 * over the right side of the screen showing the 50 most recent notifications,
 * grouped by day, with mark-read and navigate-to-source actions.
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '../api/client'
import { formatDistanceToNow, format, isToday, isYesterday } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Type config ───────────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  stock_available:           { icon: '📦', color: 'text-green-600',  bg: 'bg-green-50'   },
  reservation_assigned:      { icon: '👤', color: 'text-blue-600',   bg: 'bg-blue-50'    },
  reservation_created:       { icon: '➕', color: 'text-brand-600',  bg: 'bg-brand-50'   },
  reservation_status:        { icon: '🔄', color: 'text-indigo-600', bg: 'bg-indigo-50'  },
  follow_up_due:             { icon: '📅', color: 'text-orange-600', bg: 'bg-orange-50'  },
  weekly_summary:            { icon: '📊', color: 'text-purple-600', bg: 'bg-purple-50'  },
  monthly_report:            { icon: '📈', color: 'text-purple-700', bg: 'bg-purple-50'  },
  mention:                   { icon: '@',  color: 'text-pink-600',   bg: 'bg-pink-50'    },
  transfer_request:          { icon: '🔀', color: 'text-yellow-700', bg: 'bg-yellow-50'  },
  transfer_response:         { icon: '↩️', color: 'text-blue-600',   bg: 'bg-blue-50'    },
  unfulfilled_transfer_flag: { icon: '⚠️', color: 'text-red-600',    bg: 'bg-red-50'     },
  system:                    { icon: '⚙️', color: 'text-gray-600',   bg: 'bg-gray-50'    },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function dayLabel(dt) {
  const d = new Date(dt)
  if (isToday(d)) return 'اليوم'
  if (isYesterday(d)) return 'أمس'
  return format(d, 'd MMMM', { locale: ar })
}

function groupByDay(notifications) {
  const groups = []
  const seen = {}
  for (const n of notifications) {
    const label = dayLabel(n.created_at)
    if (!seen[label]) {
      seen[label] = { label, items: [] }
      groups.push(seen[label])
    }
    seen[label].items.push(n)
  }
  return groups
}

function timeAgo(dt) {
  try {
    return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true })
  } catch { return '' }
}

// ── Single notification row ───────────────────────────────────────────────────

function NotifRow({ notif, onRead, onNavigate }) {
  const cfg = TYPE_CONFIG[notif.notification_type] || TYPE_CONFIG.system

  return (
    <div
      className={`flex gap-3 px-4 py-3 cursor-pointer transition-colors hover:bg-gray-50 ${
        !notif.is_read ? 'bg-blue-50/40' : ''
      }`}
      onClick={() => {
        if (!notif.is_read) onRead(notif.id)
        onNavigate(notif)
      }}
    >
      {/* Icon */}
      <div className={`w-9 h-9 rounded-full ${cfg.bg} flex items-center justify-center flex-shrink-0 text-base`}>
        {cfg.icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className={`text-sm font-semibold leading-tight ${notif.is_read ? 'text-gray-700' : 'text-gray-900'}`}>
          {notif.title}
        </div>
        {notif.body && (
          <div className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">
            {notif.body}
          </div>
        )}
        <div className="text-xs text-gray-400 mt-1">{timeAgo(notif.created_at)}</div>
      </div>

      {/* Unread dot */}
      {!notif.is_read && (
        <div className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0 mt-1.5" />
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function NotificationPanel({ collapsed }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('all') // 'all' | 'unread'
  const panelRef = useRef()
  const navigate = useNavigate()
  const qc = useQueryClient()

  // Unread count — polled every 60s
  const { data: countData } = useQuery({
    queryKey: ['notif-unread-count'],
    queryFn: () => notificationsApi.unreadCount().then(r => r.data),
    refetchInterval: 60_000,
  })
  const unreadCount = countData?.count || 0

  // Full notification list — only loaded when panel is open
  const { data: notifications = [], isLoading } = useQuery({
    queryKey: ['notifications', filter],
    queryFn: () => notificationsApi.list(
      filter === 'unread' ? { unread_only: 'true' } : {}
    ).then(r => r.data),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  })

  // Mark single read
  const markReadMutation = useMutation({
    mutationFn: (id) => notificationsApi.markRead(id),
    onSuccess: () => {
      qc.invalidateQueries(['notifications'])
      qc.invalidateQueries(['notif-unread-count'])
    },
  })

  // Mark all read
  const markAllMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      qc.invalidateQueries(['notifications'])
      qc.invalidateQueries(['notif-unread-count'])
    },
  })

  // Close panel when clicking outside
  useEffect(() => {
    if (!open) return
    function handler(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Navigate to source object when clicking a notification
  function handleNavigate(notif) {
    setOpen(false)
    if (notif.reservation) {
      navigate(`/reservations/${notif.reservation}`)
    } else if (notif.transfer_request_id_ref) {
      navigate(`/transfers/${notif.transfer_request_id_ref}`)
    }
  }

  const groups = groupByDay(notifications)

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell button */}
      <button
        onClick={() => setOpen(v => !v)}
        className={`relative transition-colors ${
          open
            ? 'text-white'
            : 'text-brand-300 hover:text-white'
        }`}
        title="الإشعارات"
        aria-label="الإشعارات"
      >
        {/* Bell icon */}
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>

        {/* Badge */}
        {unreadCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center px-1 leading-none shadow">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Panel */}
      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />

          {/* Slide-in panel */}
          <div
            className="fixed top-0 left-0 h-full w-80 bg-white shadow-2xl z-50 flex flex-col animate-slide-in"
            style={{ direction: 'rtl' }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-4 border-b border-gray-100">
              <div>
                <h2 className="font-bold text-gray-900 text-base">الإشعارات</h2>
                {unreadCount > 0 && (
                  <p className="text-xs text-gray-400">{unreadCount} غير مقروء</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {unreadCount > 0 && (
                  <button
                    onClick={() => markAllMutation.mutate()}
                    disabled={markAllMutation.isPending}
                    className="text-xs text-brand-600 hover:text-brand-800 font-medium disabled:opacity-50"
                  >
                    {markAllMutation.isPending ? '...' : 'قراءة الكل'}
                  </button>
                )}
                <button
                  onClick={() => setOpen(false)}
                  className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Filter tabs */}
            <div className="flex border-b border-gray-100">
              {[
                { key: 'all',    label: 'الكل' },
                { key: 'unread', label: `غير مقروء (${unreadCount})` },
              ].map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setFilter(tab.key)}
                  className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                    filter === tab.key
                      ? 'text-brand-700 border-b-2 border-brand-600'
                      : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto">
              {isLoading && (
                <div className="p-6 space-y-3">
                  {[1, 2, 3].map(i => (
                    <div key={i} className="flex gap-3 animate-pulse">
                      <div className="w-9 h-9 rounded-full bg-gray-100 flex-shrink-0" />
                      <div className="flex-1 space-y-1.5">
                        <div className="h-3 bg-gray-100 rounded w-3/4" />
                        <div className="h-2 bg-gray-100 rounded w-full" />
                        <div className="h-2 bg-gray-100 rounded w-1/2" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!isLoading && notifications.length === 0 && (
                <div className="flex flex-col items-center justify-center h-48 text-center px-6">
                  <div className="text-4xl mb-3">🔔</div>
                  <div className="text-sm text-gray-500 font-medium">
                    {filter === 'unread' ? 'لا توجد إشعارات غير مقروءة' : 'لا توجد إشعارات'}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    ستظهر هنا إشعارات الحجوزات والتحويلات
                  </div>
                </div>
              )}

              {!isLoading && groups.map(group => (
                <div key={group.label}>
                  {/* Day separator */}
                  <div className="sticky top-0 bg-gray-50 border-y border-gray-100 px-4 py-1.5 z-10">
                    <span className="text-xs font-semibold text-gray-400">{group.label}</span>
                  </div>

                  {/* Notifications in this day */}
                  <div className="divide-y divide-gray-50">
                    {group.items.map(notif => (
                      <NotifRow
                        key={notif.id}
                        notif={notif}
                        onRead={(id) => markReadMutation.mutate(id)}
                        onNavigate={handleNavigate}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="border-t border-gray-100 px-4 py-3">
              <p className="text-xs text-gray-400 text-center">
                آخر 50 إشعار · يتجدد كل 60 ثانية
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
