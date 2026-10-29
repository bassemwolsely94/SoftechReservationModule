/**
 * TourRunner — «اعرض لي»: walks the user through the system by spotlighting (and
 * zooming into) the real elements, one step at a time. Steps find their element with
 * [data-tour="<target>"] and come from:
 *   • a screen's `tour_flow` — its own tour, then the continued screen's (list → detail)
 *   • a module workflow tour (`flows`, key 'flow:<module>.<key>')
 *   • a module journey (`journeys`, key 'journey:<module>.<key>')
 *
 * A step may carry
 *   label (the button's name, shown bold) · text (what it does) · when (when to use it /
 *   what happens next) · warn (⚠ the costly mistake — amber ring and box) ·
 *   open_hint (how to make the element appear: a tab, a record, a status)
 * and, to cross pages:
 *   route — the page it lives on; the runner opens it (when it has no :params)
 *   wait  — the step waits for the user to open that page (e.g. click a row → detail)
 *   nav   — open that page's side-menu group first, to point at its menu item
 * Journey steps instead carry their screen's `routes` (+ a param-free `route`): when the
 * user is elsewhere the card offers «روح للشاشة» (only when their role may view it) or
 * says which record to open, and continues by itself once the user is there.
 *
 * Each step has a one-line headline (`text`) and, under it, the longer explanation
 * (`more`: what the button does, when to use it, what happens next, what to watch for).
 *
 * Calm by design: started only on request, nothing blocks the page (the dimmed mask
 * ignores clicks, so the highlighted button can be pressed for real) and the tour never
 * clicks or saves anything itself. Esc / «إنهاء» ends it. Screen tours and workflow
 * tours end when the user goes to a page they do not expect; journeys keep going.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'
import { helpApi } from '../api/client'
import useLangStore from '../store/langStore'
import usePermissionStore from '../store/permissionStore'
import useHelpStore from './helpStore'
import { pick } from './text'

const PAD = 6
const BRAND_RING = 'var(--c-brand-400)'
const WARN_RING = '245 158 11'          // amber-500

const on = (pattern, path) => !!pattern && !!matchPath({ path: pattern, end: true }, path)

function findTarget(id) {
  const el = document.querySelector(`[data-tour="${id}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (r.width === 0 && r.height === 0) return null          // rendered but hidden
  return { el, r }
}

export default function TourRunner() {
  const tour = useHelpStore((s) => s.tour)
  if (!tour) return null
  return <TourBody tour={tour} />
}

function TourBody({ tour }) {
  const { tourStep, endTour } = useHelpStore()
  const helpLang = useHelpStore((s) => s.lang)
  const uiLang = useLangStore((s) => s.lang)
  const can = usePermissionStore((s) => s.can)
  usePermissionStore((s) => s.permissions)                  // re-render once they load
  const lang = helpLang || uiLang || 'ar'
  const en = lang === 'en'
  const tr = (ar, e) => (en ? e : ar)
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const startPath = useRef(pathname)
  const cardRef = useRef(null)
  const isFlow = tour.key.startsWith('flow:')
  const isJourney = tour.journey || tour.key.startsWith('journey:')
  const [rect, setRect] = useState(null)
  const [cardH, setCardH] = useState(220)
  const [tick, setTick] = useState(0)
  const step = tour.steps[tour.i]
  const last = tour.i === tour.steps.length - 1
  const next = tour.steps[tour.i + 1]

  // the page a step lives on: its route, else (screen tours) the page the tour started on;
  // workflow-tour steps without a route (the app frame) live on any page
  const pageOf = (st) => st?.route || (isFlow ? null : startPath.current)
  // journey steps: on any of their screen's routes; others: on their page (or anywhere)
  const here = isJourney
    ? !step.routes?.length || step.routes.some((r) => on(r, pathname))
    : !pageOf(step) || on(pageOf(step), pathname)
  const canOpen = !step.perm || can(step.perm, 'view')

  // usage for trainers: how far people get (sent once, when the tour really ends)
  const reached = useRef(1)
  const finished = useRef(false)
  reached.current = Math.max(reached.current, tour.i + 1)
  useEffect(() => () => {
    if (useHelpStore.getState().tour) return          // re-mount (dev), not an end
    helpApi.tourEvent({ screen_key: tour.key, reached: reached.current, done: finished.current }).catch(() => {})
  }, [tour.key])
  const finish = () => { finished.current = true; endTour() }

  // open the step's page / menu group when the step starts (not journeys — they offer «روح للشاشة»)
  useEffect(() => {
    if (step.nav) window.dispatchEvent(new CustomEvent('help:nav-show', { detail: step.nav }))
    if (isJourney) return
    const page = pageOf(step)
    if (page && !on(page, pathname) && !page.includes(':')) navigate(page)
  }, [tour.i])  // eslint-disable-line react-hooks/exhaustive-deps

  // a `wait` step continues by itself once the user opens the expected page;
  // a screen / workflow tour ends when the user goes anywhere it does not expect
  useEffect(() => {
    if (step.wait && on(step.wait, pathname)) { tourStep(tour.i + 1); return }
    if (isJourney) return
    const page = pageOf(step)
    const expected = !page || on(page, pathname) || (step.wait && on(step.wait, pathname))
      || (next && (!pageOf(next) || on(pageOf(next), pathname)))
      || (!isFlow && !step.route && (tour.routes || []).some((r) => on(r, pathname)))
    if (!expected) endTour()
  }, [pathname])  // eslint-disable-line react-hooks/exhaustive-deps

  // bring the element into view when the step changes (or the user reaches its page)
  useEffect(() => {
    if (!here) return
    const t = findTarget(step.target)
    if (t) t.el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
  }, [step.target, here])

  // follow the element (layout shifts, scrolling, data loading late)
  useLayoutEffect(() => {
    const update = () => {
      const t = here ? findTarget(step.target) : null
      setRect(t ? { top: t.r.top, left: t.r.left, width: t.r.width, height: t.r.height } : null)
    }
    update()
    const id = setInterval(update, 250)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => { clearInterval(id); window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true) }
  }, [step.target, tick, here])

  // the card grows with the step's text (and its longer explanation) — place it by its real height
  useLayoutEffect(() => {
    if (cardRef.current) setCardH(cardRef.current.offsetHeight)
  }, [tour.i, rect == null, rect?.width, here, lang])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); endTour() }
      if (e.key === 'Enter' && !step.wait && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        e.preventDefault(); last ? finish() : tourStep(tour.i + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tour.i, last, endTour, tourStep, step.wait])  // eslint-disable-line react-hooks/exhaustive-deps

  const vw = window.innerWidth
  const vh = window.innerHeight
  // a step with a longer explanation gets a wider card
  const cardW = Math.min(step.more ? 400 : 340, vw - 24)
  let cardStyle
  if (rect && rect.height > vh * 0.6) {
    // a big element (a whole table/board): keep the card out of its way, bottom corner
    cardStyle = { bottom: 12, left: 12, width: cardW }
  } else if (rect) {
    const below = rect.top + rect.height + 14
    const top = below + cardH < vh - 8 ? below : Math.max(8, rect.top - 14 - cardH)
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - cardW / 2), vw - cardW - 12)
    cardStyle = { top, left, width: cardW }
  } else {
    cardStyle = { bottom: 24, left: Math.max(12, vw / 2 - cardW / 2), width: cardW }
  }
  const ring = step.warn ? WARN_RING : BRAND_RING
  const more = pick(step.more, lang)
  const pct = Math.round(((tour.i + 1) / tour.steps.length) * 100)

  return (
    <div className="fixed inset-0 z-[90] pointer-events-none" dir={en ? 'ltr' : 'rtl'} aria-live="polite">
      {rect ? (
        // tour-spot: zoom into the element, then a soft pulse; tour-ring keeps the (amber on ⚠) outline
        <div key={tour.i} className="tour-spot tour-ring absolute rounded-lg transition-all duration-200"
             style={{
               top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
               outline: `2px solid rgb(${ring})`, outlineOffset: 0,
               boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.45)',
             }} />
      ) : (
        <div className="absolute inset-0 bg-slate-900/30" />
      )}
      <div key={`card-${tour.i}`} ref={cardRef}
           className="tour-card absolute pointer-events-auto rounded-xl bg-surface border border-line shadow-xl p-4 space-y-2.5 max-h-[80vh] overflow-y-auto"
           style={cardStyle}>
        <div className="flex items-center gap-2 text-[11px] text-faint">
          <span className="font-bold text-brand-600 truncate">
            {tour.title ? `🧭 ${pick(tour.title, lang)}` : tr('👆 اعرض لي', '👆 Show me')}
          </span>
          <span className="tabnum shrink-0">{tour.i + 1} / {tour.steps.length}</span>
          <button type="button" onClick={endTour} className="ms-auto shrink-0 hover:text-content">{tr('إنهاء ✕', 'End ✕')}</button>
        </div>
        <div className="h-1 rounded-full bg-surface-2 overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
        </div>

        {isJourney && step.screen_title && (
          <div className="text-[11px] text-muted">📍 {pick(step.screen_title, lang)}</div>
        )}
        {step.label && (
          <div className="text-[15px] font-bold text-brand-700 dark:text-brand-300 leading-6">«{pick(step.label, lang)}»</div>
        )}
        <p className="text-sm text-content leading-7 whitespace-pre-line">{pick(step.text, lang)}</p>
        {more && (
          <div className="text-[13px] text-muted leading-6 whitespace-pre-line border-s-4 border-brand-200 ps-3 max-h-[38vh] overflow-y-auto">
            {more}
          </div>
        )}
        {step.when && (
          <p className="text-xs text-muted leading-6 whitespace-pre-line">
            <span className="font-semibold text-content">{tr('متى؟ ', 'When: ')}</span>{pick(step.when, lang)}
          </p>
        )}
        {step.warn && (
          <p className="text-xs leading-6 rounded-lg border border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100 dark:border-amber-700 px-2.5 py-1.5 whitespace-pre-line">
            ⚠ {pick(step.warn, lang)}
          </p>
        )}

        {isJourney && !here && (
          <div className="text-[11px] leading-5 rounded-lg bg-brand-50 dark:bg-brand-900/30 text-content px-2.5 py-2 space-y-1.5">
            {step.route && canOpen ? (
              <>
                <div>{tr('الخطوة دي في شاشة تانية.', 'This step is on another screen.')}</div>
                <button type="button" onClick={() => navigate(step.route)}
                        className="text-xs bg-brand-600 text-white rounded-lg px-3 py-1 hover:bg-brand-700">
                  {tr('روح للشاشة ←', 'Go to screen →')}
                </button>
              </>
            ) : !canOpen ? (
              <div>{tr('الشاشة دي مش متاحة لدورك — اقرأ الخطوة واضغط «التالي».',
                       'This screen is not available for your role — read the step and press "Next".')}</div>
            ) : (
              <div>{step.open_hint ? pick(step.open_hint, lang)
                    : tr('افتح الشاشة دي وهنكمّل من هناك.', 'Open this screen and the tour continues there.')}</div>
            )}
          </div>
        )}
        {(here || !isJourney) && !rect && (
          <p className="text-[11px] text-amber-700 dark:text-amber-300 leading-5">
            {step.open_hint ? pick(step.open_hint, lang) : tr(
              'الجزء ده مش ظاهر دلوقتي على الشاشة (ممكن في تبويب تاني، أو محتاج تختار حاجة الأول، أو مش متاح لدورك).',
              'This part is not on screen right now (another tab, nothing selected yet, or not available for your role).')}
            {' '}<button type="button" onClick={() => setTick((n) => n + 1)} className="underline">{tr('دوّر تاني', 'Look again')}</button>
          </p>
        )}

        <div className="flex items-center gap-2 pt-0.5">
          {tour.i > 0 && (
            <button type="button" onClick={() => tourStep(tour.i - 1)}
                    className="text-xs border border-line rounded-lg px-3 py-1.5 text-content hover:bg-surface-2">
              {tr('السابق', 'Back')}
            </button>
          )}
          {step.wait ? (
            <span className="ms-auto text-xs font-semibold text-brand-700">
              👆 {tr('اضغط على الجزء المعلَّم عشان نكمّل', 'Click the highlighted part to continue')}
            </span>
          ) : (
            <button type="button" onClick={() => (last ? finish() : tourStep(tour.i + 1))}
                    className="ms-auto text-xs bg-brand-600 text-white rounded-lg px-4 py-1.5 hover:bg-brand-700">
              {last ? tr('تمام', 'Done') : tr('التالي', 'Next')}
            </button>
          )}
        </div>
        <div className="text-[10px] text-faint">
          {en ? 'Enter = next · Esc = end · you can press the highlighted part for real' : 'Enter = التالي · Esc = إنهاء · تقدر تضغط الجزء المعلَّم فعلاً'}
        </div>
      </div>
    </div>
  )
}

/** Start the «اعرض لي» tour of the screen the user is on (its continuation included). */
export async function startScreenTour(screenKey) {
  const { data } = await helpApi.screen(screenKey, { log: '0' })
  const steps = data.tour_flow?.length ? data.tour_flow : data.tour
  useHelpStore.getState().startTour(data.key, steps, data.routes, data.title)
}
