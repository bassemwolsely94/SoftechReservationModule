/**
 * NotificationPanel.jsx
 *
 * Pure presentational dropdown panel — all state is owned by the parent
 * (NotificationBell via useNotificationSocket).
 *
 * Props:
 *   notifications   Array    — notification objects from the hook
 *   unreadCount     number
 *   onMarkRead      (id)  => void
 *   onMarkAllRead   ()    => void
 *   onDelete        (id)  => void
 *   onClickNotif    (notif) => void
 *   onClose         ()    => void
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow, format, isToday, isYesterday } from 'date-fns'
import { ar } from 'date-fns/locale'
import { notificationsApi } from '../api/client'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ── Snooze presets ──────────────────────────────────────────────────────────────
function tomorrow9am() {
  const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0)
  return d.toISOString()
}
const SNOOZE_OPTS = [
  { label: '١٥ دقيقة',   get: () => ({ preset: '15m' }) },
  { label: 'ساعة',       get: () => ({ preset: '1h' }) },
  { label: '٣ ساعات',    get: () => ({ preset: '3h' }) },
  { label: 'غداً ٩ ص',   get: () => ({ until: tomorrow9am() }) },
]

// ── Type config ───────────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  stock_available:           { icon: '📦', bg: 'bg-green-50'  },
  reservation_assigned:      { icon: '👤', bg: 'bg-blue-50'   },
  reservation_created:       { icon: '➕', bg: 'bg-brand-50'  },
  reservation_status:        { icon: '🔄', bg: 'bg-indigo-50' },
  call_logged:               { icon: '📞', bg: 'bg-sky-50'    },  // was missing — fell back to ⚙️
  follow_up_due:             { icon: '📅', bg: 'bg-orange-50' },
  weekly_summary:            { icon: '📊', bg: 'bg-purple-50' },
  monthly_report:            { icon: '📈', bg: 'bg-purple-50' },
  transfer_request:          { icon: '🔀', bg: 'bg-yellow-50' },
  transfer_response:         { icon: '↩️', bg: 'bg-blue-50'   },
  unfulfilled_transfer_flag: { icon: '⚠️', bg: 'bg-red-50'    },
  demand_created:            { icon: '🆕', bg: 'bg-teal-50'   },
  demand_assigned:           { icon: '👤', bg: 'bg-teal-50'   },
  demand_status:             { icon: '🔄', bg: 'bg-teal-50'   },
  demand_follow_up:          { icon: '📅', bg: 'bg-teal-50'   },
  chatter_mention:           { icon: '💬', bg: 'bg-pink-50'   },
  mention:                   { icon: '@',  bg: 'bg-pink-50'   },
  personal_reminder:         { icon: '⏰', bg: 'bg-amber-50'  },
  churn_alert:               { icon: '⚠️', bg: 'bg-red-50'    },
  system:                    { icon: '⚙️', bg: 'bg-gray-50'   },
}

// ── Date helpers ──────────────────────────────────────────────────────────────

function dayLabel(dt) {
  const d = new Date(dt)
  if (isToday(d))     return 'اليوم'
  if (isYesterday(d)) return 'أمس'
  return toLatinDigits(format(d, 'd MMMM', { locale: ar }))
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
    return toLatinDigits(formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }))
  } catch { return '' }
}

// ── Notification row ──────────────────────────────────────────────────────────

function NotifRow({ notif, onMarkRead, onClickNotif, onDelete, onSnooze }) {
  const cfg = TYPE_CONFIG[notif.notification_type] || TYPE_CONFIG.system
  const [snoozeOpen, setSnoozeOpen] = useState(false)

  return (
    <div
      className={`group flex gap-3 px-4 py-3 transition-colors hover:bg-gray-50
        ${!notif.is_read ? 'bg-blue-50/40' : ''}`}
    >
      {/* Icon */}
      <div
        className={`w-9 h-9 rounded-full ${cfg.bg} flex items-center justify-center
          flex-shrink-0 text-base cursor-pointer`}
        onClick={() => onClickNotif(notif)}
      >
        {cfg.icon}
      </div>

      {/* Body */}
      <div
        className="flex-1 min-w-0 cursor-pointer"
        onClick={() => onClickNotif(notif)}
      >
        <div className={`text-sm font-semibold leading-tight ${notif.is_read ? 'text-gray-700' : 'text-gray-900'}`}>
          {notif.title}
        </div>
        {notif.body && (
          <div className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">
            {notif.body}
          </div>
        )}
        <div className="text-xs text-gray-400 mt-1">{notif.time_ago || timeAgo(notif.created_at)}</div>
      </div>

      {/* Side actions */}
      <div className="flex flex-col items-end gap-1 flex-shrink-0">
        {!notif.is_read && (
          <div className="w-2 h-2 rounded-full bg-blue-500 mt-1.5" />
        )}
        <div className="flex items-center gap-0.5">
          {/* Snooze ("remind me later") */}
          {onSnooze && (
            <div className="relative">
              <button
                onClick={(e) => { e.stopPropagation(); setSnoozeOpen(o => !o) }}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-300
                  hover:text-amber-500 p-0.5 rounded"
                title="تأجيل / ذكّرني لاحقاً"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </button>
              {snoozeOpen && (
                <div className="absolute left-0 top-full mt-1 z-30 bg-white rounded-lg shadow-xl border border-gray-100 py-1 w-28"
                  onClick={(e) => e.stopPropagation()}>
                  <div className="px-3 py-1 text-[10px] font-semibold text-gray-400">تأجيل حتى</div>
                  {SNOOZE_OPTS.map(o => (
                    <button key={o.label}
                      onClick={(e) => { e.stopPropagation(); setSnoozeOpen(false); onSnooze(notif.id, o.get()) }}
                      className="block w-full text-right px-3 py-1.5 text-xs text-gray-700 hover:bg-amber-50">
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(notif.id) }}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-300
              hover:text-red-500 p-0.5 rounded"
            title="حذف الإشعار"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Personal reminders ("remind me later") ──────────────────────────────────────

function RemindersSection() {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [when,  setWhen]  = useState('')

  const { data: items = [] } = useQuery({
    queryKey: ['personal-reminders'],
    queryFn: () => notificationsApi.reminders().then(r => Array.isArray(r.data) ? r.data : []),
    refetchInterval: 60_000,
  })
  const create = useMutation({
    mutationFn: (body) => notificationsApi.createReminder(body),
    onSuccess: () => { setTitle(''); setWhen(''); qc.invalidateQueries({ queryKey: ['personal-reminders'] }) },
  })
  const del = useMutation({
    mutationFn: (id) => notificationsApi.deleteReminder(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['personal-reminders'] }),
  })

  function add() {
    if (!title.trim() || !when) return
    create.mutate({ title: title.trim(), remind_at: new Date(when).toISOString() })
  }

  return (
    <div className="border-b border-gray-100 bg-amber-50/40 px-4 py-3">
      <input value={title} onChange={e => setTitle(e.target.value)} placeholder="⏰ ذكّرني بـ..."
        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400 text-right" />
      <div className="flex gap-1.5">
        <input type="datetime-local" value={when} onChange={e => setWhen(e.target.value)}
          className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5" dir="ltr" />
        <button onClick={add} disabled={!title.trim() || !when || create.isPending}
          className="text-xs bg-amber-500 text-white rounded-lg px-3 font-medium disabled:opacity-40">إضافة</button>
      </div>
      <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
        {items.length === 0 ? (
          <div className="text-[11px] text-gray-400 text-center py-1">لا توجد تذكيرات قادمة</div>
        ) : items.map(r => (
          <div key={r.id} className="flex items-center justify-between bg-white rounded-lg px-2 py-1 border border-amber-100">
            <div className="min-w-0">
              <div className="text-xs font-medium text-gray-800 truncate">{r.title}</div>
              <div className="text-[10px] text-amber-600">{r.time_until}</div>
            </div>
            <button onClick={() => del.mutate(r.id)} className="text-gray-300 hover:text-red-500 text-xs px-1 shrink-0">✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function NotificationPanel({
  notifications = [],
  unreadCount   = 0,
  onMarkRead,
  onMarkAllRead,
  onDelete,
  onSnooze,
  onClickNotif,
  onClose,
  onClearAll,   // provided by NotificationBell — handles API call + state refresh
  onOpenPrefs,
  onOpenInbox,
}) {
  const [filter,  setFilter]  = useState('all')   // 'all' | 'unread'
  const [search,  setSearch]  = useState('')
  const [clearing, setClearing] = useState(false)
  const [showReminders, setShowReminders] = useState(false)

  // Client-side filter + search (data is already fetched by the hook)
  let visible = notifications
  if (filter === 'unread') {
    visible = visible.filter(n => !n.is_read)
  }
  if (search.trim()) {
    const q = search.trim().toLowerCase()
    visible = visible.filter(
      n => n.title?.toLowerCase().includes(q) || n.body?.toLowerCase().includes(q)
    )
  }

  const groups = groupByDay(visible)

  async function handleClearAll() {
    if (!onClearAll) return
    setClearing(true)
    try {
      await onClearAll()   // parent handles API + state — no page reload needed
    } finally {
      setClearing(false)
    }
  }

  return (
    <div
      className="w-80 bg-white rounded-xl shadow-2xl border border-gray-100 flex flex-col overflow-hidden"
      style={{ maxHeight: '80vh', direction: 'rtl' }}
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div>
          <h2 className="font-bold text-gray-900 text-sm">الإشعارات</h2>
          {unreadCount > 0 && (
            <p className="text-xs text-gray-400">{unreadCount} غير مقروء</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowReminders(s => !s)}
            className={`text-xs font-medium px-1.5 py-0.5 rounded ${showReminders ? 'bg-amber-100 text-amber-700' : 'text-amber-600 hover:bg-amber-50'}`}
            title="تذكيرات شخصية"
          >
            ⏰ تذكير
          </button>
          {unreadCount > 0 && (
            <button
              onClick={onMarkAllRead}
              className="text-xs text-brand-600 hover:text-brand-800 font-medium"
            >
              قراءة الكل
            </button>
          )}
          {notifications.length > 0 && (
            <button
              onClick={handleClearAll}
              disabled={clearing}
              className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
            >
              {clearing ? '...' : 'حذف الكل'}
            </button>
          )}
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100"
          >
            ✕
          </button>
        </div>
      </div>

      {/* ── Personal reminders (toggle) ──────────────────────────────────── */}
      {showReminders && <RemindersSection />}

      {/* ── Filter tabs ──────────────────────────────────────────────────── */}
      <div className="flex border-b border-gray-100">
        {[
          { key: 'all',    label: 'الكل' },
          { key: 'unread', label: `غير مقروء (${unreadCount})` },
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`flex-1 py-2 text-xs font-semibold transition-colors
              ${filter === tab.key
                ? 'text-brand-700 border-b-2 border-brand-600'
                : 'text-gray-400 hover:text-gray-600'
              }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Search ───────────────────────────────────────────────────────── */}
      <div className="px-4 py-2 border-b border-gray-50">
        <div className="relative">
          <svg className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400"
            fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="بحث في الإشعارات..."
            className="w-full text-xs border border-gray-200 rounded-lg py-1.5 pr-8 pl-3
              focus:outline-none focus:ring-1 focus:ring-brand-400 text-right"
          />
        </div>
      </div>

      {/* ── List ─────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-center px-6">
            <div className="text-3xl mb-2">🔔</div>
            <div className="text-xs text-gray-500">
              {filter === 'unread' ? 'لا توجد إشعارات غير مقروءة' : 'لا توجد إشعارات'}
            </div>
          </div>
        ) : (
          groups.map(group => (
            <div key={group.label}>
              {/* Day separator */}
              <div className="sticky top-0 bg-gray-50 border-y border-gray-100 px-4 py-1 z-10">
                <span className="text-xs font-semibold text-gray-400">{group.label}</span>
              </div>
              <div className="divide-y divide-gray-50">
                {group.items.map(notif => (
                  <NotifRow
                    key={notif.id}
                    notif={notif}
                    onMarkRead={onMarkRead}
                    onClickNotif={onClickNotif}
                    onDelete={onDelete}
                    onSnooze={onSnooze}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <div className="border-t border-gray-100 px-3 py-2 flex items-center justify-between">
        {onOpenInbox
          ? <button onClick={onOpenInbox} className="text-xs text-brand-600 hover:text-brand-800 font-medium">📥 كل الإشعارات</button>
          : <span className="text-xs text-gray-400">يتجدد تلقائياً</span>}
        {onOpenPrefs && (
          <button onClick={onOpenPrefs} className="text-xs text-gray-500 hover:text-gray-800 font-medium">⚙️ الإعدادات</button>
        )}
      </div>
    </div>
  )
}
