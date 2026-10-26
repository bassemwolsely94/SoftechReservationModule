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

  _ws.onclose = () => {
    // Reconnect after 5 s
    setTimeout(_connect, 5000)
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
