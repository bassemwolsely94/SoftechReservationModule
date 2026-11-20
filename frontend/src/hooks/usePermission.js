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
import { moduleActionAllowed } from '../components/navGroups'

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

/**
 * usePermissionAny(module, actions)
 *
 * True when the role holds ANY of `actions` on `module` — for screens whose API accepts
 * several grants, e.g. call-center case writes take create, edit or approve
 * (apps/callcenter/views.py CALLCENTER). Fail-closed while permissions load.
 *
 *   const canWrite = usePermissionAny('callcenter', ['create', 'edit', 'approve'])
 */
export function usePermissionAny(module, actions) {
  const map = usePermissions(module)
  return actions.some(a => !!map[a])
}

/**
 * useModuleAction(module, actions, legacyRoles?)
 *
 * usePermissionAny plus the unseeded fallback: on a module with no matrix rows (the server fails
 * open for the legacy roles) it answers by `legacyRoles`, the screen's role list from before the
 * role review — so a write control a view-only role would only get a 403 from is hidden, while an
 * unseeded database keeps today's controls (final review I4 / C1).
 *
 *   const canEdit = useModuleAction('code_maps', 'edit', ['admin'])
 */
export function useModuleAction(module, actions, legacyRoles) {
  const { isAuthenticated, user } = useAuthStore()
  const { permissions, seeded, load } = usePermissionStore()
  useEffect(() => {
    if (isAuthenticated && permissions === null) load()
  }, [isAuthenticated, permissions, load])
  return moduleActionAllowed({ role: user?.role || 'viewer', perms: permissions, seeded }, module, actions, legacyRoles)
}

export default usePermission
