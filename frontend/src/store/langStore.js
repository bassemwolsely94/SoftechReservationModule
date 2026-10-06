/**
 * langStore.js
 *
 * Manages UI language (ar / en) and direction (rtl / ltr).
 * Persisted in localStorage so the preference survives page refresh.
 *
 * Usage:
 *   const { lang, dir, t, setLang } = useLangStore()
 *   <div dir={dir}>…</div>
 *
 * The `t(ar, en)` helper returns the correct string for the current language.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// ── Apply to <html> element ────────────────────────────────────────────────────
export function applyLangToDocument(lang) {
  if (lang === 'en') {
    document.documentElement.lang = 'en'
    document.documentElement.dir = 'ltr'
  } else {
    document.documentElement.lang = 'ar-u-nu-latn'
    document.documentElement.dir = 'rtl'
  }
}

// ── Store ──────────────────────────────────────────────────────────────────────
const useLangStore = create(
  persist(
    (set, get) => ({
      lang: 'ar',   // 'ar' | 'en'
      dir:  'rtl',  // 'rtl' | 'ltr'

      /** Call once on app mount to sync the HTML element with stored preference. */
      init() {
        applyLangToDocument(get().lang)
      },

      /** Switch language and persist. */
      setLang(lang) {
        const dir = lang === 'en' ? 'ltr' : 'rtl'
        applyLangToDocument(lang)
        set({ lang, dir })
      },

      /**
       * Translation helper — returns arText when lang=ar, enText when lang=en.
       * Falls back to arText if enText is not supplied.
       *   t('الحجوزات', 'Reservations')
       */
      t(arText, enText) {
        return get().lang === 'en' ? (enText ?? arText) : arText
      },
    }),
    {
      name:    'elrezeiky-lang',
      version: 1,
    }
  )
)

export default useLangStore
