/**
 * HelpCenterPage (/help) — the full help guide: browse every module (grouped like the
 * side menu) → module role + workflow + its screens → a screen's full help; search;
 * "what's new"; «مساري التدريبي» (role checklist + module quizzes); and, for trainers (help/edit), usage statistics + open feedback.
 */
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useLangStore from '../store/langStore'
import useHelpStore from '../help/helpStore'
import useHelpTab from '../help/useHelpTab'
import { useHelpIndex } from '../help/useHelpIndex'
import HelpArticle, { Workflow } from '../help/HelpArticle'
import HelpEditor from '../help/HelpEditor'
import HelpFeedback from '../help/HelpFeedback'
import { pick, label } from '../help/text'
import { LearnedButton, MyPath, Quiz, TeamProgress } from '../help/Onboarding'

export default function HelpCenterPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'browse'
  const moduleKey = params.get('module')
  const screenKey = params.get('screen')
  const quizKey = params.get('quiz')
  const helpLang = useHelpStore((s) => s.lang)
  const setHelpLang = useHelpStore((s) => s.setLang)
  const uiLang = useLangStore((s) => s.lang)
  const lang = helpLang || uiLang || 'ar'
  const { data: index, isLoading } = useHelpIndex()
  const [q, setQ] = useState('')
  useHelpTab(tab)

  const go = (next) => {
    const p = new URLSearchParams()
    Object.entries(next).forEach(([k, v]) => { if (v) p.set(k, v) })
    setParams(p)
  }
  const tabs = [
    ['browse', lang === 'en' ? 'Browse modules' : 'تصفح الموديولات'],
    ['path', lang === 'en' ? 'My training path' : 'مساري التدريبي'],
    ['whats_new', lang === 'en' ? "What's new" : 'الجديد'],
    ...(index?.can_edit ? [['trainers', lang === 'en' ? 'For trainers' : 'للمدربين']] : []),
  ]

  return (
    <div dir={lang === 'en' ? 'ltr' : 'rtl'} className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-content">📖 {label('guide', lang)}</h1>
          <p className="text-sm text-muted">
            {lang === 'en'
              ? 'Every screen of the system explained — what it is for, how to use it, its tabs and the module workflow. Press F1 on any screen to open its help.'
              : 'شرح كل شاشات النظام — دور الشاشة، طريقة الاستخدام، التبويبات، ودورة عمل الموديول. اضغط F1 في أي شاشة لفتح شرحها.'}
          </p>
        </div>
        <div className="flex items-center border border-line rounded-lg overflow-hidden text-sm">
          {['ar', 'en'].map((l) => (
            <button key={l} type="button" onClick={() => setHelpLang(l)}
                    className={`px-3 py-1.5 ${lang === l ? 'bg-brand-600 text-white' : 'text-muted hover:bg-surface-3'}`}>
              {l === 'ar' ? 'عربي' : 'English'}
            </button>
          ))}
        </div>
      </div>

      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={label('search', lang)}
             className="w-full text-sm bg-surface border border-line rounded-xl px-4 py-2.5 text-content placeholder-faint outline-none focus:border-brand-400" />

      {q.trim().length >= 2 ? (
        <SearchResults q={q.trim()} lang={lang} onOpen={(k) => { setQ(''); go({ tab: 'browse', screen: k }) }} />
      ) : (
        <>
          <div className="flex gap-1 border-b border-line">
            {tabs.map(([k, t]) => (
              <button key={k} type="button" onClick={() => go({ tab: k })}
                      className={`px-4 py-2 text-sm border-b-2 -mb-px ${tab === k ? 'border-brand-600 text-brand-700 font-semibold' : 'border-transparent text-muted hover:text-content'}`}>
                {t}
              </button>
            ))}
          </div>

          {isLoading && <div className="text-faint text-sm">{label('loading', lang)}</div>}
          {index && tab === 'browse' && !moduleKey && !screenKey && <Browse index={index} lang={lang} go={go} />}
          {index && tab === 'browse' && moduleKey && !screenKey && <ModuleView moduleKey={moduleKey} lang={lang} go={go} />}
          {index && tab === 'browse' && screenKey && <ScreenView screenKey={screenKey} lang={lang} go={go} index={index} />}
          {index && tab === 'path' && !quizKey && <MyPath lang={lang} go={go} canPreview={index.can_edit} />}
          {index && tab === 'path' && quizKey && <Quiz moduleKey={quizKey} lang={lang} onBack={() => go({ tab: 'path' })} />}
          {index && tab === 'whats_new' && <WhatsNew index={index} lang={lang} go={go} />}
          {index && tab === 'trainers' && index.can_edit && <Trainers index={index} lang={lang} go={go} />}
        </>
      )}
    </div>
  )
}

