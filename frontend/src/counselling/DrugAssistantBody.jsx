/**
 * DrugAssistantBody — the staff drug assistant for one item (Project 4, doc 34). Display only: the
 * server decides everything (safety flags, verified vs unverified alternatives, which guidance this
 * user may see). Order is fixed and safety comes first:
 *   block banner → safety flags → what it is → molecules → verified alternatives (add) →
 *   unverified suggestions (amber, NO add) → how to use (approved; drafts only for pharmacists)
 * Used by the POS F7 panel (desktop + mobile sheet), Ctrl+K, /m/items and the product page.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { counsellingApi } from '../api/client'
import { Badge, Icon } from '../pos/design'
import { AltCard } from '../pos/search/PosAlternatives'
import useBranchNames from '../pos/search/useBranchNames'
import GuidanceBlock from './GuidanceBlock'

const SEV = { block: 'bg-red-50 border-red-200 text-red-800', warn: 'bg-amber-50 border-amber-200 text-amber-800',
              info: 'bg-sky-50 border-sky-200 text-sky-800' }

export function useAssistant(itemId, branchId, enabled = true) {
  return useQuery({
    queryKey: ['drug-assistant', itemId, branchId || null],
    queryFn: () => counsellingApi.assistant(itemId, branchId).then(r => r.data),
    enabled: !!itemId && enabled,
    staleTime: 60_000,
    retry: false,
  })
}

function Section({ title, children, tone = '' }) {
  return (
    <section className={tone}>
      <div className="text-[11px] font-semibold text-gray-500 mb-1">{title}</div>
      {children}
    </section>
  )
}

export default function DrugAssistantBody({ itemId, branchId, onPick, data: given }) {
  const nameOf = useBranchNames()
  const q = useAssistant(itemId, branchId, !given)
  const data = given || q.data
  if (!data) {
    if (q.isError) return <div className="text-center text-sm text-red-600 py-4">تعذّر تحميل معلومات الصنف</div>
    return <div className="text-center text-sm text-gray-400 py-6">جارٍ التحميل…</div>
  }
  const { identity: idn, guidance: g } = data
  const alts = data.alternatives || {}
  const verifiedRows = [...(alts.same || []), ...(alts.other || [])]

  return (
    <div className="space-y-3" data-tour="drug-assistant-panel">
      {data.blocked && (
        <div className="rounded-lg border border-red-300 bg-red-50 text-red-800 p-3 text-sm font-semibold flex gap-2">
          <Icon name="alert" size={16} /> ممنوع البيع — {data.safety.filter(f => f.severity === 'block').map(f => f.label_ar).join('، ')}
        </div>
      )}
      {data.safety.filter(f => f.severity !== 'block').length > 0 && (
        <div className="flex flex-wrap gap-1">
          {data.safety.filter(f => f.severity !== 'block').map(f => (
            <span key={f.code} className={`text-xs rounded-full border px-2 py-0.5 ${SEV[f.severity]}`}>{f.label_ar}</span>
          ))}
        </div>
      )}

      <Section title="الصنف">
        <div className="text-sm font-semibold text-gray-900">{idn.name}</div>
        <div className="text-xs text-gray-600 flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
          {idn.form && <span>{idn.form}</span>}
          {idn.indication && <span>يستخدم في: {idn.indication}</span>}
          {idn.requires_fridge && <span className="text-sky-700">❄ ثلاجة</span>}
        </div>
      </Section>

      {data.molecules.length > 0 && (
        <Section title="المادة الفعّالة">
          <div className="flex flex-wrap gap-1">
            {data.molecules.map((m, i) => (
              <span key={i} className={`text-xs rounded border px-1.5 py-0.5 ${m.verified ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
                {m.molecule}{m.strength ? ` ${m.strength}` : ''}{m.verified ? '' : ' · غير موثّق'}
              </span>
            ))}
          </div>
        </Section>
      )}

      <Section title={`بدائل مؤكدة (${verifiedRows.length})`}>
        {verifiedRows.length > 0
          ? <div className="space-y-1.5">
              <Badge tone="warn" icon="alert" label="يتطلب تأكيد الصيدلي" className="w-full justify-center" />
              {verifiedRows.map(r => <AltCard key={r.item_id} it={r} hereBranchId={branchId} nameOf={nameOf} onPick={onPick} />)}
            </div>
          : <div className="text-xs text-gray-400">{alts.verified ? 'لا توجد بدائل معتمدة' : 'بيانات المادة الفعّالة غير معتمدة لهذا الصنف'}</div>}
      </Section>

      {data.suggestions.length > 0 && (
        <Section title="اقتراحات غير موثّقة — تأكد من العبوة والتركيز"
                 tone="rounded-lg border border-amber-200 bg-amber-50/60 p-2">
          <div className="space-y-1.5" data-tour="drug-assistant-unverified">
            {data.suggestions.map(r => <AltCard key={r.item_id} it={r} hereBranchId={branchId} nameOf={nameOf} />)}
          </div>
          <a href={`/composition?item=${data.item_id}`} target="_blank" rel="noopener noreferrer"
             className="inline-block mt-1.5 text-xs text-amber-800 underline">أبلغ عن خطأ / أكّد التطابق</a>
        </Section>
      )}

      <Section title="طريقة الاستخدام">
        {g.status === 'approved' && <GuidanceBlock content={g.content} />}
        {g.draft && (
          <div className="rounded-lg border border-dashed border-amber-300 p-2 mt-1">
            <Badge tone="warn" label={g.draft.source === 'ai_draft' ? 'مسودة آلية غير معتمدة' : 'مسودة غير معتمدة'} />
            <GuidanceBlock content={g.draft} compact />
          </div>
        )}
        {g.status === 'none' && <div className="text-xs text-gray-400">لا يوجد إرشاد معتمد بعد</div>}
        {g.can_edit && (
          <Link to={g.content_id ? `/counselling?open=${g.content_id}` : `/counselling?item=${data.item_id}`}
                className="inline-block mt-1.5 text-xs text-brand-700 underline" data-tour="drug-assistant-edit">
            {g.content_id ? 'فتح الإرشاد' : 'اقترح محتوى'}
          </Link>
        )}
      </Section>
    </div>
  )
}
