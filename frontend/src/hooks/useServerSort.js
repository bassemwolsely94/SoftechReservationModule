/**
 * useServerSort — sortable headers for a PAGED list: the server sorts ALL records (DRF-style
 * `ordering`, `-field` = descending); the browser only keeps the string.
 *
 *   const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) },
 *                                         { allowed: ['name', 'net'], defaultOrdering: '-net' })
 *   <SortTh {...headerProps('net', 'number')}>صافي</SortTh>
 *
 * Keys outside `allowed` get no props (SortTh then renders a plain, unsortable header).
 * Click cycle: first (text asc; number/date desc) → reversed → `defaultOrdering` (default '').
 * Reset the page to 1 inside `onChange`.
 */
import { useCallback } from 'react'
import { ariaSortOf, nextOrdering, parseOrdering } from './sortCompare'

export default function useServerSort(value, onChange, { allowed = [], defaultOrdering = '' } = {}) {
  const cur = parseOrdering(value)
  const headerProps = useCallback((key, type = 'text') => {
    if (!allowed.includes(key)) return {}
    const active = cur.key === key
    return {
      active, dir: active ? cur.dir : undefined, ariaSort: ariaSortOf(active, cur.dir),
      onSort: () => onChange(nextOrdering(value, key, type, defaultOrdering)),
    }
  }, [allowed, cur.key, cur.dir, value, onChange, defaultOrdering])
  return { headerProps, ordering: value }
}
