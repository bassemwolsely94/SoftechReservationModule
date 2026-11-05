import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import axios from 'axios'
import api, { authApi, migrateLegacyTokens, refreshSession, reservationsApi } from './client'

// Every request goes through a fake adapter: nothing leaves the test process.
const calls = []
let reply = () => ({ status: 200, data: {} })

function adapter(config) {
  calls.push({ method: config.method, url: config.url, baseURL: config.baseURL, data: config.data,
               headers: config.headers, withCredentials: config.withCredentials })
  const r = reply(config, calls.length)
  const res = { data: r.data ?? {}, status: r.status, statusText: String(r.status), headers: {}, config }
  if (r.status >= 400) {
    const err = new axios.AxiosError(`status ${r.status}`, 'ERR_BAD_RESPONSE', config, null, res)
    return Promise.reject(err)
  }
  return Promise.resolve(res)
}

const savedApi = api.defaults.adapter
const savedGlobal = axios.defaults.adapter

beforeEach(() => {
  calls.length = 0
  reply = () => ({ status: 200, data: {} })
  api.defaults.adapter = adapter
  axios.defaults.adapter = adapter       // refreshSession / migrateLegacyTokens use the global axios
  window.history.pushState({}, '', '/reservations')
  localStorage.clear()
})
afterEach(() => {
  api.defaults.adapter = savedApi
  axios.defaults.adapter = savedGlobal
})

describe('api client defaults', () => {
  it('talks to /api with cookies and the X-Requested-With CSRF marker', async () => {
    await api.get('/reservations/')
    expect(calls[0].baseURL).toBe('/api')
    expect(calls[0].withCredentials).toBe(true)
    expect(calls[0].headers['X-Requested-With']).toBe('XMLHttpRequest')
  })

  it('never keeps a token in localStorage after login', async () => {
    reply = () => ({ status: 200, data: { user: { id: 1 }, access: 'a', refresh: 'r' } })
    await authApi.login('u', 'p')
    expect(calls[0]).toMatchObject({ method: 'post', url: '/auth/login/' })
    expect(JSON.parse(calls[0].data)).toEqual({ username: 'u', password: 'p' })
    expect(localStorage.length).toBe(0)
  })

  it('builds resource URLs and bodies', async () => {
    await reservationsApi.changeStatus(7, 'ready', 'note')
    expect(calls[0]).toMatchObject({ method: 'post', url: '/reservations/7/change-status/' })
    expect(JSON.parse(calls[0].data)).toEqual({ status: 'ready', note: 'note' })
    await reservationsApi.list({ page: 2 })
    expect(calls[1]).toMatchObject({ method: 'get', url: '/reservations/' })
  })
})

describe('401 → refresh → retry once', () => {
  it('refreshes the cookie and retries the original request', async () => {
    reply = (cfg, n) => (n === 1 ? { status: 401 } : { status: 200, data: { ok: n } })
    const res = await api.get('/reservations/')
    expect(calls.map(c => c.url)).toEqual(['/reservations/', '/api/auth/refresh/', '/reservations/'])
    expect(calls[1].headers['X-Requested-With']).toBe('XMLHttpRequest')
    expect(res.data.ok).toBe(3)
  })

  it('does not retry a second 401 (no loop)', async () => {
    reply = (cfg) => (cfg.url.includes('refresh') ? { status: 200 } : { status: 401 })
    await expect(api.get('/reservations/')).rejects.toMatchObject({ response: { status: 401 } })
    expect(calls.map(c => c.url)).toEqual(['/reservations/', '/api/auth/refresh/', '/reservations/'])
  })

  it.each(['/auth/login/', '/auth/refresh/', '/auth/logout/', '/auth/2fa/verify/'])(
    'never refreshes for %s', async (url) => {
      reply = () => ({ status: 401 })
      await expect(api.post(url, {})).rejects.toBeTruthy()
      expect(calls).toHaveLength(1)
    })

  it('shares one refresh between concurrent 401s', async () => {
    reply = (cfg) => {
      if (cfg.url.includes('refresh')) return { status: 200 }
      return cfg._retry ? { status: 200 } : { status: 401 }
    }
    await Promise.all([api.get('/a/'), api.get('/b/'), api.get('/c/')])
    expect(calls.filter(c => c.url.includes('refresh'))).toHaveLength(1)
  })

  it('a failed refresh rejects with the original 401 (on /login no redirect)', async () => {
    window.history.pushState({}, '', '/login')
    reply = () => ({ status: 401 })
    await expect(api.get('/reservations/')).rejects.toMatchObject({ response: { status: 401 } })
    expect(window.location.pathname).toBe('/login')
  })

  it('a non-401 error passes straight through', async () => {
    reply = () => ({ status: 403, data: { detail: 'no' } })
    await expect(api.get('/finance/gl/accounts/')).rejects.toMatchObject({ response: { status: 403 } })
    expect(calls).toHaveLength(1)
  })
})

describe('refreshSession / migrateLegacyTokens', () => {
  it('refreshSession is single-flight', async () => {
    const a = refreshSession()
    const b = refreshSession()
    expect(a).toBe(b)
    await a
    expect(calls).toHaveLength(1)
  })

  it('trades a legacy refresh token for cookies once and forgets every stored token', async () => {
    localStorage.setItem('access_token', 'old-a')
    localStorage.setItem('refresh_token', 'old-r')
    localStorage.setItem('mfa_device_token', 'old-d')
    await migrateLegacyTokens()
    expect(calls).toHaveLength(1)
    expect(JSON.parse(calls[0].data)).toEqual({ refresh: 'old-r' })
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(localStorage.getItem('mfa_device_token')).toBeNull()
  })

  it('does nothing without a legacy token and survives an expired one', async () => {
    await migrateLegacyTokens()
    expect(calls).toHaveLength(0)
    localStorage.setItem('refresh_token', 'expired')
    reply = () => ({ status: 401 })
    await expect(migrateLegacyTokens()).resolves.toBeUndefined()
  })
})
