import { afterEach, describe, expect, it } from 'vitest'
import { loginUrlFor, requestRelogin, safeNext, setReloginHandler } from './sessionExpiry'

// Full audit FE-12: the return target after login is a same-site path only.
describe('safeNext', () => {
  it.each(['/pos', '/transfers/new', '/insurance/claims/12?tab=lines', '/reservations#x'])('keeps %s', (p) => {
    expect(safeNext(p)).toBe(p)
  })

  it.each([
    null, undefined, '', 'pos', 'https://evil.example/x', '//evil.example', '/\\evil.example',
    '/a\\b', '/login', '/login?next=/pos', '/login/', '/pos\nx', 'javascript:alert(1)', `/${'a'.repeat(600)}`,
  ])('refuses %s', (p) => {
    expect(safeNext(p)).toBeNull()
  })
})

describe('loginUrlFor', () => {
  it('carries the page, its query and hash', () => {
    expect(loginUrlFor({ pathname: '/pos', search: '?b=1', hash: '#x' })).toBe(`/login?next=${encodeURIComponent('/pos?b=1#x')}`)
  })

  it('is plain /login from the login page or the root', () => {
    expect(loginUrlFor({ pathname: '/login', search: '?next=/pos' })).toBe('/login')
    expect(loginUrlFor({ pathname: '/', search: '' })).toBe('/login')
  })
})

describe('relogin handler', () => {
  let off = () => {}
  afterEach(() => off())

  it('is null with no overlay mounted', () => {
    expect(requestRelogin()).toBeNull()
  })

  it('returns the handler promise, and unregisters', async () => {
    off = setReloginHandler(() => Promise.resolve('back'))
    await expect(requestRelogin()).resolves.toBe('back')
    off()
    expect(requestRelogin()).toBeNull()
  })

  it('an old unregister does not remove a newer handler', () => {
    const offA = setReloginHandler(() => Promise.resolve('a'))
    off = setReloginHandler(() => Promise.resolve('b'))
    offA()
    expect(requestRelogin()).not.toBeNull()
  })
})