function Browse({ index, lang, go }) {
  return (
    <div className="space-y-6">
      {index.groups.map((g) => {
        const mods = index.modules.filter((m) => m.group === g.key)
        if (!mods.length) return null
        return (
          <section key={g.key} className="space-y-2">
            <h2 className="text-sm font-bold text-faint">{pick(g.title, lang)}</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {mods.map((m) => (
                <button key={m.key} type="button" onClick={() => go({ tab: 'browse', module: m.key })}
                        className="text-start rounded-xl border border-line bg-surface hover:border-brand-300 hover:shadow-sm p-4 space-y-1.5 transition">
                  <div className="font-semibold text-content">{m.icon} {pick(m.title, lang)}</div>
                  <div className="text-xs text-muted line-clamp-3 leading-5">{pick(m.summary, lang)}</div>
                  <div className="text-[11px] text-faint">
                    {m.screens.length} {lang === 'en' ? 'screens' : 'شاشة'}
                    {m.has_workflow && (lang === 'en' ? ' · workflow' : ' · دورة عمل')}
                  </div>
                </button>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function Crumbs({ lang, go, module, screen }) {
  return (
    <div className="text-xs text-faint flex items-center gap-1.5 flex-wrap">
      <button type="button" onClick={() => go({ tab: 'browse' })} className="hover:text-brand-600">{label('guide', lang)}</button>
      {module && <><span>›</span><button type="button" onClick={() => go({ tab: 'browse', module: module.key })} className="hover:text-brand-600">{pick(module.title, lang)}</button></>}
      {screen && <><span>›</span><span className="text-content">{pick(screen, lang)}</span></>}
    </div>
  )
}

function ModuleView({ moduleKey, lang, go }) {
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'module', moduleKey],
    queryFn: () => helpApi.module(moduleKey).then((r) => r.data),
  })
  if (isLoading || !data) return <div className="text-faint text-sm">{label('loading', lang)}</div>
  return (
    <div className="space-y-5">
      <Crumbs lang={lang} go={go} />
      <div className="rounded-xl border border-line bg-surface p-5 space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-bold text-content flex-1">{data.icon} {pick(data.title, lang)}</h2>
          <a href={`/help/manual?module=${data.key}&lang=${lang}`} target="_blank" rel="noreferrer"
             className="text-xs border border-line rounded-lg px-3 py-1.5 text-brand-600 hover:bg-brand-50">
            🖨️ {lang === 'en' ? 'Print this module\'s manual' : 'طباعة دليل الموديول'}
          </a>
        </div>
        <p className="text-sm text-content leading-7 whitespace-pre-line">{pick(data.summary, lang)}</p>
      </div>
      {(data.workflows || []).length > 0 && (
        <div className="rounded-xl border border-line bg-surface p-5 space-y-4">
          <h3 className="text-sm font-bold text-brand-600">{label('workflow', lang)}</h3>
          <div className="grid gap-6 lg:grid-cols-2">
            {data.workflows.map((wf, i) => <Workflow key={i} wf={wf} lang={lang} />)}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {data.screens.map((s) => (
          <button key={s.key} type="button" onClick={() => go({ tab: 'browse', screen: s.key })}
                  className="text-start rounded-xl border border-line bg-surface hover:border-brand-300 p-4 space-y-1">
            <div className="font-semibold text-content">{pick(s.title, lang)}</div>
            <div className="text-xs text-muted leading-5 line-clamp-3">{pick(s.summary, lang)}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function ScreenView({ screenKey, lang, go, index }) {
  const role = useAuthStore((s) => s.user?.role)
  const [editing, setEditing] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'screen', screenKey],
    queryFn: () => helpApi.screen(screenKey).then((r) => r.data),
  })
  if (isLoading || !data) return <div className="text-faint text-sm">{label('loading', lang)}</div>
  const s = index.screens.find((x) => x.key === screenKey)
  const openRoute = s?.routes.find((r) => !r.includes(':'))
  return (
    <div className="space-y-4">
      <Crumbs lang={lang} go={go} module={{ key: data.module.key, title: data.module.title }} screen={data.title} />
      <div className="rounded-xl border border-line bg-surface p-5 space-y-5">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-bold text-content flex-1">{pick(data.title, lang)}</h2>
          {openRoute && (
            <Link to={openRoute} className="text-xs border border-line rounded-lg px-3 py-1.5 text-brand-600 hover:bg-brand-50">
              {lang === 'en' ? 'Open this screen' : 'فتح الشاشة'} ↗
            </Link>
          )}
          {data.can_edit && !editing && (
            <button type="button" onClick={() => setEditing(true)} className="text-xs border border-line rounded-lg px-3 py-1.5 text-brand-600 hover:bg-brand-50">
              ✏️ {label('edit', lang)}
            </button>
          )}
        </div>
        {editing
          ? <HelpEditor data={data} onDone={() => setEditing(false)} />
          : <HelpArticle data={data} lang={lang} role={role} showAllRoles={data.can_edit}
                         onOpenScreen={(k) => go({ tab: 'browse', screen: k })} />}
        {!editing && (
          <div className="pt-3 border-t border-line flex flex-wrap items-center gap-4">
            <HelpFeedback screenKey={data.key} lang={lang} />
            <LearnedButton screenKey={data.key} lang={lang} />
            {data.updated && <span className="text-[11px] text-faint ms-auto">{label('updated', lang)}: <span className="tabnum">{data.updated}</span></span>}
          </div>
        )}
      </div>
    </div>
  )
}

function SearchResults({ q, lang, onOpen }) {
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'search', q],
    queryFn: () => helpApi.search(q).then((r) => r.data),
    staleTime: 60_000,
  })
  if (isLoading) return <div className="text-faint text-sm">{label('loading', lang)}</div>
  if (!data?.length) return <div className="text-faint text-sm">{label('noResults', lang)}</div>
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {data.map((r) => (
        <button key={r.key} type="button" onClick={() => onOpen(r.key)}
                className="text-start rounded-xl border border-line bg-surface hover:border-brand-300 p-4 space-y-1">
          <div className="text-[11px] text-faint">{r.icon} {pick(r.module_title, lang)}</div>
          <div className="font-semibold text-content">{pick(r.title, lang)}</div>
          <div className="text-xs text-muted leading-5 line-clamp-3">{pick(r.summary, lang)}</div>
        </button>
      ))}
    </div>
  )
}

function WhatsNew({ index, lang, go }) {
  const seen = useHelpStore((s) => s.seen)
  const rows = useMemo(() => [...index.screens]
    .filter((s) => s.updated)
    .sort((a, b) => (b.updated || '').localeCompare(a.updated || ''))
    .slice(0, 40), [index])
  const modTitle = Object.fromEntries(index.modules.map((m) => [m.key, m]))
  return (
    <div className="rounded-xl border border-line bg-surface divide-y divide-line">
      {rows.map((s) => {
        const unread = seen[s.key] !== s.updated
        return (
          <button key={s.key} type="button" onClick={() => go({ tab: 'browse', screen: s.key })}
                  className="w-full text-start px-4 py-2.5 flex items-center gap-3 hover:bg-surface-2">
            <span className="text-xs text-faint tabnum w-24 shrink-0">{s.updated}</span>
            <span className="text-sm text-content flex-1">{pick(s.title, lang)}
              <span className="text-xs text-faint"> · {modTitle[s.module]?.icon} {pick(modTitle[s.module]?.title, lang)}</span></span>
            {unread && <span className="text-[10px] font-bold text-amber-700 bg-amber-50 border border-amber-300 rounded px-1.5">{label('newBadge', lang)}</span>}
          </button>
        )
      })}
    </div>
  )
}

function Trainers({ index, lang, go }) {
  const qc = useQueryClient()
  const [days, setDays] = useState(30)
  const stats = useQuery({ queryKey: ['help', 'stats', days], queryFn: () => helpApi.stats(days).then((r) => r.data) })
  const fb = useQuery({ queryKey: ['help', 'feedback'], queryFn: () => helpApi.feedbackList({ open: 1 }).then((r) => r.data) })
  const title = Object.fromEntries(index.screens.map((s) => [s.key, s.title]))
  const resolve = async (id) => { await helpApi.resolveFeedback(id); qc.invalidateQueries({ queryKey: ['help', 'feedback'] }); qc.invalidateQueries({ queryKey: ['help', 'stats'] }) }
  const st = stats.data
  const Box = ({ t, children }) => (
    <div className="rounded-xl border border-line bg-surface p-4 space-y-2">
      <h3 className="text-sm font-bold text-content">{t}</h3>{children}
    </div>
  )
  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">الفترة:</span>
        {[7, 30, 90].map((d) => (
          <button key={d} type="button" onClick={() => setDays(d)}
                  className={`px-2.5 py-1 rounded-lg border ${days === d ? 'bg-brand-600 text-white border-brand-600' : 'border-line text-muted'}`}>{d} يوم</button>
        ))}
        {st && <span className="ms-auto text-xs text-faint">شاشات معدّلة من المدربين: {st.overrides} · ملاحظات مفتوحة: {st.open_comments}</span>}
      </div>
      {st && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Box t="أكثر الشاشات التي يُفتح شرحها (محتاجة تدريب أو شرح أوضح)">
            <Rows rows={st.opens} render={(o) => <><span className="flex-1">{pick(o.title, 'ar') || o.screen_key}</span><span className="tabnum">{o.n}</span></>}
                  onClick={(o) => go({ tab: 'browse', screen: o.screen_key })} />
          </Box>
          <Box t="تقييم الشرح (الأكثر «غير مفيد» أولاً)">
            <Rows rows={st.votes} render={(v) => <><span className="flex-1">{pick(v.title, 'ar') || v.screen_key}</span>
              <span className="text-emerald-700 tabnum">👍 {v.up}</span><span className="text-red-600 tabnum">👎 {v.down}</span></>}
                  onClick={(v) => go({ tab: 'browse', screen: v.screen_key })} />
          </Box>
          <Box t="ما يبحث عنه المستخدمون">
            <Rows rows={st.searches} render={(s) => <><span className="flex-1">{s.query}</span>
              {s.misses > 0 && <span className="text-[10px] text-red-600 border border-red-200 rounded px-1">بدون نتيجة {s.misses}</span>}
              <span className="tabnum">{s.n}</span></>} />
          </Box>
          <Box t="فتح الشرح حسب الدور">
            <Rows rows={st.by_role} render={(r) => <><span className="flex-1">{r.role || '—'}</span><span className="tabnum">{r.n}</span></>} />
          </Box>
        </div>
      )}
      <TeamProgress />
      <Box t="ملاحظات المستخدمين المفتوحة">
        {(fb.data || []).length === 0 && <div className="text-sm text-faint">لا توجد ملاحظات مفتوحة 🎉</div>}
        <div className="divide-y divide-line">
          {(fb.data || []).map((f) => (
            <div key={f.id} className="py-2 flex gap-3 items-start text-sm">
              <span>{f.helpful ? '👍' : '👎'}</span>
              <div className="flex-1">
                <button type="button" onClick={() => go({ tab: 'browse', screen: f.screen_key })} className="font-semibold text-brand-600 hover:underline">
                  {pick(title[f.screen_key], 'ar') || f.screen_key}{f.tab ? ` · ${f.tab}` : ''}
                </button>
                <div className="text-content whitespace-pre-line">{f.comment}</div>
                <div className="text-[11px] text-faint">{f.staff} · {f.role} · {new Date(f.created_at).toLocaleString('ar-EG-u-nu-latn')}</div>
              </div>
              <button type="button" onClick={() => resolve(f.id)} className="text-xs border border-line rounded-lg px-2 py-1 hover:bg-emerald-50">تم ✓</button>
            </div>
          ))}
        </div>
      </Box>
    </div>
  )
}

function Rows({ rows, render, onClick }) {
  if (!rows?.length) return <div className="text-sm text-faint">لا توجد بيانات بعد</div>
  return (
    <div className="divide-y divide-line">
      {rows.map((r, i) => (
        <div key={i} onClick={onClick ? () => onClick(r) : undefined}
             className={`py-1.5 flex items-center gap-3 text-sm text-content ${onClick ? 'cursor-pointer hover:bg-surface-2' : ''}`}>
          {render(r)}
        </div>
      ))}
    </div>
  )
}
