/**
 * useNumberInputGuards — one global guard for every <input type="number">.
 *
 * Policy (applies app-wide, incl. future fields):
 *   • Plain ↑/↓ ............ inert (no accidental ±step)
 *   • Plain mouse wheel .... never changes a value (blurs the focused field so
 *                            the page scrolls instead)
 *   • Shift + ↑/↓ .......... steps by the field's own `step` (deliberate)
 *   • Shift + wheel ........ steps by `step` (we preventDefault so it doesn't
 *                            double as horizontal page-scroll)
 *
 * Stepping is done manually (not via native) so the increment, rounding and
 * min/max clamping are consistent, and it works on React-controlled inputs via
 * the native value setter + a dispatched `input` event.
 */
import { useEffect } from 'react'

// Guard every number input EXCEPT those that manage their own stepping:
//  • `.pos-num`          — the POS grid cells (numFieldHandlers in POSOrderPage)
//  • `[data-no-num-guard]` — explicit opt-out for any future component
const isNumberInput = (el) =>
  el && el.tagName === 'INPUT' && el.type === 'number' &&
  !(el.classList && el.classList.contains('pos-num')) &&
  !el.hasAttribute('data-no-num-guard')

function stepValue(el, dir) {
  const step = parseFloat(el.step) || 1
  const cur  = parseFloat(el.value) || 0
  let next = cur + dir * step
  const decimals = (String(step).split('.')[1] || '').length
  next = Number(next.toFixed(decimals))
  if (el.min !== '' && !Number.isNaN(parseFloat(el.min)) && next < parseFloat(el.min)) next = parseFloat(el.min)
  if (el.max !== '' && !Number.isNaN(parseFloat(el.max)) && next > parseFloat(el.max)) next = parseFloat(el.max)

  // Set in a way React's controlled inputs notice.
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set
  if (setter) setter.call(el, String(next)); else el.value = String(next)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

export default function useNumberInputGuards() {
  useEffect(() => {
    const onKeyDown = (e) => {
      if (!isNumberInput(e.target)) return
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
      e.preventDefault()                          // always block the native step
      if (e.shiftKey) stepValue(e.target, e.key === 'ArrowUp' ? 1 : -1)
    }
    const onWheel = (e) => {
      if (!isNumberInput(e.target)) return
      if (e.shiftKey) {
        e.preventDefault()                        // deliberate step (no h-scroll)
        const d = e.deltaY || e.deltaX
        if (d) stepValue(e.target, d < 0 ? 1 : -1)
      } else if (e.target === document.activeElement) {
        e.target.blur()                           // block accidental wheel edit; page still scrolls
      }
    }
    const onFocusIn = (e) => {
      if (isNumberInput(e.target) && !e.target.title) {
        e.target.title = 'Shift + ↑/↓ أو Shift + عجلة الماوس لتغيير القيمة'
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('wheel', onWheel, { passive: false, capture: true })
    document.addEventListener('focusin', onFocusIn, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.removeEventListener('wheel', onWheel, true)
      document.removeEventListener('focusin', onFocusIn, true)
    }
  }, [])
}
