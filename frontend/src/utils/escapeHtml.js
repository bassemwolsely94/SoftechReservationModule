/**
 * utils/escapeHtml.js — escaping for the print windows that build HTML strings (document.write).
 *
 * Text typed by customers (portal reservations) or staff reaches these templates. Without escaping, a
 * value like `<img src=x onerror=…>` runs as script in a window on the app's own origin, with the staff
 * member's session (full audit 2026-11-15, SEC-2).
 *
 * escapeDeep(obj) returns a copy where every string is escaped, so a template can keep interpolating
 * `${r.customer_name}` unchanged. Only use it on DATA, never on HTML fragments you built yourself.
 */

const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => MAP[c])
}

export function escapeDeep(value) {
  if (typeof value === 'string') return escapeHtml(value)
  if (Array.isArray(value)) return value.map(escapeDeep)
  if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const out = {}
    for (const [k, v] of Object.entries(value)) out[k] = escapeDeep(v)
    return out
  }
  return value   // numbers, booleans, null/undefined, Dates and other objects pass through
}
