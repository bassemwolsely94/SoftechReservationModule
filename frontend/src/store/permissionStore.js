/**
 * permissionStore.js
 *
 * Zustand store for the current user's effective permissions.
 * Fetched once from GET /api/users/my-permissions/ and cached for the session.
 *
 * Shape:
 *   permissions: { [module]: { [action]: boolean } }
 *   role:        string
 *
 * Usage (via usePermission hook — prefer that over direct store access):
 *   const can = usePermissionStore(s => s.can)
 *   can('reservations', 'create')  →  true | false
 */
import { create } from 'zustand'
import { usersApi } from '../api/client'

const usePermissionStore = create((set, get) => ({
  permissions: null,   // null = not loaded yet
  role: null,
  isLoading: false,
  error: null,

  /** Fetch permissions from backend. Call once after login. */
  load: async () => {
    if (get().isLoading || get().permissions !== null) return
    set({ isLoading: true, error: null })
    try {
      const { data } = await usersApi.myPermissions()
      set({
        permissions: data.permissions || {},
        role:        data.role || 'viewer',
        isLoading:   false,
      })
    } catch (err) {
      console.error('permissionStore: failed to load permissions', err)
      set({ permissions: {}, role: 'viewer', isLoading: false, error: err })
    }
  },

  /** Reset on logout. */
  reset: () => set({ permissions: null, role: null, isLoading: false, error: null }),

  /**
   * Check whether the current user may perform `action` on `module`.
   * Returns true for admin (permissions map will already have all-true).
   * Returns false if permissions not yet loaded (fail-closed).
   */
  can: (module, action) => {
    const { permissions } = get()
    if (!permissions) return false
    return !!(permissions[module]?.[action])
  },
}))

export default usePermissionStore
