import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { notificationsApi } from '../api/client'

const TYPE_ICONS = {
  stock_available:    '📦',
  follow_up_due:      '📅',
  reservation_new:    '🆕',
  status_changed:     '🔄',
  call_logged:        '📞',
  reservation_urgent: '🚨',
  system:             '⚙️',
}

// Gentle notification sound using Web Audio API (no file needed)
function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.setValueAtTime(880, ctx.currentTime)
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.1)
    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.4)
  } catch {
    // AudioContext not available — silent fallback
  }
}

export default function NotificationBell() {
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState([])
  const [open, setOpen] = useState(false)
  const [flashing, setFlashing] = useState(false)
  const prevCount = useRef(0)
  const navigate = useNavigate()

  const fetchCount = useCallback(async () => {
    try {
      const { data } = await notificationsApi.unreadCount()
      const newCount = data.unread_count

      if (newCount > prevCount.current && prevCount.current !== null) {
        // New notification arrived
        setFlashing(true)
        playNotificationSound()
        setTimeout(() => setFlashing(false), 3000)
      }
      prevCount.current = newCount
      setUnreadCount(newCount)
    } catch {
      // Silently fail
    }
  }, [])

  const fetchNotifications = useCallback(async () => {
    try {
      const { data } = await notificationsApi.list()
      setNotifications(data.notifications || [])
      setUnreadCount(data.unread_count || 0)
    } catch {
      // Silently fail
    }
  }, [])

  // Poll for new notifications every 30 seconds
  useEffect(() => {
    fetchCount()
    const interval = setInterval(fetchCount, 30_000)
    return () => clearInterval(interval)
  }, [fetchCount])

  const handleOpen = () => {
    setOpen(v => !v)
    if (!open) fetchNotifications()
  }

  const handleMarkRead = async (id) => {
    try {
      await notificationsApi.markRead(id)
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, is_read: true } : n)
      )
      setUnreadCount(prev => Math.max(0, prev - 1))
    } catch { /* silent */ }
  }

  const handleMarkAllRead = async () => {
    try {
      await notificationsApi.markAllRead()
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnreadCount(0)
    } catch { /* silent */ }
  }

  const handleClick = async (notif) => {
    if (!notif.is_read) await handleMarkRead(notif.id)
    if (notif.reservation_id) {
      setOpen(false)
      navigate(`/reservations/${notif.reservation_id}`)
    }
  }

  const formatTime = (dateStr) => {
    const d = new Date(dateStr)
    const now = new Date()
    const diffMin = Math.floor((now - d) / 60000)
    if (diffMin < 1) return 'الآن'
    if (diffMin < 60) return `منذ ${diffMin} دقيقة`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `منذ ${diffHr} ساعة`
    return d.toLocaleDateString('ar-EG')
  }

  return (
    <div className="relative" dir="rtl">
      {/* Bell button */}
      <button
        onClick={handleOpen}
        className={`relative p-2 rounded-lg transition-colors duration-150
          ${flashing
            ? 'bg-orange-100 text-orange-600 animate-pulse'
            : 'text-brand-200 hover:text-white hover:bg-brand-600'
          }`}
        title="الإشعارات"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>

        {/* Badge */}
        {unreadCount > 0 && (
          <span className={`absolute -top-1 -left-1 min-w-[18px] h-[18px] 
            bg-red-500 text-white text-xs font-bold rounded-full 
            flex items-center justify-center px-1
            ${flashing ? 'animate-bounce' : ''}`}>
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />

          <div className="absolute left-0 top-full mt-2 w-80 bg-white rounded-xl shadow-xl border border-gray-100 z-50 animate-fade-in overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <span className="font-bold text-gray-800 text-sm">
                الإشعارات
                {unreadCount > 0 && (
                  <span className="mr-2 badge bg-red-100 text-red-700">{unreadCount} جديد</span>
                )}
              </span>
              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="text-xs text-brand-600 hover:underline"
                >
                  تحديد الكل كمقروء
                </button>
              )}
            </div>

            {/* Notifications list */}
            <div className="max-h-96 overflow-y-auto divide-y divide-gray-50">
              {notifications.length === 0 ? (
                <div className="py-10 text-center text-gray-400 text-sm">
                  لا توجد إشعارات
                </div>
              ) : (
                notifications.map(n => (
                  <div
                    key={n.id}
                    onClick={() => handleClick(n)}
                    className={`flex gap-3 px-4 py-3 cursor-pointer transition-colors
                      ${n.is_read
                        ? 'hover:bg-gray-50'
                        : 'bg-orange-50 hover:bg-orange-100'
                      }`}
                  >
                    <div className="text-xl flex-shrink-0 mt-0.5">
                      {TYPE_ICONS[n.notification_type] || '🔔'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm font-semibold truncate
                        ${n.is_read ? 'text-gray-700' : 'text-gray-900'}`}>
                        {n.title}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">
                        {n.message}
                      </div>
                      <div className="text-xs text-gray-400 mt-1">
                        {formatTime(n.created_at)}
                      </div>
                    </div>
                    {!n.is_read && (
                      <div className="w-2 h-2 bg-brand-500 rounded-full flex-shrink-0 mt-2" />
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
