import { create } from 'zustand'
import { authApi, migrateLegacyTokens } from '../api/client'

const useAuthStore = create((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  // The server has already set the httpOnly session cookies; keep only the user.
  // (data.access / data.refresh are deliberately NOT stored anywhere.)
  setSession: (data) => {
    set({ user: data.user, isAuthenticated: true })
    return data.user
  },

  // Step 1 of login. Returns either:
  //   { mfa: 'verify' | 'setup', mfaToken }  → caller must complete 2FA, OR
  //   { user }                               → session already established.
  login: async (username, password) => {
    const { data } = await authApi.login(username, password)
    if (data.mfa_required)       return { mfa: 'verify', mfaToken: data.mfa_token }
    if (data.mfa_setup_required) return { mfa: 'setup',  mfaToken: data.mfa_token }
    return { user: useAuthStore.getState().setSession(data) }
  },

  logout: () => {
    // Server side: blacklist the refresh token and clear the cookies.
    authApi.logout().catch(() => {})
    // "Remember this device" lives server-side on the approved device (N2/N3);
    // nothing on this browser has to survive logout.
    localStorage.clear()
    set({ user: null, isAuthenticated: false })
  },

  loadMe: async () => {
    await migrateLegacyTokens()
    try {
      const { data } = await authApi.me()
      set({ user: data, isAuthenticated: true, isLoading: false })
    } catch {
      // Not logged in (or session expired): no tokens are kept client-side, so
      // there is nothing to wipe — keep the UI prefs.
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  },
}))

export default useAuthStore
