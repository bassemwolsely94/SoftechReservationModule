/**
 * ZoneBanner — a calm strip under the header that says what the network policy means right now
 * (security N3). Reads whoami.access_zone (not the network `zone`), whoami.policy_mode and
 * whoami.zone_access (this role's row in that zone), so it never claims more than is enforced:
 *   Z2 + enforce + read_only  «جهاز غير معتمد — للعرض فقط»          amber
 *   Z2 otherwise              «جهاز غير معتمد — اطلب اعتماده من المدير»  neutral
 *   Z3 / Z4                   «خارج شبكة الشركة»                     neutral info
 * N4: in enforce mode, whoami.softech_access adds a second line when SOFTECH is read-only («read»)
 * or unavailable («none») from this place. Same strip, no modal.
 * Nothing for Z1 or when signed out. No popup, no button: it only informs.
 */
import { useQuery } from '@tanstack/react-query'
import { accessApi } from '../api/client'

export function softechLine(info) {
  if (info?.softech_gate_mode !== 'enforce') return null
  if (info?.softech_access === 'read') return 'SOFTECH للعرض فقط من هذا المكان'
  if (info?.softech_access === 'none') return 'SOFTECH غير متاح من هذا المكان'
  return null
}

export function zoneBannerParts(info) {
  const z = info?.access_zone
  if (z === 'Z2') {
    if (info?.policy_mode === 'enforce' && info?.zone_access === 'read_only') {
      return { tone: 'warn', text: 'جهاز غير معتمد — للعرض فقط' }
    }
    return { tone: 'info', text: 'جهاز غير معتمد — اطلب اعتماده من المدير' }
  }
  if (z === 'Z3' || z === 'Z4') return { tone: 'info', text: 'خارج شبكة الشركة' }
  return null
}

const TONE = {
  warn: 'bg-amber-500/10 text-amber-800 dark:text-amber-200 border-amber-500/30',
  info: 'bg-surface-2 text-muted border-line',
}

export default function ZoneBanner() {
  const { data } = useQuery({
    queryKey: ['access-whoami'],
    queryFn: () => accessApi.whoami().then(r => r.data),
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  })
  const base = zoneBannerParts(data)
  const sf = softechLine(data)
  if (!base && !sf) return null
  const p = base || { tone: 'warn', text: sf }
  return (
    <div data-tour="shell-zone-banner" role="status"
         className={`shrink-0 border-b px-6 py-1.5 text-xs text-center ${TONE[p.tone]}`}>
      {p.text}
      {base && sf ? <span className="mx-2">·</span> : null}
      {base && sf ? sf : null}
    </div>
  )
}
