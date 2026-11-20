/**
 * frontend/src/hooks/useNotificationSocket.js
 *
 * Manages the personal notification WebSocket connection.
 *
 * Features:
 *   - Connects to  ws[s]://<host>/ws/notifications/  (auth: httpOnly session cookie)
 *   - Handles new_notification + pending_notification events
 *   - Sends ping every 25s to keep connection alive
 *   - Auto-reconnects with exponential back-off (max 32s)
 *   - Applies the server-pushed `category_counts` (unread counts) and `freshness_changed` events
 *     (perf Stage 5) — no periodic reconcile while the socket is up
 *   - Falls back to a 120 s REST poll only while WS is unavailable (paused in hidden tabs)
 *   - Exposes:  unreadCount, notifications, isConnected, markRead, markAllRead,
 *               view + setView (C26: 'action' default | 'all', saved per user)
 *
 * Usage:
 *   const { unreadCount, notifications, isConnected, markRead, markAllRead }
 *         = useNotificationSocket()
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { notificationsApi, refreshSession } from '../api/client'
import useAuthStore from '../store/authStore'
import useNotificationStore from '../store/notificationStore'
import useLiveStore, { FRESHNESS_JITTER_MS } from '../store/liveStore'

// Categories kept OUT of the main bell — routed to their own quiet feeds:
//   demand / followups → in-module bell + sidebar hint
//   monitoring         → 📡 quiet feed (SLA / transit / routine status)
//   settings           → ⚙️ cog feed (system + branch connectivity)
//   reports            → 📊 quiet feed (weekly / monthly digests)
//   mentions           → 💬 quiet feed (personal @-mentions)
// The bell keeps the ACTIONABLE tiers (delivery, reservations = critical;
// transfers + churn = high) plus 'global', and those fire the sound + visual alarm.
const MODULE_CATEGORIES = ['demand', 'followups', 'monitoring', 'settings', 'reports', 'mentions']

// C26 / D-19: the bell opens on the ACTION items (the server's fixed type list,
// apps/notifications/action_items.py, sent as `is_action` on each row and `action` in the counts).
// «الكل» is one click away; the choice is saved per user (preferences.bell_view).
export const BELL_VIEWS = ['action', 'all']
export const DEFAULT_BELL_VIEW = 'action'

/** Does a notification belong in the bell list for this view? */
export function inBellView(n, view) {
  if (!n) return false
  if (view === 'action') return !!n.is_action
  return !MODULE_CATEGORIES.includes(n.category)
}

/** The badge number for this view from a category-counts payload. */
export function bellCountFor(counts, view) {
  if (!counts) return 0
  return Number(view === 'action' ? counts.action : counts.bell) || 0
}

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
// perf Stage 5: while the socket is up the server PUSHES every count change (category_counts) and
// every new notification, so there is no periodic reconcile any more. This slow REST poll runs only
// while the socket is down (it used to be 8 s, plus a 30 s reconcile even with the socket up).
export const FALLBACK_POLL_INTERVAL = 120_000
const MAX_NOTIFICATIONS = 100    // cap the in-memory list

// ── Helper: build WebSocket URL ───────────────────────────────────────────────

function buildWsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host     = window.location.host
  return `${protocol}://${host}/ws/notifications/`
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useNotificationSocket() {
  const [notifications, setNotifications]   = useState([])
  const [unreadCount,   setUnreadCount]     = useState(0)
  const [isConnected,   setIsConnected]     = useState(false)
  const [toast,         setToast]           = useState(null)  // { id, title, body, type_icon }
  const [banner,        setBanner]          = useState(null)  // critical-tier in-app banner
  const [view,          setViewState]       = useState(DEFAULT_BELL_VIEW)
  const viewRef       = useRef(DEFAULT_BELL_VIEW)  // read by the socket handlers (no stale closure)

  const wsRef         = useRef(null)
  const reconnectRef  = useRef(null)
  const pingRef       = useRef(null)
  const pollRef       = useRef(null)
  const retryDelay    = useRef(WS_RECONNECT_BASE)
  const mountedRef    = useRef(true)
  const everOpenRef   = useRef(false)  // a later onopen is a RE-connect → one REST reconcile
  const unreadRef     = useRef(0)      // current bell count, read by the counts event handler
  useEffect(() => { unreadRef.current = unreadCount }, [unreadCount])

  // ── REST fallback helpers ─────────────────────────────────────────────────

  const fetchNotifications = useCallback(async () => {
    const asked = viewRef.current
    try {
      const { data } = await notificationsApi.list({ limit: MAX_NOTIFICATIONS, view: asked })
      if (!mountedRef.current || asked !== viewRef.current) return   // the view changed meanwhile
      const list = Array.isArray(data) ? data : []
      setNotifications(list)
      // A capped (full) list cannot count beyond its cap — then the pushed/REST `bell` count rules.
      if (list.length < MAX_NOTIFICATIONS) setUnreadCount(list.filter(n => !n.is_read).length)
    } catch { /* silent */ }
  }, [])

  // ── WebSocket connect / reconnect ─────────────────────────────────────────

  const connect = useCallback(() => {
    if (!useAuthStore.getState().isAuthenticated) {
      // Not logged in — start polling instead
      _startPolling()
      return
    }

    const url = buildWsUrl()
    const ws  = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      setIsConnected(true)
      useLiveStore.getState().setSocketUp(true)
      retryDelay.current = WS_RECONNECT_BASE
      _stopPolling()
      // After a drop, catch up once (reads / deletes elsewhere while we were away); unread arrivals
      // come in the server's pending_notifications frame. The first open needs nothing: mount loaded.
      if (everOpenRef.current) {
        fetchNotifications()
        useNotificationStore.getState().refresh()
      }
      everOpenRef.current = true

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
      useLiveStore.getState().setSocketUp(false)

      // Don't reconnect on 4001 (auth failure) or 4403 (not allowed from this place, N5)
      if (ev.code === 4001 || ev.code === 4403) {
        _startPolling()
        return
      }

      // 4500: the server's access re-check failed (a transient error, N5) — the normal back-off
      // reconnect below, like any other drop.
      // 4002: the access token ran out (N5) — rotate the cookie, reconnect at the minimum delay
      const expired = ev.code === 4002
      if (expired) retryDelay.current = WS_RECONNECT_BASE
      // Slow REST fallback until a reconnect succeeds (onopen stops it). Without it a socket that
      // keeps failing would leave the bell frozen now that there is no 30 s reconcile.
      _startPolling()
      const reconnect = () => { if (mountedRef.current) connect() }

      // Exponential back-off reconnect
      reconnectRef.current = setTimeout(() => {
        if (expired) refreshSession().catch(() => {}).finally(reconnect)
        else reconnect()
      }, retryDelay.current)
      retryDelay.current = Math.min(retryDelay.current * 2, WS_RECONNECT_MAX)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Message handler ───────────────────────────────────────────────────────

  function _handleMessage(msg) {
    const { event } = msg
    if (event === 'pong') return

    // Unread counts changed (a new notification, a read / snooze / delete on any tab). Integers only.
    if (event === 'category_counts') {
      useNotificationStore.getState().applyCounts(msg)
      const bell = bellCountFor(msg, viewRef.current)
      // The list in memory no longer matches (read or removed on another tab) → reload it once.
      if (bell !== unreadRef.current) fetchNotifications()
      setUnreadCount(bell)
      return
    }

    // A sync run / lane finished (domain keys + time only): screens showing those domains refetch.
    // A random delay spreads every open tab's refetch over a few seconds.
    if (event === 'freshness_changed') {
      const domains = Array.isArray(msg.domains) ? msg.domains : []
      setTimeout(() => useLiveStore.getState().freshnessChanged(domains),
        Math.random() * FRESHNESS_JITTER_MS)
      return
    }

    if (event === 'new_notification') {
      // Per-role notifier visibility: if this category is hidden for the user's
      // role, fully suppress it — no count, no toast, no sound.
      const visible = useNotificationStore.getState().visible
      if (visible && msg.category && !visible.has(msg.category)) return

      // The bell list takes the row when it fits the current view (C26): «الكل» = the bell's own
      // categories, «يحتاج إجراء» = any action item, even from a quiet feed (an @-mention).
      if (inBellView(msg, viewRef.current)) {
        setNotifications(prev => {
          if (prev.some(n => n.id === msg.id)) return prev
          return [msg, ...prev].slice(0, MAX_NOTIFICATIONS)
        })
        if (!msg.is_read) setUnreadCount(prev => prev + 1)
      }

      // Quiet-feed notifications bump their feed count (demand/followups sidebar hint,
      // monitoring 📡, settings ⚙️, reports 📊, mentions 💬). A quiet feed can still ALARM if its
      // type carries an alarm_tier (e.g. @-mentions): sound + visual toast, no banner.
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
      const globalBatch = msg.notifications.filter(n => inBellView(n, viewRef.current))
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
      // markRead() already took the 1 off optimistically; the counts push that follows is the truth.
      // (It used to subtract `updated` a second time, so one click dropped the badge by 2.)
      setNotifications(prev =>
        prev.map(n => n.id === msg.id ? { ...n, is_read: true } : n)
      )
    }

    if (event === 'all_marked_read') {
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnreadCount(0)
    }
  }

  // ── REST polling (WS fallback) ────────────────────────────────────────────

  // One fallback tick: the list + the per-category counts. Skipped while the tab is hidden.
  function _pollOnce() {
    if (typeof document !== 'undefined' && document.hidden) return
    fetchNotifications()
    useNotificationStore.getState().refresh()
  }

  function _startPolling() {
    if (pollRef.current) return
    // Socket down: refresh now, then every FALLBACK_POLL_INTERVAL until it reconnects.
    _pollOnce()
    pollRef.current = setInterval(_pollOnce, FALLBACK_POLL_INTERVAL)
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
    // The saved bell view (C26). The first list load waits for it so the bell never flashes the
    // wrong list; on any error it opens on the default (action items).
    const loadView = notificationsApi.getPreferences()
      .then(({ data }) => {
        const saved = data?.bell_view
        if (mountedRef.current && BELL_VIEWS.includes(saved)) { viewRef.current = saved; setViewState(saved) }
      })
      .catch(() => {})
    // Prime the AudioContext on the first user gesture so alarms can sound
    // (browsers block audio until the page has been interacted with).
    const prime = () => { _ctx() }
    window.addEventListener('pointerdown', prime, { once: true })
    window.addEventListener('keydown', prime, { once: true })
    // Initial notification load (the bell in its saved view) + per-module counts
    loadView.finally(() => { if (mountedRef.current) fetchNotifications() })
    useNotificationStore.getState().refresh()
    // Try to connect via WebSocket; falls back to the slow poll if unavailable. While it is up, the
    // server pushes new notifications and every count change — no periodic reconcile (perf Stage 5).
    connect()

    return () => {
      mountedRef.current = false
      useLiveStore.getState().setSocketUp(false)
      clearTimeout(reconnectRef.current)
      clearInterval(pingRef.current)
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
    const v = viewRef.current   // marks only what this view shows (server scope, C26)

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'mark_all_read', view: v }))
    } else {
      try { await notificationsApi.markAllRead({ view: v }) } catch { /* silent */ }
    }
  }, [])

  // Switch «يحتاج إجراء» ⇄ «الكل»: badge from the last counts at once, list reloaded, choice saved.
  const setView = useCallback((next) => {
    if (!BELL_VIEWS.includes(next) || next === viewRef.current) return
    viewRef.current = next
    setViewState(next)
    setNotifications([])
    setUnreadCount(bellCountFor(useNotificationStore.getState().bellCounts, next))
    fetchNotifications()
    notificationsApi.updatePreferences({ bell_view: next }).catch(() => {})
  }, [fetchNotifications])

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
    view,
    setView,
  }
}

export default useNotificationSocket
