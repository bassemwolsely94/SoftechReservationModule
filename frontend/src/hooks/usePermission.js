/**
 * usePermission.js
 *
 * Hook that checks whether the current user can perform an action on a module.
 *
 * Usage:
 *   const canCreate = usePermission('reservations', 'create')
 *   const canApprove = usePermission('transfers', 'approve')
 *
 * Returns:
 *   boolean — true if allowed, false if denied or permissions not yet loaded
 *
 * The store is loaded automatically on first use.
 */
import { useEffect } from 'react'
import usePermissionStore from '../store/permissionStore'
import useAuthStore from '../store/authStore'

export function usePermission(module, action) {
  const { isAuthenticated } = useAuthStore()
  const { can, load, permissions } = usePermissionStore()

  // Trigger load if authenticated and permissions not yet fetched
  useEffect(() => {
    if (isAuthenticated && permissions === null) {
      load()
    }
  }, [isAuthenticated, permissions, load])

  return can(module, action)
}

/**
 * usePermissions(module)
 *
 * Returns the full action map for a module.
 * Useful when you need to check multiple actions in one component.
 *
 * Example:
 *   const perms = usePermissions('transfers')
 *   perms.approve  // true | false
 *   perms.create   // true | false
 */
export function usePermissions(module) {
  const { isAuthenticated } = useAuthStore()
  const { permissions, load } = usePermissionStore()

  useEffect(() => {
    if (isAuthenticated && permissions === null) {
      load()
    }
  }, [isAuthenticated, permissions, load])

  return permissions?.[module] || {}
}

export default usePermission
