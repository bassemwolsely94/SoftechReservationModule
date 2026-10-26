/**
 * TourRunner — «اعرض لي»: walks the user through a screen by spotlighting the real
 * elements, one step at a time. Steps come from the screen's help (`tour`) or a module
 * journey, and find their element with [data-tour="<target>"]. A step may carry:
 *   label (the button's name, shown bold) · text (what it does) · when (when to use it /
 *   what happens next) · warn (⚠ the costly mistake — amber ring and box) ·
 *   open_hint (how to make the element appear: a tab, a record, a status).
 *
 * Journeys («رحلة عمل») cross screens: each step names its screen's routes; when the
 * user is elsewhere the card offers «روح للشاشة» (a plain page open, only for pages
 * without a record id and only when the user's role may view it) or says which record
 * to open, and continues by itself once the user is there.
 *
 * Calm by design: nothing blocks the page (the dimmed mask ignores clicks, so the
 * highlighted button can be pressed for real) and the tour never clicks or saves
 * anything itself. Esc / «إنهاء» ends it; leaving the screen ends a screen tour
 * (not a journey).
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

function findTarget(id) {
  const el = document.querySelector(`[data-tour="${id}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (r.width === 0 && r.height === 0) return null          // rendered but hidden
  return { el, r }
}

const onRoutes = (routes, pathname) =>
  !routes?.length || routes.some((r) => matchPath({ path: r, end: true }, pathname))

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
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const startPath = useRef(pathname)
  const cardRef = useRef(null)
  const [rect, setRect] = useState(null)
  const [cardH, setCardH] = useState(220)
  const [tick, setTick] = useState(0)
  const step = tour.steps[tour.i]
  const last = tour.i === tour.steps.length - 1
  const here = !tour.journey || onRoutes(step.routes, pathname)
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

  // leaving the screen ends a screen tour; a journey is meant to move between screens
  useEffect(() => {
    if (!tour.journey && pathname !== startPath.current) endTour()
  }, [pathname, endTour, tour.journey])

  // bring the element into view when the step changes (or the user reaches its screen)
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

  // the card grows with the step's text — place it by its real height
  useLayoutEffect(() => {
    if (cardRef.current) setCardH(cardRef.current.offsetHeight)
  }, [tour.i, rect == null, here, lang])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); endTour() }
      if (e.key === 'Enter' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        e.preventDefault(); last ? finish() : tourStep(tour.i + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tour.i, last, endTour, tourStep])  // eslint-disable-line react-hooks/exhaustive-deps

  const vw = window.innerWidth
  const vh = window.innerHeight
  const cardW = Math.min(340, vw - 24)
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
  const pct = Math.round(((tour.i + 1) / tour.steps.length) * 100)

  return (
    <div className="fixed inset-0 z-[90] pointer-events-none" dir={en ? 'ltr' : 'rtl'} aria-live="polite">
      {rect ? (
        <div className="tour-ring absolute rounded-lg transition-all duration-200"
             style={{
               '--tour-ring': ring,
               top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
               outline: `2px solid rgb(${ring})`, outlineOffset: 0,
               boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.45)',
             }}>
          <span key={`${tour.i}-${step.target}`} className="tour-pulse absolute inset-0 rounded-lg" style={{ '--tour-ring': ring }} />
        </div>
      ) : (
        <div className="absolute inset-0 bg-slate-900/30" />
      )}
      <div ref={cardRef} className="absolute pointer-events-auto rounded-xl bg-surface border border-line shadow-xl p-4 space-y-2.5 max-h-[80vh] overflow-y-auto"
           style={cardStyle}>
        <div className="flex items-center gap-2 text-[11px] text-faint">
          <span className="font-bold text-brand-600 truncate">
            {tour.journey ? `🧭 ${pick(tour.title, lang)}` : tr('👆 اعرض لي', '👆 Show me')}
          </span>
          <span className="tabnum shrink-0">{tour.i + 1} / {tour.steps.length}</span>
          <button type="button" onClick={endTour} className="ms-auto shrink-0 hover:text-content">{tr('إنهاء ✕', 'End ✕')}</button>
        </div>
        <div className="h-1 rounded-full bg-surface-2 overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
        </div>

        {tour.journey && step.screen_title && (
          <div className="text-[11px] text-muted">📍 {pick(step.screen_title, lang)}</div>
        )}
        {step.label && (
          <div className="text-[15px] font-bold text-brand-700 dark:text-brand-300 leading-6">«{pick(step.label, lang)}»</div>
        )}
        <p className="text-sm text-content leading-7 whitespace-pre-line">{pick(step.text, lang)}</p>
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

        {!here && (
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
        {here && !rect && (
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
          <button type="button" onClick={() => (last ? finish() : tourStep(tour.i + 1))}
                  className="ms-auto text-xs bg-brand-600 text-white rounded-lg px-4 py-1.5 hover:bg-brand-700">
            {last ? tr('تمام', 'Done') : tr('التالي', 'Next')}
          </button>
        </div>
      </div>
    </div>
  )
}
