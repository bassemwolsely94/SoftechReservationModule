/**
 * Onboarding UI — the role's training path (checklist), «فهمت هذه الشاشة» button,
 * module quizzes and the trainers' team-progress table. Grading and progress are
 * computed by the server (/api/help/onboarding/, /api/help/quizzes/); this file only
 * shows them.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick, label } from './text'

const en = (lang) => lang === 'en'

export function useOnboarding(role) {
  return useQuery({
    queryKey: ['help', 'onboarding', role || 'me'],
    queryFn: () => helpApi.onboarding(role).then((r) => r.data),
    staleTime: 60_000,
  })
}

function Bar({ percent }) {
  return (
    <div className="h-2 rounded-full bg-surface-3 overflow-hidden">
      <div className={`h-full ${percent >= 100 ? 'bg-emerald-500' : 'bg-brand-600'}`} style={{ width: `${percent}%` }} />
    </div>
  )
}

/** «فهمت هذه الشاشة ✓» — ticks the screen in my checklist (toggle). */
export function LearnedButton({ screenKey, lang }) {
  const qc = useQueryClient()
  const { data } = useOnboarding()
  const [busy, setBusy] = useState(false)
  if (!data) return null
  const state = data.learned?.[screenKey]
  const toggle = async () => {
    setBusy(true)
    try {
      await helpApi.learned(screenKey, state !== 'done')
      await qc.invalidateQueries({ queryKey: ['help', 'onboarding'] })
    } finally { setBusy(false) }
  }
  const cls = state === 'done'
    ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
    : state === 'changed' ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-line text-content hover:bg-brand-50'
  return (
    <button type="button" disabled={busy} onClick={toggle}
            className={`text-xs border rounded-lg px-3 py-1.5 ${cls}`}>
      {state === 'done'
        ? (en(lang) ? '✓ Understood' : '✓ فهمت الشاشة')
        : state === 'changed'
          ? (en(lang) ? '⟳ Help changed — mark as read again' : '⟳ الشرح اتغيّر — علّم إنك راجعته')
          : (en(lang) ? 'I understand this screen ✓' : 'فهمت هذه الشاشة ✓')}
    </button>
  )
}

const STATE = {
  todo:    ['○', 'text-faint', ['لسه', 'To do']],
  done:    ['✓', 'text-emerald-600', ['تم', 'Done']],
  changed: ['⟳', 'text-amber-600', ['الشرح اتغيّر — راجعه', 'Help changed — re-read']],
}

