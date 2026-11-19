/**
 * CanDo.jsx
 *
 * Conditionally renders children based on the current user's role permissions.
 *
 * Usage:
 *   <CanDo module="reservations" action="create">
 *     <button>إنشاء حجز</button>
 *   </CanDo>
 *
 *   <CanDo module="transfers" action="approve" fallback={<span>غير مصرح</span>}>
 *     <button>اعتماد</button>
 *   </CanDo>
 *
 * Props:
 *   module   {string}    — module key (e.g. 'reservations', 'transfers')
 *   action   {string}    — action key (e.g. 'create', 'edit', 'approve', 'delete')
 *   fallback {ReactNode} — rendered when denied (default: null = hidden)
 *   children {ReactNode} — rendered when allowed
 */
import { usePermission } from '../hooks/usePermission'

export default function CanDo({ module, action, fallback = null, children }) {
  const allowed = usePermission(module, action)
  if (!allowed) return fallback
  // data-perm lets the role UAT check each visible gated control against the backend matrix;
  // display: contents keeps the wrapper out of layout (no extra box).
  return <span data-perm={`${module}:${action}`} style={{ display: 'contents' }}>{children}</span>
}
