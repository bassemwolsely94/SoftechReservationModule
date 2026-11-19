import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

vi.mock('../api/client', () => ({
  authApi: { login: vi.fn(), verify2fa: vi.fn(), me: vi.fn(), logout: vi.fn() },
  migrateLegacyTokens: vi.fn(),
}))

const { authApi } = await import('../api/client')
const { default: useAuthStore } = await import('../store/authStore')
const { requestRelogin } = await import('../api/sessionExpiry')
const { default: SessionExpiredOverlay } = await import('./SessionExpiredOverlay')

// Full audit FE-12: the same user signs in again over the page; the page underneath is kept.
function Page() {
  return <input aria-label="draft" defaultValue="" />
}

function setup() {
  render(<><Page /><SessionExpiredOverlay /></>)
  fireEvent.change(screen.getByLabelText('draft'), { target: { value: 'half-typed basket' } })
}

let waiting
async function expire() {
  await act(async () => { waiting = requestRelogin() })
  waiting.catch(() => {})                                   // the cancel cases assert it themselves
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ user: { username: 'e2e_pharmacist', role: 'pharmacist' }, isAuthenticated: true, isLoading: false })
})
afterEach(cleanup)

describe('SessionExpiredOverlay', () => {
  it('stays hidden until a request needs a new login', () => {
    setup()
    expect(screen.queryByTestId('session-expired')).toBeNull()
  })

  it('signs the same user in again and keeps the page as it was', async () => {
    authApi.login.mockResolvedValue({ data: { user: { username: 'e2e_pharmacist', role: 'pharmacist' } } })
    setup()
    await expire()
    expect(screen.getByTestId('session-expired')).toBeTruthy()
    expect(screen.getByDisplayValue('e2e_pharmacist').readOnly).toBe(true)

    fireEvent.change(screen.getByLabelText('كلمة المرور'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'دخول ومتابعة' }))

    await expect(waiting).resolves.toBeUndefined()
    expect(authApi.login).toHaveBeenCalledWith('e2e_pharmacist', 'pw')
    expect(screen.queryByTestId('session-expired')).toBeNull()
    expect(screen.getByLabelText('draft').value).toBe('half-typed basket')
  })

  it('every request that expired meanwhile waits on the one sign-in', async () => {
    setup()
    await expire()
    const second = requestRelogin()
    expect(second).toBe(waiting)
  })

  it('asks for the 2FA code when the account has one', async () => {
    authApi.login.mockResolvedValue({ data: { mfa_required: true, mfa_token: 't' } })
    authApi.verify2fa.mockResolvedValue({ data: { user: { username: 'e2e_pharmacist' } } })
    setup()
    await expire()
    fireEvent.change(screen.getByLabelText('كلمة المرور'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'دخول ومتابعة' }))
    const code = await screen.findByLabelText(/رمز التحقق/)
    fireEvent.change(code, { target: { value: ' 123456 ' } })
    fireEvent.click(screen.getByRole('button', { name: 'تحقق ومتابعة' }))
    await expect(waiting).resolves.toBeUndefined()
    expect(authApi.verify2fa).toHaveBeenCalledWith('t', '123456', false)
  })

  it('a wrong password keeps the overlay open with the error', async () => {
    authApi.login.mockRejectedValue({ response: { data: { error: 'بيانات الدخول غير صحيحة' } } })
    setup()
    await expire()
    fireEvent.change(screen.getByLabelText('كلمة المرور'), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: 'دخول ومتابعة' }))
    expect(await screen.findByText('بيانات الدخول غير صحيحة')).toBeTruthy()
    expect(screen.getByTestId('session-expired')).toBeTruthy()
  })

  it('another account never inherits the page: it goes to the login page', async () => {
    authApi.login.mockResolvedValue({ data: { user: { username: 'someone_else' } } })
    setup()
    await expire()
    fireEvent.change(screen.getByLabelText('كلمة المرور'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'دخول ومتابعة' }))
    await expect(waiting).rejects.toThrow()
    expect(useAuthStore.getState().user.username).toBe('e2e_pharmacist')   // session not taken over
  })

  it('"another account" gives up: the waiting requests are rejected', async () => {
    setup()
    await expire()
    fireEvent.click(screen.getByRole('button', { name: /الدخول بحساب آخر/ }))
    await expect(waiting).rejects.toThrow()
    expect(screen.queryByTestId('session-expired')).toBeNull()
  })

  it('registers nothing while signed out (the client then goes to /login?next=)', () => {
    useAuthStore.setState({ user: null, isAuthenticated: false })
    render(<SessionExpiredOverlay />)
    expect(requestRelogin()).toBeNull()
  })
})
