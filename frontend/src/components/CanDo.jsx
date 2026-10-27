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
  return allowed ? children : fallback
}
