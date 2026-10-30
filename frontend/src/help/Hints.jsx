/**
 * Button emphasis outside a tour — both read the same «اعرض لي» text the tours use
 * (the screen's `tour` + its module's journey steps on this screen); no text of their own.
 *
 *   HintsLayer — «💡 تلميحات الأزرار» (Ctrl+F1 or the help panel): every explained
 *                element gets a dashed outline (amber when the step has a ⚠), and hovering
 *                or focusing it shows a small card: «label», what it does, «متى؟», ⚠.
 *                The card never takes clicks; the button works as usual.
 *   TourOffer  — a small «جديد هنا؟ 👆 اعرض لي» chip, once per screen version, for a
 *                screen whose help the user has not read yet. No modal; ✕ or leaving
 *                the screen hides it.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useLangStore from '../store/langStore'
import useHelpStore from './helpStore'
import { useCurrentHelp } from './useHelpIndex'
import { pick } from './text'

const BRAND = 'var(--c-brand-400)'
const WARN = '245 158 11'          // amber-500, as the tour ring

/** The screen's help payload, without counting as "help opened" in the trainers' report. */
function useScreenHelp(key, enabled) {
  return useQuery({
    queryKey: ['help', 'hints', key],
    queryFn: () => helpApi.screen(key, { log: '0' }).then((r) => r.data),
    enabled: !!key && enabled,
    staleTime: 5 * 60_000,
  })
}

/** target → step: the screen's own tour wins over a journey step on the same anchor. */
export function hintSteps(data) {
  const map = new Map()
  if (!data) return map
  for (const j of data.module?.journeys || []) {
    for (const st of j.steps || []) if (st.screen === data.key && !map.has(st.target)) map.set(st.target, st)
  }
  for (const st of data.tour || []) map.set(st.target, st)
  return map
}

const cssId = (t) => t.replace(/[^a-z0-9-]/g, '')

function useLang() {
  const helpLang = useHelpStore((s) => s.lang)
  const uiLang = useLangStore((s) => s.lang)
  return helpLang || uiLang || 'ar'
}

export function HintsLayer() {
  const hints = useHelpStore((s) => s.hints)
  const tour = useHelpStore((s) => s.tour)
  const { screen } = useCurrentHelp()
  const on = hints && !tour && !!screen?.has_tour
  const { data } = useScreenHelp(screen?.key, on)
  const steps = useMemo(() => hintSteps(data), [data])
  if (!hints || tour) return null
  return <HintsBody steps={on ? steps : new Map()} />
}

