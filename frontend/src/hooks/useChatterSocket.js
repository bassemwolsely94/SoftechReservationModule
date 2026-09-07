/**
 * frontend/src/hooks/useChatterSocket.js
 *
 * WebSocket hook for a single record's chatter thread.
 * URL: ws[s]://<host>/ws/chatter/{modelName}/{recordId}/?token=<jwt>
 *
 * Features:
 *   - Real-time delivery of new_chatter events
 *   - Auto-reconnect with back-off
 *   - REST polling fallback (since_id for incremental updates)
 *   - postMessage() for sending from the client
 *
 * Usage:
 *   const { messages, isConnected, postMessage, isPosting }
 *         = useChatterSocket('reservation', 42)
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { notificationsApi } from '../api/client'

const WS_RECONNECT_BASE = 2000
const WS_RECONNECT_MAX  = 32000
const PING_INTERVAL     = 25000
const POLL_INTERVAL     = 10000   // 10s poll (only when WS unavailable)

function buildWsUrl(modelName, recordId) {
  const token    = localStorage.getItem('access_token')
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host     = window.location.host
  return `${protocol}://${host}/ws/chatter/${modelName}/${recordId}/?token=${token}`
}

export function useChatterSocket(modelName, recordId) {
  const [messages,    setMessages]    = useState([])
  const [isConnected, setIsConnected] = useState(false)
  const [isPosting,   setIsPosting]   = useState(false)

  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)
  const pingRef      = useRef(null)
  const pollRef      = useRef(null)
  const retryDelay   = useRef(WS_RECONNECT_BASE)
  const mountedRef   = useRef(true)
  const lastIdRef    = useRef(0)

  // ── Initial load via REST ─────────────────────────────────────────────────

  const fetchMessages = useCallback(async (sinceId = 0) => {
    try {
      const params = sinceId ? { since_id: sinceId } : {}
      const { data } = await notificationsApi.chatterList(modelName, recordId, params)
      if (!mountedRef.current) return
      const list = Array.isArray(data) ? data : []
      if (sinceId === 0) {
        setMessages(list)
      } else {
        // Incremental append
        setMessages(prev => {
          const ids = new Set(prev.map(m => m.id))
          const fresh = list.filter(m => !ids.has(m.id))
          return fresh.length ? [...prev, ...fresh] : prev
        })
      }
      if (list.length > 0) {
        lastIdRef.current = Math.max(...list.map(m => m.id))
      }
    } catch { /* silent */ }
  }, [modelName, recordId])

  // ── Message handler ───────────────────────────────────────────────────────

  function _handleMessage(msg) {
    if (msg.event === 'pong') return
    if (msg.event === 'new_chatter') {
      setMessages(prev => {
        if (prev.some(m => m.id === msg.id)) return prev
        lastIdRef.current = Math.max(lastIdRef.current, msg.id || 0)
        return [...prev, msg]
      })
    }
  }

  // ── WebSocket connect ─────────────────────────────────────────────────────

  const connect = useCallback(() => {
    const token = localStorage.getItem('access_token')
    if (!token) { _startPolling(); return }

    const url = buildWsUrl(modelName, recordId)
    const ws  = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      setIsConnected(true)
      retryDelay.current = WS_RECONNECT_BASE
      _stopPolling()
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'ping' }))
        }
      }, PING_INTERVAL)
    }

    ws.onmessage = (event) => {
      if (!mountedRef.current) return
      try { _handleMessage(JSON.parse(event.data)) } catch { /* ignore */ }
    }

    ws.onerror = () => {}

    ws.onclose = (ev) => {
      clearInterval(pingRef.current)
      pingRef.current = null
      if (!mountedRef.current) return
      setIsConnected(false)
      if (ev.code === 4001) { _startPolling(); return }
      reconnectRef.current = setTimeout(() => {
        if (mountedRef.current) connect()
      }, retryDelay.current)
      retryDelay.current = Math.min(retryDelay.current * 2, WS_RECONNECT_MAX)
    }
  }, [modelName, recordId]) // eslint-disable-line react-hooks/exhaustive-deps

  function _startPolling() {
    if (pollRef.current) return
    pollRef.current = setInterval(() => {
      fetchMessages(lastIdRef.current)
    }, POLL_INTERVAL)
  }
  function _stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true
    setMessages([])
    lastIdRef.current = 0
    fetchMessages(0)
    connect()
    return () => {
      mountedRef.current = false
      clearTimeout(reconnectRef.current)
      clearInterval(pingRef.current)
      _stopPolling()
      if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close() }
    }
  }, [modelName, recordId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Post a message ────────────────────────────────────────────────────────

  const postMessage = useCallback(async (text) => {
    const trimmed = (text || '').trim()
    if (!trimmed) return

    setIsPosting(true)
    try {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action: 'post', message: trimmed }))
      } else {
        // REST fallback — server will push via WS to other clients
        const { data } = await notificationsApi.chatterPost(modelName, recordId, trimmed)
        // Add optimistically (WS echo won't arrive for this connection)
        setMessages(prev => {
          if (prev.some(m => m.id === data.id)) return prev
          return [...prev, data]
        })
      }
    } catch (err) {
      console.error('chatter post failed', err)
      throw err  // let UI show error toast
    } finally {
      setIsPosting(false)
    }
  }, [modelName, recordId])

  // ── Post a message with optional files (always REST — WS can't carry binary) ──
  // files: { attachment?, voiceNote? } — voiceNote uses the dedicated field, so a
  // message can carry an image attachment AND a voice note together.

  const postMessageWithAttachment = useCallback(async (text, files = {}) => {
    const trimmed = (text || '').trim()
    const { attachment, voiceNote } = files
    if (!trimmed && !attachment && !voiceNote) return

    setIsPosting(true)
    try {
      const { data } = await notificationsApi.chatterPostWithFile(
        modelName, recordId, trimmed, { attachment, voiceNote },
      )
      setMessages(prev => {
        if (prev.some(m => m.id === data.id)) return prev
        lastIdRef.current = Math.max(lastIdRef.current, data.id || 0)
        return [...prev, data]
      })
    } catch (err) {
      console.error('chatter post with files failed', err)
      throw err
    } finally {
      setIsPosting(false)
    }
  }, [modelName, recordId])

  return { messages, isConnected, isPosting, postMessage, postMessageWithAttachment }
}

export default useChatterSocket