/** «مساري التدريبي» — the role's ordered checklist + its module quizzes. */
export function MyPath({ lang, go, canPreview }) {
  const [role, setRole] = useState('')
  const { data, isLoading } = useOnboarding(role)
  if (isLoading || !data) return <div className="text-faint text-sm">{label('loading', lang)}</div>
  const p = data.progress
  const next = data.path.find((i) => i.state !== 'done')
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line bg-surface p-5 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-bold text-content flex-1">
            🎓 {en(lang) ? 'My training path' : 'مساري التدريبي'}
            <span className="text-sm font-normal text-muted"> · {data.role}</span>
          </h2>
          {canPreview && data.roles.length > 1 && (
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="text-xs bg-surface border border-line rounded-lg px-2 py-1.5 text-content">
              <option value="">{en(lang) ? 'My role' : 'دوري أنا'}</option>
              {data.roles.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
          <a href={`/help/manual?role=${data.role}&lang=${lang}`} target="_blank" rel="noreferrer"
             className="text-xs border border-line rounded-lg px-3 py-1.5 text-brand-600 hover:bg-brand-50">
            🖨️ {en(lang) ? 'Print my manual' : 'طباعة دليلي'}
          </a>
          <span className="text-2xl font-bold text-brand-600 tabnum">{p.percent}%</span>
        </div>
        <Bar percent={p.percent} />
        <div className="text-xs text-muted">
          {en(lang)
            ? `${p.learned}/${p.screens} screens understood · ${p.quizzes_passed}/${p.quizzes} quizzes passed (pass mark ${data.pass_percent}%)`
            : `${p.learned}/${p.screens} شاشة اتفهمت · ${p.quizzes_passed}/${p.quizzes} اختبار ناجح (درجة النجاح ${data.pass_percent}%)`}
        </div>
        <p className="text-sm text-content leading-7">
          {en(lang)
            ? 'Read each screen in order, try it on the real screen, then press «I understand this screen ✓». After a module\'s screens, take its short quiz. When the help of a screen changes, it is marked «re-read».'
            : 'اقرأ شرح كل شاشة بالترتيب، وجرّبها على الشاشة الحقيقية، وبعدين اضغط «فهمت هذه الشاشة ✓». بعد ما تخلص شاشات الموديول ادخل الاختبار القصير بتاعه. لو شرح شاشة اتغيّر هتلاقيها متعلّمة «راجعه».'}
        </p>
        {next && (
          <button type="button" onClick={() => go({ tab: 'browse', screen: next.key })}
                  className="text-sm bg-brand-600 text-white rounded-lg px-4 py-2 hover:bg-brand-700">
            {en(lang) ? 'Continue: ' : 'كمّل: '}{pick(next.title, lang)} ←
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-xl border border-line bg-surface divide-y divide-line">
          {data.path.map((i, n) => {
            const [icon, cls, txt] = STATE[i.state]
            return (
              <button key={i.key} type="button" onClick={() => go({ tab: 'browse', screen: i.key })}
                      className="w-full text-start px-4 py-2.5 flex items-center gap-3 hover:bg-surface-2">
                <span className="text-xs text-faint tabnum w-6">{n + 1}</span>
                <span className={`w-5 text-center font-bold ${cls}`}>{icon}</span>
                <span className="flex-1 min-w-0">
                  <span className="text-sm text-content">{pick(i.title, lang)}</span>
                  <span className="text-xs text-faint"> · {i.icon} {pick(i.module_title, lang)}</span>
                </span>
                {i.state !== 'todo' && <span className={`text-[11px] ${cls}`}>{txt[en(lang) ? 1 : 0]}</span>}
              </button>
            )
          })}
        </div>
        <div className="rounded-xl border border-line bg-surface p-4 space-y-2 self-start">
          <h3 className="text-sm font-bold text-content">{en(lang) ? 'Module quizzes' : 'اختبارات الموديولات'}</h3>
          {data.quizzes.map((q) => (
            <button key={q.module} type="button" onClick={() => go({ tab: 'path', quiz: q.module })}
                    className="w-full text-start rounded-lg border border-line px-3 py-2 flex items-center gap-2 hover:border-brand-300">
              <span className="flex-1 text-sm text-content">{q.icon} {pick(q.title, lang)}</span>
              {q.best
                ? <span className={`text-[11px] tabnum ${q.best.passed ? 'text-emerald-700' : 'text-red-600'}`}>
                    {q.best.passed ? '✓ ' : ''}{q.best.score}/{q.best.total}
                  </span>
                : <span className="text-[11px] text-faint">{q.questions} {en(lang) ? 'Q' : 'سؤال'}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/** One module quiz — options come shuffled and without answers; the server grades. */
export function Quiz({ moduleKey, lang, onBack }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'quiz', moduleKey],
    queryFn: () => helpApi.quiz(moduleKey).then((r) => r.data),
  })
  const [chosen, setChosen] = useState({})
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  if (isLoading || !data) return <div className="text-faint text-sm">{label('loading', lang)}</div>
  const submit = async () => {
    setBusy(true)
    try {
      const r = await helpApi.submitQuiz(moduleKey, data.questions.map((_, i) => chosen[i] ?? null))
      setResult(r.data)
      qc.invalidateQueries({ queryKey: ['help', 'onboarding'] })
    } finally { setBusy(false) }
  }
  const retry = () => { setChosen({}); setResult(null) }
  const answered = Object.keys(chosen).length
  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="text-xs text-faint hover:text-brand-600">
        {en(lang) ? '→ Back to my path' : '→ رجوع لمساري التدريبي'}
      </button>
      <div className="rounded-xl border border-line bg-surface p-5 space-y-1">
        <h2 className="text-lg font-bold text-content">📝 {pick(data.title, lang)}</h2>
        <div className="text-xs text-muted">
          {en(lang) ? `${data.questions.length} questions · pass mark ${data.pass_percent}%` : `${data.questions.length} أسئلة · درجة النجاح ${data.pass_percent}%`}
          {data.best && (en(lang) ? ` · your best ${data.best.score}/${data.best.total}` : ` · أفضل نتيجة لك ${data.best.score}/${data.best.total}`)}
        </div>
      </div>
      {result && (
        <div className={`rounded-xl border p-4 text-sm font-semibold ${result.passed ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : 'border-amber-300 bg-amber-50 text-amber-900'}`}>
          {result.passed
            ? (en(lang) ? `Passed — ${result.score}/${result.total} (${result.percent}%)` : `ناجح — ${result.score}/${result.total} (${result.percent}%)`)
            : (en(lang) ? `Not yet — ${result.score}/${result.total} (${result.percent}%). Read the explanations and try again.` : `لسه — ${result.score}/${result.total} (${result.percent}%). اقرأ التوضيح تحت وجرّب تاني.`)}
        </div>
      )}
      {data.questions.map((q, i) => {
        const r = result?.results[i]
        return (
          <div key={i} className="rounded-xl border border-line bg-surface p-4 space-y-2">
            <div className="text-sm font-semibold text-content">{i + 1}. {pick(q.q, lang)}</div>
            <div className="space-y-1.5">
              {q.options.map((o) => {
                const picked = chosen[i] === o.id
                let cls = picked ? 'border-brand-400 bg-brand-50' : 'border-line hover:bg-surface-2'
                if (r) {
                  if (o.id === r.answer) cls = 'border-emerald-400 bg-emerald-50'
                  else if (picked) cls = 'border-red-300 bg-red-50'
                  else cls = 'border-line opacity-70'
                }
                return (
                  <label key={o.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm text-content cursor-pointer ${cls}`}>
                    <input type="radio" name={`q${i}`} disabled={!!result} checked={picked}
                           onChange={() => setChosen((c) => ({ ...c, [i]: o.id }))} />
                    {pick(o.text, lang)}
                  </label>
                )
              })}
            </div>
            {r && <div className={`text-xs leading-6 ${r.correct ? 'text-emerald-700' : 'text-amber-800'}`}>{r.correct ? '✓ ' : '✗ '}{pick(r.explain, lang)}</div>}
          </div>
        )
      })}
      {result
        ? <button type="button" onClick={retry} className="text-sm border border-line rounded-lg px-4 py-2 hover:bg-surface-2">{en(lang) ? 'Try again' : 'حاول تاني'}</button>
        : <button type="button" disabled={busy || answered < data.questions.length} onClick={submit}
                  className="text-sm bg-brand-600 text-white rounded-lg px-4 py-2 disabled:opacity-50">
            {en(lang) ? `Submit (${answered}/${data.questions.length})` : `تسليم (${answered}/${data.questions.length})`}
          </button>}
    </div>
  )
}

/** Trainers: who finished their path, who is stuck. */
export function TeamProgress() {
  const [role, setRole] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'team', role],
    queryFn: () => helpApi.team(role ? { role } : {}).then((r) => r.data),
  })
  const roles = [...new Set((data || []).map((r) => r.role))]
  return (
    <div className="rounded-xl border border-line bg-surface p-4 space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-bold text-content flex-1">تقدّم الفريق في التدريب</h3>
        <select value={role} onChange={(e) => setRole(e.target.value)}
                className="text-xs bg-surface border border-line rounded-lg px-2 py-1 text-content">
          <option value="">كل الأدوار</option>
          {(role ? [role] : roles).map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>
      {isLoading && <div className="text-faint text-sm">…جارٍ التحميل</div>}
      {data && !data.length && <div className="text-sm text-faint">لا يوجد موظفون</div>}
      <div className="divide-y divide-line">
        {(data || []).map((r) => (
          <div key={r.id} className="py-2 grid grid-cols-12 gap-3 items-center text-sm">
            <span className="col-span-4 text-content truncate">{r.name}<span className="text-xs text-faint"> · {r.role}{r.branch ? ` · ${r.branch}` : ''}</span></span>
            <span className="col-span-3"><Bar percent={r.progress.percent} /></span>
            <span className="col-span-1 tabnum text-content">{r.progress.percent}%</span>
            <span className="col-span-2 text-xs text-muted tabnum">{r.progress.learned}/{r.progress.screens} · {r.progress.quizzes_passed}/{r.progress.quizzes}</span>
            <span className="col-span-2 text-[11px] text-faint">
              {r.failed_quizzes.length > 0 && <span className="text-red-600">رسب: {r.failed_quizzes.join('، ')} · </span>}
              {r.last_activity ? new Date(r.last_activity).toLocaleDateString('ar-EG-u-nu-latn') : 'لم يبدأ'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
