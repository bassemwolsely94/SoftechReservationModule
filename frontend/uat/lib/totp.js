// RFC 6238 TOTP (RFC 4226 HOTP underneath) with node:crypto only — the UAT 2FA specs compute
// the authenticator's codes themselves (no new npm dependency). Same parameters as the server
// (pyotp defaults in apps/users/mfa.py): SHA-1, 6 digits, 30-second steps, base32 secret.
// Pure functions; unit-tested in totp.test.mjs against the RFC 6238 appendix B vectors.
import crypto from 'node:crypto'

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
export const STEP_SECONDS = 30

/** RFC 4648 base32 → Buffer (padding, spaces and case ignored). Throws on a foreign character. */
export function base32Decode(secret) {
  const clean = String(secret).toUpperCase().replace(/[\s=-]/g, '')
  let bits = 0, value = 0
  const out = []
  for (const ch of clean) {
    const idx = B32.indexOf(ch)
    if (idx < 0) throw new Error('base32Decode: not a base32 secret')
    value = (value << 5) | idx
    bits += 5
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff)
      bits -= 8
    }
  }
  return Buffer.from(out)
}

/** RFC 4226 HOTP for a key Buffer and an integer counter. */
export function hotp(key, counter, { digits = 6, algorithm = 'sha1' } = {}) {
  const msg = Buffer.alloc(8)
  msg.writeBigUInt64BE(BigInt(counter))
  const mac = crypto.createHmac(algorithm, key).update(msg).digest()
  const offset = mac[mac.length - 1] & 0x0f
  const bin = ((mac[offset] & 0x7f) << 24) | (mac[offset + 1] << 16) | (mac[offset + 2] << 8) | mac[offset + 3]
  return String(bin % 10 ** digits).padStart(digits, '0')
}

/** The 30-second step a unix time (seconds) falls in. */
export const stepAt = (unixSeconds = Date.now() / 1000) => Math.floor(unixSeconds / STEP_SECONDS)

/** TOTP code of a base32 secret for a given step (default: now). */
export function totp(secret, { step = stepAt(), digits = 6 } = {}) {
  return hotp(base32Decode(secret), step, { digits })
}

/**
 * A login code the server will still take. The server accepts a code once and refuses its step and
 * every earlier one afterwards (verify_login_code, A-2), within ±1 step of its clock. Returns the
 * code for the first step after `lastUsedStep` that is not ahead of now+1, waiting (via `sleep`)
 * when every such step is already spent. → {code, step}
 */
export async function freshLoginCode(secret, lastUsedStep = -1, { sleep, now = () => Date.now() / 1000 } = {}) {
  for (;;) {
    const current = stepAt(now())
    const step = Math.max(current, lastUsedStep + 1)
    if (step <= current + 1) return { code: totp(secret, { step }), step }
    // the next free step opens one step before it: wait until then (+1 s margin)
    const waitMs = Math.ceil(((step - 1) * STEP_SECONDS - now()) * 1000) + 1_000
    if (!sleep) throw new Error('freshLoginCode: every usable step is spent; pass `sleep` to wait')
    await sleep(waitMs)
  }
}