function HintsBody({ steps }) {
  const toggleHints = useHelpStore((s) => s.toggleHints)
  const lang = useLang()
  const en = lang === 'en'
  const tr = (ar, e) => (en ? e : ar)
  const [active, setActive] = useState(null)        // { step, rect }

  useEffect(() => {
    const find = (node) => {
      const el = node?.closest?.('[data-tour]')
      const step = el && steps.get(el.getAttribute('data-tour'))
      return step ? { el, step } : null
    }
    const show = (e) => {
      const hit = find(e.target)
      if (!hit) return
      const r = hit.el.getBoundingClientRect()
      setActive({ step: hit.step, el: hit.el, rect: { top: r.top, left: r.left, width: r.width, height: r.height } })
    }
    const hide = (e) => {
      setActive((cur) => (cur && !cur.el.contains(e.relatedTarget) ? null : cur))
    }
    const clear = () => setActive(null)
    document.addEventListener('pointerover', show)
    document.addEventListener('focusin', show)
    document.addEventListener('pointerout', hide)
    document.addEventListener('focusout', hide)
    window.addEventListener('scroll', clear, true)
    window.addEventListener('resize', clear)
    return () => {
      document.removeEventListener('pointerover', show)
      document.removeEventListener('focusin', show)
      document.removeEventListener('pointerout', hide)
      document.removeEventListener('focusout', hide)
      window.removeEventListener('scroll', clear, true)
      window.removeEventListener('resize', clear)
    }
  }, [steps])

  // outline every explained element on this screen (the element itself is not touched)
  const css = useMemo(() => {
    const rule = (sel, rgb) => `${sel}{outline:2px dashed rgb(${rgb});outline-offset:2px;cursor:help}`
    const normal = [], warn = []
    steps.forEach((st, t) => (st.warn ? warn : normal).push(`[data-tour="${cssId(t)}"]`))
    return [normal.length && rule(normal.join(','), BRAND), warn.length && rule(warn.join(','), WARN)]
      .filter(Boolean).join('\n')
  }, [steps])

  const vw = window.innerWidth
  const vh = window.innerHeight
  const cardW = Math.min(300, vw - 24)
  let cardStyle = null
  if (active) {
    const { rect } = active
    const below = rect.top + rect.height + 10
    const top = below + 160 < vh ? below : Math.max(8, rect.top - 10 - 160)
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - cardW / 2), vw - cardW - 12)
    cardStyle = { top, left, width: cardW }
  }
  const step = active?.step

  return (
    <>
      <style>{css}</style>
      {step && (
        <div role="tooltip" dir={en ? 'ltr' : 'rtl'} style={cardStyle}
             className="fixed z-[95] pointer-events-none rounded-xl bg-surface border border-line shadow-xl p-3 space-y-1.5 animate-fade-in">
          {step.label && (
            <div className="text-sm font-bold text-brand-700 dark:text-brand-300 leading-6">«{pick(step.label, lang)}»</div>
          )}
          <p className="text-xs text-content leading-6 whitespace-pre-line">{pick(step.text, lang)}</p>
          {step.when && (
            <p className="text-[11px] text-muted leading-5 whitespace-pre-line">
              <span className="font-semibold text-content">{tr('متى؟ ', 'When: ')}</span>{pick(step.when, lang)}
            </p>
          )}
          {step.warn && (
            <p className="text-[11px] leading-5 rounded-lg border border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100 dark:border-amber-700 px-2 py-1 whitespace-pre-line">
              ⚠ {pick(step.warn, lang)}
            </p>
          )}
        </div>
      )}
      <div dir={en ? 'ltr' : 'rtl'}
           className="no-print fixed bottom-24 sm:bottom-4 start-4 z-[94] flex items-center gap-2 rounded-full bg-brand-600 text-white text-xs shadow-lg ps-3 pe-1 py-1">
        <span>💡 {steps.size
          ? tr(`تلميحات الأزرار شغالة — ${steps.size} عنصر مشروح هنا`, `Button hints on — ${steps.size} explained here`)
          : tr('تلميحات الأزرار شغالة — مفيش شرح أزرار للشاشة دي', 'Button hints on — none for this screen')}</span>
        <span className="hidden sm:inline opacity-75">Ctrl+F1</span>
        <button type="button" onClick={toggleHints} data-tour="general-help-center-hints-off"
                className="rounded-full bg-white/20 hover:bg-white/30 px-2 py-0.5">
          {tr('إيقاف ✕', 'Off ✕')}
        </button>
      </div>
    </>
  )
}

export function TourOffer() {
  const { screen } = useCurrentHelp()
  const { tour, isOpen, hints, seen, offered, markOffered, startTour } = useHelpStore()
  const lang = useLang()
  const en = lang === 'en'
  const key = screen?.key
  const fresh = !!(screen?.has_tour && screen.updated && seen[key] !== screen.updated && offered[key] !== screen.updated)
  const [shown, setShown] = useState(null)          // the screen key the chip is showing for

  // wait a moment after arriving (no flash while passing through), then offer once
  useEffect(() => {
    if (!fresh || tour || isOpen || hints) return
    const t = setTimeout(() => { setShown(key); markOffered(key, screen.updated) }, 1500)
    return () => clearTimeout(t)
  }, [key, fresh, tour, isOpen, hints]) // eslint-disable-line react-hooks/exhaustive-deps

  const visible = shown && shown === key && !tour && !isOpen && !hints   // the hints bar sits in the same corner
  const { data } = useScreenHelp(key, !!visible)
  if (!visible) return null

  return (
    <div dir={en ? 'ltr' : 'rtl'} data-tour="general-help-center-offer"
         className="no-print fixed bottom-24 sm:bottom-4 start-4 z-[94] flex items-center gap-2 rounded-xl bg-surface border border-brand-300 shadow-lg ps-3 pe-1.5 py-1.5 text-xs animate-fade-in">
      <span className="text-content">{en ? 'New here?' : 'جديد هنا؟'}</span>
      <button type="button" disabled={!data?.tour?.length}
              onClick={() => { setShown(null); startTour(data.key, data.tour) }}
              className="bg-brand-600 text-white rounded-lg px-3 py-1 hover:bg-brand-700 disabled:opacity-50">
        👆 {en ? 'Show me this screen' : 'اعرض لي الشاشة دي'}
      </button>
      <button type="button" onClick={() => setShown(null)} aria-label={en ? 'Not now' : 'مش دلوقتي'}
              className="text-faint hover:text-content px-1.5">✕</button>
    </div>
  )
}
