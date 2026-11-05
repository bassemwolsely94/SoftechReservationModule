import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
  usersApi: { myPermissions: vi.fn() },
  migrateLegacyTokens: vi.fn(() => Promise.resolve()),
}))

const { authApi, usersApi, migrateLegacyTokens } = await import('../api/client')
const { default: useAuthStore } = await import('./authStore')
const { default: usePermissionStore } = await import('./permissionStore')

const auth = () => useAuthStore.getState()
const perms = () => usePermissionStore.getState()

beforeEach(() => {
  vi.mocked(authApi.login).mockReset()
  vi.mocked(authApi.me).mockReset()
  vi.mocked(authApi.logout).mockReset().mockResolvedValue({})
  vi.mocked(usersApi.myPermissions).mockReset()
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: true })
  perms().reset()
  localStorage.clear()
})

describe('authStore', () => {
  it('login without 2FA keeps only the user, never the tokens', async () => {
    authApi.login.mockResolvedValue({ data: { user: { id: 1, role: 'pharmacist' }, access: 'A', refresh: 'R' } })
    const out = await auth().login('u', 'p')
    expect(authApi.login).toHaveBeenCalledWith('u', 'p')
    expect(out).toEqual({ user: { id: 1, role: 'pharmacist' } })
    expect(auth().isAuthenticated).toBe(true)
    expect(JSON.stringify(useAuthStore.getState())).not.toMatch(/"A"|"R"/)
    expect(localStorage.length).toBe(0)
  })

  it.each([
    [{ mfa_required: true, mfa_token: 't1' }, { mfa: 'verify', mfaToken: 't1' }],
    [{ mfa_setup_required: true, mfa_token: 't2' }, { mfa: 'setup', mfaToken: 't2' }],
  ])('a 2FA step is returned, not a session (%o)', async (data, expected) => {
    authApi.login.mockResolvedValue({ data })
    expect(await auth().login('u', 'p')).toEqual(expected)
    expect(auth().isAuthenticated).toBe(false)
    expect(auth().user).toBeNull()
  })

  it('a refused login rejects and stays logged out', async () => {
    authApi.login.mockRejectedValue(Object.assign(new Error('401'), { response: { status: 401 } }))
    await expect(auth().login('u', 'bad')).rejects.toThrow()
    expect(auth().isAuthenticated).toBe(false)
  })

  it('logout tells the server and wipes this browser', async () => {
    useAuthStore.setState({ user: { id: 1 }, isAuthenticated: true })
    localStorage.setItem('anything', 'x')
    auth().logout()
    expect(authApi.logout).toHaveBeenCalledOnce()
    expect(localStorage.length).toBe(0)
    expect(auth()).toMatchObject({ user: null, isAuthenticated: false })
  })

  it('logout still logs out locally when the server call fails', async () => {
    authApi.logout.mockRejectedValue(new Error('offline'))
    useAuthStore.setState({ user: { id: 1 }, isAuthenticated: true })
    auth().logout()
    expect(auth().isAuthenticated).toBe(false)
  })

  it('loadMe migrates legacy tokens, then loads the session', async () => {
    authApi.me.mockResolvedValue({ data: { id: 3, role: 'viewer' } })
    await auth().loadMe()
    expect(migrateLegacyTokens).toHaveBeenCalled()
    expect(auth()).toMatchObject({ user: { id: 3 }, isAuthenticated: true, isLoading: false })
  })

  it('loadMe without a session ends loading, logged out', async () => {
    authApi.me.mockRejectedValue(new Error('401'))
    await auth().loadMe()
    expect(auth()).toMatchObject({ user: null, isAuthenticated: false, isLoading: false })
  })
})

describe('permissionStore', () => {
  it('fails closed before permissions load', () => {
    expect(perms().can('reservations', 'view')).toBe(false)
  })

  it('answers from the server matrix', async () => {
    usersApi.myPermissions.mockResolvedValue({
      data: { role: 'pharmacist', permissions: { reservations: { view: true, create: true, delete: false } } },
    })
    await perms().load()
    expect(perms().role).toBe('pharmacist')
    expect(perms().can('reservations', 'view')).toBe(true)
    expect(perms().can('reservations', 'delete')).toBe(false)
    expect(perms().can('finance', 'view')).toBe(false)
  })

  it('loads once per session', async () => {
    usersApi.myPermissions.mockResolvedValue({ data: { role: 'admin', permissions: {} } })
    await perms().load()
    await perms().load()
    expect(usersApi.myPermissions).toHaveBeenCalledOnce()
  })

  it('a failed load denies everything and falls back to viewer', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    usersApi.myPermissions.mockRejectedValue(new Error('500'))
    await perms().load()
    expect(perms()).toMatchObject({ permissions: {}, role: 'viewer', isLoading: false })
    expect(perms().error).toBeTruthy()
    expect(perms().can('reservations', 'view')).toBe(false)
  })

  it('a missing role in the answer is viewer, not admin', async () => {
    usersApi.myPermissions.mockResolvedValue({ data: {} })
    await perms().load()
    expect(perms().role).toBe('viewer')
  })

  it('reset forgets everything (logout)', async () => {
    usersApi.myPermissions.mockResolvedValue({ data: { role: 'admin', permissions: { pos: { view: true } } } })
    await perms().load()
    perms().reset()
    expect(perms()).toMatchObject({ permissions: null, role: null })
    expect(perms().can('pos', 'view')).toBe(false)
  })
})
