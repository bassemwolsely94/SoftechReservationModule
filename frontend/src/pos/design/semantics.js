/**
 * POS semantic system — the ONE place that maps a *meaning* to its color tone, icon and Arabic
 * label. Colors carry fixed meaning everywhere (owner brainstorm §44): green=good/available,
 * amber=attention, red=blocked/OOS, blue=info/network, purple=promo/loyalty, cyan=cold-chain,
 * gray=inactive. Components render via these tokens; they never hard-code a color again.
 *
 * Tailwind classes (not raw hex) so light/dark + brand retheme apply. `badge` = full chip;
 * `soft`/`solid` variants; `dot` = a StatusDot color; `text` = inline colored text.
 */
export const TONES = {
  ok:      { badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', solid: 'bg-emerald-600 text-white', dot: 'bg-emerald-500', text: 'text-emerald-700' },
  low:     { badge: 'bg-amber-50 text-amber-800 border-amber-200',       solid: 'bg-amber-500 text-white',   dot: 'bg-amber-500',   text: 'text-amber-800' },
  warn:    { badge: 'bg-amber-50 text-amber-800 border-amber-200',       solid: 'bg-amber-500 text-white',   dot: 'bg-amber-500',   text: 'text-amber-800' },
  oos:     { badge: 'bg-red-50 text-red-700 border-red-200',             solid: 'bg-red-600 text-white',     dot: 'bg-red-500',     text: 'text-red-700' },
  blocked: { badge: 'bg-red-50 text-red-700 border-red-200',             solid: 'bg-red-600 text-white',     dot: 'bg-red-500',     text: 'text-red-700' },
  info:    { badge: 'bg-sky-50 text-sky-700 border-sky-200',             solid: 'bg-sky-600 text-white',     dot: 'bg-sky-500',     text: 'text-sky-700' },
  promo:   { badge: 'bg-purple-50 text-purple-700 border-purple-200',    solid: 'bg-purple-600 text-white',  dot: 'bg-purple-500',  text: 'text-purple-700' },
  cold:    { badge: 'bg-cyan-50 text-cyan-700 border-cyan-200',          solid: 'bg-cyan-600 text-white',    dot: 'bg-cyan-500',    text: 'text-cyan-700' },
  neutral: { badge: 'bg-surface-2 text-muted border-line',              solid: 'bg-gray-500 text-white',    dot: 'bg-gray-400',    text: 'text-muted' },
}

// meaning key → { tone, icon (icons.jsx name), label (ar) }
export const MEANINGS = {
  available:  { tone: 'ok',      icon: 'check',     label: 'متاح' },
  low:        { tone: 'low',     icon: 'alert',     label: 'رصيد منخفض' },
  oos:        { tone: 'oos',     icon: 'x',         label: 'غير متوفر' },
  otherbranch:{ tone: 'info',    icon: 'store',     label: 'متاح بفرع آخر' },
  transfer:   { tone: 'info',    icon: 'transfer',  label: 'تحويل' },
  reservation:{ tone: 'info',    icon: 'bookmark',  label: 'حجز' },
  delivery:   { tone: 'info',    icon: 'truck',     label: 'توصيل' },
  cold:       { tone: 'cold',    icon: 'snow',      label: 'يحفظ مبرد' },
  batch:      { tone: 'info',    icon: 'package',   label: 'اختيار باتش' },
  rx:         { tone: 'info',    icon: 'rx',        label: 'روشتة' },
  pharmacist: { tone: 'warn',    icon: 'usercheck', label: 'مراجعة صيدلي' },
  offer:      { tone: 'promo',   icon: 'tag',       label: 'عرض' },
  bundle:     { tone: 'promo',   icon: 'gift',      label: 'حزمة' },
  loyalty:    { tone: 'promo',   icon: 'star',      label: 'ولاء' },
  repeat:     { tone: 'promo',   icon: 'repeat',    label: 'شراء متكرر' },
  expiring:   { tone: 'warn',    icon: 'clock',     label: 'قرب الانتهاء' },
  blocked:    { tone: 'blocked', icon: 'block',     label: 'ممنوع' },
  margin:     { tone: 'ok',      icon: 'trending',  label: 'فرصة ربح' },
}

export const tone = (key) => TONES[key] || TONES.neutral
export const meaning = (key) => MEANINGS[key] || null

/** stock qty → meaning key (available / low / oos). `low` = at-or-below threshold. */
export function stockMeaning(qty, lowThreshold = 3) {
  if (qty == null) return null
  if (qty <= 0) return 'oos'
  if (qty <= lowThreshold) return 'low'
  return 'available'
}
