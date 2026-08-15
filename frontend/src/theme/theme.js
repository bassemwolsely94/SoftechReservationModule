/**
 * theme.js — runtime brand theming.
 *
 * The Tailwind `brand.*` palette (and brand-sky / brand-red / danger) read their
 * values from CSS variables (`--c-brand-50 … --c-brand-900`, as space-separated
 * "R G B" triplets so Tailwind's `/<alpha>` opacity modifier keeps working).
 * `applyTheme()` writes those variables on <html>, so every one of the ~900
 * `bg-brand-*` / `text-brand-*` usages retheme live with no rebuild.
 *
 * A theme is just three brand colors + an Arabic font choice:
 *   { primary, secondary, accent, arabicFont }
 * The full 10-step scale is generated from primary + secondary; the default
 * inputs reproduce the hand-tuned navy scale in index.css.
 */

export const DEFAULT_THEME = {
  primary:    '#022871',   // navy — brand-600 anchor
  secondary:  '#3880bb',   // sky  — brand-400 anchor
  accent:     '#ea0000',   // red  — danger / brand-red
  arabicFont: 'cairo',     // 'cairo' | 'jozoor' | 'tajawal'
}

export const FONT_OPTIONS = [
  { id: 'cairo',   label: 'Cairo',  label_ar: 'القاهرة',  note: 'الأوضح للنصوص الكثيفة (افتراضي)' },
  { id: 'jozoor',  label: 'Jozoor', label_ar: 'جذور',     note: 'خط الهوية الرسمي — عناوين' },
  { id: 'tajawal', label: 'Tajawal', label_ar: 'تجوال',   note: 'بديل عصري خفيف' },
]

const FONT_STACKS = {
  cairo:   "'Cairo', 'Tajawal', sans-serif",
  jozoor:  "'Jozoor', 'Cairo', sans-serif",
  tajawal: "'Tajawal', 'Cairo', sans-serif",
}

const CACHE_KEY = 'app_theme'

// ── color helpers ──────────────────────────────────────────────────────────────
function hexToRgb(hex) {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}
const triplet = (rgb) => rgb.map(Math.round).join(' ')

// mix a→b by t (0=all a, 1=all b)
function mix(a, b, t) {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ]
}

/**
 * Build the 50–900 scale (as "R G B" triplets) from primary + secondary.
 * Verified: (primary #022871, secondary #3880bb) reproduces the index.css scale.
 */
export function generateScale(primaryHex, secondaryHex) {
  const primary = hexToRgb(primaryHex)
  const sky     = hexToRgb(secondaryHex)
  const white   = [255, 255, 255]
  const black   = [0, 0, 0]
  return {
    50:  triplet(mix(sky, white, 0.93)),
    100: triplet(mix(sky, white, 0.80)),
    200: triplet(mix(sky, white, 0.58)),
    300: triplet(mix(sky, white, 0.30)),
    400: triplet(sky),
    500: triplet(mix(sky, primary, 0.55)),
    600: triplet(primary),
    700: triplet(mix(primary, black, 0.14)),
    800: triplet(mix(primary, black, 0.30)),
    900: triplet(mix(primary, black, 0.46)),
  }
}

// ── apply / persist ─────────────────────────────────────────────────────────────
export function applyTheme(theme) {
  const t = { ...DEFAULT_THEME, ...(theme || {}) }
  const root = document.documentElement
  const scale = generateScale(t.primary, t.secondary)
  for (const [step, rgb] of Object.entries(scale)) {
    root.style.setProperty(`--c-brand-${step}`, rgb)
  }
  root.style.setProperty('--c-brand-sky', triplet(hexToRgb(t.secondary)))
  root.style.setProperty('--c-brand-red', triplet(hexToRgb(t.accent)))
  root.style.setProperty('--c-danger',    triplet(hexToRgb(t.accent)))
  root.style.setProperty('--font-ar', FONT_STACKS[t.arabicFont] || FONT_STACKS.cairo)

  // keep the browser chrome / PWA color in sync
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', t.primary)
}

export function cacheTheme(theme)  { try { localStorage.setItem(CACHE_KEY, JSON.stringify(theme)) } catch {} }
export function loadCachedTheme()  { try { return JSON.parse(localStorage.getItem(CACHE_KEY)) } catch { return null } }

/**
 * tint(color, alpha) — add translucency to any color value.
 * Works for both hex ("#022871") and CSS-var colors ("rgb(var(--c-brand-600))"),
 * so it's safe to use on themeable brand colors. Replaces old `color + '33'`
 * hex-concatenation which breaks on rgb()/var() values.
 */
export function tint(color, alpha = 0.2) {
  if (typeof color !== 'string') return color
  if (color.startsWith('rgb')) return color.replace(/\)\s*$/, ` / ${alpha})`)
  if (color.startsWith('#')) return color + Math.round(alpha * 255).toString(16).padStart(2, '0')
  return color
}
