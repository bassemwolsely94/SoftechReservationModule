// C27 / P-06 — POS reference reads and discount-suggest request shaping. FRONTEND TIMING ONLY:
// nothing here decides a price, a discount or what is posted. The server answers exactly as before;
// this only avoids asking it the same question twice in a short time.
//
// cachedGet: a short in-memory cache for the POS reference lists that barely change during a shift
// (branches, customer types, a branch's stores). Keyed by the logged-in user, so a different user on
// the same browser never sees the previous user's server-filtered lists. Concurrent calls for the same
// key share one request. A failed request is never cached.
import api from './client'
import useAuthStore from '../store/authStore'

export const POS_REF_TTL_MS = 5 * 60 * 1000

const _cache = new Map()     // key → { at, promise }

function _userKey() {
  try { return String(useAuthStore.getState().user?.id ?? 'anon') } catch { return 'anon' }
}

export function refCacheKey(url, params, user = _userKey()) {
  const p = params ? Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&') : ''
  return `${user}|${url}?${p}`
}

// `keep(data)` → false drops an answer from the cache once it arrives (e.g. a "could not read" note),
// so the next visit asks again.
export function cachedGet(url, { params, ttl = POS_REF_TTL_MS, now = Date.now, get = api.get, keep } = {}) {
  const key = refCacheKey(url, params)
  const hit = _cache.get(key)
  if (hit && now() - hit.at < ttl) return hit.promise
  const promise = get(url, params ? { params } : undefined)
  _cache.set(key, { at: now(), promise })
  const drop = () => { if (_cache.get(key)?.promise === promise) _cache.delete(key) }
  promise.then(res => { if (keep && !keep(res?.data)) drop() }, drop)
  return promise
}

export function clearPosRefCache() { _cache.clear() }

// The discount-suggest request depends only on the SET of item codes (the server answers a map keyed
// by code), so line order, duplicate lines and quantity edits must not trigger another request.
export function suggestItemsKey(lines) {
  return [...new Set((lines || []).map(l => l?.softech_itemcode).filter(Boolean).map(String))].sort().join(',')
}

export const SUGGEST_DEBOUNCE_MS = 250
