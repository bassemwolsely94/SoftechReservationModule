/**
 * HelpManualPage (/help/manual?role=|module=&lang=) — printable training manual built
 * from the same help text as the panel (/api/help/manual/). Own shell (no side menu)
 * so the browser's print / "Save as PDF" gives a clean booklet: cover + contents,
 * then one chapter per module (role + workflow) followed by its screens.
 */
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useHelpStore from '../help/helpStore'
import { useHelpIndex } from '../help/useHelpIndex'
import { Workflow } from '../help/HelpArticle'
import { pick, itemText, label } from '../help/text'

const ROLES = ['pharmacist', 'salesperson', 'call_center', 'purchasing', 'delivery', 'supervisor',
  'quality_manager', 'viewer', 'admin']
const ROLE_NAMES = {
  pharmacist: ['الصيدلي', 'Pharmacist'], salesperson: ['البائع', 'Salesperson'],
  call_center: ['الكول سنتر', 'Call center'], purchasing: ['المشتريات', 'Purchasing'],
  delivery: ['الطيار / التوصيل', 'Delivery'], supervisor: ['المشرف', 'Supervisor'],
  quality_manager: ['مدير الجودة', 'Quality manager'], viewer: ['مشاهد', 'Viewer'], admin: ['مدير النظام', 'Admin'],
}

