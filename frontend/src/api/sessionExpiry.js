// Full audit FE-12: an expired session no longer throws the page away.
//
// When the refresh cookie is also dead, the API client asks the mounted <SessionExpiredOverlay>
// to sign the same user in again over the page (React state, an unsaved form or basket, stays as
// it was) and then retries the request that failed — it never reached the server (401), so the
// retry cannot double anything. With no overlay mounted it falls back to /login?next=<page>, and
// the login page returns there afterwards.

// Only a same-site path is accepted as a return target: never another origin ("//evil", "/\evil",
// "https:…"), never the login page itself, nothing with control characters.
export function safeNext(raw) {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > 500) return null
  if (raw[0] !== '/' || raw[1] === '/' || raw[1] === '\\') return null
  if (raw.includes('\\') || [...raw].some(ch => ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127)) return null
  if (raw === '/login' || raw.startsWith('/login?') || raw.startsWith('/login/')) return null
  return raw
}

// /login?next=<the page the user is on>; plain /login when that page is already the login page.
export function loginUrlFor(loc = window.location) {
  const next = safeNext(`${loc.pathname || ''}${loc.search || ''}${loc.hash || ''}`)
  return next && next !== '/' ? `/login?next=${encodeURIComponent(next)}` : '/login'
}

let handler = null

// The overlay registers itself while a user is signed in; the returned function unregisters it.
export function setReloginHandler(fn) {
  handler = fn
  return () => { if (handler === fn) handler = null }
}

// A promise that resolves once the same user is signed in again (rejects if they give up), or
// null when no overlay is mounted — the caller then sends the browser to loginUrlFor().
export function requestRelogin() {
  return handler ? handler() : null
}
