// The «أصناف المطالبة» search box (InsuranceClaimDetailPage, items tab).
// contains / notcontains follow the system search rules (utils/wildcard.js: * and % wildcards,
// word order); begins / ends compare the typed text literally. A query with no text between the
// wildcards (e.g. «*») is no filter in every mode — it must never hide all rows.
import { parseQuery, wildcardMatch } from './wildcard'

export function filterClaimItems(items, q, matchMode = 'contains', searchIn = 'both') {
  if (!parseQuery(q).segments.length) return items
  const s = q.trim().toLowerCase()
  const matches = (v) => {
    v = (v || '').toString().toLowerCase()
    if (matchMode === 'begins') return v.startsWith(s)
    if (matchMode === 'ends') return v.endsWith(s)
    return wildcardMatch(v, q)
  }
  // any in-scope field matches (code and/or name)
  const anyMatch = (it) =>
    (searchIn !== 'name' && matches(it.item_code)) ||
    (searchIn !== 'code' && matches(it.item_name))
  return matchMode === 'notcontains'
    ? items.filter(it => !anyMatch(it))   // keep rows that do NOT contain the term
    : items.filter(anyMatch)
}
