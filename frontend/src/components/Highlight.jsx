/**
 * <Highlight text="VOLTAREN 50MG 20TAB" query="vol*ren*50*tab" />
 * Marks the parts of `text` the search matched (system search rules, utils/wildcard.js).
 */
import { highlightRanges } from '../utils/wildcard'

export default function Highlight({ text, query, className = 'bg-amber-200/70 dark:bg-amber-400/30 text-inherit rounded-sm px-px' }) {
  const s = String(text ?? '')
  const ranges = highlightRanges(s, query)
  if (!ranges.length) return s
  const out = []
  let at = 0
  ranges.forEach(([a, b], i) => {
    if (a > at) out.push(s.slice(at, a))
    out.push(<mark key={i} className={className}>{s.slice(a, b)}</mark>)
    at = b
  })
  if (at < s.length) out.push(s.slice(at))
  return out
}