export default function HelpManualPage() {
  const [params, setParams] = useSearchParams()
  const myRole = useAuthStore((s) => s.user?.role)
  const helpLang = useHelpStore((s) => s.lang)
  const module = params.get('module') || ''
  const role = module ? '' : (params.get('role') || myRole || '')
  const lang = params.get('lang') || helpLang || 'ar'
  const en = lang === 'en'
  const { data: index } = useHelpIndex()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['help', 'manual', role, module],
    queryFn: () => helpApi.manual(module ? { module } : { role }).then((r) => r.data),
  })
  const set = (k, v) => {
    const p = new URLSearchParams(params)
    if (k === 'role') p.delete('module')
    if (k === 'module') p.delete('role')
    if (v) p.set(k, v); else p.delete(k)
    setParams(p)
  }
  const modTitle = module && index ? index.modules.find((m) => m.key === module)?.title : null
  const title = module
    ? `${en ? 'Training manual — ' : 'دليل التدريب — '}${pick(modTitle, lang)}`
    : `${en ? 'Training manual — ' : 'دليل التدريب — '}${(ROLE_NAMES[role] || [role, role])[en ? 1 : 0]}`

  return (
    <div dir={en ? 'ltr' : 'rtl'} className="manual min-h-screen bg-white text-gray-900">
      <style>{`
        .manual h2.chapter { break-before: page; }
        .manual h2, .manual h3, .manual .blk-title { break-after: avoid; }
        .manual li, .manual p { break-inside: avoid; }
        @media print { @page { margin: 14mm; } .manual { font-size: 11pt; } }
      `}</style>

      {/* controls — not printed */}
      <div className="no-print sticky top-0 z-10 bg-gray-50 border-b border-gray-200 px-6 py-3 flex flex-wrap items-center gap-3 text-sm">
        <a href="/help" className="text-brand-600 hover:underline">→ {label('guide', lang)}</a>
        <select value={role} onChange={(e) => set('role', e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 bg-white">
          <option value="">{en ? '— by role —' : '— حسب الدور —'}</option>
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_NAMES[r][en ? 1 : 0]}</option>)}
        </select>
        <select value={module} onChange={(e) => set('module', e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 bg-white">
          <option value="">{en ? '— by module —' : '— حسب الموديول —'}</option>
          {(index?.modules || []).map((m) => <option key={m.key} value={m.key}>{m.icon} {pick(m.title, lang)}</option>)}
        </select>
        <div className="flex border border-gray-300 rounded-lg overflow-hidden">
          {['ar', 'en'].map((l) => (
            <button key={l} type="button" onClick={() => set('lang', l)}
                    className={`px-3 py-1.5 ${lang === l ? 'bg-brand-600 text-white' : 'bg-white'}`}>{l === 'ar' ? 'عربي' : 'English'}</button>
          ))}
        </div>
        <button type="button" onClick={() => window.print()} disabled={!data}
                className="ms-auto bg-brand-600 text-white rounded-lg px-4 py-1.5 disabled:opacity-50">
          🖨️ {en ? 'Print / save as PDF' : 'طباعة / حفظ PDF'}
        </button>
      </div>

      <div className="max-w-4xl mx-auto px-8 py-8 space-y-6">
        {isLoading && <div className="text-gray-500">{label('loading', lang)}</div>}
        {isError && <div className="text-red-600">{en ? 'Could not load the manual.' : 'تعذّر تحميل الدليل.'}</div>}
        {data && (
          <>
            {/* cover + contents */}
            <section className="space-y-4">
              <div className="text-sm text-gray-500">{en ? 'ElRezeiky Pharmacies' : 'صيدليات الرزيقي'}</div>
              <h1 className="text-3xl font-bold">📖 {title}</h1>
              <p className="text-sm text-gray-600 leading-7">
                {en
                  ? 'Generated from the in-app help guide — the same text you see when you press F1. Read the chapters in order; each screen lists what it is for, its tabs, how to use it, and common mistakes.'
                  : 'هذا الدليل مأخوذ من «دليل الاستخدام» داخل النظام — نفس الشرح اللي بيظهر لما تضغط F1. اقرأ الفصول بالترتيب؛ كل شاشة فيها دورها، تبويباتها، طريقة استخدامها، والأخطاء الشائعة.'}
              </p>
              <div className="text-xs text-gray-500">
                {en ? 'Help last updated' : 'آخر تحديث للشرح'}: <span className="tabnum">{data.updated}</span>
                {' · '}{en ? 'Printed' : 'تاريخ الطباعة'}: <span className="tabnum">{new Date(data.generated_at).toLocaleDateString('en-GB')}</span>
                {' · '}{data.screens.length} {en ? 'screens' : 'شاشة'}
              </div>
              <div className="border border-gray-200 rounded-lg p-4">
                <div className="font-bold mb-2">{en ? 'Contents' : 'المحتويات'}</div>
                <ol className="space-y-1 text-sm list-decimal ps-5">
                  {data.modules.map((m) => (
                    <li key={m.key}>
                      <span className="font-semibold">{m.icon} {pick(m.title, lang)}</span>
                      <span className="text-gray-500"> — {data.screens.filter((s) => s.module === m.key).map((s) => pick(s.title, lang)).join('، ')}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </section>

            {data.modules.map((m, mi) => (
              <section key={m.key} className="space-y-4">
                <h2 className="chapter text-2xl font-bold border-b-2 border-gray-800 pb-1 pt-4">
                  {mi + 1}. {m.icon} {pick(m.title, lang)}
                </h2>
                <p className="text-sm leading-7 whitespace-pre-line">{pick(m.summary, lang)}</p>
                {m.workflows.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="font-bold">{label('workflow', lang)}</h3>
                    {m.workflows.map((wf, i) => <Workflow key={i} wf={wf} lang={lang} />)}
                  </div>
                )}
                {data.screens.filter((s) => s.module === m.key).map((s, si) => (
                  <Screen key={s.key} s={s} n={`${mi + 1}.${si + 1}`} lang={lang} />
                ))}
              </section>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function Block({ title, children }) {
  return (
    <div className="space-y-1">
      <div className="blk-title text-xs font-bold text-gray-500 uppercase tracking-wide">{title}</div>
      {children}
    </div>
  )
}

function Screen({ s, n, lang }) {
  const P = ({ t }) => <p className="text-sm leading-7 whitespace-pre-line">{pick(t, lang)}</p>
  return (
    <article className="border border-gray-200 rounded-lg p-4 space-y-3">
      <h3 className="text-lg font-bold">{n} {pick(s.title, lang)}</h3>
      <Block title={label('purpose', lang)}><P t={s.summary} /></Block>
      {s.audience && pick(s.audience, lang) && <Block title={label('audience', lang)}><P t={s.audience} /></Block>}
      {s.tabs?.length > 0 && (
        <Block title={label('tabs', lang)}>
          <ul className="space-y-1.5">
            {s.tabs.map((t) => (
              <li key={t.key} className="text-sm leading-7"><span className="font-semibold">{pick(t.title, lang)}: </span>{pick(t.body, lang)}</li>
            ))}
          </ul>
        </Block>
      )}
      {s.steps?.length > 0 && (
        <Block title={label('howto', lang)}>
          <ol className="list-decimal ps-5 space-y-1 text-sm leading-7">
            {s.steps.map((st, i) => <li key={i} className="whitespace-pre-line">{pick(itemText(st), lang)}</li>)}
          </ol>
        </Block>
      )}
      {s.tips?.length > 0 && (
        <Block title={label('tips', lang)}>
          <ul className="list-disc ps-5 space-y-1 text-sm leading-7">
            {s.tips.map((t, i) => <li key={i} className="whitespace-pre-line">{pick(itemText(t), lang)}</li>)}
          </ul>
        </Block>
      )}
      {s.faq?.length > 0 && (
        <Block title={label('faq', lang)}>
          {s.faq.map((f, i) => (
            <div key={i} className="text-sm leading-7"><div className="font-semibold">{pick(f.q, lang)}</div><div>{pick(f.a, lang)}</div></div>
          ))}
        </Block>
      )}
      {s.notes && pick(s.notes, lang) && <Block title={label('notes', lang)}><P t={s.notes} /></Block>}
    </article>
  )
}
