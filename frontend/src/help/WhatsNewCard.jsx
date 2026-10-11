/**
 * WhatsNewCard — «🆕 الجديد في الشرح هذا الأسبوع» on the home page (desktop /dashboard,
 * mobile «لوحتي»). Screens whose help or tour changed in the last 7 days that matter to
 * this person (their role's path + screens whose help they used). Read state is on the
 * server (/api/help/whats-new/): opening that screen's help after the change, or
 * «تمام، شفتها». Hidden when nothing is unread — calm, no popup.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { helpApi } from '../api/client'
import { pick } from './text'

export default function WhatsNewCard({ mobile = false }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['help', 'whats-new'],
    queryFn: () => helpApi.whatsNew().then((r) => r.data),
    staleTime: 60_000,
  })
  if (!data?.unread) return null
  const items = data.items.filter((x) => !x.read).slice(0, mobile ? 4 : 6)
  const seen = async () => { await helpApi.whatsNewSeen(); qc.invalidateQueries({ queryKey: ['help', 'whats-new'] }) }
  const open = (it) => {
    const route = it.routes.find((r) => !r.includes(':') && (mobile ? r.startsWith('/m/') : !r.startsWith('/m/')))
      || it.routes.find((r) => !r.includes(':'))
    if (!route) { navigate(`/help?tab=browse&screen=${it.key}`); return }
    navigate(route)
    // open that screen's help so the person reads what changed (this also marks it read)
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('help:open', { detail: { key: it.key } }))
      qc.invalidateQueries({ queryKey: ['help', 'whats-new'] })
    }, 500)
  }
  return (
    <section data-tour="general-whats-new" dir="rtl"
             className="rounded-2xl border border-amber-200 bg-amber-50/50 p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-sm font-bold text-content flex-1">
          🆕 الجديد في الشرح هذا الأسبوع <span className="text-xs font-normal text-muted">({data.unread})</span>
        </h2>
        <button type="button" onClick={() => navigate('/help?tab=whats_new')} className="text-xs text-brand-600 hover:underline">
          كل الجديد ←
        </button>
        <button type="button" onClick={seen} className="text-xs text-faint hover:text-content">تمام، شفتها ✓</button>
      </div>
      <div className={`grid gap-2 ${mobile ? 'grid-cols-1' : 'sm:grid-cols-2 lg:grid-cols-3'}`}>
        {items.map((it) => (
          <button key={it.key} type="button" onClick={() => open(it)}
                  className="text-start rounded-lg border border-line bg-surface px-3 py-2 hover:border-brand-300 flex items-center gap-2">
            <span className="text-lg">{it.icon}</span>
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-semibold text-content truncate">{pick(it.title, 'ar')}</span>
              {it.change_note
                ? <span className="block text-[11px] text-amber-800 truncate">اتحدّث: «{pick(it.change_note, 'ar')}»</span>
                : <span className="block text-[11px] text-faint">{pick(it.module_title, 'ar')} · اتحدّث <span className="tabnum">{it.updated}</span></span>}
            </span>
            <span className="text-[11px] font-semibold text-brand-700 shrink-0">اقرأ ←</span>
          </button>
        ))}
      </div>
    </section>
  )
}
