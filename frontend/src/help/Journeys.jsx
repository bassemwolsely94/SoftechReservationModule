/**
 * Module journeys («رحلات العمل») in the help center: each journey is a guided walk
 * through a whole process across screens. The card lists its steps (screen + button)
 * so people see the whole road before they start; «ابدأ الرحلة» opens the first screen
 * and runs it with the «اعرض لي» runner. Trainers (help/edit) edit the text in place —
 * steps, screens and buttons follow the code.
 */
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useHelpStore from './helpStore'
import { StepFields, TField } from './HelpEditor'
import { pick } from './text'

const clone = (v) => JSON.parse(JSON.stringify(v ?? null))

/** Open a journey's first screen, then run it with the «اعرض لي» runner. */
function useRunJourney() {
  const navigate = useNavigate()
  const startJourney = useHelpStore((s) => s.startJourney)
  return (j) => {
    const first = j.steps[0]
    if (first?.route) navigate(first.route)
    setTimeout(() => startJourney(j), 400)
  }
}

/**
 * «🗺️ جولة في موديولات دورك» — the role product tour (server-built from the training path: one
 * stop per module). `role` = a trainer previewing another role. Resolves false when
 * the role has no tour on this shell.
 */
export function useStartProductTour() {
  const run = useRunJourney()
  const { pathname } = useLocation()
  const shell = pathname.startsWith('/m/') || pathname === '/m' ? 'mobile' : 'desktop'
  return async (role) => {
    try {
      const { data } = await helpApi.productTour(role ? { shell, role } : { shell })
      run(data)
      return true
    } catch {
      return false
    }
  }
}

export function ProductTourButton({ lang, role, className = '' }) {
  const start = useStartProductTour()
  const [none, setNone] = useState(false)
  const en = lang === 'en'
  return (
    <button type="button" data-tour="general-help-center-product-tour"
            onClick={async () => setNone(!(await start(role)))}
            title={none ? (en ? 'No tour for this role yet' : 'مفيش جولة للدور ده') : undefined}
            className={`text-xs bg-brand-600 text-white rounded-lg px-3 py-1.5 hover:bg-brand-700 ${className}`}>
      🗺️ {en ? 'Your modules tour' : 'جولة في موديولات دورك'}
    </button>
  )
}

export default function Journeys({ journeys, lang, canEdit }) {
  if (!journeys?.length) return null
  const en = lang === 'en'
  return (
    <div data-tour="general-help-center-journeys" className="rounded-xl border border-line bg-surface p-5 space-y-4">
      <div>
        <h3 className="text-sm font-bold text-brand-600">🧭 {en ? 'Guided journeys' : 'رحلات العمل'}</h3>
        <p className="text-xs text-muted mt-1 leading-5">
          {en ? 'Each journey walks you through a whole process on the real screens, button by button. Nothing is saved or sent by the journey — you press the buttons yourself.'
              : 'كل رحلة بتمشّيك في العملية كلها على الشاشات الحقيقية، زرار زرار. الرحلة مش بتحفظ ولا بتبعت حاجة — إنت اللي بتضغط الأزرار.'}
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {journeys.map((j) => <JourneyCard key={j.id} j={j} lang={lang} canEdit={canEdit} />)}
      </div>
    </div>
  )
}

function JourneyCard({ j, lang, canEdit }) {
  const en = lang === 'en'
  const run = useRunJourney()
  const [editing, setEditing] = useState(false)
  const start = () => run(j)
  if (editing) return <JourneyEditor j={j} onDone={() => setEditing(false)} />
  return (
    <div className="rounded-lg border border-line p-4 space-y-3">
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <div className="font-semibold text-content">{pick(j.title, lang)}</div>
          <p className="text-xs text-muted leading-5 mt-0.5 whitespace-pre-line">{pick(j.summary, lang)}</p>
        </div>
        {canEdit && (
          <button type="button" onClick={() => setEditing(true)} className="text-xs text-brand-600 hover:underline shrink-0">
            ✏️ {en ? 'Edit' : 'تعديل'}
          </button>
        )}
      </div>
      <ol className="space-y-1.5">
        {j.steps.map((st, i) => (
          <li key={i} className="flex gap-2 text-xs leading-5">
            <span className="tabnum shrink-0 w-5 h-5 rounded-full bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 grid place-items-center text-[10px] font-bold">{i + 1}</span>
            <span className="text-content">
              <span className="text-faint">{pick(st.screen_title, lang)} · </span>
              {st.label ? <b>«{pick(st.label, lang)}»</b> : pick(st.text, lang)}
              {st.warn && <span className="text-amber-600" title={pick(st.warn, lang)}> ⚠</span>}
            </span>
          </li>
        ))}
      </ol>
      <button type="button" onClick={start} data-tour="general-help-center-start-journey"
              className="text-xs bg-brand-600 text-white rounded-lg px-3 py-1.5 hover:bg-brand-700">
        ▶ {en ? 'Start the journey' : 'ابدأ الرحلة'}
      </button>
    </div>
  )
}

function JourneyEditor({ j, onDone }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(() => ({ title: clone(j.title), summary: clone(j.summary), steps: clone(j.steps) }))
  const [note, setNote] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn) => {
    setBusy(true); setErr(null)
    try {
      await fn()
      qc.invalidateQueries({ queryKey: ['help'] })
      onDone()
    } catch (e) {
      setErr(e?.response?.data?.errors?.join(' · ') || e?.response?.data?.detail || 'تعذّر الحفظ')
    } finally { setBusy(false) }
  }
  const steps = draft.steps.map(({ target, label, text, when, warn, open_hint }) =>
    Object.fromEntries(Object.entries({ target, label, text, when, warn, open_hint }).filter(([, v]) => v)))
  return (
    <div className="rounded-lg border border-brand-300 p-4 space-y-3 lg:col-span-2">
      <div className="text-xs font-bold text-muted">عنوان الرحلة</div>
      <TField value={draft.title} rows={1} required onChange={(v) => setDraft({ ...draft, title: v })} />
      <div className="text-xs font-bold text-muted">ملخص</div>
      <TField value={draft.summary} rows={2} required onChange={(v) => setDraft({ ...draft, summary: v })} />
      <div className="text-xs font-bold text-muted">الخطوات (الشاشات والأزرار ثابتة حسب الكود — عدّل النص فقط)</div>
      {draft.steps.map((st, i) => (
        <StepFields key={i} step={st} index={i}
                    onChange={(v) => setDraft({ ...draft, steps: draft.steps.map((x, k) => (k === i ? v : x)) })} />
      ))}
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="سبب التعديل (اختياري)"
             className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
      {err && <div className="text-xs text-red-600">{err}</div>}
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => run(() => helpApi.saveJourney(j.id, { ...draft, steps }, note))}
                className="text-xs bg-brand-600 text-white rounded-lg px-4 py-1.5 hover:bg-brand-700 disabled:opacity-50">حفظ</button>
        {j.edited && (
          <button type="button" disabled={busy} onClick={() => run(() => helpApi.revertJourney(j.id, note))}
                  className="text-xs border border-line rounded-lg px-3 py-1.5 text-content hover:bg-surface-2">الرجوع للشرح الأصلي</button>
        )}
        <button type="button" onClick={onDone} className="ms-auto text-xs text-muted hover:underline">إلغاء</button>
      </div>
    </div>
  )
}
