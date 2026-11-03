/**
 * PhoneAlertToggle — the per-record «نبّه على الموبايل» checkbox on the reservation / transfer /
 * task forms. The server coerces the stored value by the alert policy; this only reflects it:
 *   • every event «never»  -> nothing is shown
 *   • any event «always»   -> locked on («يصل التنبيه دائماً»)
 *   • otherwise            -> a normal checkbox
 *
 *   <PhoneAlertToggle event={['reservation_sourcing','reservation_status_urgent']} value onChange />
 *
 * `event` is one key or the list of every event the record can raise (the same list the server uses).
 * Policies are fetched once (['phone-alert-policies']). That endpoint is admin/supervisor only, so
 * for other roles the fetch fails and the checkbox simply shows as optional — the server still
 * decides (it ignores the tick for «never» and always alerts for «always»).
 */
import { useQuery } from '@tanstack/react-query'
import { phoneAlertsApi } from '../api/client'

/** Every event a record type can raise — must match phone_alert_events on the server serializers. */
export const PHONE_ALERT_EVENTS = {
  reservation: ['reservation_sourcing', 'reservation_status_urgent'],
  transfer:    ['transfer_hq_submitted', 'transfer_status'],
  task:        ['task_assigned', 'task_status'],
}

export default function PhoneAlertToggle({ event, value, onChange, className = '' }) {
  const events = Array.isArray(event) ? event : [event]
  const { data: policies } = useQuery({
    queryKey: ['phone-alert-policies'],
    queryFn: () => phoneAlertsApi.policies().then(r => r.data),
    staleTime: 300_000,
    retry: false,
  })

  let modes = events.map(() => 'optional')
  if (Array.isArray(policies)) {
    modes = events.map(k => policies.find(p => p.event === k)?.mode || 'never')
  }
  if (modes.every(m => m === 'never')) return null
  const locked = modes.includes('always')

  return (
    <label
      className={`flex items-center gap-2.5 text-sm text-gray-700 ${locked ? 'cursor-default' : 'cursor-pointer'} ${className}`}>
      <input type="checkbox" className="w-4 h-4 rounded text-brand-600"
        checked={locked ? true : !!value} disabled={locked}
        onChange={e => onChange?.(e.target.checked)} />
      <span>📲 نبّه على الموبايل</span>
      {locked && <span className="text-xs text-gray-400">(يصل التنبيه دائماً)</span>}
    </label>
  )
}
