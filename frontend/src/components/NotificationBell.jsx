/**
 * NotificationBell.jsx
 *
 * Toolbar bell icon + dropdown panel + toast overlay.
 * Uses useNotificationSocket for real-time delivery (WS) with REST polling
 * fallback.  Plays a sound + flash animation + toast on new notifications.
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useNotificationSocket,
  pushSupported, isDesktopPushOn, setDesktopPush,
} from '../hooks/useNotificationSocket'
import { notificationsApi } from '../api/client'
import NotificationPanel from './NotificationPanel'
import NotificationPreferencesModal from './NotificationPreferencesModal'

// ── Toast overlay ─────────────────────────────────────────────────────────────
// Routine notifications get a quiet white toast; the actionable alarm tiers get a
// prominent coloured, pulsing visual alarm (critical = red, high = amber).
const TIER_STYLE = {
  critical: 'bg-red-50 border-red-300 ring-2 ring-red-400/60 animate-pulse',
  high:     'bg-amber-50 border-amber-300 ring-2 ring-amber-300/60',
  '':       'bg-white border-gray-100',
}
const TIER_BADGE = {
  critical: { dot: 'bg-red-500',   text: 'عاجل' },
  high:     { dot: 'bg-amber-500', text: 'هام' },
}

function NotificationToast({ toast, onDismiss }) {
  if (!toast) return null
  const tier  = toast.tier || ''
  const badge = TIER_BADGE[tier]
  return (
    <div
      className={`fixed bottom-6 left-6 z-[9999] max-w-sm w-full rounded-xl shadow-2xl
        border flex items-start gap-3 px-4 py-3 animate-toast-in ${TIER_STYLE[tier] || TIER_STYLE['']}`}
      dir="rtl"
      onClick={onDismiss}
      style={{ cursor: 'pointer' }}
    >
      <div className="text-2xl flex-shrink-0 mt-0.5">{toast.icon || '🔔'}</div>
      <div className="flex-1 min-w-0">
        {badge && (
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={`w-2 h-2 rounded-full ${badge.dot} animate-ping`} />
            <span className={`text-[10px] font-black ${tier === 'critical' ? 'text-red-600' : 'text-amber-600'}`}>
              {badge.text}
            </span>
          </div>
        )}
        <div className="text-sm font-semibold text-gray-900 leading-tight truncate">
          {toast.title}
        </div>
        {toast.body && (
          <div className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">
            {toast.body}
          </div>
        )}
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDismiss() }}
        className="text-gray-300 hover:text-gray-500 flex-shrink-0 mt-0.5"
      >
        ✕
      </button>
    </div>
  )
}

// ── Critical in-app banner (top of screen, persistent) ─────────────────────────

function NotificationBanner({ banner, onView, onDismiss }) {
  if (!banner) return null
  return (
    <div className="fixed top-0 inset-x-0 z-[9998] flex justify-center px-4 pt-3 pointer-events-none" dir="rtl">
      <div className="pointer-events-auto max-w-2xl w-full bg-red-600 text-white rounded-xl shadow-2xl
        flex items-center gap-3 px-4 py-3 animate-toast-in ring-2 ring-red-300/50">
        <span className="text-xl flex-shrink-0">{banner.icon || '🚨'}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold leading-tight">{banner.title}</div>
          {banner.body && <div className="text-xs text-white/85 truncate">{banner.body}</div>}
        </div>
        {onView && (
          <button onClick={onView}
            className="text-xs font-bold bg-white/20 hover:bg-white/30 rounded-lg px-3 py-1.5 flex-shrink-0">
            عرض
          </button>
        )}
        <button onClick={onDismiss} className="text-white/70 hover:text-white flex-shrink-0 text-lg leading-none">✕</button>
      </div>
    </div>
  )
}

// ── Bell ──────────────────────────────────────────────────────────────────────

export default function NotificationBell() {
  const [open,     setOpen]     = useState(false)
  const [flashing, setFlashing] = useState(false)
  const [desktopOn, setDesktopOnState] = useState(isDesktopPushOn())
  const prevCount  = useRef(null)
  const navigate   = useNavigate()

  // Sync desktop-push state from the server pref on mount (per-device permission still required)
  useEffect(() => {
    let alive = true
    notificationsApi.getPreferences().then(({ data }) => {
      if (!alive) return
      if (data?.enable_browser_push && pushSupported() && Notification.permission === 'granted'
          && localStorage.getItem('notif_desktop') == null) {
        localStorage.setItem('notif_desktop', '1')
        setDesktopOnState(isDesktopPushOn())
      }
    }).catch(() => {})
    return () => { alive = false }
  }, [])

  const toggleDesktop = async () => {
    if (!pushSupported()) return
    if (desktopOn) { setDesktopPush(false); setDesktopOnState(false); return }
    let perm = Notification.permission
    if (perm !== 'granted') {
      try { perm = await Notification.requestPermission() } catch { perm = 'denied' }
    }
    if (perm === 'granted') { setDesktopPush(true); setDesktopOnState(true) }
  }

  const {
    notifications,
    unreadCount,
    isConnected,
    toast,
    dismissToast,
    banner,
    dismissBanner,
    markRead,
    markAllRead,
    deleteNotif,
    snooze,
    refresh,
  } = useNotificationSocket()
  const [prefsOpen, setPrefsOpen] = useState(false)

  const bannerPath = (b) =>
    b?.reservation ? `/reservations/${b.reservation}`
    : b?.transfer_request_id_ref ? `/transfers/${b.transfer_request_id_ref}`
    : b?.demand_id_ref ? `/demands/${b.demand_id_ref}` : null

  // Visual flash when unread count rises. The alarm SOUND is fired in the socket
  // hook (tier-aware: double-beep critical / single high), so it isn't repeated here.
  useEffect(() => {
    if (prevCount.current !== null && unreadCount > prevCount.current) {
      setFlashing(true)
      setTimeout(() => setFlashing(false), 3000)
    }
    prevCount.current = unreadCount
  }, [unreadCount])

  const handleOpen = () => {
    const next = !open
    setOpen(next)
    if (next) refresh()
  }

  const handleClick = async (notif) => {
    if (!notif.is_read) await markRead(notif.id)
    setOpen(false)
    if (notif.reservation) {
      navigate(`/reservations/${notif.reservation}`)
    } else if (notif.transfer_request_id_ref) {
      navigate(`/transfers/${notif.transfer_request_id_ref}`)
    } else if (notif.demand_id_ref) {
      navigate(`/demands/${notif.demand_id_ref}`)
    }
  }

  // When a notification is cleared from the panel, update local state
  const handleClearAll = async () => {
    if (!window.confirm('هل تريد حذف جميع الإشعارات؟')) return
    try {
      const { notificationsApi } = await import('../api/client')
      await notificationsApi.clearAll()
      refresh()   // re-fetch from server (will return empty list)
    } catch { /* silent */ }
  }

  return (
    <>
      <div className="relative flex items-center gap-1" dir="rtl">
        {/* ── Desktop push toggle (OS notification when tab unfocused) ──────── */}
        {pushSupported() && (
          <button
            onClick={toggleDesktop}
            title={desktopOn ? 'إيقاف تنبيهات سطح المكتب'
                  : (Notification.permission === 'denied'
                     ? 'تنبيهات المتصفح محظورة — فعّلها من إعدادات المتصفح'
                     : 'تفعيل تنبيهات سطح المكتب')}
            className={`p-1.5 rounded-lg transition-colors ${
              desktopOn ? 'text-brand-600 hover:bg-brand-50'
                        : 'text-gray-300 hover:text-gray-500 hover:bg-gray-100'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <rect x="2" y="4" width="20" height="13" rx="2" />
              <path strokeLinecap="round" d="M8 21h8M12 17v4" />
            </svg>
          </button>
        )}
        {/* ── Bell button ──────────────────────────────────────────────────── */}
        <button
          onClick={handleOpen}
          className={`relative p-2 rounded-lg transition-colors duration-150
            ${flashing
              ? 'bg-orange-100 text-orange-600 animate-pulse'
              : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
            }`}
          title={isConnected ? 'الإشعارات (متصل)' : 'الإشعارات (غير متصل)'}
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>

          {/* Unread badge */}
          {unreadCount > 0 && (
            <span className={`absolute -top-1 -left-1 min-w-[18px] h-[18px]
              bg-red-500 text-white text-xs font-bold rounded-full
              flex items-center justify-center px-1
              ${flashing ? 'animate-bounce' : ''}`}
            >
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}

          {/* WS status dot */}
          <span
            className={`absolute bottom-1 left-1 w-1.5 h-1.5 rounded-full
              ${isConnected ? 'bg-green-400' : 'bg-gray-400'}`}
            title={isConnected ? 'WebSocket متصل' : 'وضع استطلاع'}
          />
        </button>

        {/* ── Dropdown panel ───────────────────────────────────────────────── */}
        {open && (
          <>
            {/* Backdrop */}
            <div
              className="fixed inset-0 z-40"
              onClick={() => setOpen(false)}
            />
            <div className="absolute left-0 top-full mt-2 z-50 animate-fade-in">
              <NotificationPanel
                notifications={notifications}
                unreadCount={unreadCount}
                onMarkRead={markRead}
                onMarkAllRead={markAllRead}
                onDelete={deleteNotif}
                onSnooze={snooze}
                onClickNotif={handleClick}
                onClose={() => setOpen(false)}
                onClearAll={handleClearAll}
                onOpenPrefs={() => { setOpen(false); setPrefsOpen(true) }}
                onOpenInbox={() => { setOpen(false); navigate('/notifications') }}
              />
            </div>
          </>
        )}
      </div>

      {/* ── Toast overlay (rendered outside bell so it's always visible) ──── */}
      <NotificationToast toast={toast} onDismiss={dismissToast} />

      {/* ── Critical in-app banner ───────────────────────────────────────── */}
      <NotificationBanner
        banner={banner}
        onView={() => { const p = bannerPath(banner); dismissBanner(); if (p) navigate(p) }}
        onDismiss={dismissBanner}
      />

      {/* ── Preferences modal ────────────────────────────────────────────── */}
      {prefsOpen && <NotificationPreferencesModal onClose={() => setPrefsOpen(false)} />}
    </>
  )
}
