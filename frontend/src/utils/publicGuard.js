// Self-hosted public-form guard (security N6) — the browser half of core/public_guard.py.
// Fetches a signed challenge, then finds a nonce so that
// sha256(`${challenge}:${nonce}`) starts with `difficulty` zero bits.
// Plain fetch: the public pages do not use the staff axios client.

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

export async function solveChallenge(form, { timeoutMs = 20000 } = {}) {
  const subtle = globalThis.crypto && globalThis.crypto.subtle
  if (!subtle) throw new Error('unsupported')
  const started = Date.now()

  const res = await fetch(`/api/public/challenge/?form=${encodeURIComponent(form)}`)
  if (!res.ok) throw new Error('challenge')
  const { challenge, difficulty } = await res.json()

  const enc = new TextEncoder()
  for (let nonce = 0; ; nonce++) {
    const digest = await subtle.digest('SHA-256', enc.encode(`${challenge}:${nonce}`))
    if (leadingZeroBits(new Uint8Array(digest)) >= difficulty) {
      return { challenge, nonce: String(nonce) }
    }
    if (nonce % BATCH === BATCH - 1) {
      if (Date.now() - started > timeoutMs) throw new Error('timeout')
      await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
}
