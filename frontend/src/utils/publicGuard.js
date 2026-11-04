// Self-hosted public-form guard (security N6) — the browser half of core/public_guard.py.
// Fetches a signed challenge, then finds a nonce so that
// sha256(`${challenge}:${nonce}`) starts with `difficulty` zero bits.
// Plain fetch: the public pages do not use the staff axios client.

import { useCallback, useEffect, useRef, useState } from 'react'

const BATCH = 500   // hashes between yields to the UI

// Must count exactly like core/public_guard.leading_zero_bits (MSB of byte 0 first).
// Vector: sha256('vector-challenge:492') = 0008f27a… → 12, ':3450' → 15, ':56938' → 16.
export function leadingZeroBits(bytes) {
  let n = 0
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    if (b === 0) { n += 8; continue }
    return n + Math.clz32(b) - 24
  }
  return n
}

const FILL_MARGIN_MS = 300   // on top of the server's min_fill_seconds

/**
 * Fetch a challenge for `form` and solve it. Resolves `{challenge, nonce}` to send with the form
 * (plus an empty honeypot field `website`).
 *
 * The server refuses a submit sooner than `min_fill_seconds` after the challenge was issued, so
 * this waits until that much time (+0.3 s) has passed since the fetch before it resolves.
 * Callers may pre-solve when the form opens; a solved result is valid only until the challenge
 * TTL (10 min), so a caller holding it longer than ~9 min must call again.
 *
 * Throws Error('unsupported') without crypto.subtle, Error('timeout') past `timeoutMs`
 * (including a hanging challenge request), Error('challenge') when the server refuses.
 */
export async function solveChallenge(form, { timeoutMs = 20000 } = {}) {
  const subtle = globalThis.crypto && globalThis.crypto.subtle
  if (!subtle) throw new Error('unsupported')
  const started = Date.now()

  const ctrl = new AbortController()
  const abortTimer = setTimeout(() => ctrl.abort(), timeoutMs)
  let body
  try {
    const res = await fetch(`/api/public/challenge/?form=${encodeURIComponent(form)}`,
      { signal: ctrl.signal })
    if (!res.ok) throw new Error('challenge')
    body = await res.json()
  } catch (e) {
    if (ctrl.signal.aborted) throw new Error('timeout')
    throw e
  } finally {
    clearTimeout(abortTimer)
  }
  const { challenge, difficulty, min_fill_seconds: minFill = 0 } = body
  const fetchedAt = Date.now()

  const enc = new TextEncoder()
  for (let nonce = 0; ; nonce++) {
    const digest = await subtle.digest('SHA-256', enc.encode(`${challenge}:${nonce}`))
    if (leadingZeroBits(new Uint8Array(digest)) >= difficulty) {
      const wait = fetchedAt + minFill * 1000 + FILL_MARGIN_MS - Date.now()
      if (wait > 0) await new Promise(resolve => setTimeout(resolve, wait))
      return { challenge, nonce: String(nonce) }
    }
    if (nonce % BATCH === BATCH - 1) {
      if (Date.now() - started > timeoutMs) throw new Error('timeout')
      await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
}

// ── React hook shared by every public form (NotifyPage, portal sign-in) ─────────────────────

const STALE_MS = 9 * 60 * 1000   // a solved challenge dies at 10 min on the server; refresh before that
export const NO_DEVICE_MSG = 'تعذر التحقق من الجهاز — جرّب متصفحاً آخر أو اتصل بالفرع'
export const NETWORK_MSG = 'تعذّر الاتصال، حاول مرة أخرى'

/** Arabic text for an error thrown by solveChallenge / getSolution. */
export function guardFailureMessage(e) {
  return e && (e.message === 'unsupported' || e.message === 'timeout') ? NO_DEVICE_MSG : NETWORK_MSG
}

/**
 * Pre-solves the challenge for `form` as soon as `enabled` (the form is on screen), so the submit
 * rarely waits. `getSolution()` resolves `{challenge, nonce}` - single use: the next call solves
 * afresh; one held longer than ~9 min is re-solved. A failed PRE-solve (started when the form
 * opened, not by this submit) is retried once with a fresh solve before the error surfaces.
 * `verifying` is true while a submit waits on it.
 */
export function usePublicGuard(form, enabled = true) {
  const solving = useRef(null)   // { promise, at, pre }
  const [verifying, setVerifying] = useState(false)

  const start = useCallback((pre = false) => {
    const p = solveChallenge(form)
    p.catch(() => {})            // handled where it is awaited
    solving.current = { promise: p, at: Date.now(), pre }
    return solving.current
  }, [form])

  useEffect(() => { if (enabled) start(true) }, [enabled, start])

  const getSolution = useCallback(async () => {
    let held = solving.current
    if (!held || Date.now() - held.at > STALE_MS) held = start(false)
    setVerifying(true)
    try {
      try { return await held.promise }
      catch (e) {
        if (!held.pre) throw e
        return await start(false).promise   // the pre-solve failed earlier: one fresh try
      }
    }
    finally { solving.current = null; setVerifying(false) }   // single-use, also after a failure
  }, [start])

  return { getSolution, verifying }
}
