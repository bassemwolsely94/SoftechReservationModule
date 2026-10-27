import { create } from 'zustand'
import { authApi, migrateLegacyTokens } from '../api/client'

const useAuthStore = create((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  // The server has already set the httpOnly session cookies; keep only the user.
  // (data.access / data.refresh are deliberately NOT stored anywhere.)
  setSession: (data) => {
    if (data.device_token) localStorage.setItem('mfa_device_token', data.device_token)
    set({ user: data.user, isAuthenticated: true })
    return data.user
  },

  // Step 1 of login. Returns either:
  //   { mfa: 'verify' | 'setup', mfaToken }  → caller must complete 2FA, OR
  //   { user }                               → session already established.
  login: async (username, password) => {
    const deviceToken = localStorage.getItem('mfa_device_token')
    const { data } = await authApi.login(username, password, deviceToken)
    if (data.mfa_required)       return { mfa: 'verify', mfaToken: data.mfa_token }
    if (data.mfa_setup_required) return { mfa: 'setup',  mfaToken: data.mfa_token }
    return { user: useAuthStore.getState().setSession(data) }
  },

  logout: () => {
    // Server side: blacklist the refresh token and clear the cookies.
    authApi.logout().catch(() => {})
    // Preserve the trusted-device token across logout so 2FA can be skipped on
    // this device until it expires (30 days). Everything else is cleared.
    const device = localStorage.getItem('mfa_device_token')
    localStorage.clear()
    if (device) localStorage.setItem('mfa_device_token', device)
    set({ user: null, isAuthenticated: false })
  },

  loadMe: async () => {
    await migrateLegacyTokens()
    try {
      const { data } = await authApi.me()
      set({ user: data, isAuthenticated: true, isLoading: false })
    } catch {
      // Not logged in (or session expired): no tokens are kept client-side, so
      // there is nothing to wipe — keep the trusted-device token and UI prefs.
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  },
}))

export default useAuthStore
