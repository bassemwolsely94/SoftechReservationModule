/**
 * HelpPanel — the in-app help side panel (دليل الاستخدام).
 *
 * Opens with F1, the header "؟" button, or window event 'help:open'
 * ({ detail: { key?, tab? } }). Shows the help of the screen + tab the user is on.
 * It is a docked panel, not a modal: the page stays usable while reading (calm UI).
 * Mounted once in Layout and once in MobileLayout.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useLangStore from '../store/langStore'
import useHelpStore from './helpStore'
import { useCurrentHelp } from './useHelpIndex'
import HelpArticle from './HelpArticle'
import HelpEditor from './HelpEditor'
import HelpFeedback from './HelpFeedback'
import { LearnedButton } from './Onboarding'
import TourRunner from './Tour'
import AskBox from './AskBox'
import { pick, label } from './text'

/** Global keyboard / event wiring — mount once per shell. */
export function useHelpShortcuts() {
  const toggle = useHelpStore((s) => s.toggle)
  const open = useHelpStore((s) => s.open)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'F1') { e.preventDefault(); toggle() }
    }
    const onOpen = (e) => open(e?.detail?.key || null, e?.detail?.tab || null)
    window.addEventListener('keydown', onKey)
    window.addEventListener('help:open', onOpen)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('help:open', onOpen) }
  }, [toggle, open])
}

export default function HelpPanel() {
  useHelpShortcuts()
  const isOpen = useHelpStore((s) => s.isOpen)
  return <>{isOpen && <PanelBody />}<TourRunner /></>
}

