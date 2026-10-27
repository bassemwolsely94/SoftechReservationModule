/**
 * mobileUi.jsx — shared state primitives for the standalone mobile surfaces.
 * Standardizes loading / empty / error-with-retry blocks and online detection
 * so every /m screen behaves consistently on flaky phone connections.
 */
import { useEffect, useState } from 'react'
import { subscribe } from '../api/offlineQueue'

export function MobileLoading({ text = 'جارٍ التحميل...' }) {
  return <div className="text-center text-sm text-gray-400 py-12">{text}</div>
}

export function MobileEmpty({ icon = '📭', text = 'لا توجد بيانات' }) {
  return (
    <div className="text-center py-12">
      <div className="text-3xl mb-2">{icon}</div>
      <div className="text-sm text-gray-400">{text}</div>
    </div>
  )
}

export function MobileError({ onRetry, text = 'تعذّر التحميل' }) {
  return (
    <div className="text-center py-12 space-y-3">
      <div className="text-3xl">⚠️</div>
      <div className="text-sm text-red-500">{text}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-sm text-brand-600 font-medium border border-brand-200 rounded-lg px-4 py-1.5 active:bg-brand-50"
        >
          أعد المحاولة
        </button>
      )}
    </div>
  )
}

// Tracks browser connectivity. Queries auto-refetch on reconnect (TanStack
// Query default); this drives the offline banner + lets screens hint the user.
export function useOnline() {
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off) }
  }, [])
  return online
}

// Wires the offline action queue (api/offlineQueue) into React. Returns the live
// pending-count plus a small list of transient sync toasts (auto-dismissed). The
// MobileLayout renders both; capture pages just call queuedPost.
export function useOfflineQueue() {
  const [pending, setPending] = useState(0)
  const [toasts, setToasts]   = useState([])   // [{ id, kind:'ok'|'err', text }]

  useEffect(() => {
    const timers = []
    const pushToast = (kind, text) => {
      const id = Math.random().toString(36).slice(2)
      setToasts(t => [...t, { id, kind, text }])
      timers.push(setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000))
    }
    const unsub = subscribe(ev => {
      if (ev.type === 'count') setPending(ev.count)
      else if (ev.type === 'synced') pushToast('ok', `تمت مزامنة: ${ev.label || 'إجراء'}`)
      else if (ev.type === 'error') pushToast('err', `تعذّرت مزامنة ${ev.label || 'إجراء'}${ev.message ? ` — ${ev.message}` : ''}`)
    })
    return () => { unsub(); timers.forEach(clearTimeout) }
  }, [])

  return { pending, toasts }
}
