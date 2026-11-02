/**
 * NetworkBadge — «من أين أتصل؟»: a small pill in the header saying where this session
 * reaches the system from (security N1, log only — it never blocks anything).
 *
 *   🏢 داخل الشبكة — فرع …     internal, on a listed network
 *   🏢 شبكة داخلية غير مسجلة    internal, address not on the list
 *   🌐 خارج الشبكة             external
 *
 * One call to /access/whoami/ on load and again when the window regains focus. No popup.
 */
import { useQuery } from '@tanstack/react-query'
import { accessApi } from '../api/client'

export function networkBadgeParts(info) {
  if (!info) return null
  if (info.zone !== 'internal') return { icon: '🌐', text: 'خارج الشبكة', tone: 'ext' }
  const site = info.site
  if (site) {
    const where = site.branch_label || site.name
    return { icon: '🏢', text: `داخل الشبكة — ${where}`, tone: 'in' }
  }
  return { icon: '🏢', text: 'شبكة داخلية غير مسجلة', tone: 'unlisted' }
}

const TONE = {
  in: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  unlisted: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30',
  ext: 'bg-surface-2 text-muted border-line',
}

export default function NetworkBadge({ variant = 'desktop' }) {
  const { data } = useQuery({
    queryKey: ['access-whoami'],
    queryFn: () => accessApi.whoami().then(r => r.data),
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  })
  const p = networkBadgeParts(data)
  if (!p) return null
  const title = `${p.text}${data?.ip ? ` · ${data.ip}` : ''}`
  if (variant === 'mobile') {
    return (
      <span data-tour="shell-network-badge" title={title} aria-label={title}
            className="w-9 h-9 flex items-center justify-center rounded-lg bg-white/15 text-base leading-none">
        {p.icon}
      </span>
    )
  }
  return (
    <span data-tour="shell-network-badge" title={title}
          className={`hidden md:inline-flex items-center gap-1 text-xs border rounded-full px-2.5 py-1 whitespace-nowrap ${TONE[p.tone]}`}>
      <span>{p.icon}</span>
      <span>{p.text}</span>
    </span>
  )
}
