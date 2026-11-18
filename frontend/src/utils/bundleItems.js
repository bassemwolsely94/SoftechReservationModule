// Bundle multi-add (/catalog-intelligence «الباقات»): the picked items not yet in the bundle,
// once each — an existing member is never POSTed again (the server also answers it with a 400).
export function newBundleItems(picked, bundle) {
  const seen = new Set((bundle?.items || []).map(bi => String(bi.item)))
  const fresh = []
  for (const it of picked) {
    const key = String(it.id)
    if (seen.has(key)) continue
    seen.add(key)
    fresh.push(it)
  }
  return fresh
}
