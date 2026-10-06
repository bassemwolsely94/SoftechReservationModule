/**
 * frontend/src/hooks/useNotificationSocket.js
 *
 * Manages the personal notification WebSocket connection.
 *
 * Features:
 *   - Connects to  ws[s]://<host>/ws/notifications/?token=<jwt>
 *   - Handles new_notification + pending_notification events
 *   - Sends ping every 25s to keep connection alive
 *   - Auto-reconnects with exponential back-off (max 32s)
 *   - Falls back to 30s REST polling when WS is unavailable
 *   - Exposes:  unreadCount, notifications, isConnected, markRead, markAllRead
 *
 * Usage:
 *   const { unreadCount, notifications, isConnected, markRead, markAllRead }
 *         = useNotificationSocket()
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { notificationsApi } from '../api/client'
import useNotificationStore from '../store/notificationStore'

// Categories kept OUT of the main bell — routed to their own quiet feeds:
//   demand / followups → in-module bell + sidebar hint
//   monitoring         → 📡 quiet feed (SLA / transit / routine status)
//   settings           → ⚙️ cog feed (system + branch connectivity)
//   reports            → 📊 quiet feed (weekly / monthly digests)
//   mentions           → 💬 quiet feed (personal @-mentions)
// The bell keeps the ACTIONABLE tiers (delivery, reservations = critical;
// transfers + churn = high) plus 'global', and those fire the sound + visual alarm.
const MODULE_CATEGORIES = ['demand', 'followups', 'monitoring', 'settings', 'reports', 'mentions']

// ── Alarm sound (Web Audio — no asset). Distinct tone per tier, mute-aware. ──
let _audioCtx = null
function _ctx() {
  try {
    if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(() => {})
    return _audioCtx
  } catch { return null }
}
function _beep(ctx, at, freq, dur, vol = 0.32) {
  const osc = ctx.createOscillator(), gain = ctx.createGain()
  osc.type = 'sine'
  osc.connect(gain); gain.connect(ctx.destination)
  osc.frequency.setValueAtTime(freq, at)
  gain.gain.setValueAtTime(vol, at)
  gain.gain.exponentialRampToValueAtTime(0.001, at + dur)
  osc.start(at); osc.stop(at + dur)
}
export function isMuted() { return localStorage.getItem('notif_muted') === '1' }
export function setMuted(v) { localStorage.setItem('notif_muted', v ? '1' : '0') }

// ── Browser/desktop push (Notification API — fires when the tab isn't focused) ──
export function pushSupported() {
  return typeof window !== 'undefined' && 'Notification' in window
}
export function isDesktopPushOn() {
  try {
    return localStorage.getItem('notif_desktop') === '1' &&
           pushSupported() && Notification.permission === 'granted'
  } catch { return false }
}
export function setDesktopPush(on) {
  try { localStorage.setItem('notif_desktop', on ? '1' : '0') } catch { /* ignore */ }
  // Persist to the server pref too (best-effort) so it's recorded per user.
  try { notificationsApi.updatePreferences({ enable_browser_push: !!on }) } catch { /* ignore */ }
}
function _notifPath(msg) {
  if (msg.reservation)               return `/reservations/${msg.reservation}`
  if (msg.transfer_request_id_ref)   return `/transfers/${msg.transfer_request_id_ref}`
  if (msg.demand_id_ref)             return `/demands/${msg.demand_id_ref}`
  return null
}
function maybeDesktopPush(msg, tier) {
  // Only actionable alarm-tier events, only when the user isn't looking at the tab.
  if (!tier || !isDesktopPushOn()) return
  try { if (document.hasFocus && document.hasFocus()) return } catch { /* ignore */ }
  try {
    const n = new Notification(msg.title || 'إشعار', {
      body: msg.body || '',
      tag:  `notif-${msg.id}`,
      lang: 'ar', dir: 'rtl',
    })
    n.onclick = () => {
      try { window.focus() } catch { /* ignore */ }
      const p = _notifPath(msg)
      if (p) window.dispatchEvent(new CustomEvent('notif:navigate', { detail: p }))
      n.close()
    }
  } catch { /* ignore */ }
}
function playAlarm(tier) {
  if (!tier || isMuted()) return
  const ctx = _ctx(); if (!ctx) return
  const t = ctx.currentTime
  if (tier === 'critical') {            // urgent double-beep
    _beep(ctx, t, 988, 0.16)
    _beep(ctx, t + 0.22, 988, 0.16)
  } else if (tier === 'high') {         // single beep
    _beep(ctx, t, 740, 0.2)
  }
}

const WS_RECONNECT_BASE = 2000   // 2s
const WS_RECONNECT_MAX  = 32000  // 32s
const PING_INTERVAL     = 25000  // 25s
const POLL_INTERVAL     = 8000   // 8s fallback — near-real-time feel without WS
const REFRESH_INTERVAL  = 30000  // 30s periodic reconciliation even when WS is live
const MAX_NOTIFICATIONS = 100    // cap the in-memory list

