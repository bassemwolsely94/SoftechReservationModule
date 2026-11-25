/**
 * PortalConsentCard — the customer chooses which messages they get from us (backlog P-05).
 * One switch per kind; each tap is saved at once (no modal). The backend owns the rule and records the
 * choice with source 'portal' (apps/portal/views.consent → apps/customers/consent.py).
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { portalApi } from '../../portal/portalApi'

const ITEMS = [
  { key: 'refill', label: 'تذكير بموعد صرف علاجي', hint: 'رسالة واتساب قبل موعد صرف دوائك.' },
  { key: 'marketing', label: 'العروض والخصومات', hint: 'عروض الصيدلية من وقت للتاني.' },
  { key: 'marketing_health', label: 'عروض تناسب حالتي الصحية', hint: 'عروض مرتبطة بأدويتك المزمنة.' },
  { key: 'service', label: 'رسائل الخدمة', hint: 'طلبك جاهز، أو الصنف اللي طلبته توفّر.' },
]

export default function PortalConsentCard() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['portal-consent'], queryFn: () => portalApi.consent().then(r => r.data) })
  const save = useMutation({
    mutationFn: ({ key, granted }) => portalApi.setConsent(key, granted).then(r => r.data),
    onSuccess: (d) => qc.setQueryData(['portal-consent'], d),
  })
  if (!data) return null
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3">
      <div className="font-bold text-gray-900">الرسائل اللي توصلك منّا</div>
      {ITEMS.map(({ key, label, hint }) => {
        const p = data.purposes?.[key] || {}
        const on = key === 'service' ? p.granted !== false : p.granted === true
        return (
          <label key={key} className="flex items-start justify-between gap-3">
            <span>
              <span className="block text-sm text-gray-800">{label}</span>
              <span className="block text-xs text-gray-400">{hint}</span>
            </span>
            <input type="checkbox" className="mt-1 h-5 w-5" checked={on} disabled={save.isPending}
                   onChange={() => save.mutate({ key, granted: !on })} />
          </label>
        )
      })}
      {save.isError && <div className="text-xs text-red-600">تعذّر الحفظ — حاول مرة أخرى.</div>}
      <div className="text-[11px] text-gray-400">ممكن تغيّر اختيارك في أي وقت، أو ترد «إيقاف» على أي رسالة واتساب.</div>
    </div>
  )
}
