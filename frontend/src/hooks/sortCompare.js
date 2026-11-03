/**
 * sortCompare — pure helpers behind useSortableRows / useServerSort (no React, checkable with
 * `node scripts/check-sort.mjs`).
 *
 * Types: 'text' (Arabic-aware, numbers inside text compared naturally), 'number', 'date'.
 * Empty values (null / undefined / '' / '—' / NaN) always sort LAST, whichever the direction.
 */

const ARABIC_DIGITS = { '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
                        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9' }

export function isEmpty(v) {
  if (v === null || v === undefined) return true
  if (typeof v === 'number') return Number.isNaN(v)
  if (typeof v === 'string') { const s = v.trim(); return s === '' || s === '—' || s === '-' }
  return false
}

/** number from a number or a display string ("1,234.5", "٣٢٫٥", "12%"); null when it is not a number. */
export function toNumber(v) {
  if (typeof v === 'number') return Number.isNaN(v) ? null : v
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v !== 'string') return null
  const s = v.replace(/[٠-٩۰-۹]/g, d => ARABIC_DIGITS[d]).replace(/[٫]/g, '.').replace(/[,٬\s%]/g, '')
  if (s === '' || !/^[+-]?(\d+\.?\d*|\.\d+)$/.test(s)) return null
  return Number(s)
}

/** milliseconds from a Date / ISO string / timestamp; null when invalid. */
export function toTime(v) {
  if (v instanceof Date) { const t = v.getTime(); return Number.isNaN(t) ? null : t }
  if (typeof v === 'number') return Number.isNaN(v) ? null : v
  if (typeof v !== 'string') return null
  const t = Date.parse(v)
  return Number.isNaN(t) ? null : t
}

const collator = new Intl.Collator('ar', { numeric: true, sensitivity: 'base' })

/**
 * Compare two values for `dir` ('asc' | 'desc'). Empty values come last in both directions.
 * A value that cannot be read as the requested type (e.g. "abc" in a number column) counts as empty.
 */
export function compareValues(a, b, type = 'text', dir = 'asc') {
  const conv = type === 'number' ? toNumber : type === 'date' ? toTime : v => String(v)
  const x = isEmpty(a) ? null : conv(a)
  const y = isEmpty(b) ? null : conv(b)
  if (x === null && y === null) return 0
  if (x === null) return 1
  if (y === null) return -1
  const c = type === 'text' ? collator.compare(x, y) : (x < y ? -1 : x > y ? 1 : 0)
  return dir === 'desc' ? -c : c
}

/** First click direction: text starts A→Z, numbers and dates start with the largest / latest. */
export function firstDirection(type) {
  return type === 'text' ? 'asc' : 'desc'
}

export const flip = dir => (dir === 'asc' ? 'desc' : 'asc')

/**
 * Click cycle for client-side sorting. `sort` is {key, dir, type, step} or null; returns the next
 * state (null = back to the table's default order). step 1 = first click, step 2 = reversed.
 * A table whose default order is a sort on the same key goes default → reversed → default.
 */
export function nextSort(sort, key, type = 'text', defaultSort = null) {
  if (sort && sort.key === key) {
    return sort.step === 1 ? { key, dir: flip(sort.dir), type: sort.type, step: 2 } : null
  }
  if (!sort && defaultSort && defaultSort.key === key) {
    return { key, dir: flip(defaultSort.dir || 'desc'), type: defaultSort.type || type, step: 2 }
  }
  return { key, dir: firstDirection(type), type, step: 1 }
}

/** Stable sort of `rows` by `sort` ({key, dir, type}); `getValue(row, key)` reads the cell value. */
export function sortRows(rows, sort, getValue) {
  if (!sort || !Array.isArray(rows)) return rows
  const idx = rows.map((row, i) => ({ row, i, v: getValue(row, sort.key) }))
  idx.sort((p, q) => compareValues(p.v, q.v, sort.type, sort.dir) || p.i - q.i)
  return idx.map(p => p.row)
}

/** Parse a DRF-style ordering string: '-net' → {key:'net', dir:'desc'}; '' → {key:'', dir:'asc'}. */
export function parseOrdering(value) {
  const s = typeof value === 'string' ? value.trim() : ''
  return s.startsWith('-') ? { key: s.slice(1), dir: 'desc' } : { key: s, dir: 'asc' }
}

export const toOrdering = (key, dir) => (dir === 'desc' ? `-${key}` : key)

/** Next ordering string for a server-sorted column: first → reversed → `defaultOrdering`. */
export function nextOrdering(value, key, type = 'text', defaultOrdering = '') {
  const cur = parseOrdering(value)
  if (cur.key === key) {
    return cur.dir === firstDirection(type) ? toOrdering(key, flip(cur.dir)) : defaultOrdering
  }
  return toOrdering(key, firstDirection(type))
}

export const ariaSortOf = (active, dir) => (!active ? 'none' : dir === 'asc' ? 'ascending' : 'descending')
