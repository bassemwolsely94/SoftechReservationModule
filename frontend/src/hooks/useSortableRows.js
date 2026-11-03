/**
 * useSortableRows — client-side sortable headers for a table whose rows are all in the browser.
 *
 *   const { sorted, headerProps } = useSortableRows(rows, { defaultSort, getValue, persistKey })
 *   const kb = useGridKeyboard({ rows: sorted, getKey })          // keyboard grids use the SORTED rows
 *   <SortTh {...headerProps('net', 'number')}>صافي</SortTh>
 *   {sorted.map(r => …)}                                          // totals / footer rows stay outside
 *
 * types: 'text' (Arabic-aware, natural numbers) | 'number' | 'date'. Empty / '—' values are always last.
 * Click cycle: first click (text asc; number/date desc) → reversed → back to the default order.
 *   defaultSort  { key, dir: 'asc'|'desc', type } or null (= the order the rows arrive in)
 *   getValue     (row, key) => value; default row[key]
 *   persistKey   remember the choice per table in sessionStorage
 */
import { useCallback, useMemo, useState } from 'react'
import { ariaSortOf, nextSort, sortRows } from './sortCompare'

const defaultGet = (row, key) => row?.[key]

function load(persistKey) {
  if (!persistKey) return null
  try {
    const s = JSON.parse(sessionStorage.getItem(`sort:${persistKey}`) || 'null')
    if (s && typeof s.key === 'string' && (s.dir === 'asc' || s.dir === 'desc')) return s
  } catch { /* storage unavailable */ }
  return null
}

function save(persistKey, sort) {
  if (!persistKey) return
  try {
    if (sort) sessionStorage.setItem(`sort:${persistKey}`, JSON.stringify(sort))
    else sessionStorage.removeItem(`sort:${persistKey}`)
  } catch { /* storage unavailable */ }
}

export default function useSortableRows(rows, { defaultSort = null, getValue = defaultGet, persistKey } = {}) {
  const [sort, setSort] = useState(() => load(persistKey))
  const effective = sort || (defaultSort ? { type: 'number', ...defaultSort } : null)

  const toggle = useCallback((key, type = 'text') => {
    setSort(cur => {
      const next = nextSort(cur, key, type, defaultSort)
      save(persistKey, next)
      return next
    })
  }, [defaultSort, persistKey])

  // getValue is usually an inline function, so it is read from the latest render only
  const sorted = useMemo(
    () => sortRows(rows || [], effective, getValue),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, effective?.key, effective?.dir, effective?.type],
  )

  const headerProps = useCallback((key, type = 'text') => {
    const active = !!effective && effective.key === key
    return { active, dir: active ? effective.dir : undefined, ariaSort: ariaSortOf(active, effective?.dir), onSort: () => toggle(key, type) }
  }, [effective, toggle])

  return { sorted, sort: effective, toggle, headerProps }
}
