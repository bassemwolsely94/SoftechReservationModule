/**
 * QueryState — the loading / error / empty trio for one list or panel (full audit FE-7).
 *
 *   <QueryState q={ordersQuery} empty="لا توجد طلبات" isEmpty={!orders.length}>
 *     …rows…
 *   </QueryState>
 *
 * A failed read says so (with a retry) instead of the empty text; while loading it says «جاري
 * التحميل…» instead of the empty text. Pass the whole useQuery result as `q`. Queries shown through
 * this component should set `meta: { ownErrorState: true }` so the page-level strip doesn't repeat it.
 */
import { describeQueryError } from '../utils/queryErrors'

export default function QueryState({ q, isEmpty, empty = 'لا توجد بيانات', className = 'py-10 text-center text-sm', children }) {
  if (q?.isError && !q?.data) {
    return (
      <div className={`${className} text-red-700 dark:text-red-300`} role="alert" data-testid="query-state-error">
        <div>⚠️ تعذّر التحميل: {describeQueryError(q.error)}</div>
        <button type="button" onClick={() => q.refetch?.()} className="mt-2 text-xs font-semibold underline hover:no-underline">
          إعادة المحاولة
        </button>
      </div>
    )
  }
  if (q?.isPending) return <div className={`${className} text-gray-400`} data-testid="query-state-loading">جاري التحميل…</div>
  if (isEmpty) return <div className={`${className} text-gray-400`} data-testid="query-state-empty">{empty}</div>
  return (
    <>
      {q?.isError && (
        <div className="text-xs text-red-700 dark:text-red-300 py-1" role="alert" data-testid="query-state-stale">
          ⚠️ تعذّر التحديث ({describeQueryError(q.error)}) — المعروض من آخر تحميل ناجح.
        </div>
      )}
      {children}
    </>
  )
}
