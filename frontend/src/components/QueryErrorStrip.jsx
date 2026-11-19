/**
 * QueryErrorStrip — one calm strip under the header while any read on the open screen has failed
 * (full audit FE-7). It is the safety net for screens that never read `isError`: without it a 403 or
 * a 500 looked exactly like "no data".
 *
 * It watches the query cache: a query counts while it is in error AND a mounted component uses it, so
 * the strip clears by itself on a successful retry or when the user leaves the screen. Session expiry
 * (401) and cancelled requests are not shown. A query that shows its own error can opt out with
 * `meta: { ownErrorState: true }`.
 */
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { describeQueryError, isQuietError } from '../utils/queryErrors'

export function failingQueries(cache) {
  return cache.getAll().filter(q =>
    q.state.status === 'error'
    && q.getObserversCount() > 0
    && !q.meta?.ownErrorState
    && !isQuietError(q.state.error))
}

function snapshot(cache) {
  const seen = new Map()
  for (const q of failingQueries(cache)) {
    const text = describeQueryError(q.state.error)
    seen.set(text, (seen.get(text) || 0) + 1)
  }
  return [...seen.entries()].map(([text, count]) => ({ text, count }))
}

const sameList = (a, b) => a.length === b.length && a.every((x, i) => x.text === b[i].text && x.count === b[i].count)

export default function QueryErrorStrip() {
  const qc = useQueryClient()
  const [errors, setErrors] = useState(() => snapshot(qc.getQueryCache()))
  const [dismissed, setDismissed] = useState('')

  useEffect(() => {
    const cache = qc.getQueryCache()
    const update = () => setErrors(prev => {
      const next = snapshot(cache)
      return sameList(prev, next) ? prev : next
    })
    update()
    return cache.subscribe(update)
  }, [qc])

  const signature = errors.map(e => e.text).join('|')
  if (!errors.length || dismissed === signature) return null

  const retry = () => qc.refetchQueries({ predicate: cached => failingQueries(qc.getQueryCache()).includes(cached) })

  return (
    <div role="alert" data-testid="query-error-strip" dir="rtl"
      className="shrink-0 flex items-center gap-3 px-6 py-2 text-sm bg-red-50 text-red-800 border-b border-red-200 dark:bg-red-950/40 dark:text-red-200 dark:border-red-900">
      <span aria-hidden>⚠️</span>
      <div className="flex-1 min-w-0">
        <span className="font-semibold">تعذّر تحميل بعض بيانات هذه الصفحة — ما يظهر قد يكون ناقصًا: </span>
        {errors.map((e, i) => (
          <span key={e.text}>{i > 0 && ' · '}{e.text}{e.count > 1 && ` (${e.count})`}</span>
        ))}
      </div>
      <button type="button" onClick={retry} className="text-xs font-semibold underline hover:no-underline">إعادة المحاولة</button>
      <button type="button" onClick={() => setDismissed(signature)} aria-label="إخفاء" className="text-red-400 hover:text-red-700 px-1">✕</button>
    </div>
  )
}
