/**
 * HelpEditor — trainers rewrite a screen's help in place (needs help/edit; the
 * server checks it). Same structure as the repo text: Arabic + English for every
 * field. Tabs follow the code, so their list is fixed here — only their wording
 * changes. Every save / revert is kept in the history with who, when and why.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick, itemText } from './text'

const clone = (v) => JSON.parse(JSON.stringify(v ?? null))
const emptyT = () => ({ ar: '', en: '' })

function TField({ value, onChange, rows = 2, required }) {
  const v = value || emptyT()
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
      <textarea dir="rtl" rows={rows} value={v.ar} placeholder={required ? 'عربي (مطلوب)' : 'عربي'}
                onChange={(e) => onChange({ ...v, ar: e.target.value })}
                className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
      <textarea dir="ltr" rows={rows} value={v.en} placeholder="English"
                onChange={(e) => onChange({ ...v, en: e.target.value })}
                className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
    </div>
  )
}

function Field({ title, children }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-bold text-muted">{title}</div>
      {children}
    </div>
  )
}

/** A list of texts (steps / tips). Keeps an item's `roles` if it had one. */
function TList({ items, onChange, addLabel }) {
  const set = (i, t) => onChange(items.map((it, j) => (j !== i ? it : it && it.text ? { ...it, text: t } : t)))
  const move = (i, d) => {
    const j = i + d
    if (j < 0 || j >= items.length) return
    const next = items.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  return (
    <div className="space-y-2">
      {items.map((it, i) => (
        <div key={i} className="flex gap-1.5 items-start">
          <span className="text-[11px] text-faint pt-2 w-4 tabnum">{i + 1}</span>
          <div className="flex-1">
            <TField value={itemText(it)} onChange={(t) => set(i, t)} required />
            {it?.roles && <div className="text-[10px] text-faint mt-0.5">يظهر فقط لـ: {it.roles.join('، ')}</div>}
          </div>
          <div className="flex flex-col gap-0.5">
            <button type="button" onClick={() => move(i, -1)} className="text-xs text-faint hover:text-content">▲</button>
            <button type="button" onClick={() => move(i, 1)} className="text-xs text-faint hover:text-content">▼</button>
            <button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))}
                    className="text-xs text-red-500 hover:text-red-700" title="حذف">✕</button>
          </div>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...items, emptyT()])}
              className="text-xs text-brand-600 hover:underline">+ {addLabel}</button>
    </div>
  )
}

