/**
 * Glossary — «📖 قاموس المصطلحات» in «للمدربين»: the agreed word for each thing and the
 * words to avoid («الكاشير» مش «الخزنة»), optionally only in some modules («طلب» is
 * wrong for a reservation, right for a purchase request). The note hints (NoteHints)
 * then point out an avoided word in a «إيه الجديد» note and in the help text being
 * edited. Each row shows how many screens still use an avoided word — click to open
 * one in the editor. Edits are inline; every change is kept in the history.
 * Data: /api/help/glossary/ (writes need help/edit — checked on the server).
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick } from './text'

const empty = { preferred: '', avoid: '', modules: [], why: '' }
const input = 'text-sm border border-line rounded-lg px-2 py-1 bg-surface text-content'

export default function Glossary({ index, go }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['help', 'glossary'], queryFn: () => helpApi.glossary().then((r) => r.data) })
  const [editing, setEditing] = useState(null)        // term id, 'new', or null
  const [form, setForm] = useState(empty)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmDel, setConfirmDel] = useState(null)
  const titles = Object.fromEntries((index.screens || []).map((s) => [s.key, s.title]))
  const modTitle = Object.fromEntries((index.modules || []).map((m) => [m.key, m.title]))

  const start = (t) => {
    setErr(null)
    setEditing(t ? t.id : 'new')
    setForm(t ? { preferred: t.preferred, avoid: t.avoid.join('، '), modules: t.modules, why: t.why } : empty)
  }
  const run = async (fn) => {
    setBusy(true); setErr(null)
    try {
      await fn()
      qc.invalidateQueries({ queryKey: ['help', 'glossary'] })
      setEditing(null); setConfirmDel(null)
    } catch (e) {
      const d = e?.response?.data
      setErr([d?.detail, ...(d?.errors || [])].filter(Boolean).join(' — ') || 'تعذّر الحفظ')
    } finally { setBusy(false) }
  }
  const save = () => run(() => (editing === 'new' ? helpApi.addTerm(form) : helpApi.saveTerm(editing, form)))
  const toggleMod = (k) => setForm((f) => ({ ...f, modules: f.modules.includes(k) ? f.modules.filter((m) => m !== k) : [...f.modules, k] }))

  const Form = (
    <div className="rounded-lg border border-brand-200 bg-brand-50/40 p-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        <input value={form.preferred} onChange={(e) => setForm({ ...form, preferred: e.target.value })} maxLength={60}
               placeholder="الكلمة المعتمدة (مثلاً: الكاشير)" className={`${input} w-48`} />
        <input value={form.avoid} onChange={(e) => setForm({ ...form, avoid: e.target.value })}
               placeholder="نتجنّب (افصل بفاصلة): الخزنة، الخزينة" className={`${input} flex-1 min-w-[200px]`} />
      </div>
      <input value={form.why} onChange={(e) => setForm({ ...form, why: e.target.value })} maxLength={200}
             placeholder="ليه؟ (اختياري) — مثلاً: ده اسم الشاشة في القائمة" className={`${input} w-full`} />
      <details className="text-xs text-muted">
        <summary className="cursor-pointer">
          في موديولات معيّنة بس؟ {form.modules.length ? `(${form.modules.length})` : '— لأ، في كل النظام'}
        </summary>
        <div className="mt-1 flex flex-wrap gap-1">
          {(index.modules || []).map((m) => (
            <button key={m.key} type="button" onClick={() => toggleMod(m.key)}
                    className={`px-2 py-0.5 rounded border ${form.modules.includes(m.key) ? 'bg-brand-600 text-white border-brand-600' : 'border-line'}`}>
              {m.icon} {pick(m.title, 'ar')}
            </button>
          ))}
        </div>
      </details>
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy} onClick={save} className="text-sm bg-brand-600 text-white rounded-lg px-4 py-1 disabled:opacity-50">حفظ</button>
        <button type="button" onClick={() => setEditing(null)} className="text-sm border border-line rounded-lg px-3 py-1">إلغاء</button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
  )

  return (
    <div className="rounded-xl border border-line bg-surface p-4 space-y-2" dir="rtl" data-tour="general-help-glossary">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-bold text-content flex-1">📖 قاموس المصطلحات</h3>
        {data?.can_edit && editing !== 'new' && (
          <button type="button" onClick={() => start(null)} className="text-xs text-brand-600 hover:underline">+ مصطلح</button>
        )}
      </div>
      <p className="text-xs text-faint">كلمة واحدة معتمدة لكل حاجة. وإنت بتكتب الشرح أو سطر «إيه الجديد» هيظهر «💡» لو استخدمت كلمة من «نتجنّب».</p>
      {editing === 'new' && Form}
      {data && data.terms.length === 0 && editing !== 'new' && <div className="text-sm text-faint">القاموس فاضي — ابدأ بأكتر كلمتين بيحصل فيهم لخبطة.</div>}
      <div className="divide-y divide-line">
        {(data?.terms || []).map((t) => (editing === t.id ? <div key={t.id} className="py-2">{Form}</div> : (
          <div key={t.id} className="py-2 flex flex-wrap items-start gap-x-3 gap-y-1 text-sm">
            <div className="flex-1 min-w-[220px]">
              <span className="font-bold text-emerald-700">✓ {t.preferred}</span>
              <span className="text-muted"> — مش </span>
              {t.avoid.map((a) => <span key={a} className="text-red-700 line-through decoration-red-300 me-1.5">{a}</span>)}
              {t.modules.length > 0 && (
                <span className="text-[11px] text-faint"> · في: {t.modules.map((m) => pick(modTitle[m], 'ar') || m).join('، ')}</span>
              )}
              {t.why && <div className="text-[11px] text-faint">{t.why}</div>}
              {t.uses?.count > 0 && (
                <div className="text-[11px] text-amber-800">
                  لسه مستخدمة في {t.uses.count} شاشة:{' '}
                  {t.uses.screens.map((k, i) => (
                    <button key={k} type="button" onClick={() => go({ tab: 'browse', screen: k, edit: '1' })} className="underline">
                      {pick(titles[k], 'ar') || k}{i < t.uses.screens.length - 1 ? '، ' : ''}
                    </button>
                  ))}{t.uses.count > t.uses.screens.length ? ' …' : ''}
                </div>
              )}
            </div>
            {data.can_edit && (
              <div className="flex gap-2 text-xs">
                <button type="button" onClick={() => start(t)} className="text-brand-600 hover:underline">تعديل</button>
                {confirmDel === t.id
                  ? <button type="button" disabled={busy} onClick={() => run(() => helpApi.deleteTerm(t.id))} className="text-red-600 font-semibold">متأكد؟ احذف</button>
                  : <button type="button" onClick={() => setConfirmDel(t.id)} className="text-faint hover:text-red-600">حذف</button>}
              </div>
            )}
          </div>
        )))}
      </div>
    </div>
  )
}
