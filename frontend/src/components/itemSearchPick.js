/**
 * Shared pieces of the item box picks (ItemSearchWidget modes + AdvancedItemSearchModal multi).
 *
 *  - withItemId(row): every picked item carries both `id` and `item_id`, equal. `/items/` rows
 *    have only `id`; migrated call sites read `item_id`. When both exist and differ, `id` wins.
 *    A row whose two are already equal is returned unchanged.
 *  - useTicked(): the ticked rows of a multi pick, in tick order, keyed by `id`.
 */
import { useCallback, useState } from 'react'

export function withItemId(row) {
  if (!row) return row
  // `id` wins when present (the Item pk on /items/ rows); else `item_id`. Both end up equal.
  const v = row.id ?? row.item_id
  if (v == null || (row.id === v && row.item_id === v)) return row
  return { ...row, id: v, item_id: v }
}

const keyOf = r => r?.id ?? r?.item_id

export function useTicked() {
  const [ticked, setTicked] = useState([])
  const toggle = useCallback((row) => {
    if (!row) return
    const k = keyOf(row)
    setTicked(list => list.some(r => keyOf(r) === k)
      ? list.filter(r => keyOf(r) !== k)
      : [...list, row])
  }, [])
  const isTicked = useCallback(row => ticked.some(r => keyOf(r) === keyOf(row)), [ticked])
  const clear = useCallback(() => setTicked([]), [])
  return { ticked, toggle, isTicked, clear }
}
