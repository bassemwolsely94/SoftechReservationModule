/**
 * GlossaryApply — «📖 طبّق القاموس» in the screen help editor. Asks the server where the
 * draft uses words the glossary says to avoid (POST /api/help/glossary/scan/ — same
 * matching as the «💡» hints), then lists each one in its sentence: «استبدل» changes
 * that word in the draft, «تخطّى» leaves it. Inline, no popup; nothing is saved until
 * the trainer presses «حفظ», so the normal history applies.
 */
import { useState } from 'react'
import { helpApi } from '../api/client'
import { acceptAll as allEdits, acceptOne, skipOne } from './glossaryEdits'

const FIELD = {
  title: 'العنوان', summary: 'دور الشاشة', audience: 'من يستخدمها', steps: 'خطوة', tips: 'ملاحظة',
  tabs: 'تبويب', faq: 'سؤال متكرر', notes: 'ملاحظات المدرب', tour: 'جولة «اعرض لي» — خطوة',
}
const where = (path) => {
  const [f, i, sub] = path
  const n = typeof i === 'number' ? ` ${i + 1}` : ''
  const part = sub === 'q' ? ' (السؤال)' : sub === 'a' ? ' (الإجابة)' : sub === 'title' ? ' (العنوان)' : ''
  return `${FIELD[f] || f}${n}${part}`
}
export default function GlossaryApply({ screenKey, draft, setDraft }) {
  const [items, setItems] = useState(null)      // null = closed
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const scan = async () => {
    setBusy(true); setErr(null)
    try {
      const { data } = await helpApi.scanGlossary(screenKey, draft)
      setItems(data.items.map((it) => ({ ...it, state: 'open' })))
    } catch (e) {
      setErr(e?.response?.data?.detail || 'تعذّر الفحص')
    } finally { setBusy(false) }
  }

  const apply = ({ draft: d, items: next }) => { setDraft(d); setItems(next) }
  const accept = (idx) => apply(acceptOne(draft, items, idx))
  const skip = (idx) => setItems(skipOne(items, idx))
  const acceptAll = () => apply(allEdits(draft, items))

  if (items === null) {
    return (
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy} onClick={scan} data-tour="general-help-glossary-apply"
                className="text-xs border border-line rounded-lg px-3 py-1 hover:bg-surface-2 disabled:opacity-50">
          📖 طبّق القاموس
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    )
  }
  const open = items.filter((x) => x.state === 'open').length
  const done = items.filter((x) => x.state === 'done').length
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50/40 p-3 space-y-2" dir="rtl">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-bold text-content flex-1">📖 القاموس — {items.length ? `${items.length} كلمة` : 'الشرح ماشي على القاموس ✓'}</span>
        {open > 1 && <button type="button" onClick={acceptAll} className="text-brand-700 font-semibold hover:underline">استبدل الباقي ({open})</button>}
        <button type="button" disabled={busy} onClick={scan} className="text-brand-600 hover:underline">افحص تاني</button>
        <button type="button" onClick={() => setItems(null)} className="text-faint hover:text-content">إغلاق ✕</button>
      </div>
      <div className="divide-y divide-line max-h-80 overflow-y-auto">
        {items.map((it, i) => (
          <div key={i} className={`py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm ${it.state !== 'open' ? 'opacity-60' : ''}`}>
            <span className="text-[11px] text-faint w-32 shrink-0">{where(it.path)}</span>
            <span className="flex-1 min-w-[220px] text-content leading-6">
              {it.before}<mark className="bg-amber-200 rounded px-0.5">{it.match}</mark>{it.after}
              <span className="text-muted"> ← </span><b className="text-emerald-700">{it.replacement}</b>
              {it.why && <span className="block text-[11px] text-faint">{it.why}</span>}
            </span>
            {it.state === 'open' ? (
              <span className="flex gap-2 text-xs">
                <button type="button" onClick={() => accept(i)} className="bg-brand-600 text-white rounded px-2 py-0.5">استبدل</button>
                <button type="button" onClick={() => skip(i)} className="border border-line rounded px-2 py-0.5">تخطّى</button>
              </span>
            ) : (
              <span className="text-[11px] text-muted">
                {it.state === 'done' ? '✓ اتغيّرت' : it.state === 'skipped' ? 'اتسابت' : 'النص اتغيّر — «افحص تاني»'}
              </span>
            )}
          </div>
        ))}
      </div>
      {done > 0 && <div className="text-[11px] text-emerald-700">اتغيّر {done} في المسودة — هتتحفظ لما تضغط «حفظ» (وتقدر تكتب السبب في «سبب التعديل»).</div>}
    </div>
  )
}
