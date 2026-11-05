import { Navigate } from 'react-router-dom'
import useAuthStore from '../store/authStore'

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

export function RequireRole({ roles, children }) {
  const { user } = useAuthStore()
  const userRole = user?.role || 'viewer'
  if (!roles.includes(userRole)) return <Navigate to="/dashboard" replace />
  return children
}
