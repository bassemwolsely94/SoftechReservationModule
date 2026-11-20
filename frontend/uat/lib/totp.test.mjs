// node --test uat/lib/totp.test.mjs  (from frontend/)
// RFC 6238 appendix B, SHA-1 rows: secret = ASCII "12345678901234567890", 8 digits.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { base32Decode, hotp, totp, stepAt, freshLoginCode } from './totp.js'

const RFC_SECRET_B32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'   // base32 of "12345678901234567890"
const VECTORS = [
  [59, '94287082'],
  [1111111109, '07081804'],
  [1111111111, '14050471'],
  [1234567890, '89005924'],
  [2000000000, '69279037'],
  [20000000000, '65353130'],
]

test('base32 decodes the RFC secret', () => {
  assert.equal(base32Decode(RFC_SECRET_B32).toString('ascii'), '12345678901234567890')
  assert.equal(base32Decode('gezd gnbv gy3t qojq gezd gnbv gy3t qojq').toString('ascii'), '12345678901234567890')
  assert.throws(() => base32Decode('GEZ1'))
})

test('RFC 4226 appendix D HOTP values', () => {
  const key = Buffer.from('12345678901234567890', 'ascii')
  const want = ['755224', '287082', '359152', '969429', '338314', '254676', '287922', '162583', '399871', '520489']
  want.forEach((code, counter) => assert.equal(hotp(key, counter), code))
})

for (const [t, code8] of VECTORS) {
  test(`RFC 6238 SHA-1 vector T=${t}`, () => {
    assert.equal(totp(RFC_SECRET_B32, { step: stepAt(t), digits: 8 }), code8)
    // the server's 6-digit code is the same truncation mod 10^6
    assert.equal(totp(RFC_SECRET_B32, { step: stepAt(t) }), code8.slice(-6))
  })
}

test('freshLoginCode skips spent steps and waits when it must', async () => {
  let clock = 1_000_000 * 30 + 5          // 5 s into step 1_000_000
  const now = () => clock
  const a = await freshLoginCode(RFC_SECRET_B32, -1, { now })
  assert.equal(a.step, 1_000_000)
  const b = await freshLoginCode(RFC_SECRET_B32, a.step, { now })
  assert.equal(b.step, 1_000_001)          // next step is still accepted (server window ±1)
  await assert.rejects(() => freshLoginCode(RFC_SECRET_B32, b.step, { now }))
  const waited = []
  const c = await freshLoginCode(RFC_SECRET_B32, b.step, { now, sleep: async ms => { waited.push(ms); clock += ms / 1000 } })
  assert.equal(c.step, 1_000_002)
  assert.ok(waited[0] > 25_000 && waited[0] <= 26_000, `waited ${waited[0]} ms`)
  assert.equal(c.code, totp(RFC_SECRET_B32, { step: 1_000_002 }))
})
