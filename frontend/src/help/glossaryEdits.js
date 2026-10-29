/**
 * glossaryEdits — pure draft edits for «طبّق القاموس» (GlossaryApply.jsx). Items come
 * from POST /api/help/glossary/scan/: {path, start, end, match, replacement, state}.
 * A replacement only happens when the text at that place is still the scanned word
 * (else the item becomes 'stale'); later items in the same text move by the length
 * difference.
 */
export const getAt = (obj, path) => path.reduce((o, k) => (o == null ? o : o[k]), obj)

export function setAt(obj, path, value) {
  if (!path.length) return value
  const [k, ...rest] = path
  const copy = Array.isArray(obj) ? obj.slice() : { ...obj }
  copy[k] = setAt(obj?.[k], rest, value)
  return copy
}

const same = (a, b) => JSON.stringify(a.path) === JSON.stringify(b.path)

/** Replace item `idx` → { draft, items }. */
export function acceptOne(draft, items, idx) {
  const it = items[idx]
  const text = getAt(draft, it.path)
  if (typeof text !== 'string' || text.slice(it.start, it.end) !== it.match) {
    return { draft, items: items.map((x, j) => (j === idx ? { ...x, state: 'stale' } : x)) }
  }
  const delta = it.replacement.length - (it.end - it.start)
  return {
    draft: setAt(draft, it.path, text.slice(0, it.start) + it.replacement + text.slice(it.end)),
    items: items.map((x, j) => {
      if (j === idx) return { ...x, state: 'done' }
      if (same(x, it) && x.start >= it.end) return { ...x, start: x.start + delta, end: x.end + delta }
      return x
    }),
  }
}

/** Replace every open item → { draft, items } (acceptOne keeps the later places right). */
export function acceptAll(draft, items) {
  const order = items.map((x, j) => j).filter((j) => items[j].state === 'open')
  let cur = { draft, items }
  for (const j of order) cur = acceptOne(cur.draft, cur.items, j)
  return cur
}

export const skipOne = (items, idx) => items.map((x, j) => (j === idx ? { ...x, state: 'skipped' } : x))