function PanelBody() {
  const { close, open, forcedKey, forcedTab, markSeen, startTour } = useHelpStore()
  const helpLang = useHelpStore((s) => s.lang)
  const setHelpLang = useHelpStore((s) => s.setLang)
  const uiLang = useLangStore((s) => s.lang)
  const lang = helpLang || uiLang || 'ar'
  const role = useAuthStore((s) => s.user?.role)
  const { screen, tab: currentTab } = useCurrentHelp()

  const key = forcedKey || screen?.key || null
  const tab = forcedKey ? forcedTab : currentTab
  const [editing, setEditing] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => { setEditing(false) }, [key])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !editing) close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close, editing])

  const { data, isLoading } = useQuery({
    queryKey: ['help', 'screen', key],
    queryFn: () => helpApi.screen(key, tab ? { tab } : {}).then((r) => r.data),
    enabled: !!key,
    staleTime: 0,
  })
  useEffect(() => { if (data) markSeen(data.key, data.updated) }, [data, markSeen])

  const term = q.trim()
  const results = useQuery({
    queryKey: ['help', 'search', term],
    queryFn: () => helpApi.search(term).then((r) => r.data),
    enabled: term.length >= 2,
    staleTime: 60_000,
  })

  const dir = lang === 'en' ? 'ltr' : 'rtl'
  const openScreen = (k) => { setQ(''); open(k, null) }

  return (
    <aside dir={dir}
           className="fixed top-0 bottom-0 left-0 z-[9996] w-full sm:w-[440px] bg-surface border-e border-line shadow-2xl flex flex-col animate-slide-left"
           role="complementary" aria-label={label('guide', lang)}>
      {/* header */}
      <div className="shrink-0 border-b border-line px-4 pt-3 pb-2 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">📖</span>
          <div className="flex-1 min-w-0">
            <div className="text-[11px] text-faint truncate">
              {data?.module ? `${data.module.icon || ''} ${pick(data.module.title, lang)}` : label('guide', lang)}
            </div>
            <div className="font-bold text-content truncate">{data ? pick(data.title, lang) : label('help', lang)}</div>
          </div>
          <div className="flex items-center border border-line rounded-lg overflow-hidden text-xs">
            {['ar', 'en'].map((l) => (
              <button key={l} type="button" onClick={() => setHelpLang(l)}
                      className={`px-2 py-1 ${lang === l ? 'bg-brand-600 text-white' : 'text-muted hover:bg-surface-3'}`}>
                {l === 'ar' ? 'ع' : 'EN'}
              </button>
            ))}
          </div>
          <button type="button" onClick={close} title={label('close', lang)}
                  className="text-faint hover:text-content text-xl leading-none px-1">×</button>
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={label('search', lang)}
               className="w-full text-sm bg-surface-2 border border-line rounded-lg px-3 py-1.5 text-content placeholder-faint outline-none focus:border-brand-400" />
        {forcedKey && screen && forcedKey !== screen.key && !term && (
          <button type="button" onClick={() => open(null, null)} className="text-xs text-brand-600 hover:underline">
            ← {label('back', lang)}
          </button>
        )}
      </div>

      {/* body */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {term.length >= 2 ? (
          <div className="space-y-1">
            {term.length >= 3 && <div className="mb-2"><AskBox question={term} lang={lang} screenKey={screen?.key} onOpen={openScreen} /></div>}
            {results.isLoading && <div className="text-sm text-faint">{label('loading', lang)}</div>}
            {results.data && results.data.length === 0 && <div className="text-sm text-faint">{label('noResults', lang)}</div>}
            {(results.data || []).map((r) => (
              <button key={r.key} type="button" onClick={() => openScreen(r.key)}
                      className="w-full text-start rounded-lg px-3 py-2 hover:bg-surface-3 border border-transparent hover:border-line">
                <div className="text-sm font-semibold text-content">{r.icon} {pick(r.title, lang)}</div>
                <div className="text-xs text-muted line-clamp-2">{pick(r.summary, lang)}</div>
                <div className="text-[10px] text-faint">{pick(r.module_title, lang)}</div>
              </button>
            ))}
          </div>
        ) : !key ? (
          <div className="text-sm text-muted space-y-3">
            <p>{label('noHelp', lang)}</p>
          </div>
        ) : isLoading || !data ? (
          <div className="text-sm text-faint">{label('loading', lang)}</div>
        ) : editing ? (
          <HelpEditor data={data} onDone={() => setEditing(false)} />
        ) : (
          <>
            {data.override?.base_changed && data.can_edit && (
              <div className="mb-3 rounded-lg bg-amber-50 border border-amber-300 px-3 py-2 text-xs text-amber-900">
                {label('baseChanged', lang)}
              </div>
            )}
            <HelpArticle data={data} lang={lang} tab={tab} role={role} showAllRoles={data.can_edit}
                         onOpenScreen={openScreen} />
            <div className="mt-6 pt-4 border-t border-line text-[11px] text-faint flex flex-wrap gap-x-3 gap-y-1">
              {data.updated && <span>{label('updated', lang)}: <span className="tabnum">{data.updated}</span></span>}
              {data.override?.updated_by && <span>{label('editedBy', lang)}: {data.override.updated_by}</span>}
            </div>
          </>
        )}
      </div>

      {/* footer */}
      {!editing && (
        <div className="shrink-0 border-t border-line px-4 py-2.5 space-y-2">
          {data && !term && <HelpFeedback screenKey={data.key} tab={tab} lang={lang} />}
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {data && !term && data.tour?.length > 0 && data.key === screen?.key && (
              <button type="button" onClick={() => startTour(data.key, data.tour)}
                      className="text-xs bg-brand-600 text-white rounded-lg px-3 py-1.5 hover:bg-brand-700">
                👆 {lang === 'en' ? 'Show me' : 'اعرض لي'}
              </button>
            )}
            {data && !term && <LearnedButton screenKey={data.key} lang={lang} />}
            <Link to="/help" onClick={close} className="text-brand-600 hover:underline">{label('openCenter', lang)}</Link>
            <Link to="/help?tab=path" onClick={close} className="text-brand-600 hover:underline">🎓 {lang === 'en' ? 'My path' : 'مساري'}</Link>
            {data?.can_edit && !term && (
              <button type="button" onClick={() => setEditing(true)} className="ms-auto text-brand-600 hover:underline">
                ✏️ {label('edit', lang)}
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}
