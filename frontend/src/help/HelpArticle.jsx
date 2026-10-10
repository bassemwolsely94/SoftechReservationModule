/**
 * HelpArticle — renders one screen's help (the /api/help/screens/<key>/ payload).
 * Shared by the side panel and the /help center. Display only.
 */
import { useEffect, useRef } from 'react'
import { pick, itemText, itemRoles, label } from './text'

const Section = ({ title, children, className = '' }) => (
  <section className={`space-y-2 ${className}`}>
    <h3 className="text-xs font-bold text-brand-600 tracking-wide">{title}</h3>
    {children}
  </section>
)

const P = ({ children }) => <p className="text-sm text-content leading-7 whitespace-pre-line">{children}</p>

export function Workflow({ wf, lang }) {
  const byKey = Object.fromEntries((wf.states || []).map((s) => [s.key, s]))
  return (
    <div className="space-y-2">
      {wf.title && <div className="text-sm font-semibold text-content">{pick(wf.title, lang)}</div>}
      {wf.intro && <P>{pick(wf.intro, lang)}</P>}
      <ol className="space-y-1.5">
        {(wf.states || []).map((st, i) => (
          <li key={st.key} className="rounded-lg border border-line bg-surface-2 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="w-5 h-5 shrink-0 rounded-full bg-brand-600 text-white text-[10px] flex items-center justify-center tabnum">{i + 1}</span>
              <span className="text-sm font-semibold text-content">{pick(st.label, lang)}</span>
            </div>
            {st.desc && <p className="text-xs text-muted leading-6 mt-1 whitespace-pre-line">{pick(st.desc, lang)}</p>}
            {st.next?.length > 0 && (
              <div className="text-[11px] text-faint mt-1">
                {label('next', lang)}: {st.next.map((n) => pick(byKey[n]?.label, lang) || n).join(' / ')}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function HelpArticle({ data, lang, tab, role, showAllRoles = false, onOpenScreen, showModule = true }) {
  const currentTabRef = useRef(null)

  useEffect(() => {
    if (currentTabRef.current) currentTabRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [data?.key, tab])

  if (!data) return null
  const roleOk = (it) => showAllRoles || !itemRoles(it) || itemRoles(it).includes(role)
  const steps = (data.steps || []).filter(roleOk)
  const tips = (data.tips || []).filter(roleOk)
  const tabs = data.tabs || []
  const hasTab = tabs.some((t) => t.key === tab)
  const workflows = data.module?.workflows || []

  return (
    <div className="space-y-5">
      <Section title={label('purpose', lang)}>
        <P>{pick(data.summary, lang)}</P>
      </Section>

      {data.audience && pick(data.audience, lang) && (
        <Section title={label('audience', lang)}><P>{pick(data.audience, lang)}</P></Section>
      )}

      {tabs.length > 0 && (
        <Section title={label('tabs', lang)}>
          <div className="space-y-1.5">
            {tabs.map((t) => {
              const here = hasTab && t.key === tab
              return (
                <details key={t.key} open={here || tabs.length <= 3} ref={here ? currentTabRef : null}
                         className={`rounded-lg border px-3 py-2 ${here ? 'border-brand-400 bg-brand-50' : 'border-line bg-surface-2'}`}>
                  <summary className="cursor-pointer text-sm font-semibold text-content flex items-center gap-2">
                    <span className="flex-1">{pick(t.title, lang)}</span>
                    {here && <span className="text-[10px] font-bold text-brand-700 bg-white/70 border border-brand-300 rounded px-1.5">{label('youAreHere', lang)}</span>}
                  </summary>
                  <p className="text-sm text-content leading-7 mt-1.5 whitespace-pre-line">{pick(t.body, lang)}</p>
                </details>
              )
            })}
          </div>
        </Section>
      )}

      {steps.length > 0 && (
        <Section title={label('howto', lang)}>
          <ol className="space-y-1.5">
            {steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-content leading-7">
                <span className="shrink-0 w-5 h-5 mt-1 rounded-full bg-surface-3 text-[10px] font-bold flex items-center justify-center tabnum">{i + 1}</span>
                <span className="whitespace-pre-line">{pick(itemText(s), lang)}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {workflows.length > 0 && (
        <Section title={label('workflow', lang)}>
          <div className="space-y-4">{workflows.map((wf, i) => <Workflow key={i} wf={wf} lang={lang} />)}</div>
        </Section>
      )}

      {tips.length > 0 && (
        <Section title={label('tips', lang)}>
          <ul className="space-y-1.5">
            {tips.map((t, i) => (
              <li key={i} className="text-sm text-content leading-7 flex gap-2">
                <span className="text-amber-500 shrink-0">●</span>
                <span className="whitespace-pre-line">{pick(itemText(t), lang)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.faq?.length > 0 && (
        <Section title={label('faq', lang)}>
          <div className="space-y-1.5">
            {data.faq.map((f, i) => (
              <details key={i} className="rounded-lg border border-line px-3 py-2">
                <summary className="cursor-pointer text-sm font-semibold text-content">{pick(f.q, lang)}</summary>
                <p className="text-sm text-content leading-7 mt-1.5 whitespace-pre-line">{pick(f.a, lang)}</p>
              </details>
            ))}
          </div>
        </Section>
      )}

      {data.notes && pick(data.notes, lang) && (
        <Section title={label('notes', lang)}>
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 leading-7 whitespace-pre-line">
            {pick(data.notes, lang)}
          </div>
        </Section>
      )}

      {showModule && data.module?.summary && (
        <Section title={`${label('module', lang)} — ${pick(data.module.title, lang)}`}>
          <P>{pick(data.module.summary, lang)}</P>
        </Section>
      )}

      {data.related?.length > 0 && (
        <Section title={label('related', lang)}>
          <ScreenLinks items={data.related} lang={lang} onOpen={onOpenScreen} />
        </Section>
      )}
      {data.siblings?.length > 0 && (
        <Section title={label('otherScreens', lang)}>
          <ScreenLinks items={data.siblings} lang={lang} onOpen={onOpenScreen} />
        </Section>
      )}
    </div>
  )
}

export function ScreenLinks({ items, lang, onOpen }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <button key={s.key} type="button" onClick={() => onOpen && onOpen(s.key)}
                className="text-xs border border-line rounded-full px-2.5 py-1 text-content hover:bg-brand-50 hover:border-brand-300">
          {pick(s.title, lang)}
        </button>
      ))}
    </div>
  )
}
