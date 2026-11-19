import { Navigate } from 'react-router-dom'
import useAuthStore from '../store/authStore'
import usePermissionStore from '../store/permissionStore'

// Route guards. They only steer the browser: every API checks the role itself (server-side
// permissions), so a guard bypassed in the browser still meets a 403.

export function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuthStore()
  if (isLoading) return (
    <div className="min-h-screen flex items-center justify-center bg-brand-50">
      <div className="text-brand-600 text-xl font-cairo font-semibold animate-pulse">
        صيدليات الرزيقي...
      </div>
    </div>
  )
  return isAuthenticated ? children : <Navigate to="/login" replace />
}

// `module` (optional, with `action`, default 'view') also asks the role matrix — the same
// grant the screen's API checks. Both must allow: the role list still decides who the screen
// is for, the matrix takes it away when an admin removes the grant (UAT D5). Admin passes;
// while the matrix is still loading nothing renders (no redirect, no flash of the page).
// `cap` (optional) names a user capability flag from /auth/me that admits the user on its own —
// a grant the server gives outside the matrix (e.g. can_stock_audit: named branch managers
// review daily counts on /stock-count), as navGroups' `cap`.
export function RequireRole({ roles, module, action = 'view', cap, children }) {
  const { user } = useAuthStore()
  const perms = usePermissionStore(s => s.permissions)
  const userRole = user?.role || 'viewer'
  if (cap && user?.[cap]) return children
  if (roles && !roles.includes(userRole)) return <Navigate to="/dashboard" replace />   // no list = the matrix alone decides
  if (module && userRole !== 'admin') {
    if (perms === null) return null
    if (!perms[module]?.[action]) return <Navigate to="/dashboard" replace />
  }
  return children
}
