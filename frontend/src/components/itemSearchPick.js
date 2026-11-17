/**
 * Shared pieces of the item box picks (ItemSearchWidget modes + AdvancedItemSearchModal multi).
 *
 *  - withItemId(row): every picked item carries both `id` and `item_id`, equal. `/items/` rows
 *    have only `id`; migrated call sites read `item_id`. A row that already has both is returned
 *    unchanged.
 *  - useTicked(): the ticked rows of a multi pick, in tick order, keyed by `id`.
 */
import { useCallback, useState } from 'react'

export function withItemId(row) {
  if (!row) return row
  if (row.item_id == null && row.id != null) return { ...row, item_id: row.id }
  if (row.id == null && row.item_id != null) return { ...row, id: row.item_id }
  return row
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
