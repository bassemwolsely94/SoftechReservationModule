/**
 * offlineQueue.js — offline-first action queue for the standalone mobile (/m/*) surfaces.
 *
 * Egyptian mobile data is flaky, so staff lose POSTs mid-capture. This module
 * lets the high-value *create* flows resolve optimistically: if we're offline or
 * the request dies with a network error, the mutation is persisted to IndexedDB
 * and replayed FIFO when connectivity returns (browser `online` event + app load).
 *
 * Scope guardrails (enforced by callers, not here):
 *   - POST-only, replay-safe create flows ONLY. Never queue GETs, money, or approvals.
 *   - IDEMPOTENCY: there is none server-side. If a request reaches the server but the
 *     response is lost (e.g. signal drops right after the write), the retry creates a
 *     DUPLICATE. Accepted for these capture flows; do not route anything where a
 *     duplicate is harmful through queuedPost. Each item carries a stable client id in
 *     the `X-Idempotency-Key` header so the backend *could* dedupe later.
 *
 * Public surface:
 *   queuedPost(url, body, { label })  → axios response  OR  { queued:true, id, label }
 *   flushQueue()                      → replays pending items (called automatically)
 *   getPending() / subscribe(cb)      → UI wiring (pending count + sync toasts)
 */
import api from './client'

const DB_NAME    = 'elrezeiky-offline'
const STORE_NAME = 'pending'
const DB_VERSION = 1

// ── Tiny IndexedDB wrapper (avoids an extra dependency) ─────────────────────────

let dbPromise = null
function openDb() {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('no-indexeddb')); return }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror   = () => reject(req.error)
  })
  return dbPromise
}

function txStore(mode) {
  return openDb().then(db => db.transaction(STORE_NAME, mode).objectStore(STORE_NAME))
}

async function idbGetAll() {
  try {
    const store = await txStore('readonly')
    return await new Promise((resolve, reject) => {
      const req = store.getAll()
      req.onsuccess = () => resolve(req.result || [])
      req.onerror   = () => reject(req.error)
    })
  } catch {
    return []   // IndexedDB unavailable (private mode, old browser) → degrade gracefully
  }
}

async function idbPut(item) {
  const store = await txStore('readwrite')
  return new Promise((resolve, reject) => {
    const req = store.put(item)
    req.onsuccess = () => resolve()
    req.onerror   = () => reject(req.error)
  })
}

async function idbDelete(id) {
  const store = await txStore('readwrite')
  return new Promise((resolve, reject) => {
    const req = store.delete(id)
    req.onsuccess = () => resolve()
    req.onerror   = () => reject(req.error)
  })
}

// ── Subscribers (pending count + sync result toasts) ────────────────────────────

let pendingCount = 0
const listeners  = new Set()

function emit(event) {
  for (const cb of listeners) { try { cb(event) } catch { /* listener errors are non-fatal */ } }
}

/** Subscribe to queue events: {type:'count',count} | {type:'synced',label} | {type:'error',label,message}. Returns unsubscribe. */
export function subscribe(cb) {
  listeners.add(cb)
  cb({ type: 'count', count: pendingCount })   // prime with current value
  return () => listeners.delete(cb)
}

export function getPendingCount() { return pendingCount }

async function refreshCount() {
  const all = await idbGetAll()
  pendingCount = all.length
  emit({ type: 'count', count: pendingCount })
  return pendingCount
}

// ── Enqueue + the queuedPost helper ─────────────────────────────────────────────

function newId() {
  return `q_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// A network-level failure (no response received) — request never reached the server,
// or the server's reply was lost. Safe-ish to replay. Distinct from an HTTP error.
function isNetworkError(err) {
  return !err?.response
}

async function enqueue({ method, url, body, label }) {
  const item = { id: newId(), ts: Date.now(), method, url, body, label }
  await idbPut(item)
  await refreshCount()
  return item
}

/**
 * POST that survives a dead connection. When online, sends normally and returns the
 * axios response (so callers can read `res.data`). When offline — or when the send
 * fails with a network error — the request is persisted and resolves optimistically
 * with `{ queued: true, id, label }`. HTTP errors (409 duplicate, 400 validation, …)
 * are re-thrown unchanged so existing error handling keeps working.
 */
export async function queuedPost(url, body, { label = '' } = {}) {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    const item = await enqueue({ method: 'post', url, body, label })
    return { queued: true, id: item.id, label }
  }
  try {
    return await api.post(url, body)
  } catch (err) {
    if (isNetworkError(err)) {
      const item = await enqueue({ method: 'post', url, body, label })
      return { queued: true, id: item.id, label }
    }
    throw err   // real HTTP error — let the caller handle it
  }
}

// ── Sync engine ─────────────────────────────────────────────────────────────────

let flushing = false

/**
 * Replay pending items oldest-first. Per item:
 *   success            → drop it, emit 'synced'
 *   4xx (not 401)      → permanent failure; drop it, emit 'error' (user-visible)
 *   401 / 5xx / network→ keep it and stop the run (retry on next online/load)
 */
export async function flushQueue() {
  if (flushing) return
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return
  flushing = true
  try {
    const all = (await idbGetAll()).sort((a, b) => a.ts - b.ts)
    for (const item of all) {
      try {
        await api.request({
          method:  item.method,
          url:     item.url,
          data:    item.body,
          headers: { 'X-Idempotency-Key': item.id },
        })
        await idbDelete(item.id)
        await refreshCount()
        emit({ type: 'synced', label: item.label })
      } catch (err) {
        const status = err?.response?.status
        if (isNetworkError(err) || status === 401 || (status >= 500 && status < 600)) {
          // Transient — keep the item and stop; the next reconnect will resume.
          break
        }
        // Permanent client error (400/403/404/409/…): replaying won't help. Drop it
        // and surface the failure so the action isn't silently lost.
        await idbDelete(item.id)
        await refreshCount()
        const msg = err?.response?.data?.detail
          || (typeof err?.response?.data === 'string' ? err.response.data : '')
          || 'فشل المزامنة'
        emit({ type: 'error', label: item.label, message: msg })
      }
    }
  } finally {
    flushing = false
  }
}

// ── Auto-flush wiring ───────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => { flushQueue() })
  // Prime the pending count on load, then flush anything left from a previous session.
  refreshCount().then(() => { if (navigator.onLine) flushQueue() })
}
