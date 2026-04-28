import { create } from 'zustand'
import { authApi } from '../api/client'

const useAuthStore = create((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (username, password) => {
    const { data } = await authApi.login(username, password)
    localStorage.setItem('access_token', data.access)
    localStorage.setItem('refresh_token', data.refresh)
    set({ user: data.user, isAuthenticated: true })
    return data.user
  },

  logout: () => {
    localStorage.clear()
    set({ user: null, isAuthenticated: false })
  },

  loadMe: async () => {
    const token = localStorage.getItem('access_token')
    if (!token) { set({ isLoading: false }); return }
    try {
      const { data } = await authApi.me()
      set({ user: data, isAuthenticated: true, isLoading: false })
    } catch {
      localStorage.clear()
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  },
}))

export default useAuthStore
