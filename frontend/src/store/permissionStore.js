/**
 * permissionStore.js
 *
 * Zustand store for the current user's effective permissions.
 * Fetched once from GET /api/users/my-permissions/ and cached for the session.
 *
 * Shape:
 *   permissions: { [module]: { [action]: boolean } }   (null = not loaded)
 *   role:        string
 *   seeded:      [module]   modules the matrix has rows for (others fall back to old role lists)
 *
 * Usage (via usePermission hook — prefer that over direct store access):
 *   const can = usePermissionStore(s => s.can)
 *   can('reservations', 'create')  →  true | false
 */
import { create } from 'zustand'
import { usersApi } from '../api/client'

// A failed load is "not loaded" (permissions stay null), never an empty grant set: with the
// module-only menu items an empty map would empty the menu on one transient error (role review,
// final fix minor 8). It retries once on its own; App also calls load() again on window focus.
const RETRY_MS = 3000
let retryTimer = null
let retried = false

const usePermissionStore = create((set, get) => ({
  permissions: null,   // null = not loaded yet
  role: null,
  seeded: null,        // modules the matrix has rows for; null = the server didn't say
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
        seeded:      Array.isArray(data.seeded) ? data.seeded : null,
        isLoading:   false,
        error:       null,
      })
    } catch (err) {
      console.error('permissionStore: failed to load permissions', err)
      set({ permissions: null, isLoading: false, error: err })
      if (!retried && !retryTimer) {
        retried = true
        retryTimer = setTimeout(() => { retryTimer = null; get().load() }, RETRY_MS)
      }
    }
  },

  /** Reset on logout. */
  reset: () => {
    if (retryTimer) clearTimeout(retryTimer)
    retryTimer = null
    retried = false
    set({ permissions: null, role: null, seeded: null, isLoading: false, error: null })
  },

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
