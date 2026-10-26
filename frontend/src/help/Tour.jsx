/**
 * TourRunner — «اعرض لي»: walks the user through the system by spotlighting (and
 * zooming into) the real elements, one step at a time. Steps come from the help
 * content — a screen's `tour_flow` or a module workflow tour (`flows`) — and find their
 * element with [data-tour="<target>"]. A step may also carry:
 *   route — the page it lives on; the runner opens it (when it has no :params)
 *   wait  — the step waits for the user to open that page (e.g. click a row → detail)
 *   nav   — open that page's side-menu group first, to point at its menu item
 *
 * Calm by design: started only on request, nothing blocks the page (the dimmed mask
 * ignores clicks, so the highlighted button can be pressed for real), Esc / «إنهاء»
 * ends it, and going to a page the tour does not expect ends it. A step whose element
 * is not on screen right now still shows its text with a note.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'
import { helpApi } from '../api/client'
import useLangStore from '../store/langStore'
import useHelpStore from './helpStore'
import { pick } from './text'

const CARD_W = 320
const PAD = 6

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
  const lang = helpLang || uiLang || 'ar'
  const en = lang === 'en'
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const startPath = useRef(pathname)
  const isFlow = tour.key.startsWith('flow:')
  const [rect, setRect] = useState(null)
  const [tick, setTick] = useState(0)
  const step = tour.steps[tour.i]
  const last = tour.i === tour.steps.length - 1

  // usage for trainers: how far people get (sent once, when the tour really ends)
  const reached = useRef(1)
  const finished = useRef(false)
  reached.current = Math.max(reached.current, tour.i + 1)
  useEffect(() => () => {
    if (useHelpStore.getState().tour) return          // re-mount (dev), not an end
    helpApi.tourEvent({ screen_key: tour.key, reached: reached.current, done: finished.current }).catch(() => {})
  }, [tour.key])
  const finish = () => { finished.current = true; endTour() }

  // the page a step lives on: its route, else (screen tours) the page the tour started on;
  // workflow-tour steps without a route (the app frame) live on any page
  const pageOf = (st) => st?.route || (isFlow ? null : startPath.current)
  const next = tour.steps[tour.i + 1]

  // open the step's page / menu group when the step starts
  useEffect(() => {
    if (step.nav) window.dispatchEvent(new CustomEvent('help:nav-show', { detail: step.nav }))
    const page = pageOf(step)
    if (page && !on(page, pathname) && !page.includes(':')) navigate(page)
  }, [tour.i])  // eslint-disable-line react-hooks/exhaustive-deps

  // a `wait` step continues by itself once the user opens the expected page;
  // going anywhere the tour does not expect ends it
  useEffect(() => {
    if (step.wait && on(step.wait, pathname)) { tourStep(tour.i + 1); return }
    const page = pageOf(step)
    const expected = !page || on(page, pathname) || (step.wait && on(step.wait, pathname))
      || (next && (!pageOf(next) || on(pageOf(next), pathname)))
      || (!isFlow && !step.route && (tour.routes || []).some((r) => on(r, pathname)))
    if (!expected) endTour()
  }, [pathname])  // eslint-disable-line react-hooks/exhaustive-deps

  // bring the element into view when the step changes
  useEffect(() => {
    const t = findTarget(step.target)
    if (t) t.el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
  }, [step.target])

  // follow the element (layout shifts, scrolling, data loading late)
  useLayoutEffect(() => {
    const update = () => {
      const t = findTarget(step.target)
      setRect(t ? { top: t.r.top, left: t.r.left, width: t.r.width, height: t.r.height } : null)
    }
    update()
    const id = setInterval(update, 250)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => { clearInterval(id); window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true) }
  }, [step.target, tick])

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
  let cardStyle
  if (rect && rect.height > vh * 0.6) {
    // a big element (a whole table/board): keep the card out of its way, bottom corner
    cardStyle = { bottom: 24, left: 24, width: CARD_W }
  } else if (rect) {
    const below = rect.top + rect.height + 12
    const top = below + 180 < vh ? below : Math.max(12, rect.top - 12 - 180)
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - CARD_W / 2), vw - CARD_W - 12)
    cardStyle = { top, left, width: CARD_W }
  } else {
    cardStyle = { bottom: 24, left: Math.max(12, vw / 2 - CARD_W / 2), width: CARD_W }
  }

  return (
    <div className="fixed inset-0 z-[90] pointer-events-none" dir={en ? 'ltr' : 'rtl'} aria-live="polite">
      {rect ? (
        <div key={tour.i} className="tour-spot absolute rounded-lg ring-2 ring-brand-400 transition-all duration-200"
             style={{
               top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
               boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.45)',
             }} />
      ) : (
        <div className="absolute inset-0 bg-slate-900/30" />
      )}
      <div key={`card-${tour.i}`} className="tour-card absolute pointer-events-auto rounded-xl bg-surface border border-line shadow-xl p-4 space-y-3" style={cardStyle}>
        <div className="flex items-center gap-2 text-[11px] text-faint">
          <span className="font-bold text-brand-600">{en ? 'Show me' : 'اعرض لي'}</span>
          <span className="tabnum">{tour.i + 1} / {tour.steps.length}</span>
          <button type="button" onClick={endTour} className="ms-auto hover:text-content">{en ? 'End ✕' : 'إنهاء ✕'}</button>
        </div>
        <p className="text-sm text-content leading-7 whitespace-pre-line">{pick(step.text, lang)}</p>
        {!rect && (
          <p className="text-[11px] text-amber-700 leading-5">
            {en
              ? 'This part is not on screen right now (another tab, nothing selected yet, or not available for your role).'
              : 'الجزء ده مش ظاهر دلوقتي على الشاشة (ممكن في تبويب تاني، أو محتاج تختار حاجة الأول، أو مش متاح لدورك).'}
            {' '}<button type="button" onClick={() => setTick((n) => n + 1)} className="underline">{en ? 'Look again' : 'دوّر تاني'}</button>
          </p>
        )}
        <div className="flex items-center gap-2">
          {tour.i > 0 && (
            <button type="button" onClick={() => tourStep(tour.i - 1)}
                    className="text-xs border border-line rounded-lg px-3 py-1.5 text-content hover:bg-surface-2">
              {en ? 'Back' : 'السابق'}
            </button>
          )}
          {step.wait ? (
            <span className="ms-auto text-xs font-semibold text-brand-700">
              👆 {en ? 'Click the highlighted part to continue' : 'اضغط على الجزء المعلَّم عشان نكمّل'}
            </span>
          ) : (
            <button type="button" onClick={() => (last ? finish() : tourStep(tour.i + 1))}
                    className="ms-auto text-xs bg-brand-600 text-white rounded-lg px-4 py-1.5 hover:bg-brand-700">
              {last ? (en ? 'Done' : 'تمام') : (en ? 'Next' : 'التالي')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** Start the «اعرض لي» tour of the screen the user is on (its continuation included). */
export async function startScreenTour(screenKey) {
  const { data } = await helpApi.screen(screenKey, { log: '0' })
  const steps = data.tour_flow?.length ? data.tour_flow : data.tour
  useHelpStore.getState().startTour(data.key, steps, data.routes)
}