export default function HelpEditor({ data, onDone }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(() => ({
    title: clone(data.title), summary: clone(data.summary),
    audience: clone(data.audience) || emptyT(), notes: clone(data.notes) || emptyT(),
    steps: clone(data.steps) || [], tips: clone(data.tips) || [],
    faq: clone(data.faq) || [], tabs: clone(data.tabs) || [],
  }))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const history = useQuery({
    queryKey: ['help', 'revisions', data.key],
    queryFn: () => helpApi.revisions(data.key).then((r) => r.data),
    enabled: showHistory,
  })

  const up = (k) => (v) => setDraft((d) => ({ ...d, [k]: v }))
  const refresh = (payload) => {
    qc.setQueryData(['help', 'screen', data.key], payload)
    qc.invalidateQueries({ queryKey: ['help'] })
  }

  const save = async () => {
    setBusy(true); setError(null)
    try {
      const { data: payload } = await helpApi.save(data.key, draft, note)
      refresh(payload); onDone && onDone()
    } catch (e) {
      const d = e?.response?.data
      setError(d?.errors?.join(' · ') || d?.detail || 'تعذّر الحفظ')
    } finally { setBusy(false) }
  }

  const revert = async () => {
    if (!window.confirm('الرجوع للشرح الأصلي وحذف تعديلات المدربين لهذه الشاشة؟')) return
    setBusy(true); setError(null)
    try {
      const { data: payload } = await helpApi.revert(data.key, note)
      refresh(payload); onDone && onDone()
    } catch (e) { setError(e?.response?.data?.detail || 'تعذّر الرجوع') } finally { setBusy(false) }
  }

  const base = data.base || {}
  const original = useMemo(() => [
    ['العنوان', pick(base.title, 'ar')], ['دور الشاشة', pick(base.summary, 'ar')],
    ['الخطوات', (base.steps || []).map((s, i) => `${i + 1}. ${pick(itemText(s), 'ar')}`).join('\n')],
  ], [base])

  return (
    <div className="space-y-4" dir="rtl">
      <div className="rounded-lg bg-brand-50 border border-brand-200 px-3 py-2 text-xs text-brand-800 leading-6">
        اكتب بالعربي (مطلوب) والإنجليزي. أسلوب فصيح مبسّط قريب من لغة الفريق. التعديل يظهر لكل المستخدمين فور الحفظ،
        ويُحفظ في السجل مع اسمك والسبب.
      </div>
      {data.override?.base_changed && (
        <div className="rounded-lg bg-amber-50 border border-amber-300 px-3 py-2 text-xs text-amber-900">
          المطوّرون غيّروا الشرح الأصلي بعد آخر تعديل — راجع «النسخة الأصلية» وادمج الجديد قبل الحفظ.
        </div>
      )}

      <div className="flex gap-3 text-xs">
        <button type="button" onClick={() => setShowOriginal((v) => !v)} className="text-brand-600 hover:underline">
          {showOriginal ? 'إخفاء' : 'عرض'} النسخة الأصلية
        </button>
        <button type="button" onClick={() => setShowHistory((v) => !v)} className="text-brand-600 hover:underline">
          {showHistory ? 'إخفاء' : 'عرض'} سجل التعديلات
        </button>
      </div>
      {showOriginal && (
        <div className="rounded-lg border border-line bg-surface-2 p-3 space-y-2 text-xs text-content whitespace-pre-line">
          {original.map(([k, v]) => <div key={k}><b>{k}:</b> {v}</div>)}
        </div>
      )}
      {showHistory && (
        <div className="rounded-lg border border-line p-2 space-y-1 text-xs max-h-48 overflow-y-auto">
          {history.isLoading && <div className="text-faint">…</div>}
          {(history.data || []).length === 0 && !history.isLoading && <div className="text-faint">لا توجد تعديلات سابقة</div>}
          {(history.data || []).map((r) => (
            <div key={r.id} className="flex gap-2">
              <span className="text-faint tabnum">{new Date(r.created_at).toLocaleString('ar-EG-u-nu-latn')}</span>
              <span className="font-semibold">{r.staff || '—'}</span>
              <span>{r.action === 'revert' ? 'رجوع للأصل' : 'تعديل'}</span>
              {r.note && <span className="text-muted">— {r.note}</span>}
            </div>
          ))}
        </div>
      )}

      <Field title="العنوان"><TField value={draft.title} onChange={up('title')} rows={1} required /></Field>
      <Field title="دور الشاشة"><TField value={draft.summary} onChange={up('summary')} rows={3} required /></Field>
      <Field title="من يستخدمها"><TField value={draft.audience} onChange={up('audience')} /></Field>

      {draft.tabs.length > 0 && (
        <Field title="التبويبات (القائمة ثابتة حسب الشاشة — عدّل النص فقط)">
          <div className="space-y-2">
            {draft.tabs.map((t, i) => (
              <div key={t.key} className="rounded-lg border border-line p-2 space-y-1.5">
                <div className="text-[10px] text-faint">{t.key}</div>
                <TField value={t.title} rows={1} required
                        onChange={(v) => up('tabs')(draft.tabs.map((x, j) => (j === i ? { ...x, title: v } : x)))} />
                <TField value={t.body} rows={3} required
                        onChange={(v) => up('tabs')(draft.tabs.map((x, j) => (j === i ? { ...x, body: v } : x)))} />
              </div>
            ))}
          </div>
        </Field>
      )}

      <Field title="طريقة الاستخدام (خطوات)"><TList items={draft.steps} onChange={up('steps')} addLabel="خطوة" /></Field>
      <Field title="ملاحظات مهمة وأخطاء شائعة"><TList items={draft.tips} onChange={up('tips')} addLabel="ملاحظة" /></Field>

      <Field title="أسئلة متكررة">
        <div className="space-y-2">
          {draft.faq.map((f, i) => (
            <div key={i} className="rounded-lg border border-line p-2 space-y-1.5">
              <div className="flex justify-between text-[10px] text-faint">
                <span>سؤال {i + 1}</span>
                <button type="button" className="text-red-500" onClick={() => up('faq')(draft.faq.filter((_, j) => j !== i))}>حذف</button>
              </div>
              <TField value={f.q} rows={1} required onChange={(v) => up('faq')(draft.faq.map((x, j) => (j === i ? { ...x, q: v } : x)))} />
              <TField value={f.a} rows={2} required onChange={(v) => up('faq')(draft.faq.map((x, j) => (j === i ? { ...x, a: v } : x)))} />
            </div>
          ))}
          <button type="button" onClick={() => up('faq')([...draft.faq, { q: emptyT(), a: emptyT() }])}
                  className="text-xs text-brand-600 hover:underline">+ سؤال</button>
        </div>
      </Field>

      <Field title="ملاحظات المدرب (تظهر بلون مميز)"><TField value={draft.notes} onChange={up('notes')} rows={3} /></Field>

      <Field title="سبب التعديل (يظهر في السجل)">
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300}
               className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
      </Field>

      {error && <div className="text-xs text-red-600">{error}</div>}
      <div className="flex items-center gap-2 sticky bottom-0 bg-surface py-2 border-t border-line">
        <button type="button" disabled={busy} onClick={save}
                className="text-sm bg-brand-600 text-white rounded-lg px-4 py-1.5 disabled:opacity-50">حفظ</button>
        <button type="button" disabled={busy} onClick={onDone}
                className="text-sm border border-line rounded-lg px-3 py-1.5 text-content">إلغاء</button>
        {data.override && (
          <button type="button" disabled={busy} onClick={revert}
                  className="text-xs text-red-600 hover:underline ms-auto">الرجوع للشرح الأصلي</button>
        )}
      </div>
    </div>
  )
}
