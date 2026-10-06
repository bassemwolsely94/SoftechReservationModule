/**
 * utils/wildcard.js — the system's search rules on the client (mirror of
 * apps/catalog/wildcard.py, which owns them on the server):
 *
 *   • `*` and `%` are BOTH wildcards — vol*ren*50*tab* = vol%ren%50%tab
 *   • always "contains", case-insensitive; parts in the order typed; a space is literal
 *   • the same words in ANY order also match (2nd tier — «50 voltaren»)
 *
 * wildcardMatch(text, q)   → bool, for local grid filters
 * highlightRanges(text, q) → [[start, end], …] to mark what matched (see <Highlight>)
 */

const WILD = /[*%]/

export function parseQuery(q) {
  const raw = String(q || '').trim().replace(/\s+/g, ' ')
  return {
    raw,
    segments: raw.split(WILD).filter(s => s.trim()),
    terms: raw.split(/[\s*%]+/).filter(Boolean),
  }
}

function ordered(hay, segments) {
  let at = 0
  const out = []
  for (const s of segments) {
    const i = hay.indexOf(s.toLowerCase(), at)
    if (i < 0) return null
    out.push([i, i + s.length])
    at = i + s.length
  }
  return out
}

/** Does `text` (or any of several texts) match the query by the system's rules? */
export function wildcardMatch(text, q) {
  const { segments, terms } = parseQuery(q)
  if (!segments.length) return true
  const texts = Array.isArray(text) ? text : [text]
  return texts.some(t => {
    const hay = String(t ?? '').toLowerCase()
    if (ordered(hay, segments)) return true
    return terms.length > 1 && terms.every(w => hay.includes(w.toLowerCase()))
  })
}

/** Character ranges of `text` that the query matched — literal text first, then the
 *  wildcard parts in order, then each word anywhere. [] when nothing matched (e.g. a
 *  «بالنطق» / «تقريبي» row). */
export function highlightRanges(text, q) {
  const { raw, segments, terms } = parseQuery(q)
  const hay = String(text ?? '').toLowerCase()
  if (!segments.length || !hay) return []
  const lit = hay.indexOf(raw.toLowerCase())
  if (lit >= 0) return [[lit, lit + raw.length]]
  const ord = ordered(hay, segments)
  if (ord) return ord
  const out = []
  for (const w of terms) {
    const i = hay.indexOf(w.toLowerCase())
    if (i >= 0) out.push([i, i + w.length])
  }
  return out.sort((a, b) => a[0] - b[0]).reduce((acc, r) => {
    const last = acc[acc.length - 1]
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
    else acc.push([...r])
    return acc
  }, [])
}
