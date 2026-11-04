/**
 * PageSuspense — pages are loaded on demand (React.lazy in App.jsx), so the first visit to a
 * screen fetches its code. This wraps each page outlet: the sidebar / header stay put and a calm
 * one-line «جارٍ التحميل…» appears only if the load takes longer than a blink (no flash on fast
 * links). A failed load (stale build after a release) is caught by the ErrorBoundary around it.
 */
import { Suspense, useEffect, useState } from 'react'

function Fallback() {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShow(true), 250)
    return () => clearTimeout(t)
  }, [])
  if (!show) return null
  return (
    <div className="p-6 text-sm text-gray-500 dark:text-gray-400" role="status" aria-live="polite">
      جارٍ التحميل…
    </div>
  )
}

export default function PageSuspense({ children }) {
  return <Suspense fallback={<Fallback />}>{children}</Suspense>
}
