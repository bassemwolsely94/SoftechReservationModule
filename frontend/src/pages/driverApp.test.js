import { describe, expect, it } from 'vitest'
import { driverRefusal, retryUnlessRefused, NO_PROFILE_FALLBACK } from './driverApp'

const refused = (detail) => ({ response: { status: 403, data: detail === undefined ? {} : { detail } } })

describe('/rider without a driver profile (UAT W8)', () => {
  it('shows the server refusal text', () => {
    expect(driverRefusal(refused('ليس لديك ملف سائق مرتبط.'), null)).toBe('ليس لديك ملف سائق مرتبط.')
  })
  it('either endpoint refusing is enough', () => {
    expect(driverRefusal(null, refused('x'))).toBe('x')
  })
  it('a 403 with no text falls back to the no-profile line', () => {
    expect(driverRefusal(refused())).toBe(NO_PROFILE_FALLBACK)
    expect(driverRefusal(refused('  '))).toBe(NO_PROFILE_FALLBACK)
  })
  it('no refusal: null (the screen shows tasks or the no-tasks line)', () => {
    expect(driverRefusal(null, undefined)).toBeNull()
    expect(driverRefusal({ response: { status: 500 } })).toBeNull()
  })
  it('a refusal is not retried; other failures are, up to 3 times', () => {
    expect(retryUnlessRefused(0, refused('x'))).toBe(false)
    expect(retryUnlessRefused(0, { response: { status: 500 } })).toBe(true)
    expect(retryUnlessRefused(3, { response: { status: 500 } })).toBe(false)
  })
})
