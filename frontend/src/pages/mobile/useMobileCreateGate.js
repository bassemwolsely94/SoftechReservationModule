/**
 * useMobileCreateGate(module, legacyRoles) — 'loading' | 'allowed' | 'denied' for a phone create
 * screen (UAT W8). See createGateState in mobileWriteGates.js.
 */
import { useEffect } from 'react'
import usePermissionStore from '../../store/permissionStore'
import useAuthStore from '../../store/authStore'
import { createGateState } from './mobileWriteGates'

export default function useMobileCreateGate(module, legacyRoles) {
  const { isAuthenticated, user } = useAuthStore()
  const { permissions, seeded, load } = usePermissionStore()
  useEffect(() => {
    if (isAuthenticated && permissions === null) load()
  }, [isAuthenticated, permissions, load])
  return createGateState({ role: user?.role || 'viewer', perms: permissions, seeded }, module, legacyRoles)
}
