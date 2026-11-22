/**
 * GlossaryAudit — «📖 طبّق القاموس على الكل» in the glossary box («للمدربين»): checks the
 * whole current help — every screen, workflow tour and quiz — for words the glossary says
 * to avoid (GET /api/help/glossary/audit/, same matching as the hints and the editors),
 * and lists each item with its words and a sample sentence. Nothing is replaced here:
 * «افتح وطبّق ←» opens that item's editor, where «📖 طبّق القاموس» does it word by word.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick } from './text'

const KINDS = [['', 'الكل'], ['screen', 'شاشات'], ['flow', 'جولات'], ['quiz', 'اختبارات']]
const KIND_LABEL = { screen: '📄 شاشة', flow: '🧭 جولة', quiz: '📝 اختبار' }

export default function GlossaryAudit({ go }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('')
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['help', 'glossary-audit'],
    queryFn: () => helpApi.glossaryAudit().then((r) => r.data),
    enabled: open,
    staleTime: 0,
  })
  const openItem = (it) => (it.kind === 'screen'
    ? go({ tab: 'browse', screen: it.key, edit: '1' })
    : go({ tab: 'trainers', tkind: it.kind, tkey: it.key }))

  if (!open) {
    return (
      <button data-tour="general-help-glossary-audit" type="button" onClick={() => setOpen(true)}
              className="text-xs border border-line rounded-lg px-3 py-1 hover:bg-surface-2">
        📖 طبّق القاموس على الكل
      </button>
    )
  }
  const items = (data?.items || []).filter((it) => !kind || it.kind === kind)
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50/40 p-3 space-y-2" dir="rtl">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-bold text-content flex-1">
          📖 القاموس على كل الشرح — {isFetching ? '…جارٍ الفحص'
            : data ? (data.total ? `${data.total} كلمة في ${data.items.length} مكان` : 'كل الشرح ماشي على القاموس ✓') : ''}
        </span>
        <div className="flex border border-line rounded-lg overflow-hidden">
          {KINDS.map(([k, t]) => (
            <button key={k} type="button" onClick={() => setKind(k)}
                    className={`px-2 py-0.5 ${kind === k ? 'bg-brand-600 text-white' : 'text-muted hover:bg-surface-3'}`}>{t}</button>
          ))}
        </div>
        <button type="button" disabled={isFetching} onClick={() => refetch()} className="text-brand-600 hover:underline">افحص تاني</button>
        <button type="button" onClick={() => setOpen(false)} className="text-faint hover:text-content">إغلاق ✕</button>
      </div>
      {isError && <div className="text-xs text-red-600">{error?.response?.data?.detail || 'تعذّر الفحص'}</div>}
      {data && data.terms === 0 && <div className="text-xs text-faint">القاموس فاضي — ضيف مصطلح الأول.</div>}
      <div className="divide-y divide-line max-h-96 overflow-y-auto">
        {items.map((it) => (
          <div key={`${it.kind}:${it.key}`} className="py-2 flex flex-wrap items-start gap-x-3 gap-y-1 text-sm">
            <span className="text-[11px] text-muted w-16 shrink-0">{KIND_LABEL[it.kind]}</span>
            <div className="flex-1 min-w-[220px] space-y-0.5">
              <div className="font-semibold text-content">{pick(it.title, 'ar')} <span className="text-[11px] font-normal text-faint tabnum">({it.count})</span></div>
              <div className="flex flex-wrap gap-1 text-[11px]">
                {it.words.map((w) => (
                  <span key={`${w.avoid}-${w.preferred}`} className="rounded border border-amber-200 bg-amber-50 text-amber-800 px-1.5">
                    «{w.avoid}» ×{w.n} ← «{w.preferred}»
                  </span>
                ))}
              </div>
              {it.samples[0] && (
                <div className="text-[12px] text-muted leading-6">
                  {it.samples[0].before}<mark className="bg-amber-200 rounded px-0.5">{it.samples[0].match}</mark>{it.samples[0].after}
                </div>
              )}
            </div>
            <button type="button" onClick={() => openItem(it)} className="text-xs text-brand-700 font-semibold hover:underline shrink-0">
              افتح وطبّق ←
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
