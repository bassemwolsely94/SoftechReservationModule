/**
 * useScreenPop.js
 *
 * Connects to the PBX WebSocket (/ws/pbx/agent/) and exposes the latest
 * incoming_call event so any page can react to it.
 *
 * Usage:
 *   const { screenPop, dismissPop } = useScreenPop()
 *   // screenPop: { session_id, caller_id, queue, branch, customer } | null
 *
 * The hook is idempotent — multiple consumers share a single connection via
 * a module-level singleton so the socket is not reopened on re-renders.
 */
import { useEffect, useState, useCallback } from 'react'
import { refreshSession } from '../api/client'

const RECONNECT_MS = 5000      // normal reconnect
const REFUSED_MS   = 60000     // 4001 auth / 4403 not allowed from this place (N5): slow retry

// ── Module-level singleton ────────────────────────────────────────────────────
let _ws = null
let _listeners = new Set()

function _connect() {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host  = window.location.host
  _ws = new WebSocket(`${proto}://${host}/ws/pbx/agent/`)

  _ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data)
      _listeners.forEach(cb => cb(data))
    } catch { /* ignore parse errors */ }
  }

  _ws.onclose = (ev) => {
    if (ev.code === 4001 || ev.code === 4403) {
      setTimeout(_connect, REFUSED_MS)
      return
    }
    if (ev.code === 4002) {
      // the access token ran out (N5): rotate the cookie, then the normal reconnect
      refreshSession().catch(() => {}).finally(() => setTimeout(_connect, RECONNECT_MS))
      return
    }
    setTimeout(_connect, RECONNECT_MS)
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export default function useScreenPop() {
  const [screenPop, setScreenPop] = useState(null)

  useEffect(() => {
    _connect()

    const handler = (data) => {
      if (data.type === 'incoming_call') {
        setScreenPop({
          session_id: data.session_id,
          caller_id:  data.caller_id,
          queue:      data.queue,
          branch:     data.branch,
          started_at: data.started_at,
          customer:   data.customer || null,
        })
      }
    }

    _listeners.add(handler)
    return () => _listeners.delete(handler)
  }, [])

  const dismissPop = useCallback(() => setScreenPop(null), [])

  return { screenPop, dismissPop }
}
