/**
 * TourRunner — «اعرض لي»: walks the user through the system by spotlighting (and
 * zooming into) the real elements, one step at a time. Steps come from the help
 * content — a screen's `tour_flow` or a module workflow tour (`flows`) — and find their
 * element with [data-tour="<target>"]. A step may also carry:
 *   route — the page it lives on; the runner opens it (when it has no :params)
 *   wait  — the step waits for the user to open that page (e.g. click a row → detail)
 *   nav   — open that page's side-menu group first, to point at its menu item
 *
 * Each step has a one-line headline (`text`) and, under it, the longer explanation
 * (`more`: what the button does, when to use it, what happens next, what to watch for).
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

const CARD_W = 400
const PAD = 8

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
  const cardRef = useRef(null)
  const [cardH, setCardH] = useState(220)
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

  // the card's real height (the explanation makes steps differ) for placing it
  useLayoutEffect(() => {
    if (cardRef.current) setCardH(cardRef.current.offsetHeight)
  }, [tour.i, rect?.width, lang])

  const vw = window.innerWidth
  const vh = window.innerHeight
  const w = Math.min(CARD_W, vw - 24)
  let cardStyle
  if (rect && rect.height > vh * 0.6) {
    // a big element (a whole table/board): keep the card out of its way, bottom corner
    cardStyle = { bottom: 16, left: 12, width: w }
  } else if (rect) {
    const below = rect.top + rect.height + PAD + 10
    const above = rect.top - PAD - 10 - cardH
    const top = below + cardH < vh - 8 ? below : above > 8 ? above : Math.max(8, vh - cardH - 8)
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - w / 2), vw - w - 12)
    cardStyle = { top, left, width: w }
  } else {
    cardStyle = { bottom: 16, left: Math.max(12, vw / 2 - w / 2), width: w }
  }
  const more = pick(step.more, lang)
  const pct = Math.round(((tour.i + 1) / tour.steps.length) * 100)

  return (
    <div className="fixed inset-0 z-[90] pointer-events-none" dir={en ? 'ltr' : 'rtl'} aria-live="polite">
      {rect ? (
        <div key={tour.i} className="tour-spot absolute rounded-xl ring-4 ring-brand-500 transition-all duration-200"
             style={{
               top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
               boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.55), 0 0 24px 4px rgba(59, 130, 246, 0.45)',
             }}>
          <span className="absolute -top-3 -start-3 h-7 w-7 rounded-full bg-brand-600 text-white text-sm font-bold grid place-items-center shadow-lg tabnum">
            {tour.i + 1}
          </span>
        </div>
      ) : (
        <div className="absolute inset-0 bg-slate-900/30" />
      )}
      <div key={`card-${tour.i}`} ref={cardRef}
           className="tour-card absolute pointer-events-auto rounded-2xl bg-surface border-2 border-brand-300 shadow-2xl p-4 space-y-3"
           style={cardStyle}>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-[11px] text-faint">
            <span className="font-bold text-brand-600 shrink-0">👆 {en ? 'Show me' : 'اعرض لي'}</span>
            {tour.title && <span className="truncate text-muted">· {pick(tour.title, lang)}</span>}
            <button type="button" onClick={endTour} className="ms-auto shrink-0 hover:text-content">{en ? 'End ✕' : 'إنهاء ✕'}</button>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-surface-3 overflow-hidden">
              <div className="h-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[11px] text-muted tabnum shrink-0">
              {en ? `Step ${tour.i + 1} of ${tour.steps.length}` : `خطوة ${tour.i + 1} من ${tour.steps.length}`}
            </span>
          </div>
        </div>
        <p className="text-[15px] font-bold text-content leading-7 whitespace-pre-line">{pick(step.text, lang)}</p>
        {more && (
          <div className="text-[13px] text-muted leading-6 whitespace-pre-line border-s-4 border-brand-200 ps-3 max-h-[38vh] overflow-y-auto">
            {more}
          </div>
        )}
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
                    className="ms-auto text-sm font-semibold bg-brand-600 text-white rounded-lg px-5 py-1.5 hover:bg-brand-700">
              {last ? (en ? 'Done ✓' : 'تمام ✓') : (en ? 'Next ←' : 'التالي ←')}
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