// ── Helper: build WebSocket URL ───────────────────────────────────────────────

function buildWsUrl() {
  const token    = localStorage.getItem('access_token')
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host     = window.location.host
  return `${protocol}://${host}/ws/notifications/?token=${token}`
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useNotificationSocket() {
  const [notifications, setNotifications]   = useState([])
  const [unreadCount,   setUnreadCount]     = useState(0)
  const [isConnected,   setIsConnected]     = useState(false)
  const [toast,         setToast]           = useState(null)  // { id, title, body, type_icon }
  const [banner,        setBanner]          = useState(null)  // critical-tier in-app banner

  const wsRef         = useRef(null)
  const reconnectRef  = useRef(null)
  const pingRef       = useRef(null)
  const pollRef       = useRef(null)
  const refreshRef    = useRef(null)   // 30s periodic reconciliation
  const retryDelay    = useRef(WS_RECONNECT_BASE)
  const mountedRef    = useRef(true)

  // ── REST fallback helpers ─────────────────────────────────────────────────

  const fetchUnreadCount = useCallback(async () => {
    try {
      const { data } = await notificationsApi.unreadCount()
      if (mountedRef.current) setUnreadCount(data.count ?? 0)
    } catch { /* silent */ }
  }, [])

  const fetchNotifications = useCallback(async () => {
    try {
      const { data } = await notificationsApi.list({ limit: MAX_NOTIFICATIONS })
      if (!mountedRef.current) return
      const list = Array.isArray(data) ? data : []
      setNotifications(list)
      setUnreadCount(list.filter(n => !n.is_read).length)
    } catch { /* silent */ }
  }, [])

  // ── WebSocket connect / reconnect ─────────────────────────────────────────

  const connect = useCallback(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      // No token — start polling instead
      _startPolling()
      return
    }

    const url = buildWsUrl()
    const ws  = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      setIsConnected(true)
      retryDelay.current = WS_RECONNECT_BASE
      _stopPolling()

      // Keepalive ping every 25s
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'ping' }))
        }
      }, PING_INTERVAL)
    }

    ws.onmessage = (event) => {
      if (!mountedRef.current) return
      try {
        const msg = JSON.parse(event.data)
        _handleMessage(msg)
      } catch { /* ignore malformed */ }
    }

    ws.onerror = () => { /* onclose will fire next */ }

    ws.onclose = (ev) => {
      clearInterval(pingRef.current)
      pingRef.current = null
      if (!mountedRef.current) return

      setIsConnected(false)

      // Don't reconnect on 4001 (auth failure)
      if (ev.code === 4001) {
        _startPolling()
        return
      }

      // Exponential back-off reconnect
      reconnectRef.current = setTimeout(() => {
        if (mountedRef.current) connect()
      }, retryDelay.current)
      retryDelay.current = Math.min(retryDelay.current * 2, WS_RECONNECT_MAX)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Message handler ───────────────────────────────────────────────────────

  function _handleMessage(msg) {
    const { event } = msg
    if (event === 'pong') return

    if (event === 'new_notification') {
      // Per-role notifier visibility: if this category is hidden for the user's
      // role, fully suppress it — no count, no toast, no sound.
      const visible = useNotificationStore.getState().visible
      if (visible && msg.category && !visible.has(msg.category)) return

      // Quiet-feed notifications never enter the main bell — they bump their feed
      // count only (demand/followups sidebar hint, monitoring 📡, settings ⚙️,
      // reports 📊, mentions 💬). A quiet feed can still ALARM if its type carries
      // an alarm_tier (e.g. @-mentions): fire the sound + visual toast, but keep
      // it out of the bell list / bell unread count.
      if (MODULE_CATEGORIES.includes(msg.category)) {
        if (!msg.is_read) useNotificationStore.getState().bumpCategory(msg.category, 1)
        const tier = msg.alarm_tier || ''
        if (tier) {
          playAlarm(tier)
          maybeDesktopPush(msg, tier)
          setToast({ id: msg.id, title: msg.title, body: msg.body, icon: msg.type_icon, tier })
          setTimeout(() => setToast(t => (t?.id === msg.id ? null : t)), 8000)
        }
        return
      }
      setNotifications(prev => {
        if (prev.some(n => n.id === msg.id)) return prev
        return [msg, ...prev].slice(0, MAX_NOTIFICATIONS)
      })
      if (!msg.is_read) setUnreadCount(prev => prev + 1)
      // Actionable tiers (critical/high) sound the alarm; visual alarm toast
      // lingers longer than a routine one.
      const tier = msg.alarm_tier || ''
      playAlarm(tier)
      maybeDesktopPush(msg, tier)
      setToast({ id: msg.id, title: msg.title, body: msg.body, icon: msg.type_icon, tier })
      setTimeout(() => setToast(t => (t?.id === msg.id ? null : t)), tier ? 8000 : 5000)
      // Critical events also raise a persistent in-app banner (top of screen).
      if (tier === 'critical') {
        setBanner({
          id: msg.id, title: msg.title, body: msg.body, icon: msg.type_icon,
          reservation: msg.reservation,
          transfer_request_id_ref: msg.transfer_request_id_ref,
          demand_id_ref: msg.demand_id_ref,
        })
      }
    }

    // Batched catch-up payload sent by _send_pending on reconnect
    if (event === 'pending_notifications' && Array.isArray(msg.notifications)) {
      // Keep module-scoped notifications out of the bell; reconcile their counts.
      if (msg.notifications.some(n => MODULE_CATEGORIES.includes(n.category))) {
        useNotificationStore.getState().refresh()
      }
      const globalBatch = msg.notifications.filter(n => !MODULE_CATEGORIES.includes(n.category))
      setNotifications(prev => {
        const existingIds = new Set(prev.map(n => n.id))
        const fresh = globalBatch.filter(n => !existingIds.has(n.id))
        if (!fresh.length) return prev
        return [...fresh, ...prev].slice(0, MAX_NOTIFICATIONS)
      })
      // Recalculate unread from the merged list
      setNotifications(merged => {
        setUnreadCount(merged.filter(n => !n.is_read).length)
        return merged
      })
    }

    if (event === 'marked_read') {
      setNotifications(prev =>
        prev.map(n => n.id === msg.id ? { ...n, is_read: true } : n)
      )
      setUnreadCount(prev => Math.max(0, prev - (msg.updated || 0)))
    }

    if (event === 'all_marked_read') {
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnreadCount(0)
    }
  }

  // ── REST polling (WS fallback) ────────────────────────────────────────────

  function _startPolling() {
    if (pollRef.current) return
    // Fetch full list immediately so the panel is populated right away,
    // then keep refreshing every POLL_INTERVAL (8s) for near-real-time feel.
    // fetchNotifications() updates both `notifications` and `unreadCount` in one call.
    fetchNotifications()
    pollRef.current = setInterval(fetchNotifications, POLL_INTERVAL)
  }

  function _stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true
    // Prime the AudioContext on the first user gesture so alarms can sound
    // (browsers block audio until the page has been interacted with).
    const prime = () => { _ctx() }
    window.addEventListener('pointerdown', prime, { once: true })
    window.addEventListener('keydown', prime, { once: true })
    // Initial notification load (global bell) + per-module counts
    fetchNotifications()
    useNotificationStore.getState().refresh()
    // Try to connect via WebSocket; falls back to polling if unavailable
    connect()
    // Periodic reconciliation — syncs list from server every 30s regardless
    // of WebSocket state. Catches any notifications missed by WS delivery.
    refreshRef.current = setInterval(() => {
      fetchNotifications()
      useNotificationStore.getState().refresh()
    }, REFRESH_INTERVAL)

    return () => {
      mountedRef.current = false
      clearTimeout(reconnectRef.current)
      clearInterval(pingRef.current)
      clearInterval(refreshRef.current)
      refreshRef.current = null
      _stopPolling()
      if (wsRef.current) {
        wsRef.current.onclose = null // prevent reconnect on intentional close
        wsRef.current.close()
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Public API ────────────────────────────────────────────────────────────

  const markRead = useCallback(async (id) => {
    // Optimistic update
    setNotifications(prev =>
      prev.map(n => n.id === id ? { ...n, is_read: true } : n)
    )
    setUnreadCount(prev => Math.max(0, prev - 1))

    // Send via WS if connected, else REST
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'mark_read', id }))
    } else {
      try { await notificationsApi.markRead(id) } catch { /* silent */ }
    }
  }, [])

  const markAllRead = useCallback(async () => {
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
    setUnreadCount(0)

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'mark_all_read' }))
    } else {
      try { await notificationsApi.markAllRead() } catch { /* silent */ }
    }
  }, [])

  const deleteNotif = useCallback(async (id) => {
    // Use functional update to read current state — avoids stale closure bug
    // (previously [notifications] dep caused the count check to use an old snapshot)
    setNotifications(prev => {
      const target = prev.find(n => n.id === id)
      if (target && !target.is_read) {
        setUnreadCount(c => Math.max(0, c - 1))
      }
      return prev.filter(n => n.id !== id)
    })
    try { await notificationsApi.deleteOne(id) } catch { /* silent */ }
  }, [])  // no dep on notifications — state is read via functional updater

  const refresh = useCallback(() => fetchNotifications(), [fetchNotifications])

  // Snooze: optimistically remove from the bell now; the 1-min server worker
  // re-pushes (re-alarms) when it's due.
  const snooze = useCallback(async (id, body) => {
    setNotifications(prev => {
      const t = prev.find(n => n.id === id)
      if (t && !t.is_read) setUnreadCount(c => Math.max(0, c - 1))
      return prev.filter(n => n.id !== id)
    })
    try { await notificationsApi.snooze(id, body) } catch { /* silent */ }
  }, [])

  const dismissToast  = useCallback(() => setToast(null), [])
  const dismissBanner = useCallback(() => setBanner(null), [])

  return {
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
  }
}

export default useNotificationSocket
