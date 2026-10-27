/**
 * normalize.js — client-side Arabic-folding normalization, mirroring the backend
 * catalog/search_index.normalize_search_text so command-palette matching behaves
 * the same as server search.
 */
const FOLD = {
  'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
  'ة': 'ه', 'ى': 'ي', 'ؤ': 'و', 'ئ': 'ي',
}
// tashkeel + tatweel
const STRIP = /[ؗ-ًؚ-ْـ]/g

export function normalizeSearch(value) {
  if (!value) return ''
  let s = String(value).replace(STRIP, '')
  s = s.replace(/[أإآٱةىؤئ]/g, (ch) => FOLD[ch] || ch)
  return s.toLowerCase().replace(/\s+/g, ' ').trim()
}
