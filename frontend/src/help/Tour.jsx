/**
 * TourRunner — «اعرض لي»: walks the user through a screen by spotlighting the real
 * elements, one step at a time. Steps come from the screen's help (`tour`:
 * [{ target, text }]) and find their element with [data-tour="<target>"].
 *
 * Calm by design: nothing blocks the page (the dimmed mask ignores clicks, so the
 * highlighted button can be pressed for real), Esc / «إنهاء» ends it, and leaving the
 * screen ends it. A step whose element is not on screen right now (another tab, a
 * role without that button, nothing selected yet) still shows its text with a note.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import useLangStore from '../store/langStore'
import useHelpStore from './helpStore'
import { pick } from './text'

const CARD_W = 320
const PAD = 6

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
  const startPath = useRef(pathname)
  const [rect, setRect] = useState(null)
  const [tick, setTick] = useState(0)
  const step = tour.steps[tour.i]
  const last = tour.i === tour.steps.length - 1

  // leaving the screen ends the tour
  useEffect(() => { if (pathname !== startPath.current) endTour() }, [pathname, endTour])

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
      if (e.key === 'Enter' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        e.preventDefault(); last ? endTour() : tourStep(tour.i + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tour.i, last, endTour, tourStep])

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
        <div className="absolute rounded-lg ring-2 ring-brand-400 transition-all duration-200"
             style={{
               top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
               boxShadow: '0 0 0 9999px rgba(15, 23, 42, 0.45)',
             }} />
      ) : (
        <div className="absolute inset-0 bg-slate-900/30" />
      )}
      <div className="absolute pointer-events-auto rounded-xl bg-surface border border-line shadow-xl p-4 space-y-3" style={cardStyle}>
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
          <button type="button" onClick={() => (last ? endTour() : tourStep(tour.i + 1))}
                  className="ms-auto text-xs bg-brand-600 text-white rounded-lg px-4 py-1.5 hover:bg-brand-700">
            {last ? (en ? 'Done' : 'تمام') : (en ? 'Next' : 'التالي')}
          </button>
        </div>
      </div>
    </div>
  )
}
