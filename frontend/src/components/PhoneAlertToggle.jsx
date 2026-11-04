/**
 * PhoneAlertToggle — the per-record «نبّه على الموبايل» checkbox on the reservation / transfer /
 * task forms. The server decides the mode (GET phone-alerts/modes/, open to every signed-in user):
 *   hidden   -> nothing is shown
 *   always   -> locked on
 *   optional -> a normal checkbox
 * Nothing renders until the mode is loaded, and it stays hidden if the fetch fails (fail closed);
 * the server coerces the stored value anyway.
 *
 *   <PhoneAlertToggle kind="reservation" value onChange />     kind: reservation | transfer | task
 */
import { useQuery } from '@tanstack/react-query'
import { phoneAlertsApi } from '../api/client'

export default function PhoneAlertToggle({ kind, value, onChange, className = '' }) {
  const { data: modes } = useQuery({
    queryKey: ['phone-alert-modes'],
    queryFn: () => phoneAlertsApi.modes().then(r => r.data),
    staleTime: 300_000,
    retry: false,
  })

  const mode = modes?.[kind]
  if (mode !== 'optional' && mode !== 'always') return null
  const locked = mode === 'always'

  return (
    <label
      className={`flex items-center gap-2.5 text-sm text-gray-700 ${locked ? 'cursor-default' : 'cursor-pointer'} ${className}`}>
      <input type="checkbox" className="w-4 h-4 rounded text-brand-600"
        checked={locked ? true : !!value} disabled={locked}
        onChange={e => onChange?.(e.target.checked)} />
      <span>📲 نبّه على الموبايل</span>
      {locked && <span className="text-xs text-gray-400">التنبيه على الموبايل مُفعّل دائماً لهذا النوع</span>}
    </label>
  )
}
