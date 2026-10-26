/**
 * flowArrow.js — direction-aware arrows for "from → to" text (owner 2026-10-25).
 *
 * In a right-to-left (Arabic) screen the first value sits on the RIGHT, so a flow
 * «150 ⟶ الرئيسي ⟶ 160» must point LEFT: «150 ← الرئيسي ← 160». In English (LTR) it
 * points right. Unicode arrows are not mirrored by the browser, so every flow arrow in
 * screen text goes through these helpers instead of a hard-coded glyph.
 *
 *   fa()  — the flow / "next" arrow:   ← in Arabic, → in English
 *   ba()  — the "back" arrow:          → in Arabic, ← in English
 */
import useLangStore from '../store/langStore'

const rtl = () => {
  try {
    return (useLangStore.getState().dir || document.documentElement.dir || 'rtl') === 'rtl'
  } catch {
    return true
  }
}

export const fa = () => (rtl() ? '←' : '→')
export const ba = () => (rtl() ? '→' : '←')
