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
 *   keys         optional list of this table's sortable keys: a remembered sort on any other key is ignored
 *
 * getValue is part of the memo dependencies: pass a stable function (module-level or useCallback) when you
 * can. An inline arrow works too (it re-sorts each render, cheap) and never reads a stale lookup map.
 */
import { useCallback, useMemo, useState } from 'react'
import { ariaSortOf, nextSort, sortRows } from './sortCompare'

const defaultGet = (row, key) => row?.[key]

const TYPES = ['text', 'number', 'date']

function load(persistKey, keys) {
  if (!persistKey) return null
  try {
    const s = JSON.parse(sessionStorage.getItem(`sort:${persistKey}`) || 'null')
    if (s && typeof s.key === 'string' && (s.dir === 'asc' || s.dir === 'desc') && TYPES.includes(s.type)
        && (!keys || keys.includes(s.key))) return s
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

export default function useSortableRows(rows, { defaultSort = null, getValue = defaultGet, persistKey, keys } = {}) {
  const [sort, setSort] = useState(() => load(persistKey, keys))
  const effective = sort || (defaultSort ? { type: 'number', ...defaultSort } : null)

  const toggle = useCallback((key, type = 'text') => {
    setSort(cur => {
      const next = nextSort(cur, key, type, defaultSort)
      save(persistKey, next)
      return next
    })
  }, [defaultSort, persistKey])

  const sorted = useMemo(
    () => sortRows(rows || [], effective, getValue),
    [rows, effective?.key, effective?.dir, effective?.type, getValue],
  )

  const headerProps = useCallback((key, type = 'text') => {
    const active = !!effective && effective.key === key
    return { active, dir: active ? effective.dir : undefined, ariaSort: ariaSortOf(active, effective?.dir), onSort: () => toggle(key, type) }
  }, [effective, toggle])

  return { sorted, sort: effective, toggle, headerProps }
}
