/**
 * Calendar dates in the pharmacy's own time zone (Africa/Cairo), as 'YYYY-MM-DD'.
 *
 * `new Date().toISOString().slice(0, 10)` is the UTC date: between 00:00 and 02:00/03:00
 * Cairo time it is still "yesterday", so a "today" filter hides the night's new orders.
 */
const TZ = 'Africa/Cairo'

export function cairoDate(at = new Date()) {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(at)
  } catch {
    return at.toISOString().slice(0, 10)
  }
}

export const cairoToday = () => cairoDate()

/** The Cairo date `days` calendar days before today (Cairo). */
export function cairoDaysAgo(days, at = new Date()) {
  const [y, m, d] = cairoDate(at).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d - days)).toISOString().slice(0, 10)
}
