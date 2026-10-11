/**
 * TrainingEditor — trainers (help/edit) change a role's training path or a module's
 * quiz in the app. Saving replaces the repo version for everyone at once; every save /
 * revert is kept in the history (HelpRevision 'path:<role>' / 'quiz:<module>').
 * The server validates everything (screens must exist, each question needs ≥2 options,
 * a correct answer and an explanation).
 */
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { TField } from './HelpEditor'
import { pick } from './text'

const ROLES = ['pharmacist', 'salesperson', 'call_center', 'purchasing', 'delivery', 'supervisor',
  'quality_manager', 'viewer', 'admin']
const clone = (v) => JSON.parse(JSON.stringify(v ?? null))
const emptyT = () => ({ ar: '', en: '' })
const newQuestion = () => ({ q: emptyT(), options: [emptyT(), emptyT()], answer: 0, explain: emptyT() })

const btn = 'text-xs border border-line rounded-lg px-2 py-1 hover:bg-surface-2 disabled:opacity-40'

export default function TrainingEditor({ index }) {
  // ?tkind=flow&tkey=<module>.<key>&tstep=N — opened from the usage report on a weak step
  const [params] = useSearchParams()
  const [kind, setKind] = useState(params.get('tkind') || 'path')
  const [key, setKey] = useState(params.get('tkey') || 'pharmacist')
  const focusStep = params.get('tstep') != null ? Number(params.get('tstep')) : null
  const boxRef = useRef(null)
  useEffect(() => { if (params.get('tkind')) boxRef.current?.scrollIntoView({ block: 'start' }) }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'training', kind, key],
    queryFn: () => helpApi.training(kind, key).then((r) => r.data),
  })
  const [draft, setDraft] = useState(null)
  const [note, setNote] = useState('')
  const [publicNote, setPublicNote] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [draftOf, setDraftOf] = useState(null)   // the payload the draft was made from
  useEffect(() => { setDraft(data ? clone(data.current) : null); setDraftOf(data || null); setMsg(null) }, [data])

  const flows = index.flows || []
  const switchKind = (k) => { setKind(k); setKey(k === 'path' ? 'pharmacist' : k === 'quiz' ? 'pos' : (flows[0]?.id || '').slice(5)) }
  const done = (payload, text) => {
    qc.setQueryData(['help', 'training', kind, key], payload)
    qc.invalidateQueries({ queryKey: ['help', 'onboarding'] })
    qc.invalidateQueries({ queryKey: ['help', 'quiz'] })
    const n = payload?.notified
    setNote(''); setPublicNote(''); setMsg({ ok: true, text: n ? `${text} · اتبعت إشعار لـ ${n} موظف` : text })
  }
  const run = async (fn, text) => {
    setBusy(true); setMsg(null)
    try { done((await fn()).data, text) } catch (e) {
      const d = e?.response?.data
      setMsg({ ok: false, text: [d?.detail, ...(d?.errors || [])].filter(Boolean).join(' — ') || 'تعذّر الحفظ' })
    } finally { setBusy(false) }
  }
  const save = () => run(() => helpApi.saveTraining(kind, key,
    kind === 'path' ? { screens: draft } : kind === 'quiz' ? { questions: draft } : draft, note, publicNote), 'تم الحفظ — ظاهر للجميع الآن')
  const revert = () => run(() => helpApi.revertTraining(kind, key, note), 'رجعنا للنسخة الأصلية')

  return (
    <div ref={boxRef} className="rounded-xl border border-line bg-surface p-4 space-y-3" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-bold text-content flex-1">تعديل المسارات التدريبية والاختبارات</h3>
        <div className="flex border border-line rounded-lg overflow-hidden text-xs">
          {[['path', 'مسار دور'], ['quiz', 'اختبار موديول'], ['flow', 'جولة دورة عمل']].map(([k, t]) => (
            <button key={k} type="button" onClick={() => switchKind(k)}
                    className={`px-3 py-1.5 ${kind === k ? 'bg-brand-600 text-white' : 'text-muted hover:bg-surface-3'}`}>{t}</button>
          ))}
        </div>
        <select value={key} onChange={(e) => setKey(e.target.value)}
                className="text-xs bg-surface border border-line rounded-lg px-2 py-1.5 text-content">
          {kind === 'path'
            ? ROLES.map((r) => <option key={r} value={r}>{r}</option>)
            : kind === 'quiz'
            ? index.modules.map((m) => <option key={m.key} value={m.key}>{m.icon} {pick(m.title, 'ar')}</option>)
            : flows.map((f) => <option key={f.id} value={f.id.slice(5)}>{f.mobile ? '📱 ' : '🧭 '}{pick(f.title, 'ar')}</option>)}
        </select>
      </div>

      {isLoading || !draft || draftOf !== data ? <div className="text-sm text-faint">…جارٍ التحميل</div> : (
        <>
          {data.override && (
            <div className={`text-xs rounded-lg px-3 py-2 border ${data.override.base_changed ? 'bg-amber-50 border-amber-300 text-amber-900' : 'bg-surface-2 border-line text-muted'}`}>
              نسخة معدّلة — {data.override.updated_by} · {new Date(data.override.updated_at).toLocaleString('ar-EG-u-nu-latn')}
              {data.override.base_changed && ' · تنبيه: المطوّرون غيّروا النسخة الأصلية بعد تعديلك — راجعها.'}
            </div>
          )}
          {kind === 'path'
            ? <PathEditor items={draft} onChange={setDraft} index={index} />
            : kind === 'quiz'
            ? <QuizEditor items={draft} onChange={setDraft} />
            : <FlowEditor flow={draft} onChange={setDraft} focusStep={focusStep} />}
          <div className="space-y-1 pt-2 border-t border-line">
            <label className="block text-xs font-semibold text-content">
              إيه الجديد للمستخدمين؟ <span className="font-normal text-faint">(سطر واحد، اختياري — {kind === 'flow'
                ? 'يظهر على كارت الجولة أسبوعين' : kind === 'path' ? 'يتضاف لإشعار «شاشات جديدة في مسارك»' : 'يتضاف لإشعار «اختبار اتحدّث»'})</span>
            </label>
            <input value={publicNote} onChange={(e) => setPublicNote(e.target.value)} maxLength={120}
                   placeholder={kind === 'quiz' ? 'مثال: سؤالين جداد عن المرتجعات' : kind === 'path' ? 'مثال: اتضافت شاشة التحويلات — ابدأ بيها' : 'مثال: خطوة جديدة عن طباعة الفاتورة'}
                   className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="سبب التعديل (يظهر في السجل)"
                   className="flex-1 min-w-[200px] text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
            <button type="button" disabled={busy} onClick={save}
                    className="text-sm bg-brand-600 text-white rounded-lg px-4 py-1.5 disabled:opacity-50">حفظ</button>
            {data.override && (
              <button type="button" disabled={busy} onClick={revert} className="text-sm border border-line rounded-lg px-3 py-1.5 hover:bg-surface-2">
                الرجوع للنسخة الأصلية
              </button>
            )}
          </div>
          {msg && <div className={`text-xs ${msg.ok ? 'text-emerald-700' : 'text-red-600'}`}>{msg.text}</div>}
          {data.revisions.length > 0 && (
            <details className="text-xs text-muted">
              <summary className="cursor-pointer">سجل التعديلات ({data.revisions.length})</summary>
              <div className="mt-1 space-y-0.5">
                {data.revisions.map((r) => (
                  <div key={r.id}>{new Date(r.created_at).toLocaleString('ar-EG-u-nu-latn')} · {r.staff} · {r.action === 'save' ? 'حفظ' : 'رجوع للأصل'}{r.note ? ` — ${r.note}` : ''}{r.public_note ? ` · للمستخدمين: «${r.public_note}»` : ''}</div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  )
}

function PathEditor({ items, onChange, index }) {
  const byKey = Object.fromEntries(index.screens.map((s) => [s.key, s]))
  const mods = Object.fromEntries(index.modules.map((m) => [m.key, m]))
  const [add, setAdd] = useState('')
  const move = (i, d) => { const n = items.slice(); [n[i], n[i + d]] = [n[i + d], n[i]]; onChange(n) }
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted">الترتيب = ترتيب التعلّم (أول أسبوع الأول). اختبارات المسار = اختبارات موديولات الشاشات دي.</div>
      <div className="divide-y divide-line border border-line rounded-lg">
        {items.map((k, i) => (
          <div key={k} className="flex items-center gap-2 px-3 py-1.5 text-sm">
            <span className="text-xs text-faint tabnum w-6">{i + 1}</span>
            <span className="flex-1 text-content">{pick(byKey[k]?.title, 'ar') || k}
              <span className="text-xs text-faint"> · {mods[byKey[k]?.module]?.icon} {pick(mods[byKey[k]?.module]?.title, 'ar')}</span></span>
            <button type="button" className={btn} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
            <button type="button" className={btn} disabled={i === items.length - 1} onClick={() => move(i, 1)}>↓</button>
            <button type="button" className={btn} onClick={() => onChange(items.filter((x) => x !== k))}>✕</button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <select value={add} onChange={(e) => setAdd(e.target.value)}
                className="flex-1 text-xs bg-surface border border-line rounded-lg px-2 py-1.5 text-content">
          <option value="">— أضف شاشة —</option>
          {index.modules.map((m) => (
            <optgroup key={m.key} label={`${m.icon} ${pick(m.title, 'ar')}`}>
              {m.screens.filter((k) => !items.includes(k)).map((k) => <option key={k} value={k}>{pick(byKey[k]?.title, 'ar')}</option>)}
            </optgroup>
          ))}
        </select>
        <button type="button" className={btn} disabled={!add} onClick={() => { onChange([...items, add]); setAdd('') }}>+ إضافة</button>
      </div>
    </div>
  )
}

function QuizEditor({ items, onChange }) {
  const set = (i, q) => onChange(items.map((x, j) => (j === i ? q : x)))
  const move = (i, d) => { const n = items.slice(); [n[i], n[i + d]] = [n[i + d], n[i]]; onChange(n) }
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted">حدد الإجابة الصحيحة بالدائرة. الاختيارات بتتلخبط تلقائياً لكل موظف، والإجابة والتوضيح بيظهروا بعد التسليم بس. اختبار فاضي = لا يوجد اختبار للموديول.</div>
      {items.map((q, i) => (
        <div key={i} className="rounded-lg border border-line p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-content flex-1">سؤال {i + 1}</span>
            <button type="button" className={btn} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
            <button type="button" className={btn} disabled={i === items.length - 1} onClick={() => move(i, 1)}>↓</button>
            <button type="button" className={btn} onClick={() => onChange(items.filter((_, j) => j !== i))}>حذف</button>
          </div>
          <TField value={q.q} rows={1} required onChange={(v) => set(i, { ...q, q: v })} />
          <div className="space-y-1.5">
            {q.options.map((o, oi) => (
              <div key={oi} className="flex items-start gap-2">
                <input type="radio" className="mt-2" name={`ans-${i}`} checked={q.answer === oi}
                       onChange={() => set(i, { ...q, answer: oi })} title="الإجابة الصحيحة" />
                <div className="flex-1"><TField value={o} rows={1} required
                       onChange={(v) => set(i, { ...q, options: q.options.map((x, j) => (j === oi ? v : x)) })} /></div>
                <button type="button" className={btn} disabled={q.options.length <= 2}
                        onClick={() => set(i, { ...q, options: q.options.filter((_, j) => j !== oi),
                                                answer: q.answer === oi ? 0 : q.answer > oi ? q.answer - 1 : q.answer })}>✕</button>
              </div>
            ))}
            <button type="button" className={btn} onClick={() => set(i, { ...q, options: [...q.options, emptyT()] })}>+ اختيار</button>
          </div>
          <div className="text-[11px] text-faint">التوضيح (يظهر بعد التسليم)</div>
          <TField value={q.explain} rows={1} required onChange={(v) => set(i, { ...q, explain: v })} />
        </div>
      ))}
      <button type="button" className={btn} onClick={() => onChange([...items, newQuestion()])}>+ سؤال</button>
    </div>
  )
}

/** Workflow-tour text: title, summary, each step's text. Steps and their buttons are fixed
 *  by the code (like screen tours) — trainers change the wording only. */
function FlowEditor({ flow, onChange, focusStep }) {
  const focusRef = useRef(null)
  useEffect(() => { focusRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [])
  const setStep = (i, text) => onChange({ ...flow, steps: flow.steps.map((x, j) => (j === i ? { ...x, text } : x)) })
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted">الخطوات والأزرار ثابتة حسب الشاشات — عدّل العنوان والملخص ونص كل خطوة. الصفحة اللي الخطوة بتظهر فيها مكتوبة جنب رقمها.</div>
      <div className="space-y-1"><div className="text-[11px] text-faint">العنوان</div>
        <TField value={flow.title} rows={1} required onChange={(v) => onChange({ ...flow, title: v })} /></div>
      <div className="space-y-1"><div className="text-[11px] text-faint">الملخص</div>
        <TField value={flow.summary} rows={2} onChange={(v) => onChange({ ...flow, summary: v })} /></div>
      {flow.steps.map((st, i) => (
        <div key={`${i}-${st.target}`} ref={i === focusStep ? focusRef : null}
             className={`rounded-lg border p-2 space-y-1.5 ${i === focusStep ? 'border-amber-400 bg-amber-50 ring-2 ring-amber-300' : 'border-line'}`}>
          <div className="text-[10px] text-faint">
            {i + 1}. {st.target}{st.route ? ` · ${st.route}` : ''}{st.wait ? ` · ينتظر فتح ${st.wait}` : ''}
            {i === focusStep && <span className="text-amber-700 font-semibold"> — أغلب الناس بيقفوا قبل الخطوة دي: وضّح النص</span>}
          </div>
          <TField value={st.text} rows={2} required onChange={(v) => setStep(i, v)} />
        </div>
      ))}
    </div>
  )
}
